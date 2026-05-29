#!/usr/bin/env python3
"""Compatibility shim — delegates to the cytube_cli package.

Usage (all equivalent):
    python3 cytube_chat.py 420Grindhouse
    python3 -m cytube_cli 420Grindhouse
    cytube-chat 420Grindhouse          # after pip install
"""

from cytube_cli.cli import main

if __name__ == "__main__":
    main()
