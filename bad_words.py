"""
Haqoratli so'zlar filtri: o'zbekcha (lotin + kirill), ruscha (kirill + lotin), inglizcha.

Yangi so'z qo'shish: so'zni oddiy yozilishida kerakli ro'yxatga qo'shing.
Normallashtirish avtomatik (kirill -> lotin, @ -> a, $ -> s, h -> x, takroriy harflar va h.k.).

  EXACT     — faqat aynan shu so'z bo'lsa ("mol" -> "mol-mulk"ga tegmaydi)
  PREFIX    — so'z shu bilan boshlansa ("ahmoq" -> "ahmoqsan", "ahmoqlar")
  SUBSTRING — so'z ichida qayerda bo'lsa ham ("fuck" -> "motherfucker")
"""

import re

# ======================================================
# SO'Z RO'YXATLARI
# ======================================================

EXACT = [
    # ---------- o'zbekcha ----------
    "mol", "yaramas", "la'nati", "sharmanda", "chumo", "nodon", "daun",
    "ho'kiz", "beor", "qo'rqoq", "yuzsiz",
    # ---------- ruscha ----------
    "хуй", "хуи", "хер", "нах", "нахер", "похер", "бля", "сука", "суки", "дура",
    "тварь", "чмо", "лох", "козёл", "тупой", "тупица", "мразь", "манда", "курва",
    "шмара", "свинья", "даун", "ёпт", "ёпта", "ёб", "соси", "гей", "петух",
    "blya", "suka", "xuy", "huy", "nax", "naxer", "poxer", "ept", "epta",
    # ---------- inglizcha ----------
    "shit", "shits", "shitty", "shithead", "bullshit", "dick", "dickhead", "cock",
    "pussy", "dumb", "wtf", "stfu", "gtfo", "ffs", "kys", "nigga", "fuk", "fuking",
    "faggot", "fag", "loser", "jerk", "prick", "arse", "crap", "hoe",
]

PREFIX = [
    # ---------- o'zbekcha ----------
    "ahmoq", "ahmok", "tentak", "jinni", "telba", "dovdir", "kallavaram",
    "miyasiz", "aqlsiz", "befarosat", "beadab", "iflos", "haromi", "haromzoda",
    "eshak", "to'ng'iz", "tongiz", "cho'chqa", "itvachcha", "itbet",
    "jalab", "jalap", "qahba", "qanjiq", "fohisha", "buzuqi",
    "qo'toq", "qotaq", "ko'tak", "ko'ting",
    "xezalak", "xunasa", "nomard", "ablah", "badbaxt", "padarla'nat",
    "o'lgur", "yutgur", "tupoy", "pedik",
    "sikay", "sikam", "sikd", "sikib", "sikish", "siktir", "sikvor", "sikas",
    "dalbayob", "dolboyob", "dolba", "dalba", "gandon",
    # ---------- ruscha (kirill yozilsa ham avtomatik lotinga o'tadi) ----------
    "дебил", "идиот", "кретин", "имбецил", "дурак", "придур", "урод", "ублюд",
    "сволоч", "скотин", "гнид", "падла", "падлюк", "залуп", "мандавош",
    "шалав", "шлюх", "шлюш", "shlux", "пидор", "пидар", "пидр", "педик", "педрил",
    "мудак", "мудил", "мудоз", "сукин", "сучк", "сучар", "долбо", "жопа",
    "дерьмо", "засран", "дроч", "отсос", "лошар", "тупорыл", "чурк",
    # ---------- inglizcha ----------
    "idiot", "stupid", "moron", "retard", "imbecil", "bastard", "bitch",
    "asshole", "arsehole", "dumbass", "jackass", "dipshit", "cunt", "whore",
    "slut", "skank", "twat", "wanker", "douche", "bollock", "fck",
]

SUBSTRING = [
    # ---------- ruscha mat ildizlari ----------
    "пизд", "бляд", "блят", "говн",
    "хуе", "хуё", "хуйн", "хуйл", "хуев", "нахуй", "похуй", "охуе", "хуес",
    "pizd", "blyad", "blyat", "naxuy", "poxuy",
    # ---------- inglizcha ----------
    "fuck", "motherf",
]

# еб- oilasi (ебать, заебал, уёбок, ёбаный ...) — alohida qoida,
# "колебать", "yeb qo'ydi" kabi oddiy so'zlarga tegmasligi uchun
EB_RE = re.compile(
    r"^(?:za|na|po|ot|u|vi|vy|do|raz|ras|o|ob|pri|pod|pro|vz|s)?y?"
    r"eb(?:an|al|at|as|ut|uc|ok|isx|is|l|n)"
)


# ======================================================
# NORMALLASHTIRISH
# ======================================================

_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "",
    "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    # o'zbek kirill
    "ў": "o", "қ": "q", "ғ": "g", "ҳ": "x",
}
_LEET = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "!": "i", "|": "i"}


def _prepare(text: str) -> str:
    text = text.lower()
    text = "".join(_CYR.get(ch, ch) for ch in text)
    text = re.sub(r"[‘’ʻʼ'`´]", "", text)          # apostroflarni olib tashlash
    text = text.replace("@", "a").replace("$", "s")  # @ = a, $ = s
    # harflar orasidagi . * _ - belgilarini olib tashlash (a.h.m.o.q, s-u-k-a)
    text = re.sub(r"(?<=[a-z0-9])[.*_\-](?=[a-z0-9@$!|])", "", text)
    return text


def _norm_token(tok: str, collapse: bool = True) -> str:
    tok = tok.strip("!|")
    tok = "".join(_LEET.get(ch, ch) for ch in tok)
    tok = tok.replace("h", "x")                     # h / x farqi yo'q
    if collapse:
        tok = re.sub(r"(.)\1+", r"\1", tok)         # ahmooooq -> ahmoq
    return tok


def _tokens(text: str, collapse: bool = True):
    for tok in re.findall(r"[a-z0-9!|]+", _prepare(text)):
        if re.search(r"[a-z]", tok):                # faqat raqamlardan iborat bo'lsa — o'tkazib yuborish
            yield _norm_token(tok, collapse)


def _norm_word(word: str) -> str:
    return "".join(_tokens(word))


# Takroriy harflarni qisqartirmasdan tekshiriladigan so'zlar
# (masalan "nigger" qisqartirilsa "niger" — davlat nomi bo'lib qoladi)
EXACT_RAW = ["nigger", "niggers", "niggas"]

_EXACT = {_norm_word(w) for w in EXACT}
_EXACT_RAW = {"".join(_tokens(w, collapse=False)) for w in EXACT_RAW}
_PREFIX = tuple(_norm_word(w) for w in PREFIX)
_SUBSTRING = tuple(_norm_word(w) for w in SUBSTRING)


# ======================================================
# TEKSHIRISH
# ======================================================

def find_bad_word(text: str):
    """Topilgan haqoratli so'zni qaytaradi (yoki None)."""
    for raw in _tokens(text, collapse=False):
        if raw in _EXACT_RAW:
            return raw
    for tok in _tokens(text):
        if (
            tok in _EXACT
            or tok.startswith(_PREFIX)
            or any(root in tok for root in _SUBSTRING)
            or EB_RE.match(tok)
        ):
            return tok
    return None


def contains_bad_word(text: str) -> bool:
    return find_bad_word(text) is not None
