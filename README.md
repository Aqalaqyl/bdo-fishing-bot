# bdo-fishing-bot

A screen-reading fishing bot for Black Desert Online, written in Python.
It watches the game window, hooks the fish when the bite prompt appears,
plays both minigames (the moving-marker gauge and the W/A/S/D key sequence)
and recasts the line, forever.

Defaults are tuned for **1920x1080 at 100% UI scale**. The bot never reads
game memory or injects anything: it takes screenshots with `mss`, analyses
them with OpenCV and sends key presses through DirectInput (`pydirectinput`,
Windows) or a virtual keyboard (`uinput`, Linux/Proton).

> Written for educational use on a private server. Using automation on the
> official servers violates the Terms of Service and will get an account banned.

## How a cycle works

```
cast (Space) ──> wait for bite ──> hook (Space) ──> gauge minigame ──> WASD minigame ──> wait ──> recast
                 ▲                                                                                  │
                 └──────────────────────────────────────────────────────────────────────────────────┘
```

| Stage | What the bot looks at | How |
|-------|-----------------------|-----|
| Bite | `bite_region` (centre of the screen) | Template match of `templates/bite.png`, or a count of near-white pixels when no template exists, or a frame-difference against the post-cast baseline |
| Gauge | `gauge_region` | HSV mask finds the blue success zone and the white marker; marker velocity is tracked so the press is issued *before* latency carries it out of the zone |
| WASD | `wasd_region` | Template matching of the key icons (`w.png`, `a.png`, ... and the reversed variants). Reversed icons are mapped to the opposite key (W↔S, A↔D). Keys are typed left to right |
| Catch | – | Waits `post_catch_delay_s`, optionally presses `R`, then casts again |

A cast that gets no bite within `bite_timeout_s` is recast. Six such casts
in a row (`max_consecutive_failures`) stop the bot, which catches a broken
rod, a full inventory or a mis-calibrated region.

## Installation

Python 3.10+ is required on every platform.

### Linux (one command)

```bash
git clone https://github.com/Aqalaqyl/bdo-fishing-bot
cd bdo-fishing-bot
./install.sh --uinput     # drop --uinput if you don't want to use sudo
```

`install.sh` installs the system packages (apt, dnf, pacman or zypper),
creates `.venv`, installs the bot into it and checks every import. Afterwards
use `./run.sh` instead of `python -m ...`:

```bash
./run.sh calibrate preview      # calibration tools
./run.sh --dry-run -v           # the bot
```

`--uinput` adds a udev rule and puts your user in the `input` group so the
bot can create a virtual keyboard through `/dev/uinput`. BDO under
Proton/Wine treats that like real hardware, whereas XTEST key events from
`pyautogui` are sometimes ignored by the game. **Log out and back in once**
after running it. Without it the bot falls back to `pyautogui` automatically.

Linux notes:

* You need an **X11/Xorg session**. On Wayland `mss` cannot capture the
  screen and `pynput` hotkeys do not work (the installer warns about this).
* Run the game at 1920x1080 in a borderless/windowed Proton window on the
  primary monitor; screen coordinates in the config are for that monitor.
* `input_backend` in `config.json` forces a backend (`uinput`, `pyautogui`);
  the default `auto` tries `uinput` first.

### Windows

```powershell
git clone https://github.com/Aqalaqyl/bdo-fishing-bot
cd bdo-fishing-bot
py -3 -m venv .venv
.venv\Scripts\activate
pip install -e .
bdo-fishing-bot --help
```

If BDO is started "as administrator" the bot must be too, otherwise Windows
blocks the synthetic key presses.

### Any platform via pip

`pip install .` (or `pip install -e .` for a checkout you intend to edit)
installs two commands, `bdo-fishing-bot` and `bdo-fishing-calibrate`, which
are identical to `python -m bdo_fishing_bot` and
`python -m bdo_fishing_bot.tools.calibrate`.

### Game settings

* Resolution 1920x1080, UI scale 100 (Settings → Display).
* **Windowed** or **Borderless** window mode on your primary monitor.
  Exclusive fullscreen cannot be captured by `mss`.
* Settings → Game → enable *Loot Fish Automatically* (or set
  `press_loot_key_after_catch` to `true` so the bot presses `R`).
* Equip a rod, stand at the water, do **not** press anything else while the
  bot runs. Press `F9` to pause/resume, `F10` to stop (configurable).

## Calibration (do this once)

Every PC renders a few pixels differently, so check the regions and capture
the key icons before running unattended.

1. **Check the regions.** Start fishing manually, then run

   ```powershell
   python -m bdo_fishing_bot.tools.calibrate preview
   ```

   It waits 3 s (alt-tab to the game) and writes `preview.png` with the three
   regions drawn on it: yellow = bite prompt, blue = gauge bar, red = WASD row.
   If a UI element falls outside its rectangle, copy `config.example.json` to
   `config.json` and adjust `bite_region` / `gauge_region` / `wasd_region`
   (`left, top, width, height`). Regions can be generous; the detectors only
   need the element to be inside.

2. **Capture the WASD key icons.** Record the WASD area while you fish one
   round by hand:

   ```powershell
   python -m bdo_fishing_bot.tools.calibrate burst --region wasd --seconds 90 --fps 5
   ```

   Open `captures/`, pick a frame that shows the key row and cut it up:

   ```powershell
   python -m bdo_fishing_bot.tools.calibrate split-keys captures\wasd_XXXXXX.png
   ```

   Look at each `captures\keys\key_N.png` and rename it into `templates\` as
   `w.png`, `a.png`, `s.png`, `d.png`, `w_rev.png`, `a_rev.png`, `s_rev.png` or
   `d_rev.png` (see `templates/README.md`). You can also crop them in any
   image editor; just do not resize. Verify with

   ```powershell
   python -m bdo_fishing_bot.tools.calibrate analyze wasd captures\wasd_XXXXXX.png --out check.png
   ```

   which prints the decoded sequence and the keys the bot would press.

3. **(Optional) Capture the bite prompt** the same way with
   `--region bite`, crop the "Space" prompt to `templates/bite.png`. Without it
   the bot falls back to counting bright pixels in the bite region, which
   works but is more sensitive to sun glare on the water. You can test any
   saved frame with `analyze bite <image>` and tune `bite_bright_min_pixels`.

4. **(Optional) Check the gauge colours.** Grab a frame of the gauge
   (`burst --region gauge`) and run `analyze gauge <image> --out check.png`.
   If the zone is not found, read the zone colour with
   `hsv <image> <x> <y>` and widen `gauge_zone_hsv_lower/upper`.

5. **Dry run.** Fish manually while the bot only watches and logs:

   ```powershell
   python -m bdo_fishing_bot --dry-run --debug-dir debug -v
   ```

   Every detection (bite, gauge, WASD) is logged and the frame it triggered on
   is saved to `debug\`, so you can confirm the bot sees what you see.

## Running

```powershell
python -m bdo_fishing_bot                  # uses config.json if present
python -m bdo_fishing_bot -c myconfig.json --max-casts 200
python -m bdo_fishing_bot --bite-mode change --debug-dir debug
python -m bdo_fishing_bot --cast-hold 2.0        # hold Space 2 s per cast to spend energy
```

A plain tap of Space is a normal cast. Holding it keeps the cast power gauge
filling and consumes energy for the cast; set `cast_hold_s` (or `--cast-hold`)
to how long you would hold the key yourself. The bot does not track your
energy, so once it runs out the game simply performs a normal cast.

After a 3 second countdown the first cast is sent. Stats (casts, bites,
timeouts, minigames solved, catches) are logged after every cycle.

Hotkeys (global, work while the game has focus): `F9` pause/resume,
`F10` stop. `Ctrl+C` in the console also stops it.

## Configuration reference

Copy `config.example.json` to `config.json` and change only what you need.
Unknown keys are rejected so typos are caught at start-up.

| Key | Default | Meaning |
|-----|---------|---------|
| `bite_region`, `gauge_region`, `wasd_region` | see example | Screen rectangles (`left, top, width, height`) |
| `input_backend` | `auto` | `auto`, `pydirectinput`, `uinput` or `pyautogui` |
| `cast_key`, `hook_key`, `gauge_key` | `space` | Keys sent for each action |
| `press_loot_key_after_catch`, `loot_key` | `false`, `r` | Press loot key after each catch |
| `cast_hold_s` | 0.05 | How long to hold the cast key. Raise it (e.g. `2.0`) to fill the power gauge and spend energy on each cast; also available as `--cast-hold 2.0` |
| `cast_settle_s` | 3.0 | Ignore the bite region for this long after casting |
| `bite_timeout_s` | 150 | Recast if nothing bites |
| `bite_detection` | `auto` | `auto`, `template`, `bright` or `change` |
| `bite_bright_value`, `bite_bright_min_pixels` | 225, 350 | Thresholds for `bright` mode |
| `bite_change_threshold` | 14 | Mean pixel difference for `change` mode |
| `bite_confirm_frames` | 2 | Consecutive positive frames before hooking |
| `hook_to_gauge_timeout_s` | 4 | How long to wait for the gauge to appear |
| `gauge_zone_hsv_*`, `gauge_marker_hsv_*` | blue / white | Colour ranges for zone and marker |
| `gauge_zone_margin_px` | 4 | Keep the press this far inside the zone edges |
| `gauge_lead_frames` | 1.5 | Press this many frames ahead to compensate latency |
| `gauge_to_wasd_timeout_s` | 4 | How long to wait for the key row to appear |
| `wasd_key_delay_s` | 0.09 | Delay between typed keys |
| `wasd_reversed_map` | `{"w_rev":"s", ...}` | Which key to press for each reversed icon |
| `post_catch_delay_s` | 4.5 | Wait before recasting |
| `template_threshold` | 0.80 | Minimum template-match score |
| `pause_hotkey`, `stop_hotkey` | `f9`, `f10` | Global hotkeys |
| `max_consecutive_failures` | 6 | Stop after this many bite-less casts in a row |
| `max_casts` | 0 | Stop after N casts (0 = unlimited) |
| `jitter_s` | 0.12 | Random extra delay added to waits/key holds |

## Troubleshooting

* **Keys do nothing in game (Windows)** – make sure `pydirectinput` is
  installed (the log prints `Keyboard backend: pydirectinput`) and that the
  bot runs with the same privilege level as the game.
* **Keys do nothing in game (Linux)** – the log should say
  `Keyboard backend: uinput`. If it says `pyautogui`, run
  `./install.sh --uinput`, log out and in, and check `ls -l /dev/uinput` is
  group `input` and writable.
* **Bite never detected** – run `--dry-run -v`; the log prints the live score.
  In `bright` mode lower `bite_bright_min_pixels`, or capture `bite.png`.
  Check the yellow rectangle in `preview.png` actually contains the prompt.
* **Bites detected while nothing is happening** – raise
  `bite_bright_min_pixels`, increase `bite_confirm_frames`, or shrink the
  region so it excludes bright water/sky.
* **Gauge always times out / "Gauge not detected"** – at high fishing levels
  the gauge may be skipped, which is fine. Otherwise use `analyze gauge` on a
  saved frame and adjust the HSV ranges. Lower `gauge_lead_frames` if the bot
  presses too early, raise it if too late.
* **Wrong WASD keys** – reversed icons are mapped with `wasd_reversed_map`;
  change it if your server uses a different rule. Make sure every icon
  variant has its own template and that `analyze wasd` labels them correctly.
* **Script captures a black screen** – switch the game out of exclusive
  fullscreen.

## Development

```bash
pip install opencv-python-headless mss pytest
python -m pytest tests
```

The detectors are pure functions over image arrays, so the test-suite drives
them with synthetic gauges and rendered key glyphs without the game.

## Project layout

```
bdo_fishing_bot/
  bot.py            state machine: cast → bite → hook → gauge → WASD → recast
  detectors.py      BiteDetector, analyze_gauge/GaugeTracker, WasdReader
  vision.py         template matching, NMS, HSV masks
  screen.py         mss capture
  controls.py       pydirectinput / uinput / pyautogui key presses, dry-run mode
  hotkeys.py        global pause/stop hotkeys (pynput)
  config.py         dataclass config + JSON overrides
  tools/calibrate.py  preview / burst / split-keys / analyze / hsv
templates/          your captured UI crops (see templates/README.md)
tests/              synthetic-image unit tests
install.sh, run.sh  Linux installer and launcher
pyproject.toml      pip-installable package (bdo-fishing-bot / bdo-fishing-calibrate)
```
