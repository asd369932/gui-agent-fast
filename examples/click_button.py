#!/usr/bin/env python3
"""Minimal example: find a button by name and click it.

Run:  python3 examples/click_button.py "Close"
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vision.locate import locate
from vision.actions import click


def main():
    target = " ".join(sys.argv[1:]) or "Close"

    result = locate(target)
    if not result.get("found"):
        print(f"not found: {result.get('reason')}")
        return 1

    src = result.get("source", "?")
    x, y = result["real_x"], result["real_y"]
    print(f"found {target!r} at ({x},{y}) via {src}")

    click(x, y)
    print("clicked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
