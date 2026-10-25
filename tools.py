"""PCDials maintenance tools.

  python tools.py check                 list any dial value HWiNFO isn't sharing (and suggest fixes)
  python tools.py backup-hwinfo [name]  save HWiNFO's settings as a dated, named backup
  python tools.py list-backups          list the saved backups
  python tools.py restore-hwinfo [name] restore a backup (newest if no name; exit HWiNFO first)
  python tools.py auto-tick             tick every sensor this PC has (needs HWiNFO's shared memory)
  python tools.py default-hwinfo        standard settings for a NEW HWiNFO install (exit HWiNFO first)
"""
import ctypes
import difflib
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from helper import DIALS_FILE, read_hwinfo

HERE = Path(__file__).parent
HIDDEN = subprocess.CREATE_NO_WINDOW  # background commands: no console window flashing up
BACKUPS = HERE / "hwinfo-backups"  # dated, named copies of HWiNFO's settings
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


# ---------------------------------------------------------------- HWiNFO settings backups

class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_ulong), ("cntUsage", ctypes.c_ulong), ("th32ProcessID", ctypes.c_ulong),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", ctypes.c_ulong),
                ("cntThreads", ctypes.c_ulong), ("th32ParentProcessID", ctypes.c_ulong),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", ctypes.c_ulong),
                ("szExeFile", ctypes.c_wchar * 260)]


def hwinfo_running():
    """Ask Windows for the process list directly. (Running "tasklist" instead would
    flash a console window every time Setup refreshes.)"""
    k = ctypes.windll.kernel32
    k.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    snap = k.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
    entry = PROCESSENTRY32W(dwSize=ctypes.sizeof(PROCESSENTRY32W))
    found = False
    try:
        ok = k.Process32FirstW(ctypes.c_void_p(snap), ctypes.byref(entry))
        while ok and not found:
            found = entry.szExeFile.lower() == "hwinfo64.exe"
            ok = k.Process32NextW(ctypes.c_void_p(snap), ctypes.byref(entry))
    finally:
        k.CloseHandle(ctypes.c_void_p(snap))
    return found


def safe_name(name):
    return re.sub(r'[<>:"/\\|?*]', "", name).strip()[:60] or "Backup"


def backup_hwinfo(name=""):
    """Save HWiNFO's settings into a dated, named folder in hwinfo-backups."""
    folder = BACKUPS / f"{time.strftime('%Y-%m-%d %H.%M')} - {safe_name(name)}"
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "all.reg"
        subprocess.run(["reg", "export", HWINFO_REG, str(raw), "/y"], check=True,
                       capture_output=True, creationflags=HIDDEN)
        text = raw.read_text(encoding="utf-16")

    # Leave out the VSB section: that's HWiNFO's live readings, not settings.
    out, skip = [], False
    for line in text.splitlines():
        if line.startswith("["):
            skip = line.rstrip("]").endswith(r"\HWiNFO64\VSB")
        if not skip:
            out.append(line)
    (folder / "hwinfo-settings.reg").write_text("\n".join(out) + "\n", encoding="utf-16")
    if HWINFO_INI.exists():
        shutil.copy2(HWINFO_INI, folder / "HWiNFO64.INI")
    print(f"Saved HWiNFO settings: {folder.name}")
    return folder


def list_backups():
    """Saved backups, newest first: [{folder, date, name}]."""
    items = []
    for f in BACKUPS.glob("*/hwinfo-settings.reg"):
        date, _, name = f.parent.name.partition(" - ")
        items.append({"folder": f.parent.name, "date": date.replace(".", ":"), "name": name})
    return sorted(items, key=lambda b: b["folder"], reverse=True)


def restore_hwinfo(folder=None):
    """Put a saved backup back exactly (the newest one if none is named).
    Your current settings are saved first as "Before restoring ..."."""
    if hwinfo_running():
        print("Exit HWiNFO64 first (it saves its own settings on exit and would undo the restore).")
        return 1
    backups = list_backups()
    if not backups:
        print("No saved HWiNFO settings yet.")
        return 1
    folder = BACKUPS / (folder or backups[0]["folder"])
    if not (folder / "hwinfo-settings.reg").exists():
        print(f"No backup called {folder.name}.")
        return 1

    backup_hwinfo(f"Before restoring {folder.name.partition(' - ')[2]}")
    # Clear the sensor settings first so the result is exactly the backup, not a mix.
    subprocess.run(["reg", "delete", HWINFO_REG + r"\Sensors", "/f"], capture_output=True, creationflags=HIDDEN)
    subprocess.run(["reg", "import", str(folder / "hwinfo-settings.reg")], check=True, capture_output=True, creationflags=HIDDEN)
    print(f"Restored HWiNFO settings from {folder.name}.")
    ini = folder / "HWiNFO64.INI"
    if ini.exists() and not write_hwinfo_ini(ini.read_text(encoding="ascii", errors="ignore")):
        print("Couldn't restore HWiNFO64.INI (permission refused); the sensor settings are restored.")
    print("Start HWiNFO64 again.")
    return 0


def delete_backup(folder):
    """Send a saved backup to the Recycle Bin."""
    path = BACKUPS / folder
    if not (path / "hwinfo-settings.reg").exists():
        print(f"No backup called {folder}.")
        return 1
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Add-Type -AssemblyName Microsoft.VisualBasic;"
                    "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory("
                    f"'{path}','OnlyErrorDialogs','SendToRecycleBin')"], check=True, capture_output=True, creationflags=HIDDEN)
    print(f"Moved {folder} to the Recycle Bin.")
    return 0


# ---------------------------------------------------------------- ticking sensors in HWiNFO

# Sensors with the same HWiNFO IDs on every PC (memory, FPS, CPU totals, Intel CPU,
# NVIDIA GPU). Used when HWiNFO's shared memory isn't on; otherwise every sensor
# is ticked automatically (see auto_tick).
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
PENDING = HERE / "pending-hwinfo-ticks.json"  # read from shared memory, applied once HWiNFO exits
READING_TYPES = {1: "Temp", 2: "Volt", 3: "Fan", 4: "Current", 5: "Power", 6: "Clock", 7: "Usage", 8: "Other"}


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
                           capture_output=True, creationflags=HIDDEN)
        Path(t.name).unlink(missing_ok=True)
        return r.returncode == 0


def read_shared_memory():
    """Every sensor reading HWiNFO knows about, from its shared memory:
    [(sensor key, reading key, sensor name, label)], or None if shared memory is off.
    The keys are the ones HWiNFO uses for its Gadget settings in the registry."""
    k = ctypes.windll.kernel32
    k.OpenFileMappingW.restype = k.MapViewOfFile.restype = ctypes.c_void_p
    h = k.OpenFileMappingW(4, False, r"Global\HWiNFO_SENS_SM2")  # FILE_MAP_READ
    if not h:
        return None
    view = k.MapViewOfFile(ctypes.c_void_p(h), 4, 0, 0, 0)
    try:
        (_, _, _, _, s_off, s_size, s_num, r_off, r_size, r_num) = struct.unpack_from(
            "<IIIqIIIIII", ctypes.string_at(view, 48))
        data = ctypes.string_at(view, r_off + r_size * r_num)
    finally:
        k.UnmapViewOfFile(ctypes.c_void_p(view))
        k.CloseHandle(ctypes.c_void_p(h))
    text = lambda o: data[o:o + 128].split(b"\0")[0].decode("latin-1")
    sensors = [(*struct.unpack_from("<II", data, s_off + i * s_size), text(s_off + i * s_size + 8))
               for i in range(s_num)]
    entries = []
    for i in range(r_num):
        o = r_off + i * r_size
        kind, sensor, reading = struct.unpack_from("<III", data, o)
        sid, inst, name = sensors[sensor]
        # the top byte of the reading ID repeats its type; the key uses the rest
        entries.append((f"{sid:08X}_{inst}", f"{READING_TYPES.get(kind, 'Other')}{reading & 0xFFFFFF}",
                        name, text(o + 12)))
    return entries


def configure_hwinfo(pairs, what):
    """Turn on Gadget reporting, tick these (sensor key, reading key) pairs, and set the
    general settings (sensors only, minimized, start with Windows). HWiNFO must be closed."""
    import winreg
    base = SENSORS_KEY
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as k:
        winreg.SetValueEx(k, "EnableVSB", 0, winreg.REG_DWORD, 1)  # "Enable reporting to Gadget"

    # keep anything already shared; add the rest after it
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
    for sensor, entry in pairs:
        if (sensor, entry) in existing:
            continue
        existing.add((sensor, entry))
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base}\{sensor}\{entry}") as rk:
            winreg.SetValueEx(rk, "InVSB", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(rk, "VSBidx", 0, winreg.REG_DWORD, idx)
        idx += 1
        added += 1
    print(f"Gadget reporting is on. Ticked {added} {what} ({len(existing)} shared in total).")

    lines = HWINFO_INI.read_text(encoding="ascii", errors="ignore").splitlines() if HWINFO_INI.exists() else []
    settings = dict(l.split("=", 1) for l in lines if "=" in l)
    if any(settings.get(k) != v for k, v in DEFAULT_INI.items()):
        settings.update(DEFAULT_INI)
        text = "[Settings]\n" + "".join(f"{k}={v}\n" for k, v in settings.items())
        if write_hwinfo_ini(text):
            print("Set HWiNFO to open as Sensors only, minimized, and start with Windows.")
        else:
            print("Couldn't update HWiNFO64.INI (permission refused); the sensor settings are applied.")


def apply_default_hwinfo():
    if hwinfo_running():
        print("Exit HWiNFO64 first (it saves its own settings on exit and would undo this).")
        return 1
    configure_hwinfo([(s, e) for s, entries in DEFAULT_SENSORS.items() for e in entries],
                     "standard sensors")
    print("Start HWiNFO64 again. Then tick the remaining sensors Setup lists (board, fans, drives).")
    return 0


def auto_tick():
    """Step 1 (HWiNFO running, shared memory on): note every sensor this PC has.
    Step 2 happens once HWiNFO has exited: apply_pending()."""
    entries = read_shared_memory()
    if entries is None:
        print("HWiNFO's shared memory is off. In HWiNFO: Sensors > Settings (gear) > General >")
        print("tick 'Shared Memory Support' > OK (free; it only needs to be on for this step).")
        return 1
    PENDING.write_text(json.dumps([[s, r] for s, r, _, _ in entries]), encoding="utf-8")
    print(f"Found {len(entries)} sensor readings on this PC.")
    print("Now exit HWiNFO64 (tray icon > Exit). They'll be ticked as soon as it has closed.")
    return 0


def apply_pending():
    """If auto_tick noted sensors and HWiNFO has exited, tick them. Returns True if applied."""
    if not PENDING.exists() or hwinfo_running():
        return False
    pairs = [tuple(p) for p in json.loads(PENDING.read_text(encoding="utf-8"))]
    configure_hwinfo(pairs, "sensors")
    PENDING.unlink()
    print("Start HWiNFO64 again.")
    return True


def wait_and_apply():
    """auto-tick from the command line: wait for HWiNFO to exit, then apply."""
    if auto_tick():
        return 1
    print("Waiting for HWiNFO64 to exit...")
    while not apply_pending():
        time.sleep(2)
    return 0


def show_backups():
    for b in list_backups():
        print(f"{b['date']}  {b['name']}")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    commands = {
        "check": check,
        "backup-hwinfo": lambda: 0 if backup_hwinfo(" ".join(args[1:])) else 1,
        "list-backups": show_backups,
        "restore-hwinfo": lambda: restore_hwinfo(" ".join(args[1:]) or None),
        "default-hwinfo": apply_default_hwinfo,
        "auto-tick": wait_and_apply,
    }
    if not args or args[0] not in commands:
        print(__doc__)
        sys.exit(1)
    sys.exit(commands[args[0]]())
