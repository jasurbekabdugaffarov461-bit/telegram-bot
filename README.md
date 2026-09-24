# telegram-bot

Ikki qismdan iborat Telegram loyiha:

1. **`bot.py`**: guruh moderatori (python-telegram-bot). U quyidagilarni qiladi:
   - salom va xayrga javob beradi;
   - haqoratli xabarni o'chirib, ogohlantiradi (1/3, 2/3, 3/3);
   - 3-ogohlantirishdan keyin foydalanuvchini 60 daqiqaga yozishdan cheklaydi (mute).
2. **`userbot.py`**: shaxsiy akkaunt uchun AI yordamchi (Telethon + Gemini). U quyidagilarni qiladi:
   - lichkaga kelgan xabarlarga "Muhammad Alining shaxsiy AI yordamchisi" sifatida javob beradi;
   - so'kinishga ogohlantirish beradi;
   - `/ai on`, `/ai off` va `/ai status` buyruqlari bilan boshqariladi.

`bad_words.py`: o'zbekcha (lotin va kirill), ruscha va inglizcha haqorat filtri. U `@`→a, `$`→s kabi almashtirishlarni, harf takrorlanishini (ahmooooq) va nuqta bilan bo'lingan yozuvlarni (a.h.m.o.q) ham aniqlaydi.

## O'rnatish

```bash
pip install -r requirements.txt telethon google-genai
```

Maxfiy sozlamalar fayllarini namunadan nusxa ko'chirib yarating. Bu fayllar `.gitignore` da, shuning uchun GitHub'ga yuklanmaydi.

```bash
cp bot_config.example.json bot_config.json          # BotFather tokeni
cp userbot_config.example.json userbot_config.json  # api_id, api_hash, gemini_api_key
```

## Ishga tushirish

```bash
python bot.py        # guruh boti
python userbot.py    # birinchi marta telefon raqam va kodni so'raydi
```

Windows'da `run.bat` va `run_userbot.bat` fayllarini ishlatish mumkin. Userbot'ni oynasiz, fonda ishga tushirish uchun `start_userbot_hidden.vbs` ni bosing.

## VPS'ga joylash (Ubuntu/Debian)

Windows'da `deploy_vps.bat` ni ishga tushiring. U quyidagilarni bajaradi:

1. Fayllarni serverga yuklaydi.
2. `setup_vps.sh` ni ishga tushiradi.
3. Ikkala botni systemd xizmati (`tgbot`, `userbot`) sifatida yoqadi.

Loglarni ko'rish uchun:

```bash
journalctl -u userbot -f
journalctl -u tgbot -f
```

## Userbot AI buyruqlari

| Qayerga yoziladi | Buyruq | Natija |
|---|---|---|
| Saved Messages | `/ai off` / `/ai on` | AI barcha chatlar uchun o'chadi / yoqiladi |
| Saved Messages | `/ai status` | Hozirgi holatni ko'rsatadi |
| Biror odam bilan chat | `/ai off` / `/ai on` | Bot faqat shu chatda o'chadi / yoqiladi |
