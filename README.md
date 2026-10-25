# PCDials

Desktop dials (FPS, motherboard, CPU, GPU) that read live values from HWiNFO64.
Each dial is its own small see-through widget: drag it anywhere, right-click for options.

## PCDials Setup (the easy way)

```
python setup.py
```

Opens the **PCDials Setup** window:

- **Setup tab:** shows what's working (Python + pywebview, HWiNFO running and sharing
  values, saved HWiNFO settings, all dial values found, dials running, start at login),
  with a button to fix or change each one. Also **Move missing dials to main monitor**
  and **Move all**, for when a monitor is gone for good.
- **Dials tab:** edit every dial. Pick readings from a list of what HWiNFO is sharing
  right now (with live values), set units, ranges, yellow/red limits, rows; add or delete
  dials. The preview updates as you type; **Save** writes `dials.json` and the running
  dials update by themselves within a couple of seconds.
- **Create dials for this PC** (Dials tab): builds FPS, motherboard, CPU and GPU dials
  from whatever hardware this PC has (Intel/AMD CPUs, NVIDIA/AMD GPUs, common boards),
  with suitable warning limits. It only fills the editor; nothing changes until you
  **Save**, and **Undo changes** brings your old dials back.

## Starting on a new PC (step by step)

1. **Copy** the `PCDials` folder anywhere (e.g. `D:\PCDials`).
2. **Double-click `Install.bat`.** It installs whatever is missing, using Windows'
   built-in installer (winget):
   - **Python 3.14** (just for you, no admin needed),
   - **HWiNFO64** (Windows asks for permission),
   - **pywebview** (the part that draws the dial windows),
   then opens **PCDials Setup**. (`Install.bat check` only reports, installs nothing.)
3. **Set up HWiNFO** (Setup tab, top to bottom):
   - If HWiNFO is open, close it (right-click its tray icon → Exit).
   - **Apply default HWiNFO settings.** This turns on Gadget reporting, shares the
     sensors that are the same on every PC (memory, FPS, CPU totals, Intel CPU temps
     and power, NVIDIA GPU), and sets HWiNFO to open as Sensors only, minimized, and
     start with Windows. Windows may ask permission to change HWiNFO's settings file.
   - **Start HWiNFO64.** First time only: it may show a welcome or "Sensors only"
     prompt; choose **Sensors-only** and **Start**.
4. **Tick the rest** (board temps, fans, drives, AMD parts). The **Sensor checklist**
   at the bottom of the Setup tab shows a yellow dot for each missing one and the names
   to look for. In HWiNFO: **Sensors → Settings (gear) → HWiNFO Gadget** tab → select
   the sensor → tick **Report value in Gadget** → OK. The checklist turns green
   within a few seconds.
5. **Dials tab → Create dials for this PC.** Check them in the preview, adjust
   anything you like, then **Save**.
6. **Setup tab → Start** the dials, and **Turn on** "Start dials when I log in".
7. Drag the dials where you want them. Once HWiNFO is how you like it,
   **Save current** (Saved HWiNFO settings) keeps a backup for this PC.

The saved HWiNFO settings in `hwinfo-profile` only fit the PC they were saved on;
on a new PC use **Apply default HWiNFO settings** instead.

## Multiple monitors

Dial positions are saved in real screen pixels, so they come back in the same place on
any monitor, whatever its scaling. If a dial's monitor is off or unplugged, that dial
stays hidden (it isn't moved), and shows up again in the same spot when the monitor is
back. If you get rid of a monitor, use **Move missing dials to main monitor** in Setup.

## Files

| File | What it is |
|---|---|
| `dials.json` | **The file you edit**: which values each dial shows, ranges, warning limits |
| `positions.json` | Written by the app: where each dial sits, its size, locked or not |
| `helper.py` | The app: reads HWiNFO, opens one window per dial |
| `dial.html` | How a dial is drawn (shared by all dials) |
| `Install.bat` | Installs Python, HWiNFO64 and pywebview if missing, then opens Setup |
| `Start.bat` | Starts the dials (does nothing if they're already running) |
| `pcdials.log` | What the dials did (started, closed, errors), if they ever stop unexpectedly |
| `tools.py` | `check`, `export-hwinfo`, `import-hwinfo`, `default-hwinfo` (see below) |
| `setup.py`, `setup.html` | The PCDials Setup window |
| `autodials.py` | Builds dials for any PC's hardware (`python autodials.py` prints them) |
| `hwinfo-profile\` | Saved copy of your HWiNFO settings |

## Using the dials

- **Move:** drag a dial. The position is saved automatically.
- **Right-click menu:** Lock/Unlock position, Size (Small/Medium/Large), Reload all dials,
  Restart, Close all dials.
- **After editing `dials.json`:** the dials pick up the change by themselves within a
  couple of seconds (adding or removing a whole dial restarts them).
- **Colours:** arcs go green → yellow → red as they fill (reversed for FPS and GPU load,
  where high is good). Values turn **yellow** near a limit and **bold red** past it.

## Setting up HWiNFO (new install or new PC)

**Same PC, HWiNFO reinstalled:** close HWiNFO, then run

```
python tools.py import-hwinfo
```

That restores which sensors are shared, any renamed sensors and Gadget reporting.
The saved profile only matches *this* PC's hardware.

**New HWiNFO install (any PC):** close HWiNFO, then `python tools.py default-hwinfo`
(same as **Apply default HWiNFO settings** in Setup), then tick the rest by hand.

**By hand:**

1. HWiNFO → **Sensors → Settings (gear) → HWiNFO Gadget** tab →
   tick **Enable reporting to Gadget**.
2. In that tab, select each sensor the dials use and tick **Report value in Gadget**.
3. For the FPS dial, make sure HWiNFO's PresentMon (FPS / frame time) monitoring is on.
4. Run `python tools.py check` to see anything still missing.

After changing HWiNFO settings you're happy with, save them again:
`python tools.py export-hwinfo`.

## Changing a dial (`dials.json`)

Each dial has:

- `title`, `size` (pixels; the right-click size overrides it)
- `left` / `right`: the two arcs. `min` / `max` set the range.
- `big` (optional): what the big line shows; otherwise the `left` reading
- `bigExtra` (optional): a second reading added to the big line
- `rows`: lines of one or two values

Each value can use:

| Setting | Meaning |
|---|---|
| `label` | HWiNFO's name for the reading (exactly as shown in HWiNFO) |
| `source` | Text from the sensor group, when the same label appears more than once (e.g. `"DTS"`, `"[C:]"`) |
| `hwunit` | HWiNFO's own unit, when the value is shown converted (e.g. `"MB"` shown as GB) and the label is shared |
| `name` | Short dimmed name shown before the value |
| `unit`, `decimals` | How the number is shown |
| `scale` | Multiply first (e.g. `0.0009765625` turns MB into GB) |
| `showPercent` | Also show the % between `min` and `max` |
| `warn`, `danger` | Turn yellow / red at these values. If `danger` is lower than `warn`, *low* is bad (pump, fans) |
| `invert` | Arc colours reversed: high = green |

Dial-level options: `ignoreApps` (programs whose FPS to ignore) and `showApp`
(show the measured program's name in the title).

Not sure of a label? Run `python tools.py check`, or open
<http://127.0.0.1:8765/data> while the dials are running to see every reading.

## Starting

The dials start at login from a shortcut in your Startup folder
(`shell:startup` → **PCDials**). To start them by hand: double-click **`Start.bat`**
(safe to run any time: if they're already running it does nothing).
To stop them: right-click a dial → **Close all dials**.

To preview a dial in a browser: `python helper.py --server`, then open
<http://127.0.0.1:8765/dial.html?i=0&preview>.

Needs Python 3 and `pip install pywebview`.
