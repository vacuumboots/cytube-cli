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

# ── Reconnect constants ────────────────────────────────────────
RECONNECT_BASE_DELAY = 1.0   # seconds
RECONNECT_MAX_DELAY = 30.0    # seconds
RECONNECT_BACKOFF = 2.0       # multiplier


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
        log_file=None,
    ):
        self.channel = channel
        self.server = server
        self.username = username
        self.password = password
        self.hide_joins = hide_joins
        self.hide_usercount = hide_usercount
        self.no_motd = no_motd
        self.log_file_path = log_file
        self.logged_in = False
        self.running = True
        self.auth_cookie = None
        self._input_buffer: list[str] = []
        self._users: set[str] = set()  # track who's in the room
        self._logfile = None
        self._reconnect = False  # True when we want to reconnect after disconnect
        self.sio = socketio.Client(logger=False, engineio_logger=False)
        self._setup_handlers()

    # ── Logging ──────────────────────────────────────────────────

    def _open_log(self) -> None:
        if self.log_file_path:
            self._logfile = open(self.log_file_path, "a", encoding="utf-8")

    def _close_log(self) -> None:
        if self._logfile:
            self._logfile.close()
            self._logfile = None

    def _log_line(self, line: str) -> None:
        """Write a plain-text line to the log file if one is open."""
        if self._logfile:
            # Strip ANSI for the log
            plain = strip_control(line)
            self._logfile.write(plain + "\n")
            self._logfile.flush()

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
                line = f"\r{C.BGRN}✓ Logged in as {name}{C.R}"
                print(line)
                self._log_line(line)
                self._redraw_prompt()
            elif not data.get("guest", True):
                error = data.get("error", "Login failed")
                line = f"\r{C.BRED}✗ Login: {error}{C.R}"
                print(line)
                self._log_line(line)
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
            self._log_line(line)
            self._redraw_prompt()

        @self.sio.on("usercount")
        def on_usercount(data):
            if self.hide_usercount:
                return
            line = f"\r{C.D}── {data} connected ──{C.R}"
            print(line)
            self._log_line(line)
            self._redraw_prompt()

        @self.sio.on("addUser")
        def on_add_user(data):
            name = data.get("name", "???")
            self._users.add(name)
            if self.hide_joins:
                return
            line = f"\r{C.D}→ {C.GRN}{name}{C.D} joined{C.R}"
            print(line)
            self._log_line(line)
            self._redraw_prompt()

        @self.sio.on("userLeave")
        def on_user_leave(data):
            name = data.get("name", "???")
            self._users.discard(name)
            if self.hide_joins:
                return
            line = f"\r{C.D}← {C.RED}{name}{C.D} left{C.R}"
            print(line)
            self._log_line(line)
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
                line = f"\r{C.D}── {banner} ──{C.R}"
                print(line)
                self._log_line(line)
                self._redraw_prompt()

        @self.sio.on("kick")
        def on_kick(data):
            line = f"\r{C.BRED}Kicked: {data.get('reason', 'no reason')}{C.R}"
            print(line)
            self._log_line(line)
            self.running = False
            self._reconnect = False

        @self.sio.on("needPassword")
        def on_need_password(data):
            line = f"\r{C.BYEL}Channel requires a password. Use --password{C.R}"
            print(line)
            self._log_line(line)
            self.running = False
            self._reconnect = False

        @self.sio.on("setUserList")
        def on_set_user_list(data):
            """Receive the full user list on join."""
            users = data if isinstance(data, list) else data.get("users", [])
            self._users = set(users)

        @self.sio.on("disconnect")
        def on_disconnect():
            # Let the reconnect loop handle reconnection
            pass

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
            line = f"{C.BRED}Cannot send: not logged in. Use --login{C.R}"
            print(line)
            self._log_line(line)
            return
        try:
            self.sio.emit("chatMsg", {"msg": msg, "meta": {}})
        except Exception:
            line = f"{C.BRED}Failed to send message (disconnected?){C.R}"
            print(line)
            self._log_line(line)

    def _handle_command(self, line: str) -> None:
        """Handle /commands."""
        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()

        if cmd in ("/quit", "/exit"):
            self._reconnect = False
            line = f"{C.D}Disconnecting...{C.R}"
            print(line)
            self._log_line(line)
            self.running = False
            self.sio.disconnect()
        elif cmd == "/login":
            line = (
                f"{C.BYEL}Already connected. "
                f"Use --login to authenticate at startup.{C.R}"
            )
            print(line)
            self._log_line(line)
        elif cmd == "/help":
            line = (
                f"{C.D}Commands: /quit, /names, /help  "
                f"──  Type anything else to chat{C.R}"
            )
            print(line)
            self._log_line(line)
        elif cmd == "/names":
            if self._users:
                names = ", ".join(sorted(self._users))
                line = f"{C.D}Users ({len(self._users)}): {names}{C.R}"
            else:
                line = f"{C.D}No user list available yet{C.R}"
            print(f"\r{line}")
            self._redraw_prompt()
        else:
            self.send(line)

    # ── Input loop ────────────────────────────────────────────────

    def input_loop(self) -> None:
        """Read stdin char-by-char so async handlers can redraw over partial input."""
        if self.logged_in:
            sys.stdout.write(f"{C.D}> {C.R}")
            sys.stdout.flush()
        else:
            line = f"{C.D}(guest, read-only)  Use --login NAME to send messages{C.R}"
            print(line)
            self._log_line(line)

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

    def _do_connect(self, backend: str) -> bool:
        """Connect to the backend. Returns True on success, False on failure."""
        headers = {"Origin": self.server}
        if self.auth_cookie:
            headers["Cookie"] = f"auth={self.auth_cookie}"

        self.sio.connect(
            backend,
            transports=["polling", "websocket"],
            headers=headers,
            wait_timeout=15,
        )
        return True

    def connect(self, backend: str) -> None:
        """Connect, authenticate via HTTP, and run input loop with auto-reconnect."""
        self._open_log()

        if self.username and self.password:
            line = f"{C.D}Logging in as {self.username}...{C.R}"
            print(line, end="", flush=True)
            self._log_line(line.rstrip())
            self.auth_cookie = cytube_http_login(
                self.username, self.password, self.server
            )
            if self.auth_cookie:
                line = f" {C.GRN}authenticated{C.R}"
                print(line)
                self._log_line(line)
            else:
                line = f" {C.BRED}HTTP login failed — connecting as guest{C.R}"
                print(line)
                self._log_line(line)
                self.auth_cookie = None

        self._reconnect = True
        delay = RECONNECT_BASE_DELAY

        while self.running:
            line = f"{C.D}Connecting...{C.R}"
            print(line, end="", flush=True)
            self._log_line(line.rstrip())
            try:
                self._do_connect(backend)
                line = f" {C.GRN}connected!{C.R}"
                print(line)
                self._log_line(line)
                delay = RECONNECT_BASE_DELAY  # reset backoff on success
                self.input_loop()
            except Exception as e:
                line = f" {C.BRED}failed: {e}{C.R}"
                print(line)
                self._log_line(line)

            if not self._reconnect:
                break

            if self.running:
                line = (
                    f"{C.D}Reconnecting in {delay:.0f}s...{C.R}"
                )
                print(line)
                self._log_line(line)
                time.sleep(delay)
                delay = min(delay * RECONNECT_BACKOFF, RECONNECT_MAX_DELAY)

        self._close_log()
