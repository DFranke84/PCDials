"""PCDials maintenance tools.

  python tools.py check           list any dial value HWiNFO isn't sharing (and suggest fixes)
  python tools.py export-hwinfo   save your HWiNFO settings into the hwinfo-profile folder
  python tools.py import-hwinfo   put the saved HWiNFO settings back (close HWiNFO first)
  python tools.py default-hwinfo  default settings for a NEW HWiNFO install on any PC (close HWiNFO first)
"""
import difflib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from helper import DIALS_FILE, read_hwinfo

HERE = Path(__file__).parent
PROFILE = HERE / "hwinfo-profile"
REG_FILE = PROFILE / "hwinfo-settings.reg"
INI_FILE = PROFILE / "HWiNFO64.INI"
HWINFO_INI = Path(r"C:\Program Files\HWiNFO64\HWiNFO64.INI")
HWINFO_REG = r"HKCU\Software\HWiNFO64"
SENSORS_KEY = r"Software\HWiNFO64\Sensors"


# ---------------------------------------------------------------- check

def find(readings, spec):
    """Same matching rule as dial.html: label (+ source), prefer the matching unit."""
    hits = [r for r in readings
            if r["label"] == spec["label"] and spec.get("source", "") in r["sensor"]]
    unit = spec.get("hwunit") or (spec.get("unit") or "").strip().split(" ")[0]
    for r in hits:
        if unit and r["text"].endswith(" " + unit):
            return r
    return hits[0] if hits else None


def all_specs(dial):
    for key in ("big", "bigExtra", "left", "right"):
        if key in dial:
            yield key, dial[key]
    for n, row in enumerate(dial.get("rows", []), 1):
        for spec in row:
            yield f"row {n}", spec


def missing_values(readings, dials):
    """Dial values HWiNFO isn't sharing, with close-matching label suggestions."""
    labels = sorted({r["label"] for r in readings})
    return [{"dial": dial["title"], "where": where, "label": spec["label"],
             "source": spec.get("source", ""),
             "suggest": difflib.get_close_matches(spec["label"], labels, n=3, cutoff=0.5)}
            for dial in dials for where, spec in all_specs(dial)
            if not find(readings, spec)]


def check():
    readings = read_hwinfo()
    if not readings:
        print("HWiNFO isn't sharing anything.")
        print("  - Is HWiNFO64 running (Sensors window)?")
        print("  - Sensors > Settings > HWiNFO Gadget tab > tick 'Enable reporting to Gadget'.")
        return 1

    missing = missing_values(readings, json.loads(DIALS_FILE.read_text(encoding="utf-8")))
    for m in missing:
        src = f' (source "{m["source"]}")' if m["source"] else ""
        print(f'{m["dial"]} / {m["where"]}: "{m["label"]}"{src} not found')
        if m["suggest"]:
            print(f"    did you mean: {', '.join(m['suggest'])}")
        else:
            print("    tick it in HWiNFO: Sensors > Settings > HWiNFO Gadget > 'Report value in Gadget'")

    if missing:
        print(f"\n{len(missing)} value(s) not found. Fix the label in dials.json or tick the sensor in HWiNFO.")
        return 1
    print(f"All dial values found ({len(readings)} readings shared by HWiNFO).")
    return 0


# ---------------------------------------------------------------- HWiNFO profile

def export_hwinfo():
    PROFILE.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "all.reg"
        subprocess.run(["reg", "export", HWINFO_REG, str(raw), "/y"], check=True,
                       capture_output=True)
        text = raw.read_text(encoding="utf-16")

    # Leave out the VSB section: that's HWiNFO's live readings, not settings.
    out, skip = [], False
    for line in text.splitlines():
        if line.startswith("["):
            skip = line.rstrip("]").endswith(r"\HWiNFO64\VSB")
        if not skip:
            out.append(line)
    REG_FILE.write_text("\n".join(out) + "\n", encoding="utf-16")

    if HWINFO_INI.exists():
        shutil.copy2(HWINFO_INI, INI_FILE)
    print(f"Saved HWiNFO settings to {PROFILE}")
    return 0


def hwinfo_running():
    out = subprocess.run(["tasklist", "/fi", "imagename eq HWiNFO64.exe"],
                         capture_output=True, text=True).stdout
    return "hwinfo64.exe" in out.lower()  # Windows may list it as HWiNFO64.EXE


# Default HWiNFO settings for a NEW install on any PC. These sensors use the same
# HWiNFO IDs on every PC (memory, FPS, CPU totals, Intel CPU, NVIDIA GPU); anything
# else (board temps, fans, drives, AMD parts) is ticked by hand: Setup lists them.
DEFAULT_SENSORS = {
    "F0000301_0": ["Other3", "Other4"],                    # memory used / available
    "F0000300_0": ["Usage33", "Usage67", "Group3"],        # total CPU usage / utility, avg clock
    "F0000400_0": ["Temp510", "Temp511"],                  # Intel: CPU package / core max
    "F0002A00_0": ["Temp4", "Power0", "Power1"],           # Intel: package temp, package/cores power
    "E0002000_0": ["Temp0", "Temp5", "Fan0", "Other0", "Power0", "Usage0", "Usage1", "Usage8",
                   "Other251", "Other252", "Other253"],    # NVIDIA GPU
    "F0000FF0_0": ["Other0", "Other4", "Other5", "Other20"],  # FPS (PresentMon)
}
DEFAULT_INI = {  # HWiNFO64.INI [Settings]
    "SensorsOnly": "1", "ShowWelcomeAndProgress": "0", "OpenSystemSummary": "0",
    "MinimalizeSensors": "1", "MinimalizeSensorsClose": "1", "MinimalizeMainWnd": "1",
    "Autorun": "1", "SensorInterval": "1000", "ShowFans0RPM": "1",
}


def write_hwinfo_ini(text):
    """Write HWiNFO64.INI in Program Files, asking Windows for permission if needed."""
    try:
        HWINFO_INI.write_text(text, encoding="ascii")
        return True
    except PermissionError:
        with tempfile.NamedTemporaryFile("w", suffix=".ini", delete=False, encoding="ascii") as t:
            t.write(text)
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"Start-Process -Wait -Verb RunAs -WindowStyle Hidden powershell "
                            f"-ArgumentList '-NoProfile','-Command','Copy-Item -Force \"{t.name}\" \"{HWINFO_INI}\"'"],
                           capture_output=True)
        Path(t.name).unlink(missing_ok=True)
        return r.returncode == 0


def apply_default_hwinfo():
    if hwinfo_running():
        print("Close HWiNFO64 first (it saves its own settings on exit and would undo this).")
        return 1
    import winreg
    base = SENSORS_KEY
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as k:
        winreg.SetValueEx(k, "EnableVSB", 0, winreg.REG_DWORD, 1)  # "Enable reporting to Gadget"

    # keep anything already shared; add the defaults after it
    existing, used_idx = set(), []
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as k:
        for i in range(winreg.QueryInfoKey(k)[0]):
            s = winreg.EnumKey(k, i)
            with winreg.OpenKey(k, s) as sk:
                for j in range(winreg.QueryInfoKey(sk)[0]):
                    r = winreg.EnumKey(sk, j)
                    with winreg.OpenKey(sk, r) as rk:
                        try:
                            if winreg.QueryValueEx(rk, "InVSB")[0] == 1:
                                existing.add((s, r))
                                used_idx.append(winreg.QueryValueEx(rk, "VSBidx")[0])
                        except OSError:
                            pass
    idx, added = max(used_idx, default=-1) + 1, 0
    for sensor, entries in DEFAULT_SENSORS.items():
        for entry in entries:
            if (sensor, entry) in existing:
                continue
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base}\{sensor}\{entry}") as rk:
                winreg.SetValueEx(rk, "InVSB", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(rk, "VSBidx", 0, winreg.REG_DWORD, idx)
            idx += 1
            added += 1
    print(f"Turned on Gadget reporting and added {added} standard sensors.")

    # general settings: sensors-only, start minimized, start with Windows
    lines = HWINFO_INI.read_text(encoding="ascii", errors="ignore").splitlines() if HWINFO_INI.exists() else []
    settings = dict(l.split("=", 1) for l in lines if "=" in l)
    settings.update(DEFAULT_INI)
    text = "[Settings]\n" + "".join(f"{k}={v}\n" for k, v in settings.items())
    if write_hwinfo_ini(text):
        print("Set HWiNFO to open as Sensors only, minimized, and start with Windows.")
    else:
        print("Couldn't update HWiNFO64.INI (permission refused); the sensor settings are applied.")
    print("Start HWiNFO64 again. Then tick the remaining sensors Setup lists (board, fans, drives).")
    return 0


def import_hwinfo():
    if hwinfo_running():
        print("Close HWiNFO64 first (it saves its own settings on exit and would undo the import).")
        return 1
    if not REG_FILE.exists():
        print(f"No saved profile in {PROFILE}. Run 'python tools.py export-hwinfo' first.")
        return 1

    subprocess.run(["reg", "import", str(REG_FILE)], check=True, capture_output=True)
    print("Imported sensor settings (shared sensors, names, Gadget reporting).")
    if INI_FILE.exists():
        try:
            shutil.copy2(INI_FILE, HWINFO_INI)
            print("Copied HWiNFO64.INI (general settings).")
        except PermissionError:
            print(f"To also restore general settings, copy {INI_FILE}")
            print(f"  to {HWINFO_INI.parent} (needs administrator rights).")
    print("Start HWiNFO64 again, then run 'python tools.py check'.")
    return 0


if __name__ == "__main__":
    commands = {"check": check, "export-hwinfo": export_hwinfo, "import-hwinfo": import_hwinfo,
                "default-hwinfo": apply_default_hwinfo}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        print(__doc__)
        sys.exit(1)
    sys.exit(commands[sys.argv[1]]())
