# WindowLayout

Save and restore window layouts on macOS. Automatically detects your display configuration and restores your preferred window arrangement when you connect or disconnect monitors.

![macOS](https://img.shields.io/badge/macOS-11%2B-blue) ![Python](https://img.shields.io/badge/Python-3.10%2B-green) ![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

- **Menu bar app** — lives in your menu bar as a small window icon
- **Save named layouts** — save your current window positions with a custom name
- **Restore layouts** — restore any saved layout with one click
- **Auto-restore** — automatically restores your layout when you switch between display configurations (e.g., plugging in a monitor)
- **Display detection** — identifies your setup (laptop only, laptop + external, etc.) and groups saved layouts accordingly
- **Multiple profiles** — save different layouts for different display setups (work, home, laptop)

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
4. **Auto-restore** — When you connect/disconnect a monitor and there's exactly one saved layout matching that display config, it restores automatically

### Permissions

On first use, macOS will prompt you to grant **Accessibility** permissions (System Settings → Privacy & Security → Accessibility). This is required for WindowLayout to move and resize windows belonging to other apps.

### Start at login

To launch WindowLayout automatically:

1. Open **System Settings** → **General** → **Login Items**
2. Click **+** and select `WindowLayout.app`

## How it works

- Each saved layout stores the position and size of every visible window, along with a fingerprint of your display configuration (resolution and arrangement)
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

## License

MIT
