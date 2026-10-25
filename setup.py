"""PCDials Setup: install, check and edit the dials in one window.

  python setup.py            open the setup window
  python setup.py --server   serve it only (open http://127.0.0.1:8766/setup.html in a browser)
"""
import contextlib
import ctypes
import io
import json
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import tools
from helper import (DIALS_FILE, HERE, POSITIONS_FILE, PORT as DIALS_PORT, Handler, Server,
                    load_json, monitor_connected, read_hwinfo)

# Work in real screen pixels, like the dials do, so monitor checks agree.
ctypes.windll.shcore.SetProcessDpiAwareness(2)

PORT = 8766
PYTHONW = Path(sys.executable).with_name("pythonw.exe")
STARTUP_LINK = Path.home() / r"AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\PCDials.lnk"

draft = None  # unsaved dials from the editor, used by the live preview


def powershell(script):
    return subprocess.run(["powershell", "-NoProfile", "-Command", script],
                          capture_output=True, text=True)


def captured(fn):
    """Run a tools.py command and return what it printed."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = fn()
    return {"ok": code == 0, "message": out.getvalue().strip()}


def dials_running():
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{DIALS_PORT}/dials.json", timeout=1)
        return True
    except OSError:
        return False


def status():
    try:
        import webview  # noqa: F401
        pywebview = True
    except ImportError:
        pywebview = False
    readings = read_hwinfo()
    hwinfo = tools.hwinfo_running()
    profile = tools.REG_FILE.stat().st_mtime if tools.REG_FILE.exists() else None
    return {
        "python": sys.version.split()[0],
        "pywebview": pywebview,
        "startup": STARTUP_LINK.exists(),
        "hwinfo": hwinfo,
        "sharing": len(readings),
        "dials": dials_running(),
        "profile": profile,
        "missing": tools.missing_values(readings, json.loads(DIALS_FILE.read_text(encoding="utf-8")))
                   if readings else [],
    }


def format_dials(dials):
    """dials.json layout: one line per value, so it stays easy to read and edit by hand."""
    one = lambda v: json.dumps(v, ensure_ascii=False)
    out = []
    for dial in dials:
        lines = []
        for k, v in dial.items():
            if k == "rows":
                rows = ["      [ " + ",\n        ".join(one(s) for s in row) + " ]" for row in v]
                lines.append('    "rows": [\n' + ",\n".join(rows) + "\n    ]")
            else:
                lines.append(f"    {one(k)}: {one(v)}")
        out.append("  {\n" + ",\n".join(lines) + "\n  }")
    return "[\n" + ",\n".join(out) + "\n]\n"


# ---------------------------------------------------------------- actions

def start_dials():
    if dials_running():
        return {"ok": True, "message": "The dials are already running."}
    subprocess.Popen([str(PYTHONW), str(HERE / "helper.py")], cwd=HERE,
                     creationflags=subprocess.DETACHED_PROCESS)
    return {"ok": True, "message": "Starting the dials..."}


def stop_dials():
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{DIALS_PORT}/quit", method="POST"), timeout=3)
        return {"ok": True, "message": "Dials closed."}
    except OSError:
        return {"ok": True, "message": "The dials weren't running."}


def startup_on():
    r = powershell(
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
        "$s.TargetPath='%s';$s.Arguments='\"%s\"';$s.WorkingDirectory='%s';"
        "$s.Description='PCDials desktop dials';$s.Save()"
        % (STARTUP_LINK, PYTHONW, HERE / "helper.py", HERE))
    return {"ok": r.returncode == 0, "message": r.stderr.strip() or "Dials will start when you log in."}


def startup_off():
    # to the Recycle Bin, not a permanent delete
    r = powershell(
        "Add-Type -AssemblyName Microsoft.VisualBasic;"
        "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile('%s','OnlyErrorDialogs','SendToRecycleBin')"
        % STARTUP_LINK)
    return {"ok": r.returncode == 0, "message": r.stderr.strip() or "Dials won't start at login any more."}


def install_deps():
    r = subprocess.run([sys.executable, "-m", "pip", "install", "pywebview"],
                       capture_output=True, text=True)
    last = (r.stdout.strip().splitlines() or [""])[-1]
    return {"ok": r.returncode == 0, "message": last if r.returncode == 0 else r.stderr.strip()[-500:]}


def move_to_main(all_dials=False):
    """Put dials on the main monitor: only those whose monitor is gone, or all of them.
    The dials are closed while positions.json is changed, then started again."""
    positions = load_json(POSITIONS_FILE, {})
    moved, x = [], 40
    for dial in json.loads(DIALS_FILE.read_text(encoding="utf-8")):
        pos = positions.setdefault(dial["title"], {})
        size = pos.get("size") or dial.get("size", 330)
        if all_dials or not monitor_connected(pos):
            pos.update(x=x, y=40)
            moved.append(dial["title"])
            x += size + 20
    if not moved:
        return {"ok": True, "message": "Every dial's monitor is connected; nothing to move."}
    was_running = dials_running()
    if was_running:
        stop_dials()
        time.sleep(2)  # let the dials save and close before changing their positions
    POSITIONS_FILE.write_text(json.dumps(positions, indent=2), encoding="utf-8")
    if was_running:
        start_dials()
    return {"ok": True, "message": "Moved to the main monitor: " + ", ".join(moved)}


def save_dials(dials):
    global draft
    DIALS_FILE.write_text(format_dials(dials), encoding="utf-8")
    draft = None
    return {"ok": True, "message": "Saved. Running dials update in a couple of seconds."}


ACTIONS = {
    "start_dials": start_dials, "stop_dials": stop_dials,
    "startup_on": startup_on, "startup_off": startup_off,
    "install_deps": install_deps,
    "export_hwinfo": lambda: captured(tools.export_hwinfo),
    "import_hwinfo": lambda: captured(tools.import_hwinfo),
}


# ---------------------------------------------------------------- web server

class SetupHandler(Handler):
    def send_json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/status":
            self.send_json(status())
        elif path == "/api/readings":
            self.send_json(read_hwinfo())
        elif path == "/dials.json" and draft is not None and "saved" not in self.path:
            self.send_json(draft)  # live preview shows unsaved edits
        else:
            super().do_GET()

    def do_POST(self):
        global draft
        name = self.path.removeprefix("/api/")
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or "null")
        try:
            if name == "draft":
                draft = body
                self.send_json({"ok": True})
            elif name == "save":
                self.send_json(save_dials(body))
            elif name == "move_to_main":
                self.send_json(move_to_main(bool(body and body.get("all"))))
            elif name in ACTIONS:
                self.send_json(ACTIONS[name]())
            else:
                self.send_error(404)
        except Exception as e:
            self.send_json({"ok": False, "message": str(e)})


class SetupServer(Server):
    pass


if __name__ == "__main__":
    try:
        server = SetupServer(("127.0.0.1", PORT), SetupHandler)
    except OSError:
        sys.exit("PCDials Setup is already open.")
    url = f"http://127.0.0.1:{PORT}/setup.html"
    if "--server" in sys.argv:
        server.serve_forever()
    else:
        try:
            import webview
        except ImportError:
            # Fresh PC without pywebview yet: use the web browser (its Install button fixes this)
            import webbrowser
            webbrowser.open(url)
            server.serve_forever()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        webview.create_window("PCDials Setup", url, width=1100, height=760, min_size=(900, 600),
                              background_color="#1b1e23")
        webview.start()
