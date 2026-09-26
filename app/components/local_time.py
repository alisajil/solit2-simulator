"""Times as the server's clock shows them, with the zone named."""
from __future__ import annotations

from datetime import datetime

DATE_TIME = "%Y-%m-%d %H:%M %Z"
CLOCK = "%H:%M %Z"


def local_time(moment: datetime | None, fmt: str = DATE_TIME) -> str:
    return "—" if moment is None else moment.astimezone().strftime(fmt)
