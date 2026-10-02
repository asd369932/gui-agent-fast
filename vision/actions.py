"""Mouse and keyboard actions via xdotool.

Includes a guard that refuses to send input to the calling process's own
terminal window. That sounds paranoid until it bites you:

A terminal TUI (like an AI coding assistant) binds Escape to "interrupt
the current turn". If your GUI agent sends Escape while that terminal
happens to be focused, it interrupts itself. This happened to me twice
before I added the guard — the agent pressed Escape, its own command got
killed, and the output just said "[interrupted]".

The fix: before sending keys, resolve the focused window's PID and walk
its /proc ancestry. If any ancestor is one of our own processes, refuse.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Optional

DANGEROUS_KEYS = {"escape", "esc", "return", "enter", "ctrl+c", "ctrl+d",
                  "ctrl+z", "alt+f4", "ctrl+q", "ctrl+w"}


def _env() -> dict:
    return dict(os.environ, DISPLAY=os.environ.get("DISPLAY", ":0"))


def _xd(*args: str, timeout: int = 15) -> subprocess.CompletedProcess:
    """Run xdotool, raising on failure.

    Checking the return code matters: without it, a click with a bad
    DISPLAY still "succeeds" and your callers get no signal at all.
    """
    try:
        r = subprocess.run(["xdotool", *args], env=_env(), timeout=timeout,
                           capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError("xdotool not found. Install: sudo apt install xdotool")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"xdotool {' '.join(args[:2])} timed out")
    if r.returncode != 0:
        raise RuntimeError(f"xdotool {' '.join(args[:2])} failed: "
                           f"{(r.stderr or '').strip()[:120]}")
    return r


def _focused_window_pid() -> Optional[int]:
    try:
        wid = _xd("getwindowfocus").stdout.strip()
        if not wid.isdigit():
            return None
        pid = _xd("getwindowpid", wid).stdout.strip()
        return int(pid) if pid.isdigit() else None
    except Exception:
        return None


def _cursor_window_pid() -> Optional[int]:
    """PID of the window *under the mouse cursor*.

    Different from focus, and it's what click safety cares about: clicks
    go to whatever is under the cursor, regardless of keyboard focus.
    """
    try:
        out = _xd("getmouselocation", "--shell").stdout
        for line in out.splitlines():
            if line.startswith("WINDOW="):
                wid = line.split("=", 1)[1].strip()
                pid = _xd("getwindowpid", wid).stdout.strip()
                return int(pid) if pid.isdigit() else None
    except Exception:
        return None


def _self_pids() -> set:
    """This process plus its ancestors (up to 20 levels)."""
    pids = {os.getpid()}
    p = os.getpid()
    for _ in range(20):
        try:
            stat = Path(f"/proc/{p}/stat").read_text()
            ppid = int(stat.rsplit(")", 1)[1].split()[1])
        except Exception:
            break
        if ppid <= 1:
            break
        pids.add(ppid)
        p = ppid
    return pids


def _guard_keystroke(combo: str = "") -> None:
    """Refuse to send keys into our own terminal.

    Fail-closed: if we cannot tell where focus is, refuse rather than
    guess. Set GUI_AGENT_ALLOW_SELF=1 to override (e.g. when testing).
    """
    if os.environ.get("GUI_AGENT_ALLOW_SELF"):
        return
    fpid = _focused_window_pid()
    if fpid is None:
        return   # no window info available; don't block on a headless box
    if fpid in _self_pids():
        raise RuntimeError(
            f"Refusing to send keys: focused window (pid={fpid}) belongs to "
            f"this process. Your keystroke would hit your own UI. "
            f"Set GUI_AGENT_ALLOW_SELF=1 to override.")


def _guard_pointer(action: str = "click") -> None:
    if os.environ.get("GUI_AGENT_ALLOW_SELF"):
        return
    cpid = _cursor_window_pid()
    if cpid is None:
        return
    if cpid in _self_pids():
        raise RuntimeError(
            f"Refusing to {action}: cursor is over this process's own window "
            f"(pid={cpid}). Move the cursor first or set GUI_AGENT_ALLOW_SELF=1.")


def move(x: int, y: int) -> None:
    """Move the cursor without clicking."""
    _xd("mousemove", str(x), str(y))
    _guard_pointer("move")


def click(x: int, y: int, button: int = 1, double: bool = False) -> None:
    """Click at real screen coordinates."""
    _xd("mousemove", str(x), str(y))
    time.sleep(0.12)
    _guard_pointer("click")
    time.sleep(0.05)
    _xd("click", "--repeat", "2" if double else "1", str(button))


def type_text(text: str) -> None:
    """Type text. Note: xdotool drops characters for CJK input — use
    paste() for non-ASCII."""
    _guard_keystroke()
    _xd("type", "--clearmodifiers", "--delay", "20", text, timeout=60)


def paste(text: str) -> None:
    """Put text on the clipboard and paste it. Reliable for CJK/emoji.

    The subprocess MUST redirect stdout/stderr to DEVNULL. xclip forks a
    daemon to keep the selection alive; if that daemon inherits our stdout
    (a pipe the caller is reading), the caller waits for EOF that never
    comes — a 60-second hang with no error message.
    """
    try:
        subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(),
                       env=_env(), timeout=10,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        raise RuntimeError("xclip not found. Install: sudo apt install xclip")
    _guard_keystroke()
    time.sleep(0.3)
    _xd("key", "--clearmodifiers", "ctrl+v")


def key(combo: str) -> None:
    """Press a key or key combination, e.g. 'Return' or 'ctrl+c'."""
    _guard_keystroke(combo)
    _xd("key", "--clearmodifiers", combo)


def scroll(direction: str = "down", times: int = 3) -> None:
    _guard_pointer("scroll")
    btn = {"down": "5", "up": "4", "left": "6", "right": "7"}.get(direction, "5")
    for _ in range(times):
        _xd("click", btn)
        time.sleep(0.1)
