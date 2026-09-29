import os
import re
import sys
import logging
import subprocess
from datetime import datetime, timedelta, timezone

# Oynasiz (pythonw) ishlaganda chiqishlarni bot.log fayliga yozish
if sys.stdout is None or sys.stderr is None:
    _log = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.log"),
                "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = _log

# Kutubxona o'rnatilmagan bo'lsa — avtomatik o'rnatadi
try:
    import telegram  # noqa: F401
except ImportError:
    print("python-telegram-bot o'rnatilmoqda...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot>=22.0"])

from bad_words import contains_bad_word
import ai_core
from collections import defaultdict, deque
import time as _time
from telegram import Update, ChatPermissions
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ==============================
# BOT TOKEN
# ==============================
# Token kodda SAQLANMAYDI (GitHub'ga chiqib ketmasligi uchun).
# Tartib: muhit o'zgaruvchisi -> .env fayli (BOT_TOKEN=...) -> bot_config.json:
#   {"bot_token": "123456:ABC..."}

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


_load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


def _load_token():
    token = os.getenv("BOT_TOKEN")
    if token:
        return token
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_config.json")
    try:
        import json
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("bot_token")
    except FileNotFoundError:
        return None


BOT_TOKEN = _load_token()


# ==============================
# SOZLAMALAR
# ==============================

MAX_WARNINGS = 3          # nechta ogohlantirishdan keyin mute
MUTE_MINUTES = 60         # mute davomiyligi (daqiqa)


# ==============================
# LOG
# ==============================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)


# ==============================
# SO'Z RO'YXATLARI
# ==============================

# Haqorat so'zlari bad_words.py faylida (o'zbekcha, ruscha, inglizcha).
# Yangi so'z qo'shish uchun o'sha faylni oching.

GREETINGS = [
    "salom",
    "salam",
    "assalomu alaykum",
    "assalom",
    "aleykum assalom",
    "alaykum assalom",
    "hello",
    "hi",
]

FAREWELLS = [
    "hayr",
    "xayr",
    "hayer",
    "ko'rishguncha",
    "korishguncha",
]


# ==============================
# YORDAMCHI FUNKSIYALAR
# ==============================

def normalize(text: str) -> str:
    """Kichik harf + barcha apostrof turlarini bitta ' ga keltiradi."""
    text = text.lower().strip()
    return re.sub(r"[‘’ʻʼ`´]", "'", text)


def _compile_whole(words):
    # To'liq so'z sifatida: "hi" -> "chiqdi" ichida topilmaydi,
    # "xayr" -> "xayrli" ichida topilmaydi.
    return [re.compile(rf"(?<![\w']){re.escape(w)}(?![\w'])") for w in words]


GREETING_RE = _compile_whole(GREETINGS)
FAREWELL_RE = _compile_whole(FAREWELLS)


def matches(text: str, patterns) -> bool:
    return any(p.search(text) for p in patterns)


# ==============================
# JAZO: o'chirish, ogohlantirish, mute
# ==============================

async def punish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    # 1) Haqoratli xabarni o'chirish (guruhda bot admin bo'lishi kerak)
    try:
        await message.delete()
    except TelegramError as e:
        log.info("Xabarni o'chirib bo'lmadi: %s", e)

    # 2) Ogohlantirishlarni sanash (chat + foydalanuvchi bo'yicha)
    warnings = context.chat_data.setdefault("warnings", {})
    count = warnings.get(user.id, 0) + 1
    warnings[user.id] = count

    name = user.mention_html()

    # 3) Limitga yetsa — mute (faqat guruhlarda)
    if count >= MAX_WARNINGS and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        until = datetime.now(timezone.utc) + timedelta(minutes=MUTE_MINUTES)
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
            warnings[user.id] = 0
            await chat.send_message(
                f"🔇 {name} {MUTE_MINUTES} daqiqaga yozishdan cheklandi "
                f"(qoidabuzarlik {MAX_WARNINGS} marta takrorlandi).",
                parse_mode="HTML",
            )
            return
        except TelegramError as e:
            log.warning("Mute qilib bo'lmadi (bot adminmi?): %s", e)

    await chat.send_message(
        f"⚠️ {name}, iltimos, haqorat qilmang. "
        f"Buning o'ziga yarasha javobgarligi bor.\n"
        f"Ogohlantirish: {count}/{MAX_WARNINGS}",
        parse_mode="HTML",
    )


# ==============================
# XABAR QABUL QILISH
# ==============================

# ==============================
# GURUHDA AI (faqat reply yoki bot nomi aytilganda)
# ==============================

OWNER_NAME = "Muhammad Ali"
AI_OFFER = (f"Siz ham Telegram akkauntingizga AI ulab qo'ymoqchi bo'lsangiz, {OWNER_NAME}ga yozing. "
            "Narxi — 39 000 so'm.")
EXTRA_TRIGGERS = ["bot", "botjon"]   # xabar shu so'z bilan BOSHLANSA ham javob beradi ("bot, bugun nima kun?")
GROUP_HISTORY = 20
USER_LIMIT_PER_MIN = 6               # bitta odam daqiqasiga nechta AI savol bera oladi

group_history = defaultdict(lambda: deque(maxlen=GROUP_HISTORY))   # chat_id -> [(role, matn)]
user_hits = defaultdict(deque)                                      # user_id -> vaqtlar
BOT_USERNAME = ""
BOT_NAME = ""


def group_system(chat_title):
    return f"""Sen Telegram guruhidagi AI yordamchi botsan ("{BOT_NAME}", @{BOT_USERNAME}).
Seni {OWNER_NAME} yaratgan. Guruh nomi: "{chat_title}".
Qoidalar:
- Qisqa va aniq javob ber (1–4 gap). Savol qaysi tilda bo'lsa (o'zbek, rus, ingliz), shu tilda javob ber.
- Suhbat tarixida xabarlar "Ism: matn" ko'rinishida — kim nima deganini hisobga ol.
- Hurmat bilan yoz. Haqorat, siyosiy bahs va shaxsiy ma'lumotlarga aralashma.
- "Sen kimsan?", "AI misan?", "bot misan?" desa: "Men {OWNER_NAME} yaratgan AI botman." deb javob ber
  va shu taklifni qo'sh: "{AI_OFFER}"
- Javobni "{BOT_NAME}:" deb boshlama."""


def _is_triggered(message) -> bool:
    """Botga reply qilingan yoki bot nomi / @username aytilgan bo'lsa True."""
    if message.chat.type == ChatType.PRIVATE:
        return True
    r = message.reply_to_message
    if r and r.from_user and r.from_user.username and r.from_user.username.lower() == BOT_USERNAME.lower():
        return True
    t = (message.text or message.caption or "").lower()
    if BOT_USERNAME and f"@{BOT_USERNAME.lower()}" in t:
        return True
    names = [BOT_USERNAME.lower(), BOT_NAME.lower()]
    if any(n and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", t) for n in names):
        return True
    # "bot, ..." kabi murojaat — faqat xabar boshida bo'lsa (oddiy gapdagi "bot" so'ziga javob bermaydi)
    return any(re.match(rf"\s*{re.escape(w.lower())}\b[\s,!:?.-]", t + " ") for w in EXTRA_TRIGGERS)


def _rate_ok(user_id) -> bool:
    q = user_hits[user_id]
    now = _time.time()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= USER_LIMIT_PER_MIN:
        return False
    q.append(now)
    return True


async def ai_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """AI javob beradi. Javob berilsa True."""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not ai_core.enabled() or not _rate_ok(user.id):
        return False
    text = message.text or message.caption or ""
    if BOT_USERNAME:
        text = re.sub(rf"@{re.escape(BOT_USERNAME)}", "", text, flags=re.I).strip() or text
    hist = group_history[chat.id]
    r = message.reply_to_message
    if r and (r.text or r.caption) and not (r.from_user and r.from_user.username
                                             and r.from_user.username.lower() == BOT_USERNAME.lower()):
        # boshqa odamning xabariga reply qilib botni chaqirsa — o'sha xabarni ham kontekstga qo'shamiz
        hist.append(("user", f"{r.from_user.first_name if r.from_user else '?'}: {(r.text or r.caption)[:800]}"))
    hist.append(("user", f"{user.first_name}: {text[:1500]}"))
    await context.bot.send_chat_action(chat.id, "typing")
    answer = await ai_core.complete(group_system(chat.title or "shaxsiy chat"), list(hist))
    if not answer:
        hist.pop()
        return False
    hist.append(("assistant", answer))
    await message.reply_text(answer[:4000])
    log.info("  -> AI javob: %s", answer[:150])
    return True


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.text or not update.effective_user:
        return

    text = normalize(message.text)
    log.info("Xabar keldi [%s] %s: %s",
             update.effective_chat.type, update.effective_user.full_name, message.text)

    # 1) HAQORAT — birinchi tekshiriladi
    if contains_bad_word(message.text):
        await punish(update, context)
        return

    # 2) AI — faqat botga reply qilinganda yoki bot nomi aytilganda
    if _is_triggered(message):
        if await ai_reply(update, context):
            return

    # 3) SALOM
    if matches(text, GREETING_RE):
        await message.reply_text("Assalomu alaykum! Yaxshimisiz?")
        return

    # 4) XAYR
    if matches(text, FAREWELL_RE):
        await message.reply_text("Mayli, yaxshi dam oling! 😊")
        return


# ==============================
# /start
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Assalomu alaykum! Men ishlayapman ✅\n"
        "Guruhga qo'shib, admin qilsangiz — haqoratli xabarlarni nazorat qilaman."
    )


# ==============================
# BOTNI ISHGA TUSHIRISH
# ==============================

def main():
    if not BOT_TOKEN:
        raise SystemExit('BOT_TOKEN topilmadi! bot_config.json yarating: {"bot_token": "..."}')

    async def post_init(application):
        global BOT_USERNAME, BOT_NAME
        me = await application.bot.get_me()
        BOT_USERNAME, BOT_NAME = me.username or "", me.first_name or ""
        ai_core.set_logger(lambda m: log.info(m))
        await ai_core.discover()
        print(f"Bot: @{me.username}  (Telegram'da shu botga yozing)")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).concurrent_updates(True).build()  # bir vaqtda ko'p odamga javob

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    print("==============================")
    print("       TELEGRAM BOT ISHLADI")
    print("==============================")
    print("Xabar kutilmoqda...")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


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
    import asyncio as _aio
    # Bitta nusxa: ikkinchi nusxa ishga tushsa darhol chiqib ketadi (Conflict / database is locked bo'lmasin)
    import socket as _so
    _lock = _so.socket(_so.AF_INET, _so.SOCK_STREAM)
    try:
        _lock.bind(("127.0.0.1", 47651))
    except OSError:
        print("Bu dastur allaqachon ishlayapti — ikkinchi nusxa yopildi.", flush=True)
        raise SystemExit(0)
    _keep_awake()
    while True:
        try:
            _aio.set_event_loop(_aio.new_event_loop())   # har urinishda yangi event loop
            main()
            break                      # normal to'xtatildi (Ctrl+C)
        except KeyboardInterrupt:
            break
        except Exception as _e:
            print(f"[{_t.strftime('%Y-%m-%d %H:%M:%S')}] Xato: {_e!r} — 20 soniyadan keyin qayta urinaman", flush=True)
            _t.sleep(20)
