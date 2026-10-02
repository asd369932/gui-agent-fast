#!/usr/bin/env python3
"""Benchmark: reproduce the numbers from the README.

Measures accessibility-tree lookup vs. the vision-model path.

    python3 examples/benchmark.py                 # offline only
    GUI_AGENT_API_KEY=sk-... python3 examples/benchmark.py Close   # includes vision
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vision.capture import capture, to_jpeg      # noqa: E402
from vision.locate import locate                  # noqa: E402
from vision import atspi_tree                     # noqa: E402


def timed(label, fn, runs=3):
    times = []
    result = None
    for _ in range(runs):
        t0 = time.time()
        result = fn()
        times.append((time.time() - t0) * 1000)
    avg = sum(times) / len(times)
    print(f"{label:<28} {avg:>8.0f} ms   "
          f"({'/'.join(f'{t:.0f}' for t in times)})")
    return result


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "Close"

    print("=== 1. capture + encode ===")
    timed("screenshot (scrot)", lambda: capture(), runs=3)
    shot = capture()
    timed("encode to JPEG", lambda: to_jpeg(shot), runs=3)

    print()
    print("=== 2. accessibility tree ===")
    timed("a11y tree (full dump)", lambda: atspi_tree.dump_tree(), runs=3)
    r = timed(f'locate("{target}") via a11y',
              lambda: atspi_tree.find(target), runs=3)
    if r and r.get("found"):
        print(f"    -> {r['name']!r} at ({r['x']},{r['y']})")

    print()
    print("=== 3. three-tier locate ===")
    timed(f'locate("{target}") [tiered]', lambda: locate(target), runs=3)

    if os.environ.get("GUI_AGENT_API_KEY"):
        print()
        print("=== 4. vision model (needs API key) ===")
        from vision.locate import locate_with_vision
        timed("vision model", lambda: locate_with_vision(target), runs=1)
    else:
        print()
        print("(skipping vision-model tier — set GUI_AGENT_API_KEY to include it)")


if __name__ == "__main__":
    main()
