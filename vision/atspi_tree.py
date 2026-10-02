"""AT-SPI accessibility tree reader — locate UI elements with exact coordinates.

Why this exists
---------------
Visual-model-based GUI agents are slow: a typical cloud vision model takes
4-13 seconds per screenshot, and the coordinates it returns are estimates.
Meanwhile the operating system already knows exactly where every button is.

On Linux, that knowledge is exposed through AT-SPI (Assistive Technology
Service Provider Interface) — the accessibility layer screen readers use.

This module reads the accessibility tree and returns element names with
exact screen coordinates. Measured on a 2020 laptop:

    AT-SPI lookup:      320 ms
    Vision model:     12,900 ms   (40x slower)

Text is returned natively — including CJK — with no OCR and no translation.

Requirements
------------
    sudo apt install at-spi2-core python3-gi

Usage
-----
    from atspi_tree import find, dump_tree

    el = find("Close")
    if el["found"]:
        print(el["x"], el["y"])   # exact screen coordinates

    print(dump_tree())            # human-readable text map
"""
from __future__ import annotations

from typing import Optional

# AT-SPI reports this as x/y when an element is not actually on screen
INVALID_COORD = -1000000

# Roles worth reporting (filters out noise)
INTERESTING_ROLES = {
    "push button", "toggle button", "menu item", "check box", "radio button",
    "entry", "text", "label", "link", "page tab", "list item", "combo box",
    "frame", "panel", "dialog", "table cell", "terminal", "spin button",
}


def _atspi():
    """Import Atspi lazily so the module can be imported without GTK."""
    try:
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
        Atspi.init()
        return Atspi
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "AT-SPI unavailable. Install with: "
            "sudo apt install at-spi2-core python3-gi"
        ) from e


def _bbox(node, Atspi):
    """Screen coordinates of an element, or None if not on screen."""
    try:
        r = node.get_extents(Atspi.CoordType.SCREEN)
    except Exception:
        return None
    if r.width <= 1 and r.height <= 1:
        return None
    if r.x < INVALID_COORD // 2 or r.y < INVALID_COORD // 2:
        return None
    return (r.x, r.y, r.width, r.height)


def _walk(node, depth, max_depth, out, active_only, Atspi):
    """Depth-first walk collecting useful elements."""
    if depth > max_depth or len(out) > 300:
        return
    try:
        role = node.get_role_name() or ""
        name = (node.get_name() or "").strip()
        box = _bbox(node, Atspi)
        if box and name and (not active_only or role in INTERESTING_ROLES):
            out.append({
                "role": role, "name": name,
                "x": box[0], "y": box[1], "w": box[2], "h": box[3],
                "depth": depth, "_node": node,
            })
    except Exception:
        pass
    try:
        n = min(node.get_child_count(), 40)
    except Exception:
        return
    for i in range(n):
        try:
            child = node.get_child_at_index(i)
            if child:
                _walk(child, depth + 1, max_depth, out, active_only, Atspi)
        except Exception:
            continue


def _focus_pid() -> Optional[int]:
    """PID of the focused window.

    Three levels of fallback so this works on both X11 and (partially) Wayland:

      1. xdotool      — X11 only, fastest
      2. xprop EWMH   — X11 standard protocol, no xdotool binary needed
      3. None         — caller falls back to AT-SPI's own active-state check
    """
    import os
    import subprocess

    env = dict(os.environ, DISPLAY=os.environ.get("DISPLAY", ":0"))

    # 1. xdotool
    try:
        wid = subprocess.run(["xdotool", "getwindowfocus"], env=env,
                             capture_output=True, text=True, timeout=5).stdout.strip()
        if wid.isdigit():
            pid = subprocess.run(["xdotool", "getwindowpid", wid], env=env,
                                 capture_output=True, text=True, timeout=5).stdout.strip()
            if pid.isdigit():
                return int(pid)
    except Exception:
        pass

    # 2. xprop (pure EWMH)
    try:
        out = subprocess.run(["xprop", "-root", "_NET_ACTIVE_WINDOW"], env=env,
                             capture_output=True, text=True, timeout=5).stdout
        if "#" in out:
            wid = out.split("#", 1)[1].strip().split()[0]
            if wid.startswith("0x"):
                out2 = subprocess.run(["xprop", "-id", wid, "_NET_WM_PID"], env=env,
                                      capture_output=True, text=True, timeout=5).stdout
                tail = out2.strip().split()[-1] if out2.strip() else ""
                if tail.isdigit():
                    return int(tail)
    except Exception:
        pass

    return None


def _active_root():
    """Return (window_node, app_name) for the focused window.

    IMPORTANT: do not use AT-SPI's own STATE_ACTIVE to find the active window.
    On GNOME, gnome-shell is permanently 'active', so that check returns the
    desktop shell instead of the app you care about. Match by PID instead.
    """
    Atspi = _atspi()
    focus_pid = _focus_pid()

    desktop = Atspi.get_desktop(0)
    apps = []
    for i in range(desktop.get_child_count()):
        try:
            app = desktop.get_child_at_index(i)
            if app and app.get_child_count() > 0:
                apps.append(app)
        except Exception:
            continue

    # Preferred: exact PID match
    if focus_pid:
        for app in apps:
            try:
                if app.get_process_id() == focus_pid:
                    for j in range(app.get_child_count()):
                        w = app.get_child_at_index(j)
                        if w:
                            return w, app.get_name()
            except Exception:
                continue

    # Fallback: first non-shell window with content
    for app in apps:
        try:
            name = app.get_name()
            if name in ("gnome-shell", "gjs"):
                continue
            w = app.get_child_at_index(0)
            if w:
                return w, name
        except Exception:
            continue

    return None, None


def dump_tree(max_depth: int = 6, active_only: bool = True) -> str:
    """Human/model-readable text map of the focused window.

    Example output:

        window: gnome-terminal-server (9 elements)
        push button | Close | center(1897,55)
        push button | New Tab | center(90,55)
    """
    root, app = _active_root()
    if root is None:
        return "(no focused window found)"
    elems: list = []
    _walk(root, 0, max_depth, elems, active_only, _atspi())
    if not elems:
        return (f"(window '{app}' exposes no elements — "
                f"WINE/Qt apps often don't implement accessibility)")
    lines = [f"window: {app or '?'} ({len(elems)} elements)"]
    for e in elems[:120]:
        cx, cy = e["x"] + e["w"] // 2, e["y"] + e["h"] // 2
        lines.append(f"{'  ' * e['depth']}{e['role']} | {e['name'][:50]} | center({cx},{cy})")
    return "\n".join(lines)


def find(name_substr: str, role: Optional[str] = None,
         max_depth: int = 8) -> dict:
    """Find an element by (substring of) its name.

    Returns a dict with exact center coordinates ready for clicking::

        {"found": True, "x": 1897, "y": 55, "name": "Close",
         "role": "push button", "source": "atspi"}
    """
    root, app = _active_root()
    if root is None:
        return {"found": False, "reason": "no focused window"}

    elems: list = []
    _walk(root, 0, max_depth, elems, False, _atspi())
    if not elems:
        return {"found": False,
                "reason": f"window '{app}' exposes no elements (WINE apps often don't)"}

    want = name_substr.strip()

    def role_ok(e):
        return not role or e["role"] == role

    exact = [e for e in elems if e["name"] == want and role_ok(e)]
    partial = [e for e in elems if want in e["name"] and role_ok(e)]
    reverse = [e for e in elems if e["name"] and e["name"] in want and role_ok(e)]

    candidates = exact or partial or reverse
    if not candidates:
        return {"found": False, "reason": f"'{name_substr}' not found in a11y tree",
                "available": [e["name"][:30] for e in elems[:15]]}

    best = min(candidates, key=lambda e: len(e["name"]))
    cx, cy = best["x"] + best["w"] // 2, best["y"] + best["h"] // 2
    return {"found": True, "x": cx, "y": cy, "real_x": cx, "real_y": cy,
            "name": best["name"], "role": best["role"],
            "bbox": (best["x"], best["y"], best["w"], best["h"]),
            "source": "atspi", "window": app}


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "find":
        print(json.dumps(find(" ".join(sys.argv[2:])), ensure_ascii=False,
                         indent=2, default=str))
    else:
        print(dump_tree())
