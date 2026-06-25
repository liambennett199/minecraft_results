"""Time helpers."""
from __future__ import annotations

import time


def utc_now_ts() -> int:
    return int(time.time())

