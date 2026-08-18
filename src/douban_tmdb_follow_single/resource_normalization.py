import re
import unicodedata
from typing import Any


_CHINESE_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "壹": 1, "二": 2, "两": 2, "贰": 2,
    "三": 3, "叁": 3, "四": 4, "肆": 4, "五": 5, "伍": 5,
    "六": 6, "陆": 6, "七": 7, "柒": 7, "八": 8, "捌": 8,
    "九": 9, "玖": 9,
}
_CHINESE_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100}
_CHINESE_NUMBER = "零〇一二两三四五六七八九十百壹贰叁肆伍陆柒捌玖拾佰"


def normalize_media_title(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)


def extract_year(value: Any) -> int:
    found = re.search(r"\b((?:19|20)\d{2})\b", str(value or ""))
    return int(found.group(1)) if found else 0


def _chinese_number(value: Any) -> int:
    text = str(value or "")
    if not text:
        return 0
    if not any(char in _CHINESE_UNITS for char in text):
        values = [str(_CHINESE_DIGITS[char]) for char in text if char in _CHINESE_DIGITS]
        return int("".join(values)) if values else 0
    total = 0
    current = 0
    for char in text:
        if char in _CHINESE_DIGITS:
            current = _CHINESE_DIGITS[char]
        elif char in _CHINESE_UNITS:
            total += (current or 1) * _CHINESE_UNITS[char]
            current = 0
    return total + current


def extract_season(value: Any) -> int:
    text = str(value or "")
    found = re.search(
        r"(?i)(?:\bS\s*0*(\d{1,2})(?:\b|(?=E))|\bseason\s*0*(\d{1,2})\b|"
        r"第\s*0*(\d{1,2})\s*(?:季|部))",
        text,
    )
    if found:
        return int(next(item for item in found.groups() if item is not None))
    chinese = re.search(
        r"第?\s*([%s]{1,6})\s*(?:季|部)" % _CHINESE_NUMBER,
        text,
    )
    return _chinese_number(chinese.group(1)) if chinese else 0
