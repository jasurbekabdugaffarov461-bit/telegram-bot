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
"""

MAX_WARNINGS = 3
PAUSE_MINUTES = 30        # siz o'zingiz yozsangiz, AI shu chatda necha daqiqa jim turadi
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

cfg = load_config()
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
CMD_RE = re.compile(r"^[/.!]ai\s+(on|off|status|yoq|o'?chir|holat)\s*$", re.I)

history = defaultdict(lambda: deque(maxlen=HISTORY_SIZE))   # user_id -> xabarlar
locks = defaultdict(asyncio.Lock)
paused_until = {}                                            # chat_id -> vaqt
warnings = {}                                                # user_id -> soni
pending = {}                                                 # user_id -> {"texts": [...], "task": Task}
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


async def discover_providers():
    """Har bir xizmatdagi mos (bepul) modellarni avtomatik topadi."""
    async with httpx.AsyncClient(timeout=20) as h:
        for p in PROVIDERS:
            try:
                r = await h.get(f"{p['url']}/models",
                                headers={"Authorization": f"Bearer {p['key']}"})
                r.raise_for_status()
                ids = [m["id"] for m in r.json().get("data", [])]
                if p["name"] == "openrouter":
                    ids = [i for i in ids if i.endswith(":free")]
                    pref = ("llama", "gemma", "mistral", "qwen", "deepseek")
                elif p["name"] == "nvidia":
                    ids = [i for i in ids if "instruct" in i and not any(x in i for x in
                           ("embed", "rerank", "vision", "vl", "guard", "reward", "safety", "parse", "code"))]
                    pref = ("llama-3.3-70b", "nemotron", "llama", "gemma", "qwen", "mistral")
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


async def ask_backup(sender_name, hist):
    messages = [{"role": "system",
                 "content": SYSTEM_PROMPT + f"\nSuhbatdoshning ismi: {sender_name}."}]
    for c in hist:
        messages.append({"role": "assistant" if c.role == "model" else "user",
                         "content": c.parts[0].text})
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


async def ask_ai(user_id, sender_name, text):
    if ai is None and not PROVIDERS:
        return None
    hist = history[user_id]
    hist.append(types.Content(role="user", parts=[types.Part(text=text)]))
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT + f"\nSuhbatdoshning ismi: {sender_name}.",
        temperature=0.7,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    global models
    for model in (list(models) if ai else []):
        if time.time() < model_cooldown.get(model, 0):
            continue
        for attempt in range(2):                      # 503 bo'lsa 1 marta qayta urinadi
            try:
                resp = await ai.aio.models.generate_content(
                    model=model, contents=list(hist), config=config
                )
                answer = (resp.text or "").strip()
                if answer:
                    hist.append(types.Content(role="model", parts=[types.Part(text=answer)]))
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
                if code == "429":                     # limit tugadi -> bu model 10 daqiqa dam oladi
                    model_cooldown[model] = time.time() + 600
                elif code == "404":                   # model yo'q -> ro'yxatdan chiqaramiz
                    models = [m for m in models if m != model] or models
                break
    # Gemini ishlamadi -> zaxira xizmatlar (Groq, OpenRouter)
    answer = await ask_backup(sender_name, hist)
    if answer:
        hist.append(types.Content(role="model", parts=[types.Part(text=answer)]))
        return answer
    hist.pop()   # javob olinmadi — savolni tarixdan olib tashlaymiz
    return None


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
    # Siz o'zingiz yozdingiz -> AI shu chatda vaqtincha jim
    if event.chat_id != ME_ID:
        paused_until[event.chat_id] = time.time() + PAUSE_MINUTES * 60


async def handle_command(event, cmd):
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
            f"Oxirgi xato: {stats['last_error'] or '-'}"
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


@client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def on_private_message(event):
    sender = await event.get_sender()
    if sender is None or getattr(sender, "bot", False):
        return
    raw = (event.raw_text or "").strip()
    if not raw:
        return

    name = getattr(sender, "first_name", "") or "?"
    log(f"{name}: {raw}")

    # 0) Bu chat uchun bot o'chirilgan bo'lsa — umuman javob bermaydi
    if event.chat_id in state["disabled_chats"]:
        return

    # 1) So'kinish
    if contains_bad_word(raw):
        count = warnings.get(sender.id, 0) + 1
        warnings[sender.id] = count
        if count <= MAX_WARNINGS:
            await event.respond(f"⚠️ Iltimos, haqorat qilmang. Ogohlantirish: {count}/{MAX_WARNINGS}")
        return

    # 2) Siz shu chatda yaqinda yozgan bo'lsangiz — jim
    if time.time() < paused_until.get(event.chat_id, 0):
        return

    # 3) Ketma-ket yozilgan xabarlarni yig'ib, BITTA javob berish
    p = pending.setdefault(sender.id, {"texts": [], "task": None})
    p["texts"].append(raw)
    if p["task"] and not p["task"].done():
        p["task"].cancel()
    p["task"] = asyncio.create_task(reply_later(event, sender.id, name))


async def reply_later(event, user_id, name):
    """Kutadi, keyin yig'ilgan BARCHA xabarlarga bitta javob beradi.
    Javob tayyorlanayotganda yangi xabar kelsa — bu vazifa bekor qilinadi
    va yangi xabar bilan birga qaytadan boshlanadi (2 ta javob ketmaydi)."""
    hist_len = len(history[user_id])
    try:
        await asyncio.sleep(DEBOUNCE_SECONDS)
        p = pending.get(user_id)
        if not p or not p["texts"]:
            return
        combined = "\n".join(p["texts"])

        answer = None
        if state["ai_enabled"]:
            async with locks[user_id]:
                async with client.action(event.chat_id, "typing"):
                    answer = await ask_ai(user_id, name, combined)
    except asyncio.CancelledError:
        # yangi xabar keldi -> yarim qolgan savolni tarixdan olib tashlaymiz
        h = history[user_id]
        while len(h) > hist_len:
            h.pop()
        return

    # Shu nuqtadan boshlab bekor qilinmaydi: navbatni tozalab, javob yuboramiz
    pending.pop(user_id, None)
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
    print("  Boshqaruv: Saved Messages'ga /ai on | /ai off | /ai status")
    print("==============================")
    print("Lichkaga kelgan xabarlar kutilmoqda...", flush=True)
    client.run_until_disconnected()


if __name__ == "__main__":
    main()
