#!/usr/bin/env python3
"""
Cytu.be chat → terminal client (read + write).

Connects to a cytu.be room via Socket.IO, prints chat with colored
usernames, and lets you send messages when logged in.

Usage:
    python3 cytube_chat.py 420Grindhouse                          # guest, read-only
    python3 cytube_chat.py 420Grindhouse --login myname           # login + send
    python3 cytube_chat.py 420Grindhouse --login myname --password mypass
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime

import warnings
warnings.filterwarnings("ignore", message=".*urllib3.*OpenSSL.*")

import requests
import socketio


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def strip_html(text: str) -> str:
    """Remove HTML tags and decode common entities."""
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    return text.strip()


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


# ═══════════════════════════════════════════════════════════════════
# Terminal colors
# ═══════════════════════════════════════════════════════════════════

class C:
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


NAME_COLORS = [C.BCYN, C.BGRN, C.BYEL, C.BMAG, C.BBLU,
               C.GRN, C.CYN, C.MAG, C.BLU, C.YEL, C.RED, C.BRED]


def name_color(name: str) -> str:
    h = hash(name.lower()) % len(NAME_COLORS)
    return NAME_COLORS[h]


def ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0).strftime("%H:%M")


META_FMT = {
    "server-whisper": (C.D + C.MAG, C.R),
    "announcement":  (C.B + C.BYEL, C.R),
    "action":        (C.MAG, C.R),
    "drink":         (C.D + C.GRN, C.R),
    "emote":         (C.MAG, C.R),
    "server-message": (C.D, C.R),
}


# ═══════════════════════════════════════════════════════════════════
# Server resolution
# ═══════════════════════════════════════════════════════════════════

def resolve_server(channel: str, base_url: str = "https://cytu.be") -> str:
    """Fetch the socket config and return the best backend server URL."""
    resp = requests.get(
        f"{base_url}/socketconfig/{channel}.json",
        headers={"Origin": base_url, "Referer": f"{base_url}/r/{channel}"},
        timeout=10,
    )
    resp.raise_for_status()
    config = resp.json()

    servers = config.get("servers", [])
    if not servers:
        raise RuntimeError(f"No servers found for channel '{channel}'")

    chosen = servers[0]
    for s in servers:
        if s.get("secure") and not chosen.get("secure"):
            chosen = s
        elif not s.get("ipv6Only") and chosen.get("ipv6Only"):
            chosen = s

    return chosen["url"]


# ═══════════════════════════════════════════════════════════════════
# Authentication
# ═══════════════════════════════════════════════════════════════════

def cytube_http_login(username: str, password: str, server: str) -> str | None:
    """Log into cytu.be via HTTP and return the auth cookie value."""
    s = requests.Session()
    try:
        r = s.get(f"{server}/login",
                  headers={"Origin": server, "Referer": f"{server}/"},
                  timeout=10)
        csrf = re.search(r'name="_csrf" value="([^"]+)"', r.text)
        if not csrf:
            return None
        s.post(f"{server}/login", data={
            "_csrf": csrf.group(1),
            "name": username,
            "password": password,
            "remember": "on",
        }, headers={"Origin": server, "Referer": f"{server}/login"},
            timeout=10, allow_redirects=True)
        return s.cookies.get("auth")
    except Exception:
        return None


def read_creds_file() -> tuple[str | None, str | None]:
    """Read ~/.cytube_creds, return (username, password) or (None, None)."""
    credfile = os.path.expanduser("~/.cytube_creds")
    if not os.path.exists(credfile):
        return None, None
    with open(credfile) as f:
        content = f.read().strip()
        lines = [l.strip() for l in content.split("\n")
                 if l.strip() and not l.startswith("#")]
        if len(lines) >= 2:
            return lines[0], lines[1]
        elif len(lines) >= 1:
            return lines[0], None
    return None, None


def resolve_credentials(username=None, password=None):
    """Resolve login credentials: CLI args > env vars > ~/.cytube_creds."""
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


# ═══════════════════════════════════════════════════════════════════
# Chat client
# ═══════════════════════════════════════════════════════════════════

class ChatClient:
    def __init__(self, channel, server, username, password,
                 hide_joins=False, hide_usercount=False, no_motd=False):
        self.channel = channel
        self.server = server
        self.username = username
        self.password = password
        self.hide_joins = hide_joins
        self.hide_usercount = hide_usercount
        self.no_motd = no_motd
        self.logged_in = False
        self.running = True
        self.auth_cookie = None
        self.sio = socketio.Client(logger=False, engineio_logger=False)
        self._setup_handlers()

    def _setup_handlers(self):
        sio = self.sio

        @sio.on("connect")
        def on_connect():
            sio.emit("joinChannel", {"name": self.channel})

        @sio.on("login")
        def on_login(data):
            if data.get("success"):
                self.logged_in = True
                name = data.get("name", self.username)
                print(f"\r{C.BGRN}✓ Logged in as {name}{C.R}")
                print(f"{C.D}> {C.R}", end="", flush=True)
            elif not data.get("guest", True):
                error = data.get("error", "Login failed")
                print(f"\r{C.BRED}✗ Login: {error}{C.R}")
                print(f"{C.D}> {C.R}", end="", flush=True)

        @sio.on("chatMsg")
        def on_chat_msg(data):
            username = data.get("username", "???")
            msg = data.get("msg", "")
            meta = data.get("meta", {})
            meta_class = meta.get("addClass", "")
            timestamp = data.get("time", int(time.time() * 1000))

            nc = name_color(username)
            prefix, suffix = META_FMT.get(meta_class, ("", ""))

            line = f"\r{C.D}{ts(timestamp)}{C.R} {prefix}{nc}{username}{C.R}"

            if meta_class in ("action", "emote"):
                line += f" {msg}"
            else:
                line += f"{suffix}{C.R}: {msg}"

            print(line)
            print(f"{C.D}> {C.R}", end="", flush=True)

        @sio.on("usercount")
        def on_usercount(data):
            if self.hide_usercount:
                return
            count = data if isinstance(data, int) else data
            print(f"\r{C.D}── {count} connected ──{C.R}")
            print(f"{C.D}> {C.R}", end="", flush=True)

        @sio.on("addUser")
        def on_add_user(data):
            if self.hide_joins:
                return
            name = data.get("name", "???")
            print(f"\r{C.D}→ {C.GRN}{name}{C.D} joined{C.R}")
            print(f"{C.D}> {C.R}", end="", flush=True)

        @sio.on("userLeave")
        def on_user_leave(data):
            if self.hide_joins:
                return
            name = data.get("name", "???")
            print(f"\r{C.D}← {C.RED}{name}{C.D} left{C.R}")
            print(f"{C.D}> {C.R}", end="", flush=True)

        @sio.on("setMotd")
        def on_set_motd(data):
            if self.no_motd:
                return
            text = strip_html(data)
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            if lines:
                banner = lines[0]
                if len(banner) > 100:
                    banner = banner[:97] + "..."
                print(f"\r{C.D}── {banner} ──{C.R}")
                print(f"{C.D}> {C.R}", end="", flush=True)

        @sio.on("kick")
        def on_kick(data):
            print(f"\r{C.BRED}Kicked: {data.get('reason', 'no reason')}{C.R}")
            self.running = False

        @sio.on("needPassword")
        def on_need_password(data):
            print(f"\r{C.BYEL}Channel requires a password. Use --password{C.R}")
            self.running = False

        @sio.on("disconnect")
        def on_disconnect():
            self.running = False

    def send(self, text: str) -> None:
        """Send a chat message. Strips surrounding whitespace, ignores empty."""
        msg = text.strip()
        if not msg:
            return
        if not self.logged_in:
            print(f"{C.BRED}Cannot send: not logged in. Use --login{C.R}")
            return
        self.sio.emit("chatMsg", {"msg": msg, "meta": {}})

    def _handle_command(self, line: str) -> None:
        """Handle /commands."""
        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()

        if cmd in ("/quit", "/exit"):
            print(f"{C.D}Disconnecting...{C.R}")
            self.running = False
            self.sio.disconnect()
        elif cmd == "/login":
            print(f"{C.BYEL}Already connected. "
                  f"Use --login to authenticate at startup.{C.R}")
        elif cmd == "/help":
            print(f"{C.D}Commands: /quit, /help  ── "
                  f"Type anything else to chat{C.R}")
        else:
            self.send(line)

    def input_loop(self) -> None:
        """Read stdin in a loop, send non-empty lines as chat messages."""
        if self.logged_in:
            print(f"{C.D}> {C.R}", end="", flush=True)
        else:
            print(f"{C.D}(guest, read-only)  "
                  f"Use --login NAME to send messages{C.R}")

        while self.running:
            try:
                line = sys.stdin.readline()
            except (KeyboardInterrupt, EOFError):
                break
            if not line:
                break

            stripped = line.rstrip("\n")
            if stripped.startswith("/"):
                self._handle_command(stripped)
            else:
                self.send(stripped)

            if self.running and self.sio.connected:
                print(f"{C.D}> {C.R}", end="", flush=True)

    def connect(self, backend: str) -> None:
        """Connect, authenticate via HTTP, and run input loop."""
        if self.username and self.password:
            print(f"{C.D}Logging in as {self.username}...{C.R}",
                  end="", flush=True)
            self.auth_cookie = cytube_http_login(
                self.username, self.password, self.server)
            if self.auth_cookie:
                print(f" {C.GRN}authenticated{C.R}")
            else:
                print(f" {C.BRED}HTTP login failed — connecting as guest{C.R}")
                self.auth_cookie = None

        headers = {"Origin": self.server}
        if self.auth_cookie:
            headers["Cookie"] = f"auth={self.auth_cookie}"

        print(f"{C.D}Connecting...{C.R}", end="", flush=True)
        self.sio.connect(
            backend,
            transports=["polling", "websocket"],
            headers=headers,
            wait_timeout=15,
        )
        print(f" {C.GRN}connected!{C.R}")
        self.input_loop()


# ═══════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════

def main():
    # Load .env from project directory (if it exists)
    load_dotenv(os.path.join(os.path.dirname(__file__) or ".", ".env"))

    parser = argparse.ArgumentParser(
        description="Cytu.be terminal chat client (read + write)")
    parser.add_argument("channel", help="Channel name (e.g. 420Grindhouse)")
    parser.add_argument("--server", default="https://cytu.be",
                        help="Cytu.be frontend URL")
    parser.add_argument("--login", default=None,
                        help="Cytu.be account username (for sending messages)")
    parser.add_argument("--password", default=None,
                        help="Account password (or set CYTUBE_PASSWORD env var)")
    parser.add_argument("--hide-joins", action="store_true",
                        help="Hide join/leave messages")
    parser.add_argument("--hide-usercount", action="store_true",
                        help="Hide user count")
    parser.add_argument("--no-motd", action="store_true",
                        help="Hide MOTD banner")
    args = parser.parse_args()

    login_user, login_pass = resolve_credentials(args.login, args.password)

    try:
        backend = resolve_server(args.channel, args.server)
    except Exception as e:
        print(f"{C.BRED}Failed to resolve channel server: {e}{C.R}")
        sys.exit(1)

    print(f"{C.B}{C.CYN}╔══════════════════════════════════╗{C.R}")
    print(f"{C.B}{C.CYN}║  cytu.be → {args.channel:<22s} ║{C.R}")
    print(f"{C.B}{C.CYN}╚══════════════════════════════════╝{C.R}")
    print(f"{C.D}backend: {backend}{C.R}")

    client = ChatClient(
        channel=args.channel,
        server=args.server,
        username=login_user,
        password=login_pass,
        hide_joins=args.hide_joins,
        hide_usercount=args.hide_usercount,
        no_motd=args.no_motd,
    )

    try:
        client.connect(backend)
    except KeyboardInterrupt:
        print(f"\n{C.D}Disconnecting...{C.R}")
    except Exception as e:
        print(f"\n{C.BRED}Connection error: {e}{C.R}")
        sys.exit(1)


if __name__ == "__main__":
    main()
