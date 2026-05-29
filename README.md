# cytube-cli

Terminal chat client for [cytu.be](https://cytu.be) rooms. Connects via Socket.IO, prints chat with colored usernames, and lets you send messages when logged in.

![screenshot](static/qrkRLy6%20-%20Imgur.png)

## Install

```bash
git clone https://github.com/vacuumboots/cytube-cli.git
cd cytube-cli

# Create a virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows
pip install -r requirements.txt
```

The instructions use `python3` because on macOS that's unambiguous — `python` may not exist or could point to Python 2. Once the venv is activated, plain `pip` works fine regardless.

## Usage

```bash
# Read-only guest in a public room
cytube-chat 420Grindhouse

# Log in to send messages (reads password from .env or ~/.cytube_creds)
cytube-chat 420Grindhouse --login myname

# With explicit password
cytube-chat 420Grindhouse --login myname --password mypass

# Hide join/leave spam, user count, and MOTD
cytube-chat 420Grindhouse --login myname --hide-joins --hide-usercount --no-motd
```

You can also run it as a module or the old way:

```bash
python3 -m cytube_cli 420Grindhouse
python3 cytube_chat.py 420Grindhouse     # compatibility shim
```

## Authentication

Credentials are resolved in this order:

1. `--login` / `--password` CLI flags
2. `CYTUBE_USERNAME` / `CYTUBE_PASSWORD` environment variables (set in `.env` or exported)
3. `~/.cytube_creds` file (username on line 1, password on line 2)

To use a `.env` file:

```bash
cp .env.example .env
# Edit .env with your credentials
```

## Chat commands

| Command  | Action              |
|----------|---------------------|
| `/help`  | Show available commands |
| `/quit`  | Disconnect and exit |

Anything else is sent as a chat message.

## How it works

- Fetches the channel's Socket.IO backend from `/socketconfig/{channel}.json`
- Authenticates via HTTP login to get an auth cookie
- Connects via Socket.IO (WebSocket with polling fallback)
- Renders messages with consistent colored usernames (hashed color assignment)
- Supports cytu.be message types: standard chat, `/me` actions, emotes, announcements, server whispers, and drink events

## License

MIT — see [LICENSE](LICENSE)
