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
# Avval BOT_TOKEN muhit o'zgaruvchisidan, bo'lmasa bot_config.json faylidan o'qiladi:
#   {"bot_token": "123456:ABC..."}

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

    # 2) SALOM
    if matches(text, GREETING_RE):
        await message.reply_text("Assalomu alaykum! Yaxshimisiz?")
        return

    # 3) XAYR
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
        me = await application.bot.get_me()
        print(f"Bot: @{me.username}  (Telegram'da shu botga yozing)")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    print("==============================")
    print("       TELEGRAM BOT ISHLADI")
    print("==============================")
    print("Xabar kutilmoqda...")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
