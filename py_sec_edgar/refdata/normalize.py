from __future__ import annotations

import re
from typing import Optional


_DIGITS_RE = re.compile(r"\d+")


def normalize_ticker(raw: object) -> Optional[str]:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    return value.upper()


def normalize_cik(raw: object) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw)
    digits = "".join(_DIGITS_RE.findall(text))
    if not digits:
        return None
    if len(digits) > 10:
        return digits[-10:]
    return digits.zfill(10)
