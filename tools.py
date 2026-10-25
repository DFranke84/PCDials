"""PCDials maintenance tools.

  python tools.py check           list any dial value HWiNFO isn't sharing (and suggest fixes)
  python tools.py export-hwinfo   save your HWiNFO settings into the hwinfo-profile folder
  python tools.py import-hwinfo   put the saved HWiNFO settings back (close HWiNFO first)
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


# ---------------------------------------------------------------- check

def find(readings, spec):
    """Same matching rule as dial.html: label (+ source), prefer the matching unit."""
    hits = [r for r in readings
            if r["label"] == spec["label"] and spec.get("source", "") in r["sensor"]]
    unit = (spec.get("unit") or "").strip().split(" ")[0]
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
    commands = {"check": check, "export-hwinfo": export_hwinfo, "import-hwinfo": import_hwinfo}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        print(__doc__)
        sys.exit(1)
    sys.exit(commands[sys.argv[1]]())
