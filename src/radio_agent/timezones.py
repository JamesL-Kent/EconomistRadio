from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def load_timezone(name: str) -> ZoneInfo:
    """Load an IANA timezone with a clear operator-facing error on Windows hosts."""
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as error:
        raise RuntimeError(
            f"Timezone '{name}' could not be loaded. Install the Python 'tzdata' package "
            "or change station.timezone to a valid IANA timezone."
        ) from error
