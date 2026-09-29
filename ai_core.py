"""
Umumiy AI moduli (guruh boti uchun): Gemini + zaxira xizmatlar
(Groq, OpenRouter, Cerebras, Mistral, NVIDIA, Cloudflare, Cohere).

Kalitlar .env yoki userbot_config.json dan olinadi (userbot bilan bir xil).
"""

import os
import re
import sys
import json
import time
import subprocess
import asyncio
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))


def _ensure(module, package):
    try:
        __import__(module)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", package])


_ensure("google.genai", "google-genai")
import httpx                      # noqa: E402
from google import genai          # noqa: E402
from google.genai import types    # noqa: E402

log = print


def set_logger(fn):
    global log
    log = fn


# ------------------------------------------------------------
# Kalitlar
# ------------------------------------------------------------

def _load_cfg():
    cfg = {}
    path = os.path.join(BASE, "userbot_config.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            cfg.update(json.load(f))
    env = os.path.join(BASE, ".env")
    if os.path.exists(env):
        with open(env, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip()
                v = v[1:-1] if v[:1] in "\"'" and v[-1:] == v[:1] and len(v) > 1 else v.split(" #")[0].strip()
                if v:
                    cfg[k.strip().lower()] = v
    return cfg


cfg = _load_cfg()
ai = genai.Client(api_key=cfg["gemini_api_key"]) if cfg.get("gemini_api_key") else None
models = [cfg.get("gemini_model") or "gemini-3.8-flash"]
cooldown = {}

PROVIDERS = []
for name, url, key in [
    ("groq", "https://api.groq.com/openai/v1", "groq_api_key"),
    ("openrouter", "https://openrouter.ai/api/v1", "openrouter_api_key"),
    ("cerebras", "https://api.cerebras.ai/v1", "cerebras_api_key"),
    ("mistral", "https://api.mistral.ai/v1", "mistral_api_key"),
    ("nvidia", "https://integrate.api.nvidia.com/v1", "nvidia_api_key"),
]:
    if cfg.get(key):
        PROVIDERS.append({"name": name, "url": url, "key": cfg[key], "models": []})
if cfg.get("cloudflare_api_key") and cfg.get("cloudflare_account_id"):
    PROVIDERS.append({"name": "cloudflare", "key": cfg["cloudflare_api_key"], "models": [],
                      "url": f"https://api.cloudflare.com/client/v4/accounts/{cfg['cloudflare_account_id']}/ai/v1"})
if cfg.get("cohere_api_key"):
    PROVIDERS.append({"name": "cohere", "url": "https://api.cohere.ai/compatibility/v1",
                      "key": cfg["cohere_api_key"], "models": []})
_FAST = ["cerebras", "groq", "cloudflare", "mistral", "openrouter", "nvidia", "cohere"]   # tezligi bo'yicha
PROVIDERS.sort(key=lambda p: _FAST.index(p["name"]) if p["name"] in _FAST else 99)


def enabled():
    return bool(ai or PROVIDERS)


# ------------------------------------------------------------
# Modellarni topish
# ------------------------------------------------------------

async def discover():
    global models
    if ai:
        try:
            found = []
            async for m in await ai.aio.models.list():
                n = (m.name or "").replace("models/", "")
                acts = getattr(m, "supported_actions", None) or []
                if "flash" in n and "generateContent" in acts and not any(
                        x in n for x in ("image", "tts", "audio", "live", "embed", "native")):
                    found.append(n)

            def ver(n):
                mm = re.search(r"(\d+(?:\.\d+)?)", n)
                return float(mm.group(1)) if mm else 0.0
            found = [n for n in found if ver(n) >= 3 or "latest" in n]
            found.sort(key=lambda n: ("lite" in n, "preview" in n, "latest" in n, -ver(n)))
            models = models[:1] + [n for n in found if n not in models[:1]][:8]
        except Exception as e:
            log(f"[AI] Gemini modellari topilmadi: {str(e)[:150]}")

    rules = {
        "openrouter": (lambda i: i.endswith(":free"), ("llama", "gemma", "mistral", "qwen", "deepseek")),
        "cloudflare": (lambda i: i.startswith("@cf/") and not any(x in i for x in
                       ("lora", "vision", "guard", "coder", "code", "math", "awq")),
                       ("llama-3.3-70b", "gpt-oss-120b", "llama-4", "gpt-oss", "qwen", "gemma")),
        "cohere": (lambda i: "command" in i and not any(x in i for x in ("vision", "light", "nightly")),
                   ("command-a", "command-r-plus", "command-r")),
        "mistral": (lambda i: not any(x in i for x in ("embed", "moderation", "ocr", "codestral",
                                                        "devstral", "voxtral", "pixtral")),
                    ("mistral-small-latest", "mistral-medium-latest", "small")),
        "nvidia": (lambda i: not any(x in i for x in ("embed", "rerank", "vision", "-vl", "guard", "reward",
                                                       "safety", "parse", "code", "retriev", "clip", "ocr",
                                                       "translate", "audio", "asr", "tts")),
                   ("llama-3.3-70b-instruct", "nemotron", "deepseek", "kimi", "qwen", "gemma")),
    }
    default = (lambda i: not any(x in i for x in ("whisper", "tts", "guard", "embed", "vision", "audio", "prompt")),
               ("llama-3.3-70b", "llama", "gpt-oss", "qwen", "gemma"))
    async with httpx.AsyncClient(timeout=20) as h:
        for p in PROVIDERS:
            try:
                hdr = {"Authorization": f"Bearer {p['key']}"}
                if p["name"] == "cloudflare":
                    r = await h.get(p["url"].replace("/ai/v1", "/ai/models/search"),
                                    params={"task": "Text Generation", "per_page": 100}, headers=hdr)
                    ids = [m["name"] for m in r.json().get("result", [])]
                elif p["name"] == "cohere":
                    r = await h.get("https://api.cohere.com/v1/models",
                                    params={"endpoint": "chat", "page_size": 100}, headers=hdr)
                    ids = [m["name"] for m in r.json().get("models", [])]
                else:
                    r = await h.get(f"{p['url']}/models", headers=hdr)
                    ids = [m["id"] for m in r.json().get("data", [])]
                keep, pref = rules.get(p["name"], default)
                ids = [i for i in ids if keep(i)]
                ids.sort(key=lambda i: next((n for n, k in enumerate(pref) if k in i), 99))
                p["models"] = ids[:3]
            except Exception as e:
                log(f"[AI] {p['name']} ulanmadi: {str(e)[:150]}")
    log(f"[AI] Gemini: {', '.join(models) if ai else '-'} | zaxira: "
        f"{', '.join(p['name'] for p in PROVIDERS if p['models']) or '-'}")


# ------------------------------------------------------------
# Javob olish
# ------------------------------------------------------------

async def _gemini(system, hist):
    global models
    if not ai:
        return None
    contents = [types.Content(role="model" if r == "assistant" else "user", parts=[types.Part(text=t)])
                for r, t in hist]
    conf = types.GenerateContentConfig(
        system_instruction=system, temperature=0.7,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    for m in list(models):
        if time.time() < cooldown.get(m, 0):
            continue
        try:
            r = await asyncio.wait_for(
                ai.aio.models.generate_content(model=m, contents=contents, config=conf), timeout=12)
            if (r.text or "").strip():
                return r.text.strip()
        except asyncio.TimeoutError:
            log(f"[AI] {m}: sekin (12 s) — keyingisiga")
            cooldown[m] = time.time() + 120
            continue
        except Exception as e:
            msg = str(e)
            log(f"[AI] {m}: {msg[:160]}")
            if msg.startswith("503"):
                cooldown[m] = time.time() + 300
            elif msg.startswith("429"):
                if "PerDay" in msg or "per day" in msg.lower():
                    now = datetime.now(timezone.utc)
                    reset = now.replace(hour=7, minute=5, second=0, microsecond=0)
                    cooldown[m] = (reset if reset > now else reset + timedelta(days=1)).timestamp()
                else:
                    cooldown[m] = time.time() + 60
            elif msg.startswith("404"):
                models = [x for x in models if x != m] or models
    return None


async def _backup(system, hist):
    msgs = [{"role": "system", "content": system}] + [{"role": r, "content": t} for r, t in hist]
    async with httpx.AsyncClient(timeout=20) as h:
        for p in PROVIDERS:
            for m in p["models"]:
                k = f"{p['name']}:{m}"
                if time.time() < cooldown.get(k, 0):
                    continue
                try:
                    r = await h.post(f"{p['url']}/chat/completions",
                                     headers={"Authorization": f"Bearer {p['key']}"},
                                     json={"model": m, "messages": msgs, "temperature": 0.7, "max_tokens": 600})
                    if r.status_code == 200:
                        ans = (r.json()["choices"][0]["message"]["content"] or "").strip()
                        if ans:
                            return ans
                    else:
                        log(f"[AI] {k}: {r.status_code} {r.text[:120]}")
                        if r.status_code == 429:
                            cooldown[k] = time.time() + 300
                except Exception as e:
                    log(f"[AI] {k}: {str(e)[:120]}")
    return None


async def complete(system, hist):
    """hist: [("user"|"assistant", matn), ...]. Javob matni yoki None."""
    # Gemini 5 soniyada javob bermasa — zaxira ham parallel ishga tushadi, qaysi biri oldin bo'lsa o'sha
    tasks = {asyncio.create_task(_gemini(system, hist))}
    try:
        await asyncio.wait(tasks, timeout=5)
        t1 = next(iter(tasks))
        if t1.done():
            return (not t1.exception() and t1.result()) or await _backup(system, hist)
        tasks.add(asyncio.create_task(_backup(system, hist)))
        pending = set(tasks)
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                if not t.exception() and t.result():
                    return t.result()
        return None
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
