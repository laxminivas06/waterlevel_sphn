"""
app/time_utils.py - Timezone Management Subsystem
HydroSense IoT - Sphoorthy Engineering College (Hyderabad, Telangana, India)

Standard Timezone: India Standard Time (IST, UTC+05:30)
Ensures 100% time and date accuracy across all cloud deployments (PythonAnywhere, AWS, Render, Linux),
local hardware microcontrollers (NodeMCU ESP8266, ESP32), and frontend display components.
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Tuple, Union

# India Standard Time (IST) is UTC+05:30 with zero daylight saving transitions
IST = timezone(timedelta(hours=5, minutes=30))


def get_ist_now() -> datetime:
    """
    Returns the current datetime in Indian Standard Time (IST, UTC+05:30).
    Returned as a naive datetime object matching local Indian wall-clock time
    to allow seamless arithmetic with stored timestamp strings.
    """
    return datetime.now(IST).replace(tzinfo=None)


def get_ist_now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Returns the current IST datetime formatted as a string."""
    return get_ist_now().strftime(fmt)


def parse_to_ist(val: Any) -> Tuple[str, str]:
    """
    Parses any incoming timestamp value (ISO with Z, epoch integer/float, datetime object,
    or standard timestamp string) and returns a normalized tuple of:
    (timestamp_str: 'YYYY-MM-DD HH:MM:SS', date_str: 'YYYY-MM-DD') in IST.
    """
    if not val:
        now = get_ist_now()
        return now.strftime("%Y-%m-%d %H:%M:%S"), now.strftime("%Y-%m-%d")

    # Unix epoch timestamp (int or float)
    if isinstance(val, (int, float)):
        try:
            dt = datetime.fromtimestamp(val, tz=timezone.utc).astimezone(IST).replace(tzinfo=None)
            return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    # Datetime object
    if isinstance(val, datetime):
        if val.tzinfo is not None:
            dt = val.astimezone(IST).replace(tzinfo=None)
        else:
            dt = val
        return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.strftime("%Y-%m-%d")

    s = str(val).strip()
    if not s:
        now = get_ist_now()
        return now.strftime("%Y-%m-%d %H:%M:%S"), now.strftime("%Y-%m-%d")

    # Check for ISO string with timezone offset (e.g. 2026-11-09T07:05:52Z or +00:00)
    if s.endswith("Z") or ("+" in s[10:]) or ("-" in s[10:] and len(s) > 19):
        try:
            iso_str = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso_str).astimezone(IST).replace(tzinfo=None)
            return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    # Standard clean timestamp
    s_clean = s.replace("T", " ")[:19]
    try:
        dt = datetime.strptime(s_clean, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.strftime("%Y-%m-%d")
    except Exception:
        now = get_ist_now()
        return now.strftime("%Y-%m-%d %H:%M:%S"), now.strftime("%Y-%m-%d")
