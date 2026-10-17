"""Business time helpers. Stored timestamps are UTC. Business dates are Asia/Kolkata."""
from datetime import datetime, timezone, timedelta
from typing import Optional

IST = timezone(timedelta(hours=5, minutes=30))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def business_today() -> str:
    return now_utc().astimezone(IST).date().isoformat()


def business_month() -> str:
    return now_utc().astimezone(IST).strftime("%Y%m")


def as_utc(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def business_date_of(value: str) -> str:
    parsed = as_utc(value)
    if not parsed:
        return str(value or "")[:10]
    return parsed.astimezone(IST).date().isoformat()


def business_month_of(value: str) -> str:
    parsed = as_utc(value)
    if not parsed:
        return str(value or "")[:7]
    return parsed.astimezone(IST).strftime("%Y-%m")
