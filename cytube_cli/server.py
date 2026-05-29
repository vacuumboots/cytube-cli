"""Cytu.be server resolution — find the Socket.IO backend for a channel."""

import requests


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
