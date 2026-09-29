"""
Telegram akkauntga QR-kod orqali kirish (SMS/kod kerak emas).

Telefonda: Telegram -> Settings (Sozlamalar) -> Devices (Qurilmalar)
          -> "Link Desktop Device" (Kompyuterni ulash) -> ekrandagi QR-kodni skanerlang.
Muvaffaqiyatli kirilgach my_account.session yangilanadi va userbot yana ishlaydi.
"""

import os
import sys
import json
import asyncio
import subprocess
import getpass

BASE = os.path.dirname(os.path.abspath(__file__))


def _ensure(module, package):
    try:
        __import__(module)
    except ImportError:
        print(f"{package} o'rnatilmoqda...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", package])


_ensure("telethon", "telethon")
_ensure("qrcode", "qrcode[pil]")

import qrcode                                           # noqa: E402
from telethon import TelegramClient                     # noqa: E402
from telethon.errors import SessionPasswordNeededError  # noqa: E402


def load_api():
    api_id = api_hash = None
    env = os.path.join(BASE, ".env")
    if os.path.exists(env):
        for line in open(env, encoding="utf-8-sig"):
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                v = v.split(" #")[0].strip().strip('"').strip("'")
                if k.strip() == "API_ID" and v:
                    api_id = int(v)
                if k.strip() == "API_HASH" and v:
                    api_hash = v
    cfg = os.path.join(BASE, "userbot_config.json")
    if (not api_id or not api_hash) and os.path.exists(cfg):
        c = json.load(open(cfg, encoding="utf-8-sig"))
        api_id = api_id or int(c["api_id"])
        api_hash = api_hash or c["api_hash"]
    return api_id, api_hash


async def main():
    api_id, api_hash = load_api()
    client = TelegramClient(os.path.join(BASE, "my_account"), api_id, api_hash)
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"Allaqachon kirilgan: {me.first_name}. Hech narsa qilish shart emas.")
        await client.disconnect()
        return

    png = os.path.join(BASE, "login_qr.png")
    while True:
        qr = await client.qr_login()
        qrcode.make(qr.url).save(png)
        print("\n==============================================")
        print(" QR-kod ochildi (login_qr.png).")
        print(" Telefonda: Telegram -> Settings -> Devices ->")
        print("            Link Desktop Device -> QR-kodni skanerlang")
        print("==============================================")
        try:
            os.startfile(png)          # Windows: rasmni ochadi
        except Exception:
            print(f"Rasmni o'zingiz oching: {png}")
        try:
            await qr.wait(timeout=110)
            break
        except asyncio.TimeoutError:
            print("QR-kod eskirdi, yangisi chiqarilmoqda...")
        except SessionPasswordNeededError:
            pw = getpass.getpass("Ikki bosqichli parol (ekranda ko'rinmaydi): ")
            await client.sign_in(password=pw)
            break

    try:
        os.remove(png)
    except Exception:
        pass
    me = await client.get_me()
    print(f"\nTAYYOR! Kirildi: {me.first_name}")
    print("Endi oynani yoping va autostart_on.bat ni bosing.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
    input("\nEnter bosing...")
