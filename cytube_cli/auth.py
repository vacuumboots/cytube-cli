"""Authentication: HTTP login, credential resolution, and .env loading."""

import os
import re
import sys

import requests


def load_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ (if it exists)."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key not in os.environ:
                os.environ[key] = value


def cytube_http_login(username: str, password: str, server: str) -> str | None:
    """Log into cytu.be via HTTP and return the auth cookie value."""
    s = requests.Session()
    try:
        r = s.get(
            f"{server}/login",
            headers={"Origin": server, "Referer": f"{server}/"},
            timeout=10,
        )
        csrf = re.search(r'name="_csrf" value="([^"]+)"', r.text)
        if not csrf:
            return None
        s.post(
            f"{server}/login",
            data={
                "_csrf": csrf.group(1),
                "name": username,
                "password": password,
                "remember": "on",
            },
            headers={"Origin": server, "Referer": f"{server}/login"},
            timeout=10,
            allow_redirects=True,
        )
        return s.cookies.get("auth")
    except requests.RequestException:
        return None


def read_creds_file() -> tuple[str | None, str | None]:
    """Read ~/.cytube_creds, return (username, password) or (None, None)."""
    credfile = os.path.expanduser("~/.cytube_creds")
    if not os.path.exists(credfile):
        return None, None
    with open(credfile) as f:
        content = f.read().strip()
        lines = [
            ln.strip()
            for ln in content.split("\n")
            if ln.strip() and not ln.startswith("#")
        ]
        if len(lines) >= 2:
            return lines[0], lines[1]
        elif len(lines) >= 1:
            return lines[0], None
    return None, None


def resolve_credentials(username=None, password=None):
    """Resolve login credentials: CLI args > env vars > ~/.cytube_creds."""
    if password and not username:
        print("Warning: --password requires --login; password ignored", file=sys.stderr)
        password = None
    if username and password:
        return username, password
    if username:
        pw = password or os.environ.get("CYTUBE_PASSWORD")
        if not pw:
            _, pw = read_creds_file()
        return username, pw
    u = os.environ.get("CYTUBE_USERNAME")
    p = os.environ.get("CYTUBE_PASSWORD")
    if u:
        return u, p
    return read_creds_file()
