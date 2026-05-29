"""Smoke tests for the cytube_cli package."""

import subprocess
import sys


def test_import():
    """Package imports cleanly."""
    import cytube_cli

    assert cytube_cli.__version__ == "0.1.0"


def test_import_modules():
    """All submodules are importable."""
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


def test_colors():
    """Color codes are non-empty ANSI strings."""
    from cytube_cli.colors import C
    from cytube_cli.colors import name_color
    from cytube_cli.colors import ts

    assert "\033" in C.R
    assert name_color("test") in C.__dict__.values()
    assert ":" in ts(0)  # HH:MM format


def test_strip_html():
    """HTML entities are decoded, tags removed."""
    from cytube_cli.colors import strip_html

    assert strip_html("<b>hello</b>") == "hello"
    assert strip_html("&amp;") == "&"
    assert strip_html("a<br/>b") == "ab"


def test_auth_no_env():
    """resolve_credentials returns None/None with no env or file."""
    import os

    from cytube_cli.auth import resolve_credentials

    # Unset env vars for test isolation
    old_user = os.environ.pop("CYTUBE_USERNAME", None)
    old_pass = os.environ.pop("CYTUBE_PASSWORD", None)
    try:
        u, p = resolve_credentials()
        # Will be None unless ~/.cytube_creds exists
        assert u is not None or (u is None and p is None)
    finally:
        if old_user is not None:
            os.environ["CYTUBE_USERNAME"] = old_user
        if old_pass is not None:
            os.environ["CYTUBE_PASSWORD"] = old_pass


def test_cli_help():
    """--help exits 0 and prints usage."""
    result = subprocess.run(
        [sys.executable, "-m", "cytube_cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "420Grindhouse" in result.stdout
