"""CLI entry point — argument parsing and main orchestration."""

import argparse
import os
import sys

from cytube_cli.auth import load_dotenv
from cytube_cli.auth import resolve_credentials
from cytube_cli.client import ChatClient
from cytube_cli.colors import C
from cytube_cli.server import resolve_server


def main():
    # Load .env from the project directory (or wherever the package lives)
    pkg_dir = os.path.dirname(__file__)
    load_dotenv(os.path.join(pkg_dir, "..", ".env"))
    load_dotenv(".env")  # also try cwd

    parser = argparse.ArgumentParser(
        description="Cytu.be terminal chat client (read + write)"
    )
    parser.add_argument("channel", help="Channel name (e.g. 420Grindhouse)")
    parser.add_argument(
        "--server", default="https://cytu.be", help="Cytu.be frontend URL"
    )
    parser.add_argument(
        "--login", default=None, help="Cytu.be account username (for sending messages)"
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Account password (or set CYTUBE_PASSWORD env var)",
    )
    parser.add_argument(
        "--hide-joins", action="store_true", help="Hide join/leave messages"
    )
    parser.add_argument("--hide-usercount", action="store_true", help="Hide user count")
    parser.add_argument("--no-motd", action="store_true", help="Hide MOTD banner")
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
