# Browser Discord Rich Presence (Opera GX and more)

Show what you're doing in your browser on your Discord profile: which browser you're using, which tab is playing audio, and how many tabs you have open.

```
Watching: lofi hip hop radio
in Opera GX · YouTube · 5 tabs
```

Works with **Opera GX, Opera, Chrome, Edge and Brave** (tab mode), and detects **Vivaldi and Firefox** by window title (Windows only). The script is a single Python file with **no external dependencies**.

> **Made with AI:** this project's code and documentation were written by an AI assistant ([Claude](https://claude.ai), made by Anthropic) at my request. See [AI disclosure](#ai-disclosure) below.
>
> Not affiliated with Discord, Opera or Anthropic. This is an unofficial hobby project.

---

## Features

- Detects the browser you're using (Opera GX, Opera, Chrome, Edge, Firefox, Brave, Vivaldi)
- **Tab mode** (with the included extension):
  - Shows the tab that is actually **playing audio**, even in a background tab or another window
  - Falls back to your active tab when nothing is playing
  - Shows how many tabs you have open
  - Uses the browser's real audio state, so a paused video stops saying "Watching"
- Recognizes YouTube, YouTube Music, Twitch, Netflix, Disney+, Prime Video, Hulu, Crunchyroll, Max, Kick, Spotify, SoundCloud, Apple Music and Deezer, with "Watching" or "Listening to" wording
- **Window-title fallback** if the extension isn't installed (active tab only, Windows only)
- Incognito / private tabs are never shared
- Presence turns off automatically when you close the browser
- Everything stays on your PC: the extension talks only to `127.0.0.1`

## How it works

```
Browser extension  --(HTTP POST, localhost only)-->  operagx_presence.py  --(Discord IPC)-->  Discord desktop app
```

1. The extension reports your tabs (title, URL, audio state) to a tiny local server inside the script.
2. The script builds a status and sends it to the Discord desktop app over Discord's local IPC pipe.
3. If the extension isn't running, the script reads the browser window title instead.

## Requirements

- Python 3.8 or newer (only needed to run or build the script)
- **Discord desktop app** running (the web version can't receive presence)
- Windows for window-title detection. Tab mode and the Discord connection use standard IPC and should also work on macOS/Linux.

## Setup

### 1. Create a Discord application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**.
2. The **application name** is what appears after "Playing" on your profile (for example, `Opera GX`).
3. Copy the **Application ID**.
4. *(Optional)* Under **Rich Presence > Art Assets**, upload images named: `operagx`, `opera`, `chrome`, `edge`, `firefox`, `brave`, `vivaldi`. Without them the status still works, just without a logo.

### 2. Configure the script

Open `operagx_presence.py` and paste your Application ID:

```python
CLIENT_ID = "PASTE_YOUR_APPLICATION_ID_HERE"
```

### 3. Turn on activity sharing in Discord

**User Settings > Activity Privacy > Share your detected activities with others**

### 4. Install the tab extension (recommended)

1. Keep the `tab-extension` folder somewhere permanent.
2. Open your browser's extensions page:
   - Opera GX / Opera: `opera://extensions`
   - Chrome: `chrome://extensions`
   - Edge: `edge://extensions`
   - Brave: `brave://extensions`
3. Turn on **Developer mode**.
4. Click **Load unpacked** and select the `tab-extension` folder.

### 5. Run it

```bash
python operagx_presence.py
```

Open the browser, play a video, and check your Discord profile.

## Build a standalone `.exe` (Windows)

Put `build_exe.bat` next to `operagx_presence.py` and double-click it, or run:

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole --name operagx_presence operagx_presence.py
```

The exe is created in `dist/`. Set your `CLIENT_ID` **before** building.
Because of `--noconsole` it runs silently in the background; end `operagx_presence.exe` in Task Manager to stop it.

To start it with Windows, press `Win + R`, type `shell:startup`, and put a shortcut to the exe in that folder.

> Antivirus programs sometimes flag PyInstaller executables as false positives. You can run the `.py` file directly or build the exe yourself from this source.

## Configuration

All options are at the top of `operagx_presence.py`:

| Option | Default | What it does |
|---|---|---|
| `CLIENT_ID` | *(required)* | Your Discord Application ID |
| `SHOW_TITLE` | `True` | `False` = only show the browser name, never tab/page titles (also disables tab mode) |
| `HIDE_PRIVATE` | `True` | Hide titles in Incognito / InPrivate / Private windows (title-fallback mode) |
| `SHOW_SITE_ONLY` | `False` | `True` = "Watching YouTube" instead of the video title |
| `SHOW_TAB_COUNT` | `True` | Show "N tabs" in the status |
| `CHECK_EVERY` | `15` | Seconds between checks (Discord rate-limits faster updates) |
| `PORT` | `47821` | Local port for the extension; must match `background.js` and `manifest.json` |

## Privacy

- Tab titles and the tab count are visible to anyone who can see your Discord profile. Use `SHOW_SITE_ONLY` or `SHOW_TITLE = False` if you want less shown.
- The extension only sends data to `http://127.0.0.1:47821`. Nothing is sent to any external server.
- Incognito/private tabs are never sent. Extensions don't run in private windows by default, and the extension also filters them out.
- The local server only accepts requests that include a custom header, which blocks random web pages from spoofing your status.

## Troubleshooting

| Problem | Fix |
|---|---|
| Nothing shows on Discord | Use the **desktop** app, enable *Share your detected activities*, and make sure your status isn't Invisible |
| "Can't reach Discord" in the log | Start Discord first, then the script |
| Still not connecting | Run Discord and the script at the **same admin level** (normally both non-admin). Reinstall Discord if it asks for admin every launch |
| Two Discord clients open | Close extras (Canary/PTB); Rich Presence works with one client |
| Tab mode not working | Check the extension is enabled, and that nothing else is using port `47821` |
| Status says it's busy on the port | The script is probably already running; close the other copy |
| No logo on the profile | Upload art assets with the exact names listed above |

## Limitations

- **Firefox:** window-title mode only (Windows). The extension uses Chromium's Manifest V3, so it won't load in Firefox.
- **Audio state:** a muted tab that's still playing counts as playing; tabs playing silently won't be detected.
- **Window-title mode** only sees the active tab of the focused browser window.
- Extensions are loaded unpacked (developer mode), so your browser may show a "disable developer mode extensions" notice on startup.
- Discord limits how often presence can update, so changes can take up to `CHECK_EVERY` seconds to appear.

## Project structure

```
.
├── operagx_presence.py     # main script (Discord IPC + local tab server)
├── build_exe.bat           # builds a Windows exe with PyInstaller
├── tab-extension/
│   ├── manifest.json       # Manifest V3 extension
│   └── background.js       # reports tabs to the local script
└── README.md
```

## AI disclosure

The script (`operagx_presence.py`), the browser extension (`tab-extension/`), the build script and this README were generated by **Claude**, an AI assistant made by Anthropic, based on my prompts and requirements.

AI-written code can contain bugs, so please read it and test it before relying on it. If you find a problem, open an issue or a pull request.

## License

Add the license of your choice (for example, [MIT](https://choosealicense.com/licenses/mit/)) as a `LICENSE` file.
