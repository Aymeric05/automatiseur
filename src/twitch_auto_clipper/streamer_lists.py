"""Streamer lists kept as text files: one Twitch login per line, # starts a comment."""

from __future__ import annotations

from pathlib import Path


def load_streamer_list(path: Path) -> list[str]:
    """Twitch logins of a streamers list, in its order."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return list(dict.fromkeys(
        login for line in lines if (login := line.split("#", 1)[0].strip().lower())
    ))


def load_top_streamers(path: Path) -> frozenset[str]:
    return frozenset(load_streamer_list(path))


def add_streamer(path: Path, login: str, note: str) -> bool:
    """Append ``login`` (with a ``note`` comment) unless the list has it; True when added."""
    login = login.strip().lower()
    if not login or login in load_top_streamers(path):
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    separator = "" if not text or text.endswith("\n") else "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{separator}{login}  # {note}\n")
    return True
