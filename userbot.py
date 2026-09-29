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
import io
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


def _try_ensure(module, package):
    try:
        _ensure(module, package)
        return True
    except Exception as e:
        print(f"{package} o'rnatilmadi: {e}")
        return False


HAS_TTS = _try_ensure("edge_tts", "edge-tts")                    # ovozli javob (bepul, kalitsiz)
HAS_FFMPEG = HAS_TTS and _try_ensure("imageio_ffmpeg", "imageio-ffmpeg")   # mp3 -> telegram ovoz formati

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
AI_OFFER_PRICE = "39 000 so'm"
AI_OFFER = (f"Siz ham {OWNER_NAME}dek Telegram akkauntingizga AI ulab qo'ymoqchi bo'lsangiz, "
            f"{OWNER_NAME}ga yetkazaman. Narxi — {AI_OFFER_PRICE}.")
OFFER_REPEAT_DAYS = 30     # so'ramasa ham taklif: bir odamga shuncha kunda bir marta

SYSTEM_PROMPT = f"""Sen {OWNER_NAME}ning shaxsiy AI yordamchisisan.
{OWNER_NAME} hozir band. Sen uning Telegram lichkasiga kelgan xabarlarga uning o'rniga javob berasan.

Qoidalar:
- "Kimsan?", "sen AI misan?", "bot misan?", "bu kim?" kabi savollarga: "Men {OWNER_NAME}ning shaxsiy AI yordamchisiman." deb javob ber
  va DOIM shu taklifni qo'sh: "{AI_OFFER}"
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
PAYMENT_WORDS = [                          # to'lov xabarlari — kutishsiz, har safar signal
    "tashladim", "tashlab qo'ydim", "tashlab qoydim", "to'ladim", "toladim", "to'lab qo'ydim",
    "o'tkazdim", "otkazdim", "o'tkazib qo'ydim", "chek", "kvitansiya",
    "оплатил", "оплатила", "перевел", "перевёл", "перевела", "скинул", "скинула", "чек",
    "paid", "i sent the money",
]
VOICE_MAX_MB = 20
IMAGE_MAX_MB = 10
VIDEO_MAX_MB = 20
VIDEO_MAX_SEC = 90         # shundan uzun oddiy videolar tahlil qilinmaydi

HISTORY_FILE = os.path.join(BASE, "suhbatlar.json")      # har bir odam bilan suhbat (o'chib-yonsa ham eslaydi)
ORDERS_FILE = os.path.join(BASE, "buyurtmalar.json")     # buyurtmalar ro'yxati

VOICE_REPLY = True                 # ovozli xabarga ovozli javob
VOICE_UZ = "uz-UZ-SardorNeural"    # ayol ovozi kerak bo'lsa: "uz-UZ-MadinaNeural"
VOICE_RU = "ru-RU-DmitryNeural"
VOICE_EN = "en-US-GuyNeural"
VOICE_MAX_CHARS = 700              # bundan uzun javob matn bilan yuboriladi

# --- Spam / firibgarlik ---
SPAM_HARD = [                      # shular bo'lsa — javob berilmaydi
    "yutib oldingiz", "yutuq oldingiz", "yutuqni oling", "g'olib bo'ldingiz", "sovrin yutdingiz",
    "tekin premium", "bepul premium", "premium sovg'a", "sms kod", "smsdagi kod", "kelgan kodni",
    "kodni ayting", "kodni yuboring", "karta raqamingiz", "cvv", "1xbet", "mostbet", "kazino", "casino",
    "выиграли", "вы победили", "ваш приз", "код из смс", "пришел код", "пришёл код", "казино",
    "you won", "you have won", "claim your prize",
]
SPAM_SOFT = [                      # havola bilan birga kelsa — spam
    "ovoz ber", "golos", "airdrop", "kripto", "crypto", "invest", "daromad", "pul ishla", "ish taklif",
    "uydan turib", "bonus", "sovg'a", "yutuq", "stavka", "подарок", "заработ", "инвест", "голос",
    "ставк", "бонус", "free", "giveaway", "prize", "earn",
]
DANGER_EXT = (".apk", ".exe", ".scr", ".bat", ".cmd", ".msi", ".vbs", ".jar", ".js", ".ps1")
LINK_RE = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/|bit\.ly|tinyurl|goo\.gl)", re.I)

def load_biznes():
    """biznes.txt dagi ma'lumot (bo'sh yoki namuna bo'lsa — None)."""
    try:
        with open(BIZNES_FILE, encoding="utf-8-sig") as f:
            lines = [l.rstrip() for l in f if not l.lstrip().startswith("#")]
        text = "\n".join(lines).strip()
        return text or None
    except FileNotFoundError:
        return None


def system_prompt(sender_name=None, offer=False, user_id=None):
    p = SYSTEM_PROMPT
    if offer:
        p += f"""
Bu odamga hali AI ulash xizmati taklif qilinmagan. Javobingning oxirida, tabiiy tarzda, bir marta shu taklifni qo'sh:
"{AI_OFFER}" (suhbat mavzusiga qarab so'zlarini biroz moslashtirishing mumkin, narxni o'zgartirma)."""
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
    p += f"""
Agar suhbatdosh to'lov cheki (kvitansiya, o'tkazma skrinshoti) rasmini yuborsa: to'lovni o'zing TASDIQLAMA,
"{OWNER_NAME}ga yetkazdim, tekshirib tasdiqlaydi" de va javobing ENG OXIRIDA alohida qatorda yoz:
#CHEK: summa=...; sana=...; vaqt=...; karta=**** (faqat oxirgi 4 raqam); qabul qiluvchi=...; tizim=...
(rasmda ko'ringanini yoz, ko'rinmaganiga ? qo'y; bu qator mijozga ko'rsatilmaydi)."""
    b = busy_info()
    if b:
        p += f"""
MUHIM: {OWNER_NAME} hozir {b[0]} — soat {b[1]} dan keyin o'zi javob beradi.
Suhbat boshida (yoki "qachon javob beradi?" deyishsa) buni albatta ayt."""
    if user_id:
        mine = [o for o in orders if o["id"] == user_id][-3:]
        if mine:
            p += "\nBu odamning oldingi buyurtmalari (kerak bo'lsa hisobga ol): " + \
                 "; ".join(f"№{o['n']} {o['summary'][:120]} — holati: {o['status']}" for o in mine)
    if sender_name:
        p += f"\nSuhbatdoshning ismi: {sender_name}."
    return p


MAX_WARNINGS = 3
PAUSE_MINUTES = 0         # siz o'zingiz yozsangiz, AI shu chatda necha daqiqa jim turadi (0 = to'xtamaydi)
HISTORY_SIZE = 20         # har bir odam bilan oxirgi nechta xabar eslab qolinadi
FALLBACK_MODELS = ["gemini-3.8-flash"]   # qo'shimcha "flash" modellar ishga tushishda avtomatik topiladi
DEBOUNCE_SECONDS = 1.5      # odam ketma-ket yozsa, shuncha kutib, hammasiga BITTA javob beriladi
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
    st.setdefault("offered", {})         # user_id -> AI ulash taklif qilingan vaqt
    st.setdefault("busy_until", 0)       # band rejimi (qachongacha)
    st.setdefault("busy_reason", "")
    return st


def should_offer(user_id):
    last = state.get("offered", {}).get(str(user_id), 0)
    return time.time() - last > OFFER_REPEAT_DAYS * 86400


def save_state():
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


state = load_state()


def busy_info():
    """Band rejimi yoqilgan bo'lsa: (sabab, "HH:MM"), aks holda None."""
    if time.time() < state.get("busy_until", 0):
        return (state.get("busy_reason") or "band",
                datetime.fromtimestamp(state["busy_until"], TZ).strftime("%H:%M"))
    return None
ME_ID = None
CMD_RE = re.compile(r"^[/.!]ai\s+(on|off|status|yoq|o'?chir|holat|hisobot|report)\s*$", re.I)

history = defaultdict(lambda: deque(maxlen=HISTORY_SIZE))   # user_id -> xabarlar


def load_history():
    """suhbatlar.json dan oldingi suhbatlarni tiklaydi (kompyuter o'chib-yonsa ham AI eslaydi)."""
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return
    for uid, msgs in data.items():
        h = history[int(uid)]
        for role, text in msgs[-HISTORY_SIZE:]:
            h.append(types.Content(role=role, parts=[types.Part(text=text)]))


def save_history():
    try:
        data = {str(u): [[c.role, c.parts[0].text or ""] for c in h if c.parts]
                for u, h in history.items() if h}
        tmp = HISTORY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, HISTORY_FILE)
    except Exception as e:
        print(f"Suhbatlar saqlanmadi: {e}", flush=True)


load_history()
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
        # Tartib: asosiy model -> sifatli "Flash" (3.x, yangisi oldin) -> "Flash Lite" (katta limit)
        # 2.x modellar yangi foydalanuvchilar uchun yopilgan — ularni tashlab ketamiz
        def ver(n):
            m = re.search(r"(\d+(?:\.\d+)?)", n)
            return float(m.group(1)) if m else 0.0
        found = [n for n in found if ver(n) >= 3 or "latest" in n]
        found.sort(key=lambda n: ("lite" in n, "preview" in n, "latest" in n, -ver(n)))
        models = models[:1] + [n for n in found if n not in models[:1]][:8]
        log(f"Modellar: {', '.join(models)}")
    except Exception as e:
        log(f"Modellar ro'yxatini olib bo'lmadi: {str(e)[:150]}")


# ==============================
# ZAXIRA AI: Groq va OpenRouter (bepul, OpenAI formatidagi API)
# ==============================
import httpx  # noqa: E402  (google-genai bilan birga o'rnatiladi)

PROVIDERS = []   # [{"name", "url", "key", "models": [...]}]
FAST_ORDER = ["cerebras", "groq", "cloudflare", "mistral", "openrouter", "nvidia", "cohere"]  # tezligi bo'yicha
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
PROVIDERS.sort(key=lambda p: FAST_ORDER.index(p["name"]) if p["name"] in FAST_ORDER else 99)


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
    async with httpx.AsyncClient(timeout=20) as h:
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
    global FAST_THINK
    extra = {}
    if FAST_THINK:
        try:
            extra["thinking_config"] = types.ThinkingConfig(thinking_level="minimal")
        except Exception:
            FAST_THINK = False
    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=0.7,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        **extra,
    )
    for model in list(models):
        if time.time() < model_cooldown.get(model, 0):
            continue
        for attempt in range(2):                      # 503 bo'lsa 1 marta qayta urinadi
            try:
                resp = await asyncio.wait_for(
                    ai.aio.models.generate_content(model=model, contents=contents, config=config),
                    timeout=GEMINI_TIMEOUT)
                answer = (resp.text or "").strip()
                if answer:
                    count(True)
                    return answer
                break
            except asyncio.TimeoutError:
                log(f"AI sekin ({model}): {GEMINI_TIMEOUT} soniyada javob bermadi — keyingisiga o'tamiz")
                model_cooldown[model] = time.time() + 120
                break
            except Exception as e:
                msg = str(e)
                code = msg[:3]
                log(f"AI xatosi ({model}): {msg[:300]}")
                count(False, f"{model}: {msg[:80]}")
                if code == "400" and FAST_THINK and "think" in msg.lower():
                    FAST_THINK = False                # bu model "minimal" ni bilmaydi -> oddiy rejimga
                    log("  (tez rejim qo'llanmadi — oddiy rejimda davom etamiz)")
                    return await ask_gemini(contents, system)
                if code == "503":                     # band -> kutmasdan keyingi modelga, 5 daqiqa chetlab turamiz
                    model_cooldown[model] = time.time() + 300
                if code == "429":
                    if "PerDay" in msg or "per day" in msg.lower():
                        # kunlik limit tugadi -> limit yangilanguncha (07:00 UTC ≈ 12:00 Toshkent) ishlatmaymiz
                        now = datetime.now(timezone.utc)
                        reset = now.replace(hour=7, minute=5, second=0, microsecond=0)
                        if reset <= now:
                            reset += timedelta(days=1)
                        model_cooldown[model] = reset.timestamp()
                        log(f"  {model}: kunlik limit tugadi, {reset.astimezone(TZ):%H:%M} gacha ishlatilmaydi")
                    else:                             # daqiqalik limit -> 1 daqiqa dam oladi
                        model_cooldown[model] = time.time() + 60
                elif code == "404":                   # model yo'q -> ro'yxatdan chiqaramiz
                    models = [m for m in models if m != model] or models
                break
    return None


FAST_THINK = True        # Gemini uzoq "o'ylamasin" — javob 2-3 barobar tezroq
GEMINI_TIMEOUT = 12      # bitta Gemini modeli shuncha soniyada javob bermasa — keyingisiga
RACE_HEAD_START = 3      # Gemini shuncha soniyada javob bermasa — zaxira AI ham parallel ishga tushadi


async def race(primary, backup_fn, head=RACE_HEAD_START):
    """Avval Gemini; u sekinlashsa zaxira ham parallel boshlanadi — qaysi biri oldin javob bersa, o'sha."""
    tasks = {asyncio.create_task(primary)}
    try:
        done, _ = await asyncio.wait(tasks, timeout=head)
        t1 = next(iter(tasks))
        if t1.done():
            return (not t1.exception() and t1.result()) or await backup_fn()
        tasks.add(asyncio.create_task(backup_fn()))
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


async def ask_ai(user_id, sender_name, text, images=None, offer=False):
    """Suhbat tarixini hisobga olib javob beradi. images: [(bytes, mime), ...]"""
    if ai is None and not PROVIDERS:
        return None
    hist = history[user_id]
    has_video = any(m.startswith("video/") for _, m in (images or []))
    shown = text if not images else (text if has_video else f"[📷 {len(images)} ta rasm yubordi] {text}".strip())
    hist.append(types.Content(role="user", parts=[types.Part(text=shown)]))
    system = system_prompt(sender_name, offer, user_id)

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
        answer = await race(ask_gemini(list(hist), system), lambda: ask_backup(system, hist))

    if answer:
        hist.append(types.Content(role="model", parts=[types.Part(text=answer)]))
        save_history()
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
    t = normalize(text)
    pay = next((w for w in PAYMENT_WORDS if normalize(w) in t), None)
    if pay:
        await client.send_message("me", f"💰 TO'LOV XABARI («{pay}»)\n👤 {who(name, username, user_id)}\n"
                                        f"💬 {text[:1500]}\n\n⚠️ Kartangizni tekshiring!")
        log(f"  -> to'lov signali yuborildi ({pay})")
        return
    word = is_important(text)
    if not word or time.time() - alert_sent.get(user_id, 0) < ALERT_COOLDOWN_MIN * 60:
        return
    alert_sent[user_id] = time.time()
    await client.send_message("me", f"🔔 MUHIM XABAR («{word}»)\n👤 {who(name, username, user_id)}\n💬 {text[:1500]}")
    log(f"  -> signal yuborildi ({word})")


ORDER_RE = re.compile(r"^\s*#\s*BUYURTMA\s*:?\s*(.*)$", re.I | re.M)
CHEK_RE = re.compile(r"^\s*#\s*CHEK\s*:?\s*(.*)$", re.I | re.M)
STATUS_ICON = {"yangi": "🆕", "chek keldi": "🧾", "to'landi": "💰", "bajarildi": "✅", "bekor": "❌"}
OPEN_STATUSES = ("yangi", "chek keldi", "to'landi")


def _load_orders():
    try:
        with open(ORDERS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        # birinchi ishga tushish: kunlik_log.json dagi eski buyurtmalarni ko'chiramiz
        old = [e for e in daylog if e.get("kind") == "order"]
        return [{"n": i + 1, "t": e["t"], "id": e["id"], "name": e["name"], "user": e.get("user", ""),
                 "summary": e["text"].replace("BUYURTMA: ", "", 1), "status": "yangi", "chek": ""}
                for i, e in enumerate(old)]
    except Exception:
        return []


orders = _load_orders()


def save_orders():
    try:
        with open(ORDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(orders, f, ensure_ascii=False, indent=1)
    except Exception as e:
        log(f"Buyurtmalar saqlanmadi: {e}")


def fmt_order(o):
    s = (f"№{o['n']} {STATUS_ICON.get(o['status'], '')} {o['status']} | {o['t'][8:10]}.{o['t'][5:7]} {o['t'][11:]}"
         f" | {o['name']}" + (f" (@{o['user']})" if o.get("user") else "") + f"\n   📝 {o['summary'][:300]}")
    if o.get("chek"):
        s += f"\n   🧾 {o['chek'][:200]}"
    return s


async def extract_order(answer, user_id, name, username):
    """AI javobidan #BUYURTMA qatorini olib tashlaydi, ro'yxatga qo'shadi va sizga yuboradi."""
    m = ORDER_RE.search(answer or "")
    if not m:
        return answer
    summary = m.group(1).strip() or "(tafsilot yo'q)"
    clean = ORDER_RE.sub("", answer).strip()
    n = max((o["n"] for o in orders), default=0) + 1
    orders.append({"n": n, "t": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"), "id": user_id, "name": name,
                   "user": username or "", "summary": summary, "status": "yangi", "chek": ""})
    save_orders()
    await client.send_message("me", f"📥 YANGI BUYURTMA №{n}\n👤 {who(name, username, user_id)}\n📝 {summary}\n\n"
                                    f"Belgilash: /ai tolandi {n}  |  /ai bajarildi {n}  |  /ai bekor {n}")
    add_daylog(user_id, name, username, f"BUYURTMA №{n}: {summary}", kind="order")
    log(f"  -> buyurtma №{n} yuborildi: {summary[:100]}")
    return clean


async def extract_cheque(answer, user_id, name, username, chat_id, img_ids):
    """AI javobidan #CHEK qatorini olib tashlaydi va chek ma'lumotini (rasmi bilan) sizga yuboradi."""
    m = CHEK_RE.search(answer or "")
    if not m:
        return answer
    info = m.group(1).strip() or "(o'qib bo'lmadi)"
    clean = CHEK_RE.sub("", answer).strip()
    order = next((o for o in reversed(orders) if o["id"] == user_id and o["status"] in ("yangi", "chek keldi")), None)
    tail = ""
    if order:
        order["status"], order["chek"] = "chek keldi", info
        save_orders()
        tail = f"\n📥 Buyurtma №{order['n']}: {order['summary'][:150]}\nTasdiqlash: /ai tolandi {order['n']}"
    await client.send_message("me", f"🧾 TO'LOV CHEKI KELDI\n👤 {who(name, username, user_id)}\n💵 {info}{tail}\n\n"
                                    f"⚠️ Kartangizga pul tushganini o'zingiz tekshiring!")
    if img_ids:
        try:
            await client.forward_messages("me", img_ids, from_peer=chat_id)
        except Exception as e:
            log(f"Chek rasmini yuborib bo'lmadi: {e}")
    add_daylog(user_id, name, username, f"CHEK: {info}", kind="payment")
    log(f"  -> chek yuborildi: {info[:100]}")
    return clean


# ==============================
# SPAM / FIRIBGARLIK
# ==============================

spam_alert_sent = {}


def spam_check(text, filename, sender):
    """('spam', sabab) — javob berilmaydi; ('link', sabab) — javob beriladi, lekin sizga ogohlantirish; yoki None."""
    t = normalize(text or "")
    if filename and filename.lower().endswith(DANGER_EXT):
        return "spam", f"xavfli fayl: {filename}"
    hard = next((w for w in SPAM_HARD if normalize(w) in t), None)
    if hard:
        return "spam", f"«{hard}»"
    if LINK_RE.search(t):
        soft = next((w for w in SPAM_SOFT if normalize(w) in t), None)
        if soft:
            return "spam", f"havola + «{soft}»"
        if not getattr(sender, "contact", False):
            return "link", "notanish odam havola yubordi"
    return None


# ==============================
# OVOZLI JAVOB (edge-tts, bepul)
# ==============================

_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]+")


def _pick_voice(text):
    if re.search(r"[а-яА-ЯёЁ]", text):
        return VOICE_UZ if re.search(r"[ўқғҳЎҚҒҲ]", text) else VOICE_RU
    words = set(re.findall(r"[a-z']+", text.lower()))
    if len(words & {"the", "you", "is", "are", "and", "what", "hello", "your", "will", "can", "i'm"}) >= 2:
        return VOICE_EN
    return VOICE_UZ


def _ffmpeg_to_ogg(mp3):
    import imageio_ffmpeg
    flags = 0x08000000 if sys.platform == "win32" else 0          # oyna chiqmasin
    r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", "pipe:0", "-c:a", "libopus",
                        "-b:a", "32k", "-f", "ogg", "pipe:1"], input=mp3, capture_output=True,
                       timeout=60, creationflags=flags)
    if r.returncode != 0 or not r.stdout:
        return None, 0
    tm = re.findall(rb"time=(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    dur = int(float(tm[-1][0]) * 3600 + float(tm[-1][1]) * 60 + float(tm[-1][2])) if tm else 0
    return r.stdout, dur


async def send_voice(chat_id, text):
    """Matnni ovozga aylantirib, ovozli xabar qilib yuboradi. Muvaffaqiyatli bo'lsa True."""
    if not (VOICE_REPLY and HAS_TTS) or len(text) > VOICE_MAX_CHARS:
        return False
    clean = _EMOJI_RE.sub("", re.sub(r"[*_`#~]", "", text)).strip()
    if not clean:
        return False
    try:
        import edge_tts
        buf = bytearray()
        async for chunk in edge_tts.Communicate(clean, _pick_voice(clean)).stream():
            if chunk["type"] == "audio":
                buf += chunk["data"]
        if not buf:
            return False
        data, name, dur = bytes(buf), "javob.mp3", 0
        if HAS_FFMPEG:
            ogg, dur = await asyncio.get_running_loop().run_in_executor(None, _ffmpeg_to_ogg, data)
            if ogg:
                data, name = ogg, "javob.ogg"
        from telethon.tl.types import DocumentAttributeAudio
        f = io.BytesIO(data)
        f.name = name
        await client.send_file(chat_id, f, voice_note=True,
                               attributes=[DocumentAttributeAudio(duration=dur or max(1, len(clean) // 14), voice=True)])
        return True
    except Exception as e:
        log(f"Ovozli javob xatosi: {str(e)[:200]}")
        return False


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
            tag = {"voice": "🎤 ", "image": "📷 ", "order": "📥 ", "payment": "🧾 ", "spam": "🚫 "}.get(e["kind"], "")
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


def media_stats():
    """Bugungi xabarlar turi bo'yicha statistika (/ai status uchun)."""
    e = _today_entries()
    def n(kind):
        return sum(1 for x in e if x["kind"] == kind)
    voice_fail = sum(1 for x in e if x["kind"] == "voice" and "aylantirilmadi" in x["text"])
    return (f"Bugun kelgan: 💬 {n('text')} matn | 🎤 {n('voice')} ovozli"
            f"{f' ({voice_fail} tasi tushunilmadi)' if voice_fail else ''} | 🎥 {n('video')} video"
            f" | 📷 {n('image')} rasm | 📥 {n('order')} buyurtma\n"
            f"Ovoz→matn: {'✅ Groq Whisper' if cfg.get('groq_api_key') else '❌ Groq kaliti yo`q'}"
            f" | Video/rasm: {'✅ Gemini' if ai else '❌ Gemini kaliti yo`q'}")


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
    m = EXT_RE.match(text)
    if m:
        parts = (event.raw_text or "").strip().split(None, 2)
        await handle_ext(event, m.group(1).lower(), parts[2] if len(parts) > 2 else "")
        return
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
        save_history()
    if PAUSE_MINUTES > 0:
        paused_until[event.chat_id] = time.time() + PAUSE_MINUTES * 60


EXT_RE = re.compile(r"^[/.!]ai\s+(band|bo'?sh|buyurtmalar|buyurtma|to'?landi|bajarildi|bekor|yordam|help)\b", re.I)
HELP_TEXT = """🤖 Buyruqlar (Saved Messages'da):
/ai status — holat
/ai on | /ai off — AI ni yoqish/o'chirish
/ai hisobot — bugungi hisobot
/ai band 2 soat uchrashuvdaman — band rejimi (yoki: /ai band 30 daqiqa, /ai band 16:00 darsda)
/ai bosh — band rejimini o'chirish
/ai buyurtmalar — ochiq buyurtmalar (/ai buyurtmalar hammasi — barchasi)
/ai tolandi 3 | /ai bajarildi 3 | /ai bekor 3 — buyurtma holati"""


def parse_busy(arg):
    """'2 soat uchrashuvda' | '30 daqiqa' | '16:00 gacha darsda' -> (timestamp, sabab)."""
    arg = arg.strip()
    now = datetime.now(TZ)
    m = re.match(r"(\d{1,2})[:.](\d{2})\s*(?:gacha|дo|до)?\s*(.*)$", arg, re.I)
    if m:
        until = now.replace(hour=int(m.group(1)) % 24, minute=int(m.group(2)) % 60, second=0, microsecond=0)
        if until <= now:
            until += timedelta(days=1)
        return until.timestamp(), m.group(3).strip()
    m = re.match(r"(\d+(?:[.,]\d+)?)\s*(soat|daqiqa|daq|minut|min|час|мин|hour|h|s|m)\w*\s*(.*)$", arg, re.I)
    if m:
        n = float(m.group(1).replace(",", "."))
        unit = m.group(2).lower()
        minutes = n if unit.startswith(("daq", "min", "мин", "m")) else n * 60
        return time.time() + minutes * 60, m.group(3).strip()
    return time.time() + 3600, arg          # vaqt aytilmasa — 1 soat


async def handle_ext(event, cmd, arg):
    if event.chat_id != ME_ID:
        try:
            await event.delete()
        except Exception:
            pass
        await client.send_message("me", "ℹ️ Bu buyruq faqat Saved Messages (Избранное) da ishlaydi.")
        return
    cmd = cmd.replace("'", "")
    if cmd in ("yordam", "help"):
        await event.reply(HELP_TEXT)
    elif cmd == "band":
        if arg.strip().lower() in ("off", "ochir", "o'chir", "yoq"):
            cmd = "bosh"
        else:
            until, reason = parse_busy(arg)
            state["busy_until"], state["busy_reason"] = until, reason or "band"
            save_state()
            b = busy_info()
            await event.reply(f"⏳ Band rejimi yoqildi: «{b[0]}», soat {b[1]} gacha.\n"
                              f"AI hammaga shuni aytadi. O'chirish: /ai bosh")
            log(f"Buyruq: band {b[0]} {b[1]} gacha")
    if cmd == "bosh":
        state["busy_until"] = 0
        save_state()
        await event.reply("✅ Band rejimi o'chirildi.")
    elif cmd in ("buyurtmalar", "buyurtma"):
        show_all = "hamm" in arg.lower() or "barch" in arg.lower()
        lst = orders if show_all else [o for o in orders if o["status"] in OPEN_STATUSES]
        if not lst:
            await event.reply("📥 Ochiq buyurtma yo'q." + ("" if show_all else "\nHammasi: /ai buyurtmalar hammasi"))
            return
        head = f"📥 {'Barcha' if show_all else 'Ochiq'} buyurtmalar ({len(lst)} ta):\n\n"
        await send_long("me", head + "\n\n".join(fmt_order(o) for o in lst[-30:]) +
                        "\n\nBelgilash: /ai tolandi N | /ai bajarildi N | /ai bekor N")
    elif cmd in ("tolandi", "bajarildi", "bekor"):
        m = re.search(r"\d+", arg)
        o = next((x for x in orders if m and x["n"] == int(m.group())), None)
        if not o:
            await event.reply("❗ Buyurtma raqamini yozing, masalan: /ai tolandi 3\nRo'yxat: /ai buyurtmalar")
            return
        o["status"] = {"tolandi": "to'landi"}.get(cmd, cmd)
        save_orders()
        await event.reply(f"Yangilandi:\n{fmt_order(o)}")
        log(f"Buyruq: buyurtma №{o['n']} -> {o['status']}")


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
            f"{media_stats()}\n"
            f"Biznes ma'lumoti: {'✅ bor' if load_biznes() else '❌ biznes.txt bo`sh'}\n"
            f"Kunlik hisobot: har kuni {REPORT_HOUR}:00 (hozir olish: /ai hisobot)\n"
            f"Band rejimi: {('⏳ ' + busy_info()[0] + ', ' + busy_info()[1] + ' gacha') if busy_info() else 'yo`q'}\n"
            f"Ochiq buyurtmalar: {sum(1 for o in orders if o['status'] in OPEN_STATUSES)} ta (/ai buyurtmalar)\n"
            f"Ovozli javob: {'✅' if VOICE_REPLY and HAS_TTS else '❌'} | Eslab qolingan suhbatlar: {len(history)} ta\n"
            f"Barcha buyruqlar: /ai yordam"
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


typing_at = {}   # user_id -> oxirgi "yozmoqda..." vaqti


@client.on(events.UserUpdate)
async def on_user_update(event):
    try:
        if event.typing:
            typing_at[event.user_id] = time.time()
        elif event.cancel:
            typing_at.pop(event.user_id, None)
    except Exception:
        pass


@client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def on_private_message(event):
    sender = await event.get_sender()
    if sender is None or getattr(sender, "bot", False):
        return
    name = getattr(sender, "first_name", "") or "?"
    username = getattr(sender, "username", None)
    raw = (event.raw_text or "").strip()
    kind, image = "text", None

    # --- Spam / firibgarlik ---
    fname = (getattr(event.file, "name", None) or "") if event.file else ""
    sp = spam_check(raw, fname, sender)
    if sp and sp[0] == "spam":
        log(f"{name}: 🚫 SPAM ({sp[1]}): {raw[:150]}")
        add_daylog(sender.id, name, username, f"[SPAM: {sp[1]}] {raw}", "spam")
        if time.time() - spam_alert_sent.get(sender.id, 0) > ALERT_COOLDOWN_MIN * 60:
            spam_alert_sent[sender.id] = time.time()
            await client.send_message("me", f"🚫 SHUBHALI XABAR ({sp[1]}) — AI javob bermadi\n"
                                            f"👤 {who(name, username, sender.id)}\n💬 {raw[:800]}\n\n"
                                            f"⚠️ Havolani ochmang, kod yoki karta ma'lumotini bermang!")
        return
    if sp and sp[0] == "link" and time.time() - spam_alert_sent.get(sender.id, 0) > ALERT_COOLDOWN_MIN * 60:
        spam_alert_sent[sender.id] = time.time()
        await client.send_message("me", f"🔗 Notanish odam havola yubordi — ochishdan oldin tekshiring\n"
                                        f"👤 {who(name, username, sender.id)}\n💬 {raw[:800]}")

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
    p = pending.setdefault(sender.id, {"texts": [], "images": [], "task": None, "voice": False, "img_ids": []})
    if raw:
        p["texts"].append(raw)
    if image and len(p["images"]) < 3:
        p["images"].append(image)
        if kind == "image":
            p["img_ids"].append(event.id)
    if kind == "voice":
        p["voice"] = True
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
        # odam hali yozayotgan bo'lsa ("yozmoqda...") — tugatishini kutamiz (ko'pi bilan 15 s)
        waited = 0
        while time.time() - typing_at.get(user_id, 0) < 6 and waited < 15:
            await asyncio.sleep(0.5)
            waited += 0.5
        p = pending.get(user_id)
        if not p or not (p["texts"] or p["images"]):
            return
        combined = "\n".join(p["texts"])
        images = list(p["images"])
        want_voice = p.get("voice", False)
        img_ids = list(p.get("img_ids", []))

        answer = None
        if state["ai_enabled"]:
            async with locks[user_id]:
                async with client.action(event.chat_id, "typing"):
                    offer = should_offer(user_id)
                    answer = await ask_ai(user_id, name, combined, images or None, offer)
                    if not answer:
                        # bir vaqtda ko'p odam yozib, daqiqalik limit to'lgan bo'lishi mumkin —
                        # 20 soniya kutib yana bir marta urinamiz (tarix ikki marta yozilmasin)
                        h = history[user_id]
                        while len(h) > hist_len:
                            h.pop()
                        await asyncio.sleep(20)
                        answer = await ask_ai(user_id, name, combined, images or None, offer)
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
        answer = await extract_cheque(answer, user_id, name, username, event.chat_id, img_ids)
        if answer and AI_OFFER_PRICE.split()[0] in answer.replace("\u00a0", " "):
            state["offered"][str(user_id)] = time.time()
            save_state()
        if answer:
            if want_voice and await send_voice(event.chat_id, answer):
                log(f"  -> AI (🎤 ovozli): {answer[:200]}")
            else:
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
        b = busy_info()
        answer = (f"Assalomu alaykum! {OWNER_NAME} hozir {b[0]}, soat {b[1]} dan keyin javob beradi. 🙏"
                  if b else BUSY_REPLY)          # AI limiti tugagan / band — odam javobsiz qolmasin
        busy_sent[user_id] = time.time()
    if answer:
        await event.respond(answer)
        log(f"  -> oddiy javob: {answer}")


def main():
    global ME_ID
    # Oynasiz ishlaganda (pythonw) kod kiritib bo'lmaydi — sessiya bekor qilingan bo'lsa, aniq xabar beramiz
    if not (sys.stdin and sys.stdin.isatty()):
        client.loop.run_until_complete(client.connect())
        if not client.loop.run_until_complete(client.is_user_authorized()):
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ❌ TELEGRAM SESSIYASI BEKOR QILINGAN. "
                  "run_userbot.bat ni ishga tushirib, telefon raqam va kod bilan qayta kiring. "
                  "(10 daqiqadan keyin yana tekshiriladi)", flush=True)
            client.loop.run_until_complete(client.disconnect())
            time.sleep(600)
            raise RuntimeError("sessiya bekor qilingan")
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
    print("  Boshqaruv: Saved Messages'ga /ai yordam — barcha buyruqlar")
    print(f"  Eslab qolingan suhbatlar: {len(history)} | Buyurtmalar: {len(orders)} | "
          f"Ovozli javob: {'bor' if HAS_TTS else 'yo`q'}")
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
    # Bitta nusxa: ikkinchi nusxa ishga tushsa darhol chiqib ketadi (Conflict / database is locked bo'lmasin)
    import socket as _so
    _lock = _so.socket(_so.AF_INET, _so.SOCK_STREAM)
    try:
        _lock.bind(("127.0.0.1", 47652))
    except OSError:
        print("Bu dastur allaqachon ishlayapti — ikkinchi nusxa yopildi.", flush=True)
        raise SystemExit(0)
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
