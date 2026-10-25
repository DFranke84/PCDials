"""Create a starting set of dials for whatever PC this is, from what HWiNFO shares.

  python autodials.py           print the generated dials (doesn't change anything)

Finds the standard readings by their usual HWiNFO names for Intel/AMD CPUs,
NVIDIA/AMD/Intel GPUs and common motherboard sensor chips. Anything not found is
left out, so every generated value works on this PC.
"""
import json
import re

from helper import read_hwinfo

GB = 0.0009765625  # MB -> GB


def unit_of(r):
    u = r["text"].split(" ", 1)[1] if " " in r["text"] else ""
    return u if u.startswith("°") or u == "%" else (" " + u if u else "")


class Finder:
    def __init__(self, readings):
        self.readings = readings

    def find(self, labels, sensor=None, unit=None, pick=None):
        """First reading matching any label regex (in order), optionally only from
        sensors matching `sensor` and with this HWiNFO unit."""
        for pattern in labels:
            hits = [r for r in self.readings
                    if re.fullmatch(pattern, r["label"], re.I)
                    and (not sensor or re.search(sensor, r["sensor"], re.I))
                    and (not unit or r["text"].endswith(" " + unit))
                    and r["value"] is not None]
            if hits:
                return pick(hits) if pick else hits[0]
        return None

    def spec(self, r, **extra):
        """A dials.json value for reading r. Adds "source" only when the label is
        used by more than one sensor."""
        if r is None:
            return None
        s = {"label": r["label"]}
        if len([x for x in self.readings if x["label"] == r["label"]]) > 1:
            s["source"] = r["sensor"]
        s["unit"] = unit_of(r)
        s.update(extra)
        hw = unit_of(r).strip()
        if hw and s["unit"].strip().split(" ")[0] != hw:
            s["hwunit"] = hw  # shown in another unit (e.g. MB as GB): remember HWiNFO's
        return s


def row(*specs):
    specs = [s for s in specs if s]
    return specs or None


def short_name(sensor, strip):
    """'CPU [#0]: Intel Core i9-12900K: DTS' -> 'Core i9-12900K'."""
    name = sensor.split(": ")[1] if ": " in sensor else sensor
    name = re.sub(r"\s*\(.*?\)", "", name)
    for word in strip:
        name = re.sub(rf"^{word}\s+", "", name, flags=re.I)
    return name.strip()


# ---------------------------------------------------------------- dials

def cpu_dial(f):
    load = f.find([r"Total CPU Utility", r"Total CPU Usage"])
    if not load:
        return None
    amd = "AMD" in load["sensor"]
    warn, danger = (88, 95) if amd else (85, 95)
    temp = f.find([r"CPU Package", r"CPU \(Tctl/Tdie\)", r"CPU Die \(average\)", r"CPU Tctl"],
                  sensor=r"^CPU \[")
    hot = f.find([r"Core Max", r"CPU CCD1 \(Tdie\)", r"CPU CCD\d \(Tdie\)"], sensor=r"^CPU \[")
    clock = f.find([r"Core Effective Clocks", r"Average Effective Clock"], sensor=r"^CPU \[")
    volt = f.find([r"Vcore", r"CPU Core Voltage.*", r"Core VIDs \(avg\)"])
    power = f.find([r"CPU Package Power", r"CPU PPT"], sensor=r"^CPU \[")
    cores = f.find([r"IA Cores Power", r"CPU Core Power.*", r"Core Powers \(avg\)"], sensor=r"^CPU \[")

    d = {
        "title": short_name(load["sensor"], ["Intel", "AMD"]),
        "size": 330,
        "left": f.spec(load, min=0, max=100, decimals=1),
        "right": f.spec(temp or hot, min=20, max=100) if (temp or hot) else None,
        "rows": [r for r in [
            row(f.spec(temp, name="Pkg", warn=warn, danger=danger),
                f.spec(hot, name="Max", warn=warn + 3, danger=danger + 3)),
            row(f.spec(clock, name="Clock", unit=" GHz", scale=0.001, decimals=2),
                f.spec(volt, name="Vcore", decimals=3)),
            row(f.spec(power, name="Pkg", decimals=0), f.spec(cores, name="Cores", decimals=0)),
        ] if r],
    }
    return d


def gpu_dial(f):
    gpu = r"^GPU \["
    load = f.find([r"GPU Core Load", r"GPU Utilization", r"GPU D3D Usage", r"GPU Load"], sensor=gpu)
    if not load:
        return None
    vendor_amd = "AMD" in load["sensor"] or "Radeon" in load["sensor"]
    temp = f.find([r"GPU Temperature", r"GPU Edge Temperature"], sensor=gpu)
    hot = f.find([r"GPU Hot Spot Temperature", r"GPU Junction Temperature", r"GPU Hotspot.*"], sensor=gpu)
    used = f.find([r"GPU Memory Allocated", r"GPU D3D Memory Dedicated", r"GPU Memory Used",
                   r"GPU Memory Usage"], sensor=gpu, unit="MB")  # AMD calls it "Usage" (in MB)
    free = f.find([r"GPU Memory Available", r"GPU Memory Free"], sensor=gpu)
    memctl = f.find([r"GPU Memory Controller Load", r"GPU Memory Usage"], sensor=gpu, unit="%")
    power = f.find([r"GPU Power", r"Total Board Power", r"GPU ASIC Power", r"GPU Package Power"], sensor=gpu)
    fan = f.find([r"GPU Fan1?", r"GPU Fan"], sensor=gpu, unit="RPM")

    big = None
    if used:
        total_gb = round((used["value"] + (free["value"] if free else 0)) * GB, 1) if free else None
        big = f.spec(used, unit=" GB", scale=GB, decimals=1)
        if total_gb:
            big.update(min=0, max=total_gb, showPercent=True,
                       warn=round(total_gb * 0.9, 1), danger=round(total_gb * 0.96, 1))

    tw, td = (80, 90) if vendor_amd else (75, 83)
    return {
        "title": short_name(load["sensor"], ["NVIDIA GeForce", "NVIDIA", "AMD Radeon", "AMD", "Intel"]),
        "size": 330,
        "big": big,
        "left": f.spec(load, min=0, max=100, decimals=0, invert=True),
        "right": f.spec(temp, min=20, max=90, decimals=0) if temp else None,
        "rows": [r for r in [
            row(f.spec(load, name="Load", decimals=0), f.spec(memctl, name="Mem", decimals=0)),
            row(f.spec(temp, name="GPU", decimals=0, warn=tw, danger=td),
                f.spec(hot, name="Hot", decimals=0, warn=tw + 15, danger=td + 17)),
            row(f.spec(power, name="Power", decimals=0), f.spec(fan, name="Fan")),
        ] if r],
    }


def board_dial(f):
    board = f.find([r"Motherboard", r"System\d?", r"MB Temp.*"], unit="°C")
    used = f.find([r"Physical Memory Used"])
    if not board and not used:
        return None
    chip = board["sensor"] if board else ""
    vrm = f.find([r"VRM.*", r"MOS.*", r"VR MOS"], unit="°C")
    pch = f.find([r"PCH Temperature", r"Chipset.*"], unit="°C")
    free = f.find([r"Physical Memory Available"])

    # fans and pumps on the board's sensor chip that are spinning now
    fans = [r for r in f.readings
            if r["sensor"] == chip and r["text"].endswith(" RPM") and (r["value"] or 0) > 0]
    # CPU fan and pump first: they're the ones that matter for cooling
    fans.sort(key=lambda r: 0 if re.fullmatch(r"CPU( Fan)?", r["label"], re.I)
              else 1 if re.search(r"pump|aio", r["label"], re.I) else 2)
    fan_specs = []
    for r in fans[:4]:
        extra = {"name": re.sub(r"(?i)^(chassis|system fan)\s*", "Ch", r["label"])[:6]}
        if re.search(r"pump|aio", r["label"], re.I):
            extra.update(name="Pump", warn=1500, danger=500)
        elif re.fullmatch(r"CPU( Fan)?", r["label"], re.I):
            extra.update(name="CPU", warn=300, danger=100)
        fan_specs.append(f.spec(r, **extra))

    # hottest drive sensor on the Windows (C:) drive
    ssd = f.find([r"Drive Temperature.*"], sensor=r"\[C:\]", pick=lambda hs: max(hs, key=lambda r: r["value"]))

    big = None
    if used:
        total = round((used["value"] + (free["value"] if free else 0)) * GB, 1)
        big = f.spec(used, unit=" GB", scale=GB, min=0, max=total, decimals=1, showPercent=True,
                     warn=round(total * 0.85, 1), danger=round(total * 0.95, 1))

    return {
        "title": short_name(chip, ["ASUS", "MSI", "Gigabyte", "ASRock"]) or "Motherboard",
        "size": 330,
        "big": big,
        "left": f.spec(board, min=20, max=70) if board else None,
        "right": f.spec(vrm or pch, min=20, max=100) if (vrm or pch) else None,
        "rows": [r for r in [
            row(f.spec(board, name="Board", warn=45, danger=55),
                f.spec(vrm, name="VRM", warn=85, danger=100)),
            row(*fan_specs[:2]),
            row(*fan_specs[2:4]),
            row(f.spec(ssd, name="SSD C:", warn=65, danger=75),
                f.spec(pch, name="PCH", decimals=0, warn=80, danger=90)),
        ] if r],
    }


IGNORE_APPS = ["dwm.exe", "explorer.exe", "chrome.exe", "msedge.exe", "msedgewebview2.exe",
               "firefox.exe", "Claude.exe", "Code.exe", "HWiNFO64.exe", "Taskmgr.exe", "steam.exe",
               "steamwebhelper.exe", "Discord.exe", "Spotify.exe", "ApplicationFrameHost.exe",
               "SearchHost.exe", "StartMenuExperienceHost.exe", "ShellExperienceHost.exe",
               "TextInputHost.exe"]


def fps_dial(f):
    fps = f.find([r"Framerate Presented \(avg\)", r"Framerate \(avg\)", r"Framerate"])
    if not fps:
        return None
    frame = f.find([r"Frame Time Presented \(avg\)", r"Frame Time \(avg\)", r"Frame Time"])
    low1 = f.find([r"Framerate Presented \(1% low\)", r"Framerate \(1% low\)"])
    low01 = f.find([r"Framerate Presented \(0\.1% low\)", r"Framerate \(0\.1% low\)"])
    return {
        "title": "FPS",
        "size": 300,
        "showApp": True,
        "ignoreApps": IGNORE_APPS,
        "left": f.spec(fps, unit=" FPS", min=0, max=144, decimals=0, invert=True),
        "right": f.spec(frame, min=0, max=50) if frame else None,
        "rows": [r for r in [
            row(f.spec(frame, name="Frame", decimals=1)),
            row(f.spec(low1, name="1% low", unit=" FPS", decimals=0)),
            row(f.spec(low01, name="0.1% low", unit=" FPS", decimals=0)),
        ] if r],
    }


def generate(readings):
    f = Finder(readings)
    dials = [d for d in (fps_dial(f), board_dial(f), cpu_dial(f), gpu_dial(f)) if d]
    for d in dials:  # drop parts that weren't found
        for k in [k for k, v in d.items() if v is None]:
            del d[k]
        d.setdefault("left", {"label": "", "min": 0, "max": 100})
        d.setdefault("right", {"label": "", "min": 0, "max": 100})
    return dials


if __name__ == "__main__":
    print(json.dumps(generate(read_hwinfo()), indent=2, ensure_ascii=False))
