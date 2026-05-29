# cytube-cli

Terminal chat client for [cytu.be](https://cytu.be) rooms. Connects via Socket.IO, prints chat with colored usernames, and lets you send messages when logged in.

## Install

```bash
git clone https://github.com/vacuumboots/cytube-cli.git
cd cytube-cli
pip install -r requirements.txt
```

## Usage

```bash
# Read-only guest in a public room
python3 cytube_chat.py 420Grindhouse

# Log in to send messages (reads password from .env or ~/.cytube_creds)
python3 cytube_chat.py 420Grindhouse --login myname

# With explicit password
python3 cytube_chat.py 420Grindhouse --login myname --password mypass

# Hide join/leave spam, user count, and MOTD
python3 cytube_chat.py 420Grindhouse --login myname --hide-joins --hide-usercount --no-motd
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
