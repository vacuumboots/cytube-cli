"""Socket.IO chat client — connects to a cytu.be room and handles messages."""

import sys
import time

import socketio

from cytube_cli.auth import cytube_http_login
from cytube_cli.colors import META_FMT
from cytube_cli.colors import C
from cytube_cli.colors import name_color
from cytube_cli.colors import strip_html
from cytube_cli.colors import ts


class ChatClient:
    """Connect to a cytu.be room, print chat, and optionally send messages."""

    def __init__(
        self,
        channel,
        server,
        username,
        password,
        hide_joins=False,
        hide_usercount=False,
        no_motd=False,
    ):
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

    # ── Socket.IO event handlers ──────────────────────────────────

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
            print(f"\r{C.D}── {data} connected ──{C.R}")
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
            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
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

    # ── Sending ───────────────────────────────────────────────────

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
            print(
                f"{C.BYEL}Already connected. "
                f"Use --login to authenticate at startup.{C.R}"
            )
        elif cmd == "/help":
            print(f"{C.D}Commands: /quit, /help  ── Type anything else to chat{C.R}")
        else:
            self.send(line)

    # ── Input loop ────────────────────────────────────────────────

    def input_loop(self) -> None:
        """Read stdin in a loop, send non-empty lines as chat messages."""
        if self.logged_in:
            print(f"{C.D}> {C.R}", end="", flush=True)
        else:
            print(f"{C.D}(guest, read-only)  Use --login NAME to send messages{C.R}")

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

    # ── Connection ────────────────────────────────────────────────

    def connect(self, backend: str) -> None:
        """Connect, authenticate via HTTP, and run input loop."""
        if self.username and self.password:
            print(f"{C.D}Logging in as {self.username}...{C.R}", end="", flush=True)
            self.auth_cookie = cytube_http_login(
                self.username, self.password, self.server
            )
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
