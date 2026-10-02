# gui-agent-fast

**40x faster element location for GUI agents — by asking the OS instead of the model.**

A pure-vision GUI agent locates a button in ~13 seconds and gets an approximate
answer. Reading the accessibility tree locates the same button in ~0.3 seconds
with exact coordinates:

| Method | Time | Accuracy |
|---|---|---|
| Vision model (GPT-4o / Claude / DeepSeek-VL) | 4,000–13,000 ms | estimated |
| **Accessibility tree (AT-SPI)** | **240–350 ms** | **exact** |
| Cached coordinates | 14 ms | exact (same window) |

Measured on a 2020 laptop with a 4 GB GPU. No hardware changed — just a
different information source.

---

## The idea

A vision-based GUI agent does this:

```
screenshot -> upload -> model guesses coordinates -> click
```

The model is guessing. It sees a downscaled image and estimates where the
"Close" button probably is. For a 1920x1080 screen that means a 1280x720
JPEG goes over the network, and you wait seconds for an estimate that is
sometimes off by 20 pixels.

But your operating system already knows exactly where that button is. It
has to — that's how it draws it, hit-tests it, and lets screen readers
announce it. On Linux this is exposed through **AT-SPI**, the accessibility
API.

```
a11y tree -> exact element + exact coordinates -> click
```

No screenshot. No network. No guessing.

Real output from this library:

```
window: gnome-terminal-server (9 elements)
frame | Terminal | center(993,556)
  push button | Minimize | center(1817,55)
  push button | Restore  | center(1857,55)
  push button | Close    | center(1897,55)
toggle button | Menu     | center(1769,55)
```

Those coordinates come from the window manager itself. Click `(1897,55)`
and you hit "Close" — deterministically, every time.

CJK element names come back intact with no OCR step. In the output above
you can see Chinese names (终端/最小化/关闭) resolved natively.

---

## Install

```bash
sudo apt install at-spi2-core python3-gi xdotool scrot wmctrl
pip install pillow
```

Optional, for the OCR tier:

```bash
sudo apt install tesseract-ocr            # + tesseract-ocr-chi-sim for Chinese
```

## Use

```python
from vision.locate import locate
from vision.actions import click

result = locate("Close")
if result["found"]:
    print(f"found at ({result['real_x']},{result['real_y']}) "
          f"via {result['source']}")
    click(result["real_x"], result["real_y"])
```

The `locate()` call tries three tiers, cheapest first:

| Tier | Time | Coverage |
|---|---|---|
| 1. Accessibility tree | 0.3 s | native apps (GTK/Qt with a11y enabled) |
| 2. OCR (tesseract) | 0.5–8 s | any text, no API key |
| 3. Vision model | 4–13 s | anything, needs an API key |

Pass `use_vision=False` to keep everything offline.

To enable tier 3, point the library at any OpenAI-compatible vision endpoint:

```bash
export GUI_AGENT_API_KEY=sk-...
export GUI_AGENT_BASE=https://api.openai.com     # or your provider
export GUI_AGENT_MODEL=gpt-4o-mini
```

## Benchmarks

Reproduce the numbers yourself:

```bash
python3 examples/benchmark.py Close
```

```
=== 2. accessibility tree ===
a11y tree (full dump)           18 ms   (19/15/21)
locate("Close") via a11y       246 ms   (322/343/332)

=== 3. three-tier locate ===
locate("Close") [tiered]        15 ms   (cache hit)
```

---

## Two things that will bite you

### 1. Don't use AT-SPI's "active window" state

The obvious way to find the focused window is to look for the one in
`STATE_ACTIVE`. On GNOME this always returns `gnome-shell` — the desktop
shell is permanently active — and you end up reading desktop icons instead
of your application.

Match by PID instead: take the focused window's PID from X11 and compare
it against each AT-SPI application's `get_process_id()`.

This library does that, with fallbacks for Wayland where `xdotool`/xprop
are unavailable.

### 2. The coordinate scaling step

If you send a 1920-wide screenshot to a model that downscales to 1280, the
coordinates it returns are in 1280-space. Multiply by the ratio (1.5) before
clicking. Forgetting this is the single most common bug in vision-based
agents — everything "works" but clicks land consistently wrong.

```python
jpeg, ratio = to_jpeg(screenshot)      # ratio = 1920/1280 = 1.5
# model says (640, 360)
real_x, real_y = 640 * ratio, 360 * ratio   # (960, 540)
```

## Safety: don't let the agent type into itself

If you run a TUI (editor, REPL, AI assistant) and the agent sends Escape
while that terminal is focused, the keystroke goes to *your own UI*. On an
assistant with `Escape = interrupt`, the agent interrupts its own task.

This bit me twice — the agent pressed Escape to close a dialog, the focused
window happened to be its own terminal, and it killed the very command that
was running the agent.

`actions.py` guards against it: before sending keys it resolves the focused
window's PID, walks `/proc` ancestry, and refuses if the target is one of
our own processes. Fail-closed, with `GUI_AGENT_ALLOW_SELF=1` as an override.

## What this does NOT solve

- **WINE / Electron / games** often expose nothing through AT-SPI. Grep the
  output for "exposes no elements" — that's the signal to fall back to OCR
  or the vision model.
- **Wayland** is partially supported. The screenshot path needs `grim`
  instead of `scrot`, and window-focus lookup falls back to AT-SPI's own
  state. Pure X11 is the well-tested path.
- **Canvas / custom-drawn UI** has no elements to read. Vision model it is.

AT-SPI coverage is genuinely good on GNOME/KDE native apps and poor on
everything else. The tiered design exists precisely because no single
method covers everything.

## Layout

```
vision/
  atspi_tree.py   accessibility tree reader (tier 1)
  locate.py       three-tier locate + coordinate cache
  capture.py      screenshot + JPEG encoding (the fast path)
  actions.py      mouse/keyboard with self-target guard
examples/
  click_button.py minimal end-to-end example
  benchmark.py    reproduce the numbers above
```

## License

MIT
