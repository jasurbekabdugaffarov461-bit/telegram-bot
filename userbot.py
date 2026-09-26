"""
Shaxsiy akkaunt uchun AI yordamchi (userbot + Gemini).

Kimdir LICHKANGIZGA yozsa:
  - so'kinsa         -> ogohlantirish (1/3, 2/3, 3/3), AI javob bermaydi
  - boshqa xabarlar  -> Gemini AI javob beradi ("Muhammad Alining shaxsiy AI yordamchisi")
  - AI ishlamay qolsa -> salom/xayr uchun oddiy javoblar

Siz o'zingiz o'sha chatga yozsangiz, AI shu chatda 30 daqiqa jim turadi
(siz bilan suhbatdoshingiz orasiga aralashmaydi).

AI'ni yoqish / o'chirish (o'zingiz yozasiz):
  "Saqlangan xabarlar" (Saved Messages) chatida — HAMMA chatlar uchun:
      /ai off     — AI o'chadi (faqat salom/xayr oddiy javoblari qoladi)
      /ai on      — AI yoqiladi
      /ai status  — holatni ko'rish
  Biror odam bilan chatda — faqat SHU chat uchun:
      /ai off     — bu odamga umuman javob bermaydi
      /ai on      — bu chatda yana yoqiladi
  (buyruq xabari darhol o'chiriladi, suhbatdosh ko'rmaydi)

Sozlamalar: userbot_config.json
  api_id, api_hash        — my.telegram.org
  gemini_api_key          — aistudio.google.com
  gemini_model (ixtiyoriy)
DIQQAT: my_account.session va userbot_config.json ni hech kimga bermang.
"""

import os
import re
import sys
import json
import time
import asyncio
import subprocess
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque

BASE = os.path.dirname(os.path.abspath(__file__))

# Oynasiz (pythonw) ishlaganda chiqishlarni userbot.log fayliga yozish
if sys.stdout is None or sys.stderr is None:
    _log = open(os.path.join(BASE, "userbot.log"), "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = _log


def _ensure(module, package):
    try:
        __import__(module)
    except ImportError:
        print(f"{package} o'rnatilmoqda...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])


_ensure("telethon", "telethon")
_ensure("google.genai", "google-genai")

from telethon import TelegramClient, events  # noqa: E402
from google import genai                     # noqa: E402
from google.genai import types               # noqa: E402

from bad_words import contains_bad_word      # noqa: E402

CONFIG_FILE = os.path.join(BASE, "userbot_config.json")
STATE_FILE = os.path.join(BASE, "userbot_state.json")
SESSION_FILE = os.path.join(BASE, "my_account")


# ==============================
# SOZLAMALAR
# ==============================

OWNER_NAME = "Muhammad Ali"

SYSTEM_PROMPT = f"""Sen {OWNER_NAME}ning shaxsiy AI yordamchisisan.
{OWNER_NAME} hozir band. Sen uning Telegram lichkasiga kelgan xabarlarga uning o'rniga javob berasan.

Qoidalar:
- "Kimsan?", "sen kimsan?", "bu kim?" kabi savollarga: "Men {OWNER_NAME}ning shaxsiy AI yordamchisiman." deb javob ber.
- Salom berishsa: "Assalomu alaykum! Yaxshimisiz?" uslubida samimiy javob qaytar.
- Xayrlashishsa: "Mayli, yaxshi dam oling!" uslubida javob ber.
- Suhbatdosh qaysi tilda yozsa (o'zbek, rus, ingliz), o'sha tilda javob ber.
- Qisqa yoz: odatda 1–3 gap. Samimiy va hurmat bilan.
- {OWNER_NAME} nomidan va'da berma. Uchrashuv, pul, qarz, ish kelishuvi kabi masalalarda qaror qilma —
  "{OWNER_NAME}ga yetkazaman, o'zi javob beradi" de.
- {OWNER_NAME}ning telefon raqami, manzili, parollari, kartalari va boshqa shaxsiy ma'lumotlarini hech qachon aytma.
- O'zingni inson deb ko'rsatma, {OWNER_NAME}ning o'zi deb ham tanishtirma.
- Oddiy savollarga (bilim, maslahat) yordam berishing mumkin.
- Tarixda "[{OWNER_NAME}ning o'zi yozdi]" bilan boshlangan xabarlarni {OWNER_NAME}ning o'zi yozgan.
  Ularni hisobga ol, unga qarshi gapirma va aytganlarini takrorlama; bu belgini javobingda yozma.
"""

# --- Qo'shimcha funksiyalar ---
TZ = timezone(timedelta(hours=5))          # Toshkent vaqti (UTC+5)
REPORT_HOUR = 21                           # kunlik hisobot soati (21:00)
BIZNES_FILE = os.path.join(BASE, "biznes.txt")
DAYLOG_FILE = os.path.join(BASE, "kunlik_log.json")
IMPORTANT_WORDS = [                        # shu so'zlar bo'lsa — sizga darhol signal
    "shoshilinch", "tezda", "tezroq", "zudlik", "muhim", "srochno", "срочно", "urgent", "asap",
    "pul", "qarz", "to'lov", "tolov", "oylik", "karta", "деньги", "долг",
    "uchrashuv", "uchrashamiz", "встреча", "meeting",
    "kasal", "kasalxona", "shifoxona", "avariya", "больница",
    "qo'ng'iroq qil", "tel qil", "telefon qil", "позвони", "call me",
    "buyurtma", "zakaz", "заказ", "narxi", "qancha turadi", "сколько стоит",
]
ALERT_COOLDOWN_MIN = 10
VOICE_MAX_MB = 20
IMAGE_MAX_MB = 10
VIDEO_MAX_MB = 20
VIDEO_MAX_SEC = 90         # shundan uzun oddiy videolar tahlil qilinmaydi

def load_biznes():
    """biznes.txt dagi ma'lumot (bo'sh yoki namuna bo'lsa — None)."""
    try:
        with open(BIZNES_FILE, encoding="utf-8-sig") as f:
            lines = [l.rstrip() for l in f if not l.lstrip().startswith("#")]
        text = "\n".join(lines).strip()
        return text or None
    except FileNotFoundError:
        return None


def system_prompt(sender_name=None):
    p = SYSTEM_PROMPT
    biz = load_biznes()
    if biz:
        p += f"""
Ish (biznes) haqida ma'lumot — mijozlar so'rasa, FAQAT shu ma'lumotdan foydalan, yo'q narsani (narx, muddat) o'ylab topma:
<<<
{biz}
>>>
Agar suhbatdosh xizmat buyurtma qilmoqchi bo'lsa: unga nima kerakligi, muddat, taxminiy byudjet va bog'lanish uchun
telefon yoki username'ini so'ra. Ma'lumot yig'ilgach, "{OWNER_NAME}ga yetkazdim, tez orada bog'lanadi" de va javobingning
ENG OXIRIDA alohida qatorda shunday yoz:  #BUYURTMA: <buyurtmaning qisqa xulosasi>
(bu qator mijozga ko'rsatilmaydi, faqat {OWNER_NAME}ga yuboriladi)."""
    p += """
Agar suhbatdosh ovozli xabar yuborgan bo'lsa, uning matni "[Ovozli xabar]:" deb beriladi — oddiy xabar kabi javob ber."""
    if sender_name:
        p += f"\nSuhbatdoshning ismi: {sender_name}."
    return p


MAX_WARNINGS = 3
PAUSE_MINUTES = 0         # siz o'zingiz yozsangiz, AI shu chatda necha daqiqa jim turadi (0 = to'xtamaydi)
HISTORY_SIZE = 20         # har bir odam bilan oxirgi nechta xabar eslab qolinadi
FALLBACK_MODELS = ["gemini-3.8-flash"]   # qo'shimcha "flash" modellar ishga tushishda avtomatik topiladi
DEBOUNCE_SECONDS = 7      # odam ketma-ket yozsa, shuncha kutib, hammasiga BITTA javob beriladi
BUSY_REPLY = f"Assalomu alaykum! {OWNER_NAME} hozir band, bo'shagach o'zi javob beradi. 🙏"
BUSY_REPLY_EVERY_MIN = 30 # "band" xabari bir odamga necha daqiqada bir marta

GREETING_REPLY = "Assalomu alaykum! Yaxshimisiz?"
FAREWELL_REPLY = "Mayli, yaxshi dam oling! 😊"
GREETINGS = [
    "salom", "salam", "assalomu alaykum", "assalomu aleykum", "assalom",
    "aleykum assalom", "alaykum assalom", "va alaykum assalom",
    "ассалому алайкум", "салом", "hello", "hi",
]
FAREWELLS = ["hayr", "xayr", "hayer", "ko'rishguncha", "korishguncha", "хайр"]


# ==============================
# YORDAMCHI
# ==============================

def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def normalize(text):
    return re.sub(r"[‘’ʻʼ`´]", "'", text.lower().strip())


def _compile(words):
    return [re.compile(rf"(?<![\w']){re.escape(normalize(w))}(?![\w'])") for w in words]


GREETING_RE = _compile(GREETINGS)
FAREWELL_RE = _compile(FAREWELLS)


def matches(text, patterns):
    return any(p.search(text) for p in patterns)


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        print("my.telegram.org -> API development tools bo'limidan oling:")
        cfg = {
            "api_id": int(input("api_id: ").strip()),
            "api_hash": input("api_hash: ").strip(),
        }
    if not cfg.get("gemini_api_key") and sys.stdin and sys.stdin.isatty():
        cfg["gemini_api_key"] = input("Gemini API key (aistudio.google.com): ").strip()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return cfg


# ==============================
# AI
# ==============================

def _load_dotenv(path):
    """.env faylidagi KALIT=qiymat qatorlarini muhit o'zgaruvchilariga yuklaydi."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if v[:1] in "\"'" and v[-1:] == v[:1] and len(v) > 1:
                v = v[1:-1]
            else:
                v = v.split(" #")[0].strip()
            if v:
                os.environ.setdefault(k.strip(), v)


_load_dotenv(os.path.join(BASE, ".env"))

cfg = load_config()
# .env dagi qiymatlar userbot_config.json dagilardan ustun turadi
for _env, _key in [("API_ID", "api_id"), ("API_HASH", "api_hash"),
                   ("GEMINI_API_KEY", "gemini_api_key"), ("GROQ_API_KEY", "groq_api_key"),
                   ("OPENROUTER_API_KEY", "openrouter_api_key"), ("CEREBRAS_API_KEY", "cerebras_api_key"),
                   ("MISTRAL_API_KEY", "mistral_api_key"), ("NVIDIA_API_KEY", "nvidia_api_key"),
                   ("COHERE_API_KEY", "cohere_api_key"), ("CLOUDFLARE_API_KEY", "cloudflare_api_key"),
                   ("CLOUDFLARE_ACCOUNT_ID", "cloudflare_account_id")]:
    if os.environ.get(_env):
        cfg[_key] = int(os.environ[_env]) if _key == "api_id" else os.environ[_env]
ai = genai.Client(api_key=cfg["gemini_api_key"]) if cfg.get("gemini_api_key") else None
models = [cfg["gemini_model"]] if cfg.get("gemini_model") else []
models += [m for m in FALLBACK_MODELS if m not in models]

# ==============================
# YOQISH / O'CHIRISH HOLATI
# ==============================

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        st = {}
    st.setdefault("ai_enabled", True)
    st.setdefault("disabled_chats", [])
    return st


def save_state():
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


state = load_state()
ME_ID = None
CMD_RE = re.compile(r"^[/.!]ai\s+(on|off|status|yoq|o'?chir|holat|hisobot|report)\s*$", re.I)

history = defaultdict(lambda: deque(maxlen=HISTORY_SIZE))   # user_id -> xabarlar
locks = defaultdict(asyncio.Lock)
paused_until = {}                                            # chat_id -> vaqt
warnings = {}                                                # user_id -> soni
pending = {}                                                 # user_id -> {"texts", "images", "task", "event"}
alert_sent = {}                                              # user_id -> vaqt (muhim xabar signali)
busy_sent = {}                                               # user_id -> vaqt
model_cooldown = {}                                          # model -> qachongacha dam oladi
stats = {"day": time.strftime("%Y-%m-%d"), "ok": 0, "fail": 0, "last_error": ""}


def count(ok, err=""):
    today = time.strftime("%Y-%m-%d")
    if stats["day"] != today:
        stats.update(day=today, ok=0, fail=0)
    stats["ok" if ok else "fail"] += 1
    if err:
        stats["last_error"] = f"{time.strftime('%H:%M')} {err}"


async def discover_models():
    """API'dagi mavjud 'flash' modellarni topib, zaxira sifatida qo'shadi."""
    global models
    if ai is None:
        return
    try:
        found = []
        async for m in await ai.aio.models.list():
            name = (m.name or "").replace("models/", "")
            actions = getattr(m, "supported_actions", None) or []
            if "flash" in name and "generateContent" in actions and not any(
                x in name for x in ("image", "tts", "audio", "live", "embed", "native")
            ):
                found.append(name)
        # asosiy model birinchi, keyin "lite" (odatda alohida limit), keyin qolganlari
        found.sort(key=lambda n: (0 if "lite" in n else 1, "preview" in n, n))
        models = models[:1] + [n for n in found if n not in models[:1]][:4]
        log(f"Modellar: {', '.join(models)}")
    except Exception as e:
        log(f"Modellar ro'yxatini olib bo'lmadi: {str(e)[:150]}")


# ==============================
# ZAXIRA AI: Groq va OpenRouter (bepul, OpenAI formatidagi API)
# ==============================
import httpx  # noqa: E402  (google-genai bilan birga o'rnatiladi)

PROVIDERS = []   # [{"name", "url", "key", "models": [...]}]
if cfg.get("groq_api_key"):
    PROVIDERS.append({"name": "groq", "url": "https://api.groq.com/openai/v1",
                      "key": cfg["groq_api_key"], "models": []})
if cfg.get("openrouter_api_key"):
    PROVIDERS.append({"name": "openrouter", "url": "https://openrouter.ai/api/v1",
                      "key": cfg["openrouter_api_key"], "models": []})
if cfg.get("cerebras_api_key"):
    PROVIDERS.append({"name": "cerebras", "url": "https://api.cerebras.ai/v1",
                      "key": cfg["cerebras_api_key"], "models": []})
if cfg.get("mistral_api_key"):
    PROVIDERS.append({"name": "mistral", "url": "https://api.mistral.ai/v1",
                      "key": cfg["mistral_api_key"], "models": []})
if cfg.get("nvidia_api_key"):
    PROVIDERS.append({"name": "nvidia", "url": "https://integrate.api.nvidia.com/v1",
                      "key": cfg["nvidia_api_key"], "models": []})
if cfg.get("cloudflare_api_key") and cfg.get("cloudflare_account_id"):
    PROVIDERS.append({"name": "cloudflare",
                      "url": f"https://api.cloudflare.com/client/v4/accounts/{cfg['cloudflare_account_id']}/ai/v1",
                      "key": cfg["cloudflare_api_key"], "models": []})
if cfg.get("cohere_api_key"):   # bepul "Trial" kalit: oyiga ~1000 so'rov — eng oxirgi zaxira
    PROVIDERS.append({"name": "cohere", "url": "https://api.cohere.ai/compatibility/v1",
                      "key": cfg["cohere_api_key"], "models": []})


async def discover_providers():
    """Har bir xizmatdagi mos (bepul) modellarni avtomatik topadi."""
    async with httpx.AsyncClient(timeout=20) as h:
        for p in PROVIDERS:
            try:
                if p["name"] == "cloudflare":
                    r = await h.get(p["url"].replace("/ai/v1", "/ai/models/search"),
                                    params={"task": "Text Generation", "per_page": 100},
                                    headers={"Authorization": f"Bearer {p['key']}"})
                    r.raise_for_status()
                    ids = [m["name"] for m in r.json().get("result", [])]
                elif p["name"] == "cohere":
                    r = await h.get("https://api.cohere.com/v1/models",
                                    params={"endpoint": "chat", "page_size": 100},
                                    headers={"Authorization": f"Bearer {p['key']}"})
                    r.raise_for_status()
                    ids = [m["name"] for m in r.json().get("models", [])]
                else:
                    r = await h.get(f"{p['url']}/models",
                                    headers={"Authorization": f"Bearer {p['key']}"})
                    r.raise_for_status()
                    ids = [m["id"] for m in r.json().get("data", [])]
                if p["name"] == "openrouter":
                    ids = [i for i in ids if i.endswith(":free")]
                    pref = ("llama", "gemma", "mistral", "qwen", "deepseek")
                elif p["name"] == "cloudflare":
                    # faqat Cloudflare'ning o'z (bepul) modellari: "@cf/..." — hamkor modellar pullik
                    ids = [i for i in ids if i.startswith("@cf/") and not any(x in i for x in
                           ("lora", "vision", "guard", "coder", "code", "math", "awq"))]
                    pref = ("llama-3.3-70b", "gpt-oss-120b", "llama-4", "gpt-oss", "qwen", "gemma", "mistral", "llama")
                elif p["name"] == "cohere":
                    ids = [i for i in ids if "command" in i and not any(x in i for x in ("vision", "light", "nightly"))]
                    pref = ("command-a", "command-r-plus", "command-r", "command")
                elif p["name"] == "nvidia":
                    ids = [i for i in ids if not any(x in i for x in
                           ("embed", "rerank", "vision", "-vl", "guard", "reward", "safety", "parse",
                            "code", "retriev", "clip", "ocr", "translate", "audio", "asr", "tts"))]
                    pref = ("llama-3.3-70b-instruct", "nemotron", "deepseek", "kimi", "qwen", "gemma", "mistral", "llama")
                elif p["name"] == "mistral":
                    ids = [i for i in ids if not any(x in i for x in
                           ("embed", "moderation", "ocr", "codestral", "devstral", "voxtral", "pixtral"))]
                    pref = ("mistral-small-latest", "mistral-medium-latest", "mistral-large-latest", "small")
                else:
                    ids = [i for i in ids if not any(x in i for x in
                           ("whisper", "tts", "guard", "embed", "vision", "audio", "prompt"))]
                    pref = ("llama-3.3-70b", "llama", "gpt-oss", "qwen", "gemma")
                ids.sort(key=lambda i: next((n for n, k in enumerate(pref) if k in i), 99))
                p["models"] = ids[:3]
                log(f"{p['name']} modellari: {', '.join(p['models']) or 'topilmadi'}")
            except Exception as e:
                log(f"{p['name']} ulanmadi: {str(e)[:150]}")


async def ask_provider(p, model, messages):
    async with httpx.AsyncClient(timeout=40) as h:
        r = await h.post(
            f"{p['url']}/chat/completions",
            headers={"Authorization": f"Bearer {p['key']}",
                     "HTTP-Referer": "https://github.com/jasurbekabdugaffarov461-bit/telegram-bot",
                     "X-Title": "telegram-userbot"},
            json={"model": model, "messages": messages, "temperature": 0.7, "max_tokens": 600},
        )
        if r.status_code != 200:
            raise Exception(f"{r.status_code} {r.text[:200]}")
        return (r.json()["choices"][0]["message"]["content"] or "").strip()


def _to_openai_messages(system, hist):
    messages = [{"role": "system", "content": system}]
    for c in hist:
        messages.append({"role": "assistant" if c.role == "model" else "user",
                         "content": c.parts[0].text})
    return messages


async def ask_backup(system, hist):
    messages = _to_openai_messages(system, hist)
    for p in PROVIDERS:
        for model in p["models"]:
            key = f"{p['name']}:{model}"
            if time.time() < model_cooldown.get(key, 0):
                continue
            try:
                answer = await ask_provider(p, model, messages)
                if answer:
                    count(True)
                    log(f"  (zaxira: {key})")
                    return answer
            except Exception as e:
                msg = str(e)
                log(f"AI xatosi ({key}): {msg[:300]}")
                count(False, f"{key}: {msg[:80]}")
                if msg.startswith("429"):
                    model_cooldown[key] = time.time() + 300
    return None


async def ask_gemini(contents, system):
    """Gemini modellari (rasm ham tushunadi). Javob yoki None."""
    global models
    if ai is None:
        return None
    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=0.7,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    for model in list(models):
        if time.time() < model_cooldown.get(model, 0):
            continue
        for attempt in range(2):                      # 503 bo'lsa 1 marta qayta urinadi
            try:
                resp = await ai.aio.models.generate_content(model=model, contents=contents, config=config)
                answer = (resp.text or "").strip()
                if answer:
                    count(True)
                    return answer
                break
            except Exception as e:
                msg = str(e)
                code = msg[:3]
                log(f"AI xatosi ({model}): {msg[:300]}")
                count(False, f"{model}: {msg[:80]}")
                if code == "503" and attempt < 1:
                    await asyncio.sleep(2)
                    continue
                if code == "503":                     # band -> 2 daqiqa boshqa modelga o'tamiz
                    model_cooldown[model] = time.time() + 120
                if code == "429":                     # limit tugadi -> 10 daqiqa dam oladi
                    model_cooldown[model] = time.time() + 600
                elif code == "404":                   # model yo'q -> ro'yxatdan chiqaramiz
                    models = [m for m in models if m != model] or models
                break
    return None


async def ask_ai(user_id, sender_name, text, images=None):
    """Suhbat tarixini hisobga olib javob beradi. images: [(bytes, mime), ...]"""
    if ai is None and not PROVIDERS:
        return None
    hist = history[user_id]
    has_video = any(m.startswith("video/") for _, m in (images or []))
    shown = text if not images else (text if has_video else f"[📷 {len(images)} ta rasm yubordi] {text}".strip())
    hist.append(types.Content(role="user", parts=[types.Part(text=shown)]))
    system = system_prompt(sender_name)

    answer = None
    if images and ai:
        parts = [types.Part(text=text or "Bu rasmda nima bor? Qisqa javob ber.")]
        if has_video:
            parts[0] = types.Part(text=text + "\n(Videoni ko'rib, undagi narsalarni va aytilgan gapni hisobga olib javob ber.)")
        parts += [types.Part.from_bytes(data=b, mime_type=m) for b, m in images]
        contents = list(hist)[:-1] + [types.Content(role="user", parts=parts)]
        answer = await ask_gemini(contents, system)
    if not answer and images:
        # rasmni ko'ra oladigan model ishlamadi -> matnli zaxira, rasmni ko'rmasligini aytamiz
        if has_video:   # videoni ko'ra olmasak ham, ovozi matnga aylantirilgan — shunga javob beramiz
            note = system + "\nSuhbatdosh video yubordi. Sen videoni ko'ra olmaysan, faqat undagi gapning " \
                            "matni berilgan — shunga javob ber."
        else:
            note = system + "\nSuhbatdosh rasm yubordi, lekin sen hozir rasmni ko'ra olmaysan. " \
                            f"Buni xushmuomalalik bilan ayt va {OWNER_NAME}ga yetkazishingni bildir."
        answer = await ask_backup(note, hist)
    if not answer and not images:
        answer = await ask_gemini(list(hist), system) or await ask_backup(system, hist)

    if answer:
        hist.append(types.Content(role="model", parts=[types.Part(text=answer)]))
        return answer
    hist.pop()   # javob olinmadi — savolni tarixdan olib tashlaymiz
    return None


async def ask_once(prompt, system="Sen yordamchisan. O'zbek tilida qisqa va aniq yoz."):
    """Tarixsiz bir martalik so'rov (hisobot uchun)."""
    c = [types.Content(role="user", parts=[types.Part(text=prompt)])]
    return await ask_gemini(c, system) or await ask_backup(system, c)


# ==============================
# OVOZLI XABAR -> MATN (Groq Whisper)
# ==============================

async def transcribe(data, filename="voice.ogg"):
    key = cfg.get("groq_api_key")
    if not key:
        return None
    async with httpx.AsyncClient(timeout=90) as h:
        for model in ("whisper-large-v3-turbo", "whisper-large-v3"):
            try:
                r = await h.post("https://api.groq.com/openai/v1/audio/transcriptions",
                                 headers={"Authorization": f"Bearer {key}"},
                                 files={"file": (filename, data, "application/octet-stream")},
                                 data={"model": model, "response_format": "json"})
                if r.status_code == 200:
                    return (r.json().get("text") or "").strip() or None
                log(f"Whisper xatosi ({model}): {r.status_code} {r.text[:200]}")
            except Exception as e:
                log(f"Whisper xatosi ({model}): {str(e)[:200]}")
    return None


# ==============================
# KUNLIK LOG, MUHIM XABAR SIGNALI, BUYURTMALAR
# ==============================

def _load_daylog():
    try:
        with open(DAYLOG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


daylog = _load_daylog()


def add_daylog(user_id, name, username, text, kind="text"):
    daylog.append({"t": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"), "id": user_id,
                   "name": name, "user": username or "", "kind": kind, "text": text[:1000]})
    del daylog[:-2000]                                  # juda kattalashib ketmasin
    try:
        with open(DAYLOG_FILE, "w", encoding="utf-8") as f:
            json.dump(daylog, f, ensure_ascii=False)
    except Exception as e:
        log(f"Log saqlanmadi: {e}")


def who(name, username, user_id):
    return f"{name}" + (f" (@{username})" if username else "") + f"  [tg://user?id={user_id}]"


def is_important(text):
    t = normalize(text)
    return next((w for w in IMPORTANT_WORDS if normalize(w) in t), None)


async def maybe_alert(user_id, name, username, text):
    word = is_important(text)
    if not word or time.time() - alert_sent.get(user_id, 0) < ALERT_COOLDOWN_MIN * 60:
        return
    alert_sent[user_id] = time.time()
    await client.send_message("me", f"🔔 MUHIM XABAR («{word}»)\n👤 {who(name, username, user_id)}\n💬 {text[:1500]}")
    log(f"  -> signal yuborildi ({word})")


ORDER_RE = re.compile(r"^\s*#\s*BUYURTMA\s*:?\s*(.*)$", re.I | re.M)


async def extract_order(answer, user_id, name, username):
    """AI javobidan #BUYURTMA qatorini olib tashlaydi va sizga yuboradi."""
    m = ORDER_RE.search(answer or "")
    if not m:
        return answer
    summary = m.group(1).strip() or "(tafsilot yo'q)"
    clean = ORDER_RE.sub("", answer).strip()
    await client.send_message("me", f"📥 YANGI BUYURTMA\n👤 {who(name, username, user_id)}\n📝 {summary}")
    add_daylog(user_id, name, username, f"BUYURTMA: {summary}", kind="order")
    log(f"  -> buyurtma yuborildi: {summary[:100]}")
    return clean


# ==============================
# KUNLIK HISOBOT
# ==============================

def _today_entries():
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    return [e for e in daylog if e["t"].startswith(today)]


async def build_report():
    entries = _today_entries()
    if not entries:
        return "📋 Bugungi hisobot: lichkaga hech kim yozmadi."
    by_user = {}
    for e in entries:
        by_user.setdefault(e["id"], {"name": e["name"], "user": e["user"], "msgs": []})["msgs"].append(e)
    raw = []
    for uid, u in by_user.items():
        raw.append(f"=== {u['name']} (@{u['user'] or '-'}), {len(u['msgs'])} ta xabar ===")
        for e in u["msgs"][-15:]:
            tag = {"voice": "🎤 ", "image": "📷 ", "order": "📥 "}.get(e["kind"], "")
            raw.append(f"{e['t'][11:]} {tag}{e['text'][:300]}")
    prompt = ("Quyida bugun Telegram lichkamga kelgan xabarlar. O'zbek tilida qisqa hisobot yoz:\n"
              "1) Har bir odam — 1 qatorda nima haqida yozgani.\n"
              "2) Oxirida '❗ Javob berishingiz kerak:' ro'yxati — savol bergan, buyurtma qilgan yoki muhim "
              "narsa yozganlar (kimligi va nima uchun).\nQisqa bo'lsin.\n\n" + "\n".join(raw)[:12000])
    summary = await ask_once(prompt)
    head = f"📋 Bugungi hisobot ({datetime.now(TZ).strftime('%d.%m.%Y')}): {len(by_user)} ta odam, {len(entries)} ta xabar\n\n"
    if summary:
        return head + summary
    # AI ishlamasa — oddiy ro'yxat
    lines = [f"• {u['name']} (@{u['user'] or '-'}): {len(u['msgs'])} ta — «{u['msgs'][-1]['text'][:80]}»"
             for u in by_user.values()]
    return head + "\n".join(lines)


async def send_long(chat, text):
    for i in range(0, len(text), 4000):
        await client.send_message(chat, text[i:i + 4000])


async def report_loop():
    while True:
        now = datetime.now(TZ)
        nxt = now.replace(hour=REPORT_HOUR, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        await asyncio.sleep((nxt - now).total_seconds())
        try:
            await send_long("me", await build_report())
            log("Kunlik hisobot yuborildi")
        except Exception as e:
            log(f"Hisobot xatosi: {e}")
        await asyncio.sleep(60)


# ==============================
# TELEGRAM
# ==============================

client = TelegramClient(SESSION_FILE, cfg["api_id"], cfg["api_hash"])


@client.on(events.NewMessage(outgoing=True, func=lambda e: e.is_private))
async def on_my_message(event):
    text = normalize(event.raw_text or "")
    m = CMD_RE.match(text)
    if m:
        await handle_command(event, m.group(1).lower())
        return
    if event.chat_id == ME_ID:
        return
    # Siz o'zingiz yozdingiz -> AI suhbat davomini bilishi uchun tarixga qo'shamiz
    mine = (event.raw_text or "").strip()
    if mine:
        if not history[event.chat_id]:   # tarix "user" xabari bilan boshlanishi kerak
            history[event.chat_id].append(types.Content(role="user", parts=[types.Part(text="(suhbat)")]))
        history[event.chat_id].append(types.Content(
            role="model", parts=[types.Part(text=f"[{OWNER_NAME}ning o'zi yozdi]: {mine}")]))
    if PAUSE_MINUTES > 0:
        paused_until[event.chat_id] = time.time() + PAUSE_MINUTES * 60


async def handle_command(event, cmd):
    if cmd in ("hisobot", "report"):
        if event.chat_id == ME_ID:
            await event.reply("⏳ Hisobot tayyorlanmoqda...")
            await send_long("me", await build_report())
        return
    on = cmd in ("on", "yoq")
    off = cmd in ("off", "ochir", "o'chir")
    chat_id = event.chat_id

    if chat_id == ME_ID:
        # Saved Messages -> umumiy
        if on or off:
            state["ai_enabled"] = on
            save_state()
        n = len(state["disabled_chats"])
        await event.reply(
            f"🤖 AI: {'✅ YOQILGAN' if state['ai_enabled'] else '⛔ O`CHIRILGAN'} (hamma chatlar)\n"
            f"Alohida o'chirilgan chatlar: {n} ta\n"
            f"Bugun AI: {stats['ok']} ta javob, {stats['fail']} ta xato\n"
            f"Modellar: {', '.join(models)}\n"
            f"Zaxira: {', '.join(p['name'] + '(' + str(len(p['models'])) + ')' for p in PROVIDERS) or 'yo`q'}\n"
            f"Oxirgi xato: {stats['last_error'] or '-'}\n"
            f"Biznes ma'lumoti: {'✅ bor' if load_biznes() else '❌ biznes.txt bo`sh'}\n"
            f"Kunlik hisobot: har kuni {REPORT_HOUR}:00 (hozir olish: /ai hisobot)"
        )
        log(f"Buyruq: /ai {cmd} (umumiy) -> ai_enabled={state['ai_enabled']}")
        return

    # Biror odam bilan chat -> faqat shu chat
    if off and chat_id not in state["disabled_chats"]:
        state["disabled_chats"].append(chat_id)
        paused_until.pop(chat_id, None)
    elif on and chat_id in state["disabled_chats"]:
        state["disabled_chats"].remove(chat_id)
    elif on:
        paused_until.pop(chat_id, None)     # 30 daqiqalik pauzani ham bekor qiladi
    save_state()
    try:
        await event.delete()                # buyruqni suhbatdosh ko'rmasin
    except Exception:
        pass
    status = "⛔ o'chirildi" if chat_id in state["disabled_chats"] else "✅ yoqildi"
    await client.send_message("me", f"🤖 AI bu chat uchun {status} (chat id: {chat_id})")
    log(f"Buyruq: /ai {cmd} (chat {chat_id}) -> {status}")


def _video_ok(event):
    """Oddiy video: faqat qisqa (<= VIDEO_MAX_SEC) bo'lsa."""
    dur = getattr(event.file, "duration", None) if event.file else None
    return dur is not None and dur <= VIDEO_MAX_SEC


def _is_image(event):
    if event.photo:
        return True
    mime = (getattr(event.file, "mime_type", "") or "") if event.file else ""
    return bool(event.document) and mime.startswith("image/") and not event.sticker


@client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def on_private_message(event):
    sender = await event.get_sender()
    if sender is None or getattr(sender, "bot", False):
        return
    name = getattr(sender, "first_name", "") or "?"
    username = getattr(sender, "username", None)
    raw = (event.raw_text or "").strip()
    kind, image = "text", None

    # --- Dumaloq video / qisqa video: ovoz (Whisper) + tasvir (Gemini) ---
    if event.video_note or (event.video and not event.gif and _video_ok(event)):
        kind = "video"
        size = (event.file.size or 0) if event.file else 0
        text = data = None
        if size <= VIDEO_MAX_MB * 1024 * 1024:
            try:
                data = await event.download_media(file=bytes)
                text = await transcribe(data, "video.mp4")
            except Exception as e:
                log(f"Videoni yuklab bo'lmadi: {e}")
        if data:
            image = (data, "video/mp4")          # Gemini videoni "ko'radi"
        label = "[Dumaloq video]" if event.video_note else "[Video]"
        raw = (f"{label} ovozi: {text}" if text else f"{label} (gapirilmagan yoki ovozi tushunilmadi)") \
              + (f"\nIzoh: {raw}" if raw else "")

    # --- Ovozli xabar / audio ---
    elif event.voice or (event.audio and not raw):
        kind = "voice"
        size = (event.file.size or 0) if event.file else 0
        text = None
        if size <= VOICE_MAX_MB * 1024 * 1024:
            try:
                data = await event.download_media(file=bytes)
                text = await transcribe(data, "voice.ogg")
            except Exception as e:
                log(f"Ovozni yuklab bo'lmadi: {e}")
        if not text:
            log(f"{name}: [ovozli xabar — tushunilmadi]")
            add_daylog(sender.id, name, username, "[ovozli xabar — matnga aylantirilmadi]", "voice")
            if state["ai_enabled"] and event.chat_id not in state["disabled_chats"] \
                    and time.time() >= paused_until.get(event.chat_id, 0):
                await event.respond("🎤 Ovozli xabarni hozir tushuna olmadim, iltimos yozib yuboring.")
            return
        raw = f"[Ovozli xabar]: {text}"

    # --- Rasm ---
    elif _is_image(event):
        kind = "image"
        size = (event.file.size or 0) if event.file else 0
        if size <= IMAGE_MAX_MB * 1024 * 1024:
            try:
                data = await event.download_media(file=bytes)
                mime = "image/jpeg" if event.photo else (event.file.mime_type or "image/jpeg")
                image = (data, mime)
            except Exception as e:
                log(f"Rasmni yuklab bo'lmadi: {e}")

    if not raw and not image:
        return

    tag = "[📷 rasm] " if kind == "image" else ""
    log(f"{name}: {tag}{raw}")
    add_daylog(sender.id, name, username, tag + raw, kind)

    # 0) Bu chat uchun bot o'chirilgan bo'lsa — javob bermaydi (lekin muhim xabar signali ishlaydi)
    await maybe_alert(sender.id, name, username, raw)
    if event.chat_id in state["disabled_chats"]:
        return

    # 1) So'kinish
    if raw and contains_bad_word(raw):
        n = warnings.get(sender.id, 0) + 1
        warnings[sender.id] = n
        if n <= MAX_WARNINGS:
            await event.respond(f"⚠️ Iltimos, haqorat qilmang. Ogohlantirish: {n}/{MAX_WARNINGS}")
        return

    # 2) Siz shu chatda yaqinda yozgan bo'lsangiz — jim
    if time.time() < paused_until.get(event.chat_id, 0):
        return

    # 3) Ketma-ket yozilgan xabarlarni yig'ib, BITTA javob berish
    p = pending.setdefault(sender.id, {"texts": [], "images": [], "task": None})
    if raw:
        p["texts"].append(raw)
    if image and len(p["images"]) < 3:
        p["images"].append(image)
    if p["task"] and not p["task"].done():
        p["task"].cancel()
    p["task"] = asyncio.create_task(reply_later(event, sender.id, name, username))


async def reply_later(event, user_id, name, username=None):
    """Kutadi, keyin yig'ilgan BARCHA xabarlarga bitta javob beradi.
    Javob tayyorlanayotganda yangi xabar kelsa — bu vazifa bekor qilinadi
    va yangi xabar bilan birga qaytadan boshlanadi (2 ta javob ketmaydi)."""
    hist_len = len(history[user_id])
    try:
        await asyncio.sleep(DEBOUNCE_SECONDS)
        p = pending.get(user_id)
        if not p or not (p["texts"] or p["images"]):
            return
        combined = "\n".join(p["texts"])
        images = list(p["images"])

        answer = None
        if state["ai_enabled"]:
            async with locks[user_id]:
                async with client.action(event.chat_id, "typing"):
                    answer = await ask_ai(user_id, name, combined, images or None)
    except asyncio.CancelledError:
        # yangi xabar keldi -> yarim qolgan savolni tarixdan olib tashlaymiz
        h = history[user_id]
        while len(h) > hist_len:
            h.pop()
        return

    # Shu nuqtadan boshlab bekor qilinmaydi: navbatni tozalab, javob yuboramiz
    pending.pop(user_id, None)
    if answer:
        answer = await extract_order(answer, user_id, name, username)
        if answer:
            await event.respond(answer)
            log(f"  -> AI: {answer[:200]}")
        return

    # AI o'chiq yoki ishlamadi — oddiy javoblar
    text = normalize(combined)
    if matches(text, GREETING_RE):
        answer = GREETING_REPLY
    elif matches(text, FAREWELL_RE):
        answer = FAREWELL_REPLY
    elif state["ai_enabled"] and time.time() - busy_sent.get(user_id, 0) > BUSY_REPLY_EVERY_MIN * 60:
        answer = BUSY_REPLY          # AI limiti tugagan / band — odam javobsiz qolmasin
        busy_sent[user_id] = time.time()
    if answer:
        await event.respond(answer)
        log(f"  -> oddiy javob: {answer}")


def main():
    global ME_ID
    client.start()   # birinchi marta: telefon raqam va kod so'raydi
    me = client.loop.run_until_complete(client.get_me())
    ME_ID = me.id
    client.loop.run_until_complete(discover_models())
    client.loop.run_until_complete(discover_providers())
    client.loop.create_task(report_loop())
    print("==============================")
    print(f"  USERBOT ISHLADI: {me.first_name}")
    if not ai and not PROVIDERS:
        ai_txt = "O'CHIQ (API kalit yo'q)"
    elif not state["ai_enabled"]:
        ai_txt = "o'chirilgan (/ai on bilan yoqing)"
    else:
        ai_txt = f"yoqilgan ({models[0] if ai else '-'}" + \
                 (f" + zaxira: {', '.join(p['name'] for p in PROVIDERS)}" if PROVIDERS else "") + ")"
    print(f"  AI: {ai_txt}")
    print("  Boshqaruv: Saved Messages'ga /ai on | /ai off | /ai status | /ai hisobot")
    print(f"  Biznes ma'lumoti: {'bor' if load_biznes() else 'yo`q (biznes.txt ni to`ldiring)'}"
          f" | Ovoz: {'Groq Whisper' if cfg.get('groq_api_key') else 'yo`q'} | Hisobot: {REPORT_HOUR}:00")
    print("==============================")
    print("Lichkaga kelgan xabarlar kutilmoqda...", flush=True)
    client.run_until_disconnected()


def _keep_awake():
    """Windows: bot ishlab turgan paytda kompyuter uyqu rejimiga o'tmasin
    (sozlamalarni o'zgartirmaydi — dastur yopilsa, odatiy holat qaytadi)."""
    if sys.platform == "win32":
        try:
            import ctypes
            ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        except Exception:
            pass


if __name__ == "__main__":
    # Internet bo'lmasa yoki ulanish uzilsa — 20 soniyadan keyin qayta urinadi
    import time as _t
    _keep_awake()
    while True:
        try:
            main()
            break                      # normal to'xtatildi (Ctrl+C)
        except KeyboardInterrupt:
            break
        except Exception as _e:
            print(f"[{_t.strftime('%Y-%m-%d %H:%M:%S')}] Xato: {_e!r} — 20 soniyadan keyin qayta urinaman", flush=True)
            _t.sleep(20)
