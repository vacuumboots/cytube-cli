"""Terminal colors, username color hashing, and text formatting."""

import hashlib
import re
from datetime import datetime


class C:
    """ANSI terminal color codes."""

    R = "\033[0m"
    B = "\033[1m"
    D = "\033[2m"
    RED = "\033[31m"
    GRN = "\033[32m"
    YEL = "\033[33m"
    BLU = "\033[34m"
    MAG = "\033[35m"
    CYN = "\033[36m"
    WHT = "\033[37m"
    BRED = "\033[91m"
    BGRN = "\033[92m"
    BYEL = "\033[93m"
    BBLU = "\033[94m"
    BMAG = "\033[95m"
    BCYN = "\033[96m"


# Color pool for deterministic per-user colors
NAME_COLORS = [
    C.BCYN,
    C.BGRN,
    C.BYEL,
    C.BMAG,
    C.BBLU,
    C.GRN,
    C.CYN,
    C.MAG,
    C.BLU,
    C.YEL,
    C.RED,
    C.BRED,
]


# Per-message-type formatting: (prefix, suffix) applied around username
META_FMT = {
    "server-whisper": (C.D + C.MAG, C.R),
    "announcement": (C.B + C.BYEL, C.R),
    "action": (C.MAG, C.R),
    "drink": (C.D + C.GRN, C.R),
    "emote": (C.MAG, C.R),
    "server-message": (C.D, C.R),
}


def name_color(name: str) -> str:
    """Return a stable ANSI color for a username (deterministic across sessions)."""
    h = int(hashlib.md5(name.lower().encode()).hexdigest(), 16) % len(NAME_COLORS)
    return NAME_COLORS[h]


def ts(ms: int) -> str:
    """Convert a unix-milliseconds timestamp to HH:MM string."""
    return datetime.fromtimestamp(ms / 1000.0).strftime("%H:%M")


def strip_html(text: str) -> str:
    """Remove HTML tags and decode common entities."""
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    return text.strip()


def strip_control(text: str) -> str:
    """Strip ANSI escape sequences and other control characters from text."""
    # ANSI escape sequences: ESC [ ... m (or other terminator)
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
    # Other control chars except tab, newline, carriage return
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text
