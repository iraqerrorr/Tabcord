#!/usr/bin/env python3
"""
Browser -> Discord Rich Presence (no external packages needed).

Shows which browser you're using (Opera GX, Opera, Chrome, Edge, Firefox,
Brave, Vivaldi) and what you're watching/listening to (YouTube, Twitch,
Netflix, Spotify, etc.) based on the browser window title.

SETUP
1. https://discord.com/developers/applications -> New Application.
   The application NAME shows after "Playing ..." (e.g. "Web Browser").
2. Copy the Application ID into CLIENT_ID below.
3. (Optional) Rich Presence > Art Assets: upload logos named
   operagx, opera, chrome, edge, firefox, brave, vivaldi, browser
4. Keep the Discord DESKTOP app open, then run:  python operagx_presence.py
5. Discord: User Settings > Activity Privacy > turn on
   "Share your detected activities with others".

TAB MODE (recommended): load the "tab-extension" folder into your browser
(opera://extensions > Developer mode > Load unpacked). It reports which tab
is playing audio / active plus how many tabs are open. Without it, the script
falls back to the window title (active tab only, Windows only).
"""

import ctypes
import json
import os
import re
import socket
import struct
import subprocess
import sys
import time
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# ------------------------- EDIT THESE -------------------------
CLIENT_ID = "PASTE_YOUR_APPLICATION_ID_HERE"
SHOW_TITLE = True        # False = only show browser name, never page/video titles
HIDE_PRIVATE = True      # hide titles in Incognito / InPrivate / Private windows
CHECK_EVERY = 15         # seconds between checks (Discord rate-limits faster)
PORT = 47821             # must match the extension
SHOW_TAB_COUNT = True    # show "5 tabs" in the status
SHOW_SITE_ONLY = False   # True = show 'Watching YouTube' without the video title
# --------------------------------------------------------------

IS_WIN = sys.platform.startswith("win")

# exe name -> (display name, art asset key)
BROWSERS = {
    "opera.exe": ("Opera", "opera"),        # becomes Opera GX if path contains "GX"
    "chrome.exe": ("Chrome", "chrome"),
    "msedge.exe": ("Edge", "edge"),
    "firefox.exe": ("Firefox", "firefox"),
    "brave.exe": ("Brave", "brave"),
    "vivaldi.exe": ("Vivaldi", "vivaldi"),
}

# keyword in tab title -> (site name, verb)
MEDIA_SITES = {
    "youtube": ("YouTube", "Watching"),
    "twitch": ("Twitch", "Watching"),
    "netflix": ("Netflix", "Watching"),
    "disney+": ("Disney+", "Watching"),
    "prime video": ("Prime Video", "Watching"),
    "hulu": ("Hulu", "Watching"),
    "crunchyroll": ("Crunchyroll", "Watching"),
    "max": ("Max", "Watching"),
    "kick": ("Kick", "Watching"),
    "spotify": ("Spotify", "Listening to"),
    "soundcloud": ("SoundCloud", "Listening to"),
    "apple music": ("Apple Music", "Listening to"),
    "deezer": ("Deezer", "Listening to"),
}

BROWSER_WORDS = ["google chrome", "microsoft edge", "mozilla firefox",
                 "brave", "vivaldi", "opera gx", "opera"]
PRIVATE_WORDS = ["incognito", "inprivate", "private browsing", "private window"]
JUNK_TITLES = ["legacy window", "default ime", "msctfime", "gdi+"]


# ---------------------- Discord IPC client ----------------------
class DiscordIPC:
    def __init__(self, client_id):
        self.client_id = client_id
        self.conn = None

    def _paths(self):
        for i in range(10):
            if IS_WIN:
                yield rf"\\?\pipe\discord-ipc-{i}"
            else:
                base = (os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR")
                        or os.environ.get("TMP") or os.environ.get("TEMP") or "/tmp")
                base = base.rstrip("/")
                yield f"{base}/discord-ipc-{i}"
                yield f"{base}/app/com.discordapp.Discord/discord-ipc-{i}"
                yield f"{base}/snap.discord/discord-ipc-{i}"

    def connect(self):
        for path in self._paths():
            try:
                if IS_WIN:
                    self.conn = open(path, "r+b", buffering=0)
                else:
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    s.connect(path)
                    self.conn = s
                self._send(0, {"v": 1, "client_id": self.client_id})
                _, data = self._recv()
                if data.get("evt") == "READY":
                    return True
                self.close()
            except OSError:
                self.conn = None
        return False

    def _send(self, op, payload):
        raw = json.dumps(payload).encode("utf-8")
        frame = struct.pack("<II", op, len(raw)) + raw
        if IS_WIN:
            self.conn.write(frame)
        else:
            self.conn.sendall(frame)

    def _read_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.conn.read(n - len(buf)) if IS_WIN else self.conn.recv(n - len(buf))
            if not chunk:
                raise OSError("Discord closed the connection")
            buf += chunk
        return buf

    def _recv(self):
        op, length = struct.unpack("<II", self._read_exact(8))
        return op, json.loads(self._read_exact(length).decode("utf-8"))

    def set_activity(self, activity):
        self._send(1, {
            "cmd": "SET_ACTIVITY",
            "args": {"pid": os.getpid(), "activity": activity},
            "nonce": str(uuid.uuid4()),
        })
        return self._recv()

    def close(self):
        try:
            if self.conn:
                self.conn.close()
        except OSError:
            pass
        self.conn = None


# ---------------------- Browser detection ----------------------
def _windows_browser_windows():
    """Return [(is_foreground, title, exe_path)] for visible browser windows."""
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    fg = user32.GetForegroundWindow()
    found = []

    def proc_path(pid):
        h = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value
            return ""
        finally:
            kernel32.CloseHandle(h)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value
        if any(j in title.lower() for j in JUNK_TITLES):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        path = proc_path(pid.value)
        if os.path.basename(path).lower() in BROWSERS:
            found.append((hwnd == fg, title, path))
        return True

    user32.EnumWindows(callback, 0)
    return found


def _other_os_browser():
    """No titles available: just detect a running browser by process name."""
    names = {
        "Opera GX": "opera.*gx|opera_gx", "Chrome": "chrome", "Firefox": "firefox",
        "Edge": "msedge|microsoft-edge", "Brave": "brave", "Vivaldi": "vivaldi",
    }
    for name, pattern in names.items():
        try:
            if subprocess.run(["pgrep", "-fi", pattern], capture_output=True).returncode == 0:
                return {"browser": name, "asset": name.lower().replace(" ", ""), "title": None, "site": None}
        except Exception:
            pass
    return None


def clean_title(raw):
    raw = raw.replace("\u200b", "").strip()
    parts = re.split(r"\s[-–—]\s", raw)
    while len(parts) > 1 and any(w in parts[-1].lower() for w in BROWSER_WORDS):
        parts.pop()
    parts = [re.sub(r"\s+and \d+ more pages?$", "", p, flags=re.I) for p in parts]
    return parts


def detect():
    if not IS_WIN:
        return _other_os_browser()

    windows = _windows_browser_windows()
    if not windows:
        return None

    def media_hit(title):
        low = title.lower()
        return any(k in low for k in MEDIA_SITES)

    # Priority: foreground browser > a window that looks like media > first one
    windows.sort(key=lambda w: (not w[0], not media_hit(w[1])))
    _, title, path = windows[0]

    exe = os.path.basename(path).lower()
    name, asset = BROWSERS[exe]
    if exe == "opera.exe" and "gx" in path.lower():
        name, asset = "Opera GX", "operagx"

    info = {"browser": name, "asset": asset, "title": None, "site": None, "verb": None}
    if not SHOW_TITLE:
        return info
    if HIDE_PRIVATE and any(w in title.lower() for w in PRIVATE_WORDS):
        info["title"] = "__private__"
        return info

    parts = clean_title(title)
    last = parts[-1].lower()
    for key, (site, verb) in MEDIA_SITES.items():
        if key in last:
            info["site"], info["verb"] = site, verb
            info["title"] = " - ".join(parts[:-1]) if len(parts) > 1 else None
            return info
    info["title"] = " - ".join(parts)
    return info


# ---------------------- Tab extension link ----------------------
SITE_HOSTS = {
    "music.youtube.com": ("YouTube Music", "Listening to"),
    "youtube.com": ("YouTube", "Watching"),
    "twitch.tv": ("Twitch", "Watching"),
    "netflix.com": ("Netflix", "Watching"),
    "disneyplus.com": ("Disney+", "Watching"),
    "primevideo.com": ("Prime Video", "Watching"),
    "hulu.com": ("Hulu", "Watching"),
    "crunchyroll.com": ("Crunchyroll", "Watching"),
    "max.com": ("Max", "Watching"),
    "kick.com": ("Kick", "Watching"),
    "open.spotify.com": ("Spotify", "Listening to"),
    "soundcloud.com": ("SoundCloud", "Listening to"),
    "music.apple.com": ("Apple Music", "Listening to"),
    "deezer.com": ("Deezer", "Listening to"),
}
TAB_STATE = {"data": None, "time": 0.0}
TAB_MAX_AGE = 45  # seconds before extension data counts as stale


class TabHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Custom header forces a CORS preflight, so random web pages can't spoof this.
        if self.headers.get("X-Source") != "operagx-presence":
            self.send_response(403)
            self.end_headers()
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            TAB_STATE["data"] = json.loads(self.rfile.read(min(n, 2_000_000)))
            TAB_STATE["time"] = time.time()
            self.send_response(204)
        except Exception:
            self.send_response(400)
        self.end_headers()

    def log_message(self, *args):
        pass


def start_tab_server():
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), TabHandler)
    except OSError:
        print(f"Port {PORT} is busy (is the script already running?). Tab mode off.")
        return
    threading.Thread(target=server.serve_forever, daemon=True).start()


def site_for(url):
    host = (urlparse(url).hostname or "").lower()
    for key in sorted(SITE_HOSTS, key=len, reverse=True):
        if host == key or host.endswith("." + key):
            return SITE_HOSTS[key]
    return (None, None)


def strip_site_suffix(title, url):
    """Remove trailing ' - YouTube' / ' | Twitch' etc. from a tab title."""
    host = (urlparse(url).hostname or "").lower().replace("www.", "")
    brand = host.split(".")[-2] if host.count(".") >= 1 else host
    parts = re.split(r"\s[-–—|·]\s", title.strip())
    if len(parts) > 1 and brand and brand in parts[-1].lower().replace(" ", ""):
        parts.pop()
    return " - ".join(parts)


def tab_info():
    """Return tab-based info from the extension, or None if stale/missing."""
    data = TAB_STATE["data"]
    if not data or time.time() - TAB_STATE["time"] > TAB_MAX_AGE:
        return None
    tabs = data.get("tabs") or []
    if not tabs:
        return None

    audible = [t for t in tabs if t.get("audible")]
    focused = data.get("focusedWindowId")
    active = [t for t in tabs if t.get("active")]
    active_focused = [t for t in active if t.get("windowId") == focused]

    if audible:
        audible.sort(key=lambda t: not t.get("active"))  # active+audible first
        tab, playing = audible[0], True
    elif active_focused:
        tab, playing = active_focused[0], False
    elif active:
        tab, playing = active[0], False
    else:
        tab, playing = tabs[0], False

    site, verb = site_for(tab["url"])
    ua = data.get("ua", "")
    browser = "Opera GX" if "OPR/" in ua else "Edge" if "Edg/" in ua else "Chrome"
    return {
        "tab_title": strip_site_suffix(tab.get("title", ""), tab["url"]),
        "site": site, "verb": verb, "playing": playing,
        "tab_count": len(tabs), "ua_browser": browser,
        "asset": {"Opera GX": "operagx", "Edge": "edge", "Chrome": "chrome"}[browser],
    }


# ---------------------- Build the presence ----------------------
def clip(text, limit=120):
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_activity(info, start):
    title, site = info.get("title"), info.get("site")
    playing = info.get("playing")

    if title == "__private__":
        details = "Browsing privately"
    elif playing and site:
        details = f"{info['verb']} {site}" if SHOW_SITE_ONLY or not title else f"{info['verb']}: {title}"
    elif playing:
        details = f"Playing audio: {title}" if title else "Playing audio"
    elif site and not title:
        details = f"Browsing {site}"
    elif title:
        details = f"Browsing: {title}"
    else:
        details = "Browsing the web"

    bits = [f"in {info['browser']}"]
    if site and title != "__private__":
        bits.append(site)
    if SHOW_TAB_COUNT and info.get("tab_count"):
        n = info["tab_count"]
        bits.append(f"{n} tab{'s' if n != 1 else ''}")

    return {
        "details": clip(details),
        "state": clip(" · ".join(bits), 120),
        "timestamps": {"start": start},
        "assets": {"large_image": info["asset"], "large_text": info["browser"]},
    }


# --------------------------- Main loop ---------------------------
def main():
    if CLIENT_ID.startswith("PASTE"):
        sys.exit("Edit operagx_presence.py and set CLIENT_ID first (see top of file).")

    start_tab_server()
    ipc = DiscordIPC(CLIENT_ID)
    start, last_browser, last_payload = None, None, None
    print("Watching your browser + tabs... (Ctrl+C to quit)")

    try:
        while True:
            info = detect()
            tabs = tab_info() if SHOW_TITLE else None
            if tabs:
                if info is None:
                    info = {"browser": tabs["ua_browser"], "asset": tabs["asset"]}
                info.update({
                    "title": tabs["tab_title"] or None, "site": tabs["site"],
                    "verb": tabs["verb"], "playing": tabs["playing"],
                    "tab_count": tabs["tab_count"],
                })

            if info is None:
                if last_payload is not None:
                    try:
                        ipc.set_activity(None)
                    except OSError:
                        ipc.close()
                    last_payload, last_browser = None, None
                    print("Presence OFF")
            else:
                if info["browser"] != last_browser or start is None:
                    start, last_browser = int(time.time()), info["browser"]
                activity = build_activity(info, start)

                if activity != last_payload:
                    try:
                        if ipc.conn is None and not ipc.connect():
                            print("Can't reach Discord. Is the desktop app open?")
                        else:
                            ipc.set_activity(activity)
                            last_payload = activity
                            print("Presence:", activity["details"], "|", activity["state"])
                    except OSError:
                        ipc.close()
                        last_payload = None

            time.sleep(CHECK_EVERY)
    except KeyboardInterrupt:
        try:
            ipc.set_activity(None)
        except Exception:
            pass
        ipc.close()


if __name__ == "__main__":
    main()
