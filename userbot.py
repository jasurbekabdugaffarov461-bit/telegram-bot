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
FALLBACK_MODELS = ["gemini-3.8-flash", "gemini-2.5-flash"]

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


async def ask_ai(user_id, sender_name, text):
    if ai is None:
        return None
    hist = history[user_id]
    hist.append(types.Content(role="user", parts=[types.Part(text=text)]))
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT + f"\nSuhbatdoshning ismi: {sender_name}.",
        temperature=0.7,
    )
    global models
    for model in list(models):
        try:
            resp = await ai.aio.models.generate_content(
                model=model, contents=list(hist), config=config
            )
            answer = (resp.text or "").strip()
            if answer:
                hist.append(types.Content(role="model", parts=[types.Part(text=answer)]))
                if models[0] != model:          # ishlagan modelni birinchi qo'yamiz
                    models = [model] + [m for m in models if m != model]
                return answer
        except Exception as e:
            log(f"AI xatosi ({model}): {str(e)[:200]}")
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
            f"Alohida o'chirilgan chatlar: {n} ta"
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

    # 3) AI javobi (bir odamning xabarlari navbat bilan)
    answer = None
    if state["ai_enabled"]:
        async with locks[sender.id]:
            async with client.action(event.chat_id, "typing"):
                answer = await ask_ai(sender.id, name, raw)

    # 4) AI o'chiq yoki ishlamasa — oddiy javoblar
    if not answer:
        text = normalize(raw)
        if matches(text, GREETING_RE):
            answer = GREETING_REPLY
        elif matches(text, FAREWELL_RE):
            answer = FAREWELL_REPLY

    if answer:
        await event.respond(answer)
        log(f"  -> AI: {answer}")


def main():
    global ME_ID
    client.start()   # birinchi marta: telefon raqam va kod so'raydi
    me = client.loop.run_until_complete(client.get_me())
    ME_ID = me.id
    print("==============================")
    print(f"  USERBOT ISHLADI: {me.first_name}")
    if not ai:
        ai_txt = "O'CHIQ (gemini_api_key yo'q)"
    elif not state["ai_enabled"]:
        ai_txt = "o'chirilgan (/ai on bilan yoqing)"
    else:
        ai_txt = f"yoqilgan ({models[0]})"
    print(f"  AI: {ai_txt}")
    print("  Boshqaruv: Saved Messages'ga /ai on | /ai off | /ai status")
    print("==============================")
    print("Lichkaga kelgan xabarlar kutilmoqda...", flush=True)
    client.run_until_disconnected()


if __name__ == "__main__":
    main()
