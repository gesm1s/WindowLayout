# WindowLayout

Save and restore window layouts on macOS. Automatically detects your display configuration and restores your preferred window arrangement when you connect or disconnect monitors.

![macOS](https://img.shields.io/badge/macOS-11%2B-blue) ![Python](https://img.shields.io/badge/Python-3.10%2B-green) ![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

- **Menu bar app** — lives in your menu bar as a small window icon
- **Save named layouts** — save your current window positions with a custom name
- **Restore layouts** — restore any saved layout with one click
- **Auto-restore on display change** — automatically restores your layout when you connect or disconnect monitors
- **Auto-restore on startup** — after a configurable delay (30s), restores the matching layout when your Mac boots up
- **Display detection** — identifies your setup (laptop only, laptop + external, etc.) and groups saved layouts accordingly
- **Multiple profiles** — save different layouts for different display setups (work, home, laptop)
- **Better window capture** — captures windows from open apps even when a window is not currently active/on-screen
- **Optional diagnostics mode** — shows a per-app capture summary after save, with one-click copy to clipboard

## Installation

### Option A: Download the app (no Python required)

1. Go to the [Releases](../../releases) page
2. Download `WindowLayout.app.zip`
3. Unzip and move `WindowLayout.app` to your Applications folder
4. Double-click to launch

> **First launch:** macOS may show a security warning. Right-click the app → Open → Open to bypass it.

### Option B: Run the Python script

Requires Python 3.10+ and [PyObjC](https://pyobjc.readthedocs.io/):

```bash
pip install pyobjc
python3 window_layout.py
```

### Option C: Build the app yourself

```bash
pip install pyobjc py2app setuptools Pillow

# Generate the app icon
python3 gen_icon.py

# Build the .app bundle
python3 setup.py py2app
```

The app will be in `dist/WindowLayout.app`.

## Usage

1. **Launch** — A small window icon appears in your menu bar
2. **Save a layout** — Arrange your windows how you like, then click the menu bar icon → **Save layout...** → enter a name
3. **Restore a layout** — Click the menu bar icon → select a saved layout
4. **Auto-restore on display change** — When you connect/disconnect a monitor and there's exactly one saved layout matching that display config, it restores automatically
5. **Auto-restore on startup** — If enabled (on by default), WindowLayout waits 30 seconds after launch to let apps open, then repositions windows to match your saved layout. Toggle this in the menu under **Auto-restore on startup**.
6. **Diagnostics (optional)** — Enable **Diagnostics after save** in the menu to inspect exactly which windows were captured. Use **Copy to clipboard** in the diagnostics dialog to share or troubleshoot.

### Permissions

On first use, macOS will prompt you to grant **Accessibility** permissions (System Settings → Privacy & Security → Accessibility). This is required for WindowLayout to move and resize windows belonging to other apps.

### Start at login

To launch WindowLayout automatically:

1. Open **System Settings** → **General** → **Login Items**
2. Click **+** and select `WindowLayout.app`

## How it works

- Each saved layout stores the position and size of filtered app windows, including windows from open apps that are not currently active/on-screen, along with a fingerprint of your display configuration (resolution and arrangement)
- When displays change, WindowLayout compares the new fingerprint against saved layouts
- If exactly one layout matches, it's restored automatically; otherwise, matching layouts are highlighted in the menu
- Window restoration uses AppleScript to set window bounds per application

## Files

| File | Description |
|------|-------------|
| `window_layout.py` | Main application script |
| `setup.py` | py2app build configuration |
| `gen_icon.py` | Generates the app icon (`WindowLayout.icns`) |
| `~/.window_layouts.json` | Saved layouts (created at runtime) |
| `~/.window_layouts_settings.json` | Settings — auto-restore and diagnostics toggles (created at runtime) |

## License

MIT
