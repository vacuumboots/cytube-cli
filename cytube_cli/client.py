"""Socket.IO chat client — connects to a cytu.be room and handles messages."""

import select
import sys
import termios
import time
import tty

import socketio

from cytube_cli.auth import cytube_http_login
from cytube_cli.colors import META_FMT
from cytube_cli.colors import C
from cytube_cli.colors import name_color
from cytube_cli.colors import strip_control
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
        self._input_buffer: list[str] = []
        self.sio = socketio.Client(logger=False, engineio_logger=False)
        self._setup_handlers()

    # ── Socket.IO event handlers ──────────────────────────────────

    def _setup_handlers(self):

        @self.sio.on("connect")
        def on_connect():
            self.sio.emit("joinChannel", {"name": self.channel})

        @self.sio.on("login")
        def on_login(data):
            if data.get("success"):
                self.logged_in = True
                name = data.get("name", self.username)
                print(f"\r{C.BGRN}✓ Logged in as {name}{C.R}")
                self._redraw_prompt()
            elif not data.get("guest", True):
                error = data.get("error", "Login failed")
                print(f"\r{C.BRED}✗ Login: {error}{C.R}")
                self._redraw_prompt()

        @self.sio.on("chatMsg")
        def on_chat_msg(data):
            username = data.get("username", "???")
            msg = strip_control(data.get("msg", ""))
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
            self._redraw_prompt()

        @self.sio.on("usercount")
        def on_usercount(data):
            if self.hide_usercount:
                return
            print(f"\r{C.D}── {data} connected ──{C.R}")
            self._redraw_prompt()

        @self.sio.on("addUser")
        def on_add_user(data):
            if self.hide_joins:
                return
            name = data.get("name", "???")
            print(f"\r{C.D}→ {C.GRN}{name}{C.D} joined{C.R}")
            self._redraw_prompt()

        @self.sio.on("userLeave")
        def on_user_leave(data):
            if self.hide_joins:
                return
            name = data.get("name", "???")
            print(f"\r{C.D}← {C.RED}{name}{C.D} left{C.R}")
            self._redraw_prompt()

        @self.sio.on("setMotd")
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
                self._redraw_prompt()

        @self.sio.on("kick")
        def on_kick(data):
            print(f"\r{C.BRED}Kicked: {data.get('reason', 'no reason')}{C.R}")
            self.running = False

        @self.sio.on("needPassword")
        def on_need_password(data):
            print(f"\r{C.BYEL}Channel requires a password. Use --password{C.R}")
            self.running = False

        @self.sio.on("disconnect")
        def on_disconnect():
            self.running = False

    # ── Prompt restoration ────────────────────────────────────────

    def _redraw_prompt(self) -> None:
        """Re-print the prompt with current partial input, thread-safe."""
        buffer = "".join(self._input_buffer)
        sys.stdout.write(f"\r\x1b[K{C.D}> {C.R}{buffer}")
        sys.stdout.flush()

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
        """Read stdin char-by-char so async handlers can redraw over partial input."""
        if self.logged_in:
            sys.stdout.write(f"{C.D}> {C.R}")
            sys.stdout.flush()
        else:
            print(f"{C.D}(guest, read-only)  Use --login NAME to send messages{C.R}")

        # Switch terminal to raw mode so we get keystrokes immediately
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        tty.setraw(fd)
        try:
            while self.running:
                r, _, _ = select.select([sys.stdin], [], [], 0.1)
                if not r:
                    continue
                ch = sys.stdin.read(1)
                if not ch:  # EOF
                    break
                if ch == "\r":  # Enter
                    line = "".join(self._input_buffer)
                    self._input_buffer.clear()
                    # Echo the newline
                    sys.stdout.write("\r\n")
                    sys.stdout.flush()
                    if line.startswith("/"):
                        self._handle_command(line)
                    else:
                        self.send(line)
                    if self.running and self.sio.connected:
                        sys.stdout.write(f"{C.D}> {C.R}")
                        sys.stdout.flush()
                elif ch in ("\x7f", "\x08"):  # Backspace
                    if self._input_buffer:
                        self._input_buffer.pop()
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()
                elif ch == "\x03":  # Ctrl-C
                    raise KeyboardInterrupt
                elif len(ch) == 1 and ord(ch) >= 0x20:  # Printable
                    self._input_buffer.append(ch)
                    sys.stdout.write(ch)
                    sys.stdout.flush()
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

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
