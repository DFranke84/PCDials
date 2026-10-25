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

## Moving to a different PC

Copy the `PCDials` folder, install Python and HWiNFO64, then run `python setup.py`:

1. **Install** pywebview if asked (Setup tab).
2. In HWiNFO, turn on Gadget reporting and tick the sensors you want (see below).
   The saved HWiNFO settings in `hwinfo-profile` only fit the PC they came from.
3. Dials tab → **Create dials for this PC**, check the preview, **Save**.
4. Setup tab → **Start** the dials, and **Turn on** start at login.

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
| `tools.py` | `check`, `export-hwinfo`, `import-hwinfo` (see below) |
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

**By hand (or on a different PC):**

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
(`shell:startup` → **PCDials**). To start them by hand: double-click that shortcut,
or run `pythonw helper.py`. To stop them: right-click a dial → **Close all dials**.

To preview a dial in a browser: `python helper.py --server`, then open
<http://127.0.0.1:8765/dial.html?i=0&preview>.

Needs Python 3 and `pip install pywebview`.
