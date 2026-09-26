"""bot_config.json va userbot_config.json dagi barcha kalitlarni bitta .env fayliga yig'adi."""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    try:
        with open(os.path.join(BASE, name), encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


b = load("bot_config.json")
u = load("userbot_config.json")

rows = [
    ("# --- Guruh boti (BotFather) ---", None),
    ("BOT_TOKEN", b.get("bot_token", "")),
    ("", None),
    ("# --- Userbot (my.telegram.org) ---", None),
    ("API_ID", u.get("api_id", "")),
    ("API_HASH", u.get("api_hash", "")),
    ("", None),
    ("# --- AI xizmatlari ---", None),
    ("GEMINI_API_KEY", u.get("gemini_api_key", "")),
    ("GROQ_API_KEY", u.get("groq_api_key", "")),
    ("OPENROUTER_API_KEY", u.get("openrouter_api_key", "")),
    ("CEREBRAS_API_KEY", u.get("cerebras_api_key", "")),
    ("MISTRAL_API_KEY", u.get("mistral_api_key", "")),
    ("NVIDIA_API_KEY", u.get("nvidia_api_key", "")),
    ("COHERE_API_KEY", u.get("cohere_api_key", "")),
    ("CLOUDFLARE_API_KEY", u.get("cloudflare_api_key", "")),
    ("CLOUDFLARE_ACCOUNT_ID", u.get("cloudflare_account_id", "")),
]

lines = ["# Telegram bot va userbot — MAXFIY kalitlar. GitHub'ga YUKLANMAYDI (.gitignore)", ""]
for k, v in rows:
    lines.append(k if v is None else f"{k}={v}")

path = os.path.join(BASE, ".env")
with open(path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

filled = [k for k, v in rows if v not in (None, "")]
print(f".env yaratildi: {path}")
print(f"To'ldirilgan kalitlar ({len(filled)} ta): {', '.join(filled)}")
