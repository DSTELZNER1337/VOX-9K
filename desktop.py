"""Optional native window for the existing loopback VOX-9K application."""
from pathlib import Path
import html
import importlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

from desktop_editing import install_editing_menu

BASE_DIR = Path(__file__).resolve().parent
APP_URL = "http://127.0.0.1:5000"
SERVICE_NAME = "vox-9k"
API_VERSION = 1


class DesktopStartupError(RuntimeError):
    pass


def application_health(timeout=0.5):
    """Identify VOX-9K without warming or initializing either engine."""
    try:
        with urllib.request.urlopen(APP_URL + "/health", timeout=timeout) as response:
            data = json.loads(response.read(16384).decode("utf-8"))
        if (isinstance(data, dict) and data.get("service") == SERVICE_NAME
                and data.get("api_version") == API_VERSION
                and isinstance(data.get("instance_id"), str) and data["instance_id"]):
            return data
    except (OSError, ValueError, urllib.error.URLError):
        pass
    return None


def port_in_use():
    # Do not infer service ownership merely from an open port.
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", 5000))
        except OSError:
            return True
    return False


class DesktopServices:
    def __init__(self, startup_timeout=60):
        self.startup_timeout = startup_timeout
        self.closed = threading.Event()
        self._lock = threading.Lock()
        self.process = None
        self._log = None
        self.log_path = None
        self.instance_id = uuid.uuid4().hex

    def connect(self):
        if self.closed.is_set():
            raise DesktopStartupError("The desktop window was closed.")
        existing = application_health()
        if existing is not None:
            return APP_URL
        if port_in_use():
            raise DesktopStartupError("Port 5000 is occupied by an unrecognized or busy service. Close the conflicting application or retry after its current read finishes. No existing process was stopped.")
        with self._lock:
            if self.closed.is_set():
                raise DesktopStartupError("The desktop window was closed.")
            directory = BASE_DIR / "audit"
            directory.mkdir(exist_ok=True)
            self.log_path = directory / ("desktop-" + self.instance_id + ".log")
            self._log = self.log_path.open("a", encoding="utf-8")
            env = os.environ.copy()
            env.update(VOX_INSTANCE_ID=self.instance_id, VOX_DESKTOP_PARENT_PIPE="1", PYTHONUNBUFFERED="1")
            try:
                self.process = subprocess.Popen(
                    [sys.executable, str(BASE_DIR / "server.py")], cwd=str(BASE_DIR),
                    env=env, stdin=subprocess.PIPE, stdout=self._log, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception:
                self._log.close()
                self._log = None
                raise
            process = self.process
        deadline = time.monotonic() + self.startup_timeout
        while not self.closed.is_set() and time.monotonic() < deadline:
            if process.poll() is not None:
                raise DesktopStartupError("The local VOX-9K service exited during startup. Check " + str(self.log_path))
            health = application_health()
            if health is not None:
                if health["instance_id"] != self.instance_id:
                    raise DesktopStartupError("Another VOX-9K instance acquired port 5000 during startup. This launch will close only its own service; retry to connect to the existing instance.")
                return APP_URL
            self.closed.wait(0.1)
        if self.closed.is_set():
            raise DesktopStartupError("The desktop window was closed.")
        raise DesktopStartupError("The local VOX-9K service did not become ready in time. Check " + str(self.log_path))

    def close(self):
        """Release only services owned by this desktop launch; safe to repeat."""
        self.closed.set()
        with self._lock:
            process, self.process = self.process, None
            log, self._log = self._log, None
        try:
            if process is not None:
                if process.stdin is not None:
                    process.stdin.close()
                try:
                    process.wait(timeout=7)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
        finally:
            if log is not None:
                log.close()


def startup_page(message, error=False):
    heading = "VOX-9K could not start" if error else "Starting VOX-9K"
    return ("<!doctype html><html><head><title>VOX-9K</title></head>"
            "<body style='background:#121212;color:#e8e8e8;font-family:Arial,sans-serif;padding:30px;line-height:1.6'>"
            "<h1>" + heading + "</h1><p>" + html.escape(str(message)) + "</p></body></html>")


def main(webview_module=None, services=None):
    try:
        webview = webview_module or importlib.import_module("webview")
    except ImportError:
        print(r"Desktop mode needs the optional dependency. Run: .\.venv\Scripts\python.exe -m pip install -r requirements-desktop.txt", file=sys.stderr)
        return 1
    if hasattr(webview, "settings"):
        webview.settings["ALLOW_DOWNLOADS"] = True
    services = services or DesktopServices()
    startup_failed = threading.Event()
    try:
        window = webview.create_window(
            "VOX-9K", html=startup_page("Preparing the local speech service. Cached models may take a moment to warm up."),
            width=1280, height=960, min_size=(960, 720), resizable=True,
            text_select=True, background_color="#121212",
        )
        window.events.closed += services.close
        window.events.loaded += lambda: install_editing_menu(window)

        def start_services():
            try:
                url = services.connect()
                if not services.closed.is_set():
                    window.load_url(url)
            except Exception as error:
                startup_failed.set()
                services.close()
                try:
                    window.load_html(startup_page(error, error=True))
                except Exception:
                    print("VOX-9K startup error:", error, file=sys.stderr)

        # Require modern WebView2: never fall back to legacy MSHTML.
        webview.start(start_services, gui="edgechromium", debug=False)
        return 1 if startup_failed.is_set() else 0
    except Exception as error:
        print("VOX-9K desktop failed:", error, "Check pywebview and the Microsoft Edge WebView2 Runtime.", file=sys.stderr)
        return 1
    finally:
        services.close()


if __name__ == "__main__":
    raise SystemExit(main())
