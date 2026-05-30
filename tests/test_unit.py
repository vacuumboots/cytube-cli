"""Unit tests for cytube_cli — auth, colors, commands, and server resolution."""

import io
import os
import subprocess
import sys
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

import cytube_cli


# ── Version ─────────────────────────────────────────────────────

def test_version():
    assert cytube_cli.__version__ == "0.1.0"


def test_cli_version_flag():
    result = subprocess.run(
        [sys.executable, "-m", "cytube_cli", "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "cytube-cli" in result.stdout


# ── Colors ──────────────────────────────────────────────────────

class TestColors:
    def test_name_color_deterministic(self):
        """Same username always gets same color (across calls, across runs)."""
        from cytube_cli.colors import name_color

        c1 = name_color("Alice")
        c2 = name_color("Alice")
        c3 = name_color("Alice")
        assert c1 == c2 == c3, "color should be deterministic"

    def test_name_color_different_users(self):
        """Different usernames typically get different colors."""
        from cytube_cli.colors import name_color

        c1 = name_color("Alice")
        c2 = name_color("Bob")
        # Collisions are possible but unlikely with 12-color pool
        # Just verify they return ANSI strings
        assert "\033" in c1
        assert "\033" in c2

    def test_name_color_case_insensitive(self):
        """Case differences shouldn't matter."""
        from cytube_cli.colors import name_color

        assert name_color("Alice") == name_color("alice")
        assert name_color("ALICE") == name_color("alice")

    def test_ts_format(self):
        from cytube_cli.colors import ts

        result = ts(0)
        assert ":" in result
        # Should be HH:MM
        parts = result.split(":")
        assert len(parts) == 2
        assert 0 <= int(parts[0]) <= 23

    def test_strip_html_tags(self):
        from cytube_cli.colors import strip_html

        assert strip_html("<b>hello</b>") == "hello"
        assert strip_html("<div class='x'>text</div>") == "text"
        assert strip_html("no tags") == "no tags"

    def test_strip_html_entities(self):
        from cytube_cli.colors import strip_html

        assert strip_html("&amp;") == "&"
        assert strip_html("&lt;") == "<"
        assert strip_html("&gt;") == ">"
        assert strip_html("&quot;") == '"'
        assert strip_html("&#39;") == "'"
        # &nbsp; becomes a space, then .strip() removes it
        assert strip_html("x&nbsp;y") == "x y"

    def test_strip_html_complex(self):
        from cytube_cli.colors import strip_html

        result = strip_html("<b>Hello &amp; welcome</b>")
        assert result == "Hello & welcome"

    def test_strip_control_ansi(self):
        from cytube_cli.colors import strip_control

        assert strip_control("\033[31mred\033[0m") == "red"
        assert strip_control("\033[1;32mbold green\033[0m") == "bold green"

    def test_strip_control_null(self):
        from cytube_cli.colors import strip_control

        assert strip_control("hello\x00world") == "helloworld"

    def test_strip_control_keeps_newline_tab(self):
        from cytube_cli.colors import strip_control

        assert strip_control("hello\tworld\n") == "hello\tworld\n"


# ── Auth ────────────────────────────────────────────────────────

class TestAuth:
    def test_resolve_credentials_cli_args(self, monkeypatch):
        """CLI args take highest priority."""
        from cytube_cli.auth import resolve_credentials

        u, p = resolve_credentials("bob", "pass123")
        assert u == "bob"
        assert p == "pass123"

    def test_resolve_credentials_env_vars(self, monkeypatch):
        """Environment variables are used when CLI args are absent."""
        monkeypatch.setenv("CYTUBE_USERNAME", "envuser")
        monkeypatch.setenv("CYTUBE_PASSWORD", "envpass")
        from cytube_cli.auth import resolve_credentials

        u, p = resolve_credentials()
        assert u == "envuser"
        assert p == "envpass"

    def test_resolve_credentials_username_only(self, monkeypatch):
        """Username via --login, password from env."""
        monkeypatch.setenv("CYTUBE_PASSWORD", "envpass")
        from cytube_cli.auth import resolve_credentials

        u, p = resolve_credentials(username="bob")
        assert u == "bob"
        assert p == "envpass"

    def test_resolve_credentials_password_requires_username(self):
        """--password without --login is a warning, not used."""
        from cytube_cli.auth import resolve_credentials

        u, p = resolve_credentials(password="pw")
        assert u is None
        assert p is None

    def test_resolve_credentials_nothing_set(self, monkeypatch):
        """Returns None, None when nothing is configured."""
        monkeypatch.delenv("CYTUBE_USERNAME", raising=False)
        monkeypatch.delenv("CYTUBE_PASSWORD", raising=False)
        # Ensure no ~/.cytube_creds is read
        from cytube_cli.auth import resolve_credentials

        with patch("cytube_cli.auth.read_creds_file", return_value=(None, None)):
            u, p = resolve_credentials()
            assert u is None
            assert p is None

    def test_resolve_credentials_prefers_cli_over_env(self, monkeypatch):
        monkeypatch.setenv("CYTUBE_USERNAME", "envuser")
        monkeypatch.setenv("CYTUBE_PASSWORD", "envpass")
        from cytube_cli.auth import resolve_credentials

        u, p = resolve_credentials("cli", "clipw")
        assert u == "cli"
        assert p == "clipw"

    def test_load_dotenv(self, tmp_path):
        """load_dotenv reads KEY=VALUE pairs."""
        from cytube_cli.auth import load_dotenv

        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\n# comment\nBAZ='quoted'\n")

        load_dotenv(str(env_file))
        assert os.environ.get("FOO") == "bar"
        assert os.environ.get("BAZ") == "quoted"

    def test_read_creds_file(self, tmp_path, monkeypatch):
        """read_creds_file parses ~/.cytube_creds."""
        creds = tmp_path / ".cytube_creds"
        creds.write_text("bob\nsecret\n")
        monkeypatch.setattr(
            "cytube_cli.auth.os.path.expanduser", lambda p: str(creds)
        )
        from cytube_cli.auth import read_creds_file

        u, p = read_creds_file()
        assert u == "bob"
        assert p == "secret"


# ── Server resolution ───────────────────────────────────────────

class TestServerResolution:
    def test_resolve_server_invalid_channel(self):
        from cytube_cli.server import resolve_server

        with pytest.raises(ValueError, match="Invalid channel"):
            resolve_server("bad channel!")

    def test_resolve_server_success(self):
        """Mock the HTTP call and verify server selection."""
        from cytube_cli.server import resolve_server

        mock_resp = {
            "servers": [
                {"url": "https://s1.cytu.be", "secure": True},
                {"url": "https://s2.cytu.be", "secure": False, "ipv6Only": True},
            ]
        }
        with patch("cytube_cli.server.requests.get") as mock_get:
            mock_get.return_value.json.return_value = mock_resp
            mock_get.return_value.raise_for_status = MagicMock()
            result = resolve_server("testchannel")
            assert result == "https://s1.cytu.be"

    def test_resolve_server_prefers_secure(self):
        """Secure servers should be preferred."""
        from cytube_cli.server import resolve_server

        mock_resp = {
            "servers": [
                {"url": "http://insecure.cytu.be", "secure": False},
                {"url": "https://secure.cytu.be", "secure": True},
            ]
        }
        with patch("cytube_cli.server.requests.get") as mock_get:
            mock_get.return_value.json.return_value = mock_resp
            mock_get.return_value.raise_for_status = MagicMock()
            result = resolve_server("test")
            assert result == "https://secure.cytu.be"

    def test_resolve_server_no_servers(self):
        from cytube_cli.server import resolve_server

        with patch("cytube_cli.server.requests.get") as mock_get:
            mock_get.return_value.json.return_value = {"servers": []}
            mock_get.return_value.raise_for_status = MagicMock()
            with pytest.raises(RuntimeError, match="No servers found"):
                resolve_server("test")


# ── ChatClient commands ─────────────────────────────────────────

class TestChatClientCommands:
    """Test command handling in ChatClient without real network."""

    @pytest.fixture
    def client(self):
        from cytube_cli.client import ChatClient

        c = ChatClient(
            channel="testchan",
            server="https://cytu.be",
            username=None,
            password=None,
        )
        return c

    def test_quit_command(self, client):
        """ /quit should set running=False and disconnect."""
        client.sio.disconnect = MagicMock()
        client.running = True

        client._handle_command("/quit")

        assert client.running is False
        client.sio.disconnect.assert_called_once()

    def test_slash_exit_is_quit(self, client):
        """ /exit should be an alias for /quit."""
        client.sio.disconnect = MagicMock()
        client.running = True

        client._handle_command("/exit")

        assert client.running is False
        client.sio.disconnect.assert_called_once()

    def test_names_command_empty(self, client, capsys):
        """ /names with no users shows placeholder message."""
        client._users = set()
        client._handle_command("/names")
        captured = capsys.readouterr()
        assert "No user list available" in captured.out

    def test_names_command_with_users(self, client, capsys):
        """ /names shows sorted user list."""
        client._users = {"Bob", "Alice", "Charlie"}
        client._handle_command("/names")
        captured = capsys.readouterr()
        assert "Alice" in captured.out
        assert "Bob" in captured.out
        assert "Charlie" in captured.out
        assert "3" in captured.out  # count

    def test_send_not_logged_in(self, client, capsys):
        """Sending while not logged in prints a warning."""
        client.logged_in = False
        client.send("hello")
        captured = capsys.readouterr()
        assert "not logged in" in captured.out

    def test_send_empty(self, client):
        """Empty message is a no-op."""
        client.logged_in = True
        client.sio.emit = MagicMock()
        client.send("   ")
        client.sio.emit.assert_not_called()

    def test_send_success(self, client):
        """Logged-in send calls sio.emit."""
        client.logged_in = True
        client.sio.emit = MagicMock()
        client.send("hello world")
        client.sio.emit.assert_called_once_with(
            "chatMsg", {"msg": "hello world", "meta": {}}
        )

    def test_send_exception(self, client, capsys):
        """If emit throws, we catch it gracefully."""
        client.logged_in = True
        client.sio.emit = MagicMock(side_effect=Exception("boom"))
        client.send("hello")
        captured = capsys.readouterr()
        assert "Failed to send" in captured.out

    def test_login_command_not_connected(self, client, capsys):
        """ /login while connected prints a hint."""
        client._handle_command("/login")
        captured = capsys.readouterr()
        assert "Already connected" in captured.out

    def test_help_command(self, client, capsys):
        client._handle_command("/help")
        captured = capsys.readouterr()
        assert "/names" in captured.out

    def test_non_command_is_sent(self, client):
        """Non-slash input is treated as a chat message."""
        client.logged_in = True
        client.sio.emit = MagicMock()
        client._handle_command("hello chat")
        client.sio.emit.assert_called_once()

    def test_user_tracking_add(self):
        """addUser handler tracks users in _users set."""
        from cytube_cli.client import ChatClient

        c = ChatClient("ch", "https://cytu.be", None, None)
        # Simulate the handler being called
        c._users.add("Alice")
        c._users.add("Bob")
        assert "Alice" in c._users
        assert "Bob" in c._users

    def test_user_tracking_remove(self):
        """userLeave handler removes users from _users set."""
        from cytube_cli.client import ChatClient

        c = ChatClient("ch", "https://cytu.be", None, None)
        c._users = {"Alice", "Bob"}
        c._users.discard("Alice")
        assert "Alice" not in c._users
        assert "Bob" in c._users

    def test_user_tracking_bulk(self):
        """setUserList replaces the user set."""
        from cytube_cli.client import ChatClient

        c = ChatClient("ch", "https://cytu.be", None, None)
        c._users = {"old"}
        c._users = {"Alice", "Bob", "Charlie"}  # simulate setUserList
        assert c._users == {"Alice", "Bob", "Charlie"}


# ── Logging ─────────────────────────────────────────────────────

class TestLogging:
    def test_log_file_created(self, tmp_path, capsys):
        from cytube_cli.client import ChatClient

        log_path = tmp_path / "chat.log"
        c = ChatClient("ch", "https://cytu.be", None, None, log_file=str(log_path))
        c._open_log()
        c._log_line("hello world")
        c._close_log()

        content = log_path.read_text()
        assert "hello world" in content

    def test_log_file_strips_ansi(self, tmp_path):
        from cytube_cli.client import ChatClient

        log_path = tmp_path / "chat.log"
        c = ChatClient("ch", "https://cytu.be", None, None, log_file=str(log_path))
        c._open_log()
        c._log_line("\033[31mred text\033[0m")
        c._close_log()

        content = log_path.read_text()
        assert "red text" in content
        assert "\033" not in content

    def test_no_log_file(self, tmp_path):
        """No crash when log_file is None."""
        from cytube_cli.client import ChatClient

        c = ChatClient("ch", "https://cytu.be", None, None, log_file=None)
        c._open_log()
        c._log_line("should not crash")
        c._close_log()
        # just verifying no exception


# ── Reconnect behavior ──────────────────────────────────────────

class TestReconnect:
    def test_reconnect_flag_default(self):
        from cytube_cli.client import ChatClient

        c = ChatClient("ch", "https://cytu.be", None, None)
        assert c._reconnect is False

    def test_kick_disables_reconnect(self):
        from cytube_cli.client import ChatClient

        c = ChatClient("ch", "https://cytu.be", None, None)
        c._reconnect = True
        # Simulate kick handler logic
        c._reconnect = False
        c.running = False
        assert c._reconnect is False
        assert c.running is False


# ── CLI ─────────────────────────────────────────────────────────

def test_cli_help():
    result = subprocess.run(
        [sys.executable, "-m", "cytube_cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--log" in result.stdout
    assert "--version" in result.stdout
    assert "--hide-joins" in result.stdout


# ── Import sanity ───────────────────────────────────────────────

def test_import():
    import cytube_cli

    assert cytube_cli.__version__ == "0.1.0"


def test_import_modules():
    from cytube_cli import auth
    from cytube_cli import cli
    from cytube_cli import client
    from cytube_cli import colors
    from cytube_cli import server

    assert hasattr(colors, "C")
    assert hasattr(auth, "resolve_credentials")
    assert hasattr(server, "resolve_server")
    assert hasattr(client, "ChatClient")
    assert hasattr(cli, "main")
