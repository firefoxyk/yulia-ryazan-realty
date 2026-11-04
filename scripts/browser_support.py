"""Dependency-free local Chrome CDP support for optional browser checks."""
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "artifacts/screenshots"
http = build_opener(ProxyHandler({}))

class CDP:
    def __init__(self, url):
        parsed = urlsplit(url)
        self.sock = socket.create_connection((parsed.hostname, parsed.port), timeout=15)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {parsed.path} HTTP/1.1\r\nHost: {parsed.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        header = b""
        while not header.endswith(b"\r\n\r\n"):
            header += self.sock.recv(1)
        assert header.split()[1] == b"101", header
        self.next_id = 0
        self.events = []

    def exact(self, count):
        result = b""
        while len(result) < count:
            data = self.sock.recv(count - len(result))
            if not data:
                raise RuntimeError("Browser closed websocket")
            result += data
        return result

    def receive(self):
        parts = []
        while True:
            first, second = self.exact(2)
            size = second & 127
            if size == 126:
                size = struct.unpack("!H", self.exact(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self.exact(8))[0]
            mask = self.exact(4) if second & 128 else None
            data = self.exact(size)
            if mask:
                data = bytes(v ^ mask[i % 4] for i, v in enumerate(data))
            if first & 15 == 8:
                raise RuntimeError("Websocket closed")
            if first & 15 in (0, 1):
                parts.append(data)
                if first & 128:
                    return json.loads(b"".join(parts))

    def call(self, method, **params):
        self.next_id += 1
        ident = self.next_id
        data = json.dumps(dict(id=ident, method=method, params=params)).encode()
        mask = os.urandom(4)
        size = len(data)
        header = bytes([129, 128 | size]) if size < 126 else bytes([129, 128 | 126]) + struct.pack("!H", size)
        self.sock.sendall(header + mask + bytes(v ^ mask[i % 4] for i, v in enumerate(data)))
        while True:
            result = self.receive()
            if result.get("id") == ident:
                if "error" in result:
                    raise RuntimeError(result["error"])
                return result.get("result", {})
            self.events.append(result)

    def evaluate(self, expression):
        result = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        assert "exceptionDetails" not in result, result
        return result["result"].get("value")

    def navigate(self, url):
        self.events.clear()
        self.call("Page.navigate", url=url)
        if not any(e.get("method") == "Page.loadEventFired" for e in self.events):
            while True:
                event = self.receive()
                self.events.append(event)
                if event.get("method") == "Page.loadEventFired":
                    break
        self.evaluate("document.fonts.ready.then(() => true)")

    def screenshot(self, name, full=True):
        metrics = self.call("Page.getLayoutMetrics")["cssContentSize"]
        params = dict(format="png", captureBeyondViewport=full)
        if full:
            params["clip"] = dict(x=0, y=0, width=metrics["width"], height=metrics["height"], scale=1)
        result = self.call("Page.captureScreenshot", **params)
        path = SHOTS / name
        path.write_bytes(base64.b64decode(result["data"]))
        print("Screenshot:", name, path.stat().st_size, flush=True)


@contextmanager
def open_browser():
    candidates = [os.environ.get("BROWSER_PATH"), shutil.which("google-chrome"),
                  shutil.which("chromium"), shutil.which("chromium-browser"),
                  r"C:\Program Files\Google\Chrome\Application\chrome.exe"]
    executable = next((p for p in candidates if p and Path(p).is_file()), None)
    if not executable:
        raise RuntimeError("Chrome/Chromium unavailable. Set BROWSER_PATH to an installed browser.")
    SHOTS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="yulia-catalog-browser-") as profile:
        process = subprocess.Popen([executable, "--headless", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", "--disable-extensions", "--disable-background-networking",
            "--no-proxy-server", "--remote-debugging-port=0", "--user-data-dir=" + profile, "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cdp = None
        try:
            port_file = Path(profile) / "DevToolsActivePort"
            deadline = time.monotonic() + 15
            while not port_file.exists():
                if time.monotonic() > deadline or process.poll() is not None:
                    raise RuntimeError("Chrome debugging port unavailable")
                time.sleep(.1)
            port = int(port_file.read_text().splitlines()[0])
            with http.open(f"http://127.0.0.1:{port}/json/list") as response:
                tabs = json.load(response)
            cdp = CDP(next(tab["webSocketDebuggerUrl"] for tab in tabs if tab["type"] == "page"))
            cdp.call("Page.enable")
            cdp.call("Runtime.enable")
            yield cdp
        finally:
            if cdp:
                cdp.sock.close()
            process.terminate()
            process.wait(timeout=10)
