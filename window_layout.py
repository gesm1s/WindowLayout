#!/usr/bin/env python3
"""
WindowLayout – save and restore window layouts via a menu bar icon.
Automatically detects display configuration (work / home / laptop).
Requirements: pip install pyobjc
"""

import json
import hashlib
import os
import subprocess
import time
import threading

import objc
import AppKit
import Quartz
from Quartz import CGDisplayBounds

SAVE_FILE = os.path.expanduser("~/.window_layouts.json")

SKIP_APPS = frozenset((
    "Dock", "Window Server", "SystemUIServer", "Control Center",
    "Notification Center", "WindowLayout",
))


# ── Display detection ────────────────────────────────────────────

def get_display_config():
    """Return a sorted list of info about all connected displays."""
    max_displays = 16
    (err, display_ids, count) = Quartz.CGGetOnlineDisplayList(max_displays, None, None)
    if err != 0:
        return []
    screens = []
    for did in display_ids[:count]:
        bounds = CGDisplayBounds(did)
        screens.append({
            "id": did,
            "width": int(bounds.size.width),
            "height": int(bounds.size.height),
            "x": int(bounds.origin.x),
            "y": int(bounds.origin.y),
            "is_builtin": Quartz.CGDisplayIsBuiltin(did),
        })
    screens.sort(key=lambda s: (s["x"], s["y"]))
    return screens


def display_fingerprint(screens=None):
    """Create a short hash identifying the current display configuration."""
    if screens is None:
        screens = get_display_config()
    desc = "|".join(
        f"{s['width']}x{s['height']}@{s['x']},{s['y']}"
        for s in screens
    )
    return hashlib.sha256(desc.encode()).hexdigest()[:12]


def describe_displays(screens=None):
    """Human-readable description of the display configuration."""
    if screens is None:
        screens = get_display_config()
    if len(screens) <= 1:
        return "Laptop only"
    external = [s for s in screens if not s["is_builtin"]]
    parts = []
    for s in external:
        parts.append(f"{s['width']}x{s['height']}")
    return f"Laptop + {', '.join(parts)}" if parts else f"{len(screens)} displays"


# ── Windows ──────────────────────────────────────────────────────

def get_all_windows():
    option = (Quartz.kCGWindowListOptionOnScreenOnly
              | Quartz.kCGWindowListExcludeDesktopElements)
    win_list = Quartz.CGWindowListCopyWindowInfo(option, Quartz.kCGNullWindowID)
    windows = []
    for w in win_list:
        if w.get("kCGWindowLayer", 99) != 0:
            continue
        owner = w.get("kCGWindowOwnerName", "")
        title = w.get("kCGWindowName", "")
        bounds = w.get("kCGWindowBounds", {})
        if not owner or owner in SKIP_APPS:
            continue
        windows.append({
            "app": owner,
            "title": title,
            "x": int(bounds.get("X", 0)),
            "y": int(bounds.get("Y", 0)),
            "w": int(bounds.get("Width", 800)),
            "h": int(bounds.get("Height", 600)),
        })
    return windows


def _applescript_string(s):
    """Safely escape a string for use in AppleScript."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def restore_window(app, title, x, y, w, h):
    app_str = _applescript_string(app)
    if title:
        title_str = _applescript_string(title)
        script = (
            f'tell application {app_str}\n'
            f'  set wins to (every window whose name contains {title_str})\n'
            f'  if (count of wins) > 0 then\n'
            f'    set bounds of item 1 of wins to {{{x}, {y}, {x+w}, {y+h}}}\n'
            f'  end if\n'
            f'end tell'
        )
    else:
        script = (
            f'tell application {app_str}\n'
            f'  if (count of windows) > 0 then\n'
            f'    set bounds of window 1 to {{{x}, {y}, {x+w}, {y+h}}}\n'
            f'  end if\n'
            f'end tell'
        )
    subprocess.run(["osascript", "-e", script], capture_output=True)


# ── Storage ──────────────────────────────────────────────────────

def load_layouts():
    if os.path.exists(SAVE_FILE):
        with open(SAVE_FILE) as f:
            return json.load(f)
    return {}


def save_layouts(data):
    with open(SAVE_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Dialogs (AppKit) ─────────────────────────────────────────────

def show_alert(message, info=""):
    alert = AppKit.NSAlert.alloc().init()
    alert.setMessageText_(message)
    if info:
        alert.setInformativeText_(info)
    alert.runModal()


def show_input_dialog(title, message, default_text=""):
    alert = AppKit.NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_(message)
    alert.addButtonWithTitle_("Save")
    alert.addButtonWithTitle_("Cancel")
    field = AppKit.NSTextField.alloc().initWithFrame_(
        AppKit.NSMakeRect(0, 0, 300, 24)
    )
    field.setStringValue_(default_text)
    alert.setAccessoryView_(field)
    alert.window().setInitialFirstResponder_(field)
    result = alert.runModal()
    if result == AppKit.NSAlertFirstButtonReturn:
        return field.stringValue()
    return None


def show_confirm(title, message):
    alert = AppKit.NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_(message)
    alert.addButtonWithTitle_("Delete")
    alert.addButtonWithTitle_("Cancel")
    return alert.runModal() == AppKit.NSAlertFirstButtonReturn


def show_notification(title, subtitle, message):
    notification = AppKit.NSUserNotification.alloc().init()
    notification.setTitle_(title)
    notification.setSubtitle_(subtitle)
    notification.setInformativeText_(message)
    center = AppKit.NSUserNotificationCenter.defaultUserNotificationCenter()
    center.deliverNotification_(notification)


# ── App delegate ─────────────────────────────────────────────────

class AppDelegate(AppKit.NSObject):

    def applicationDidFinishLaunching_(self, notification):
        self.layouts = load_layouts()
        self._last_fingerprint = display_fingerprint()

        # Create status bar icon
        self.status_item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(
            AppKit.NSVariableStatusItemLength
        )
        btn = self.status_item.button()
        icon = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "macwindow.on.rectangle", "WindowLayout"
        )
        if icon:
            btn.setImage_(icon)
        else:
            btn.setTitle_("WL")

        self.rebuild_menu()

        # Listen for display changes
        AppKit.NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self,
            objc.selector(self.displayConfigChanged_, signature=b"v@:@"),
            AppKit.NSApplicationDidChangeScreenParametersNotification,
            None,
        )

    def rebuild_menu(self):
        self.layouts = load_layouts()
        menu = AppKit.NSMenu.alloc().init()

        screens = get_display_config()
        fp = display_fingerprint(screens)
        desc = describe_displays(screens)

        # Current display configuration
        header = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            desc, None, ""
        )
        header.setEnabled_(False)
        header.setImage_(AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "display", None
        ))
        menu.addItem_(header)
        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        # Save
        save_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Save layout...", "saveLayout:", ""
        )
        save_item.setTarget_(self)
        save_item.setImage_(AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "square.and.arrow.down", None
        ))
        menu.addItem_(save_item)
        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        # Layouts matching current displays
        matching = [
            n for n, v in self.layouts.items()
            if v.get("display_fingerprint") == fp
        ]
        other = [n for n in self.layouts if n not in matching]

        if matching:
            section = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "── Matching current displays ──", None, ""
            )
            section.setEnabled_(False)
            menu.addItem_(section)
            for name in matching:
                info = self.layouts[name]
                count = len(info.get("windows", []))
                item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    f"{name}  ({count} windows)", "restoreLayout:", ""
                )
                item.setTarget_(self)
                item.setRepresentedObject_(name)
                item.setImage_(AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                    "arrow.counterclockwise", None
                ))
                menu.addItem_(item)

        if other:
            section = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "── Other layouts ──", None, ""
            )
            section.setEnabled_(False)
            menu.addItem_(section)
            for name in other:
                info = self.layouts[name]
                label = info.get("display_description", "")
                count = len(info.get("windows", []))
                item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    f"{name}  ({label}, {count} windows)", "restoreLayout:", ""
                )
                item.setTarget_(self)
                item.setRepresentedObject_(name)
                item.setImage_(AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                    "arrow.counterclockwise", None
                ))
                menu.addItem_(item)

        # Delete submenu
        if self.layouts:
            menu.addItem_(AppKit.NSMenuItem.separatorItem())
            delete_menu = AppKit.NSMenu.alloc().init()
            for name in self.layouts:
                d_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    name, "deleteLayout:", ""
                )
                d_item.setTarget_(self)
                d_item.setRepresentedObject_(name)
                delete_menu.addItem_(d_item)
            delete_parent = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Delete layout", None, ""
            )
            delete_parent.setImage_(AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "trash", None
            ))
            menu.addItem_(delete_parent)
            menu.setSubmenu_forItem_(delete_menu, delete_parent)

        menu.addItem_(AppKit.NSMenuItem.separatorItem())
        quit_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "terminate:", "q"
        )
        quit_item.setImage_(AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "xmark.circle", None
        ))
        menu.addItem_(quit_item)

        self.menu = menu
        self.status_item.setMenu_(self.menu)

    # ── Actions ──────────────────────────────────────────────────

    @objc.IBAction
    def saveLayout_(self, sender):
        screens = get_display_config()
        desc = describe_displays(screens)
        name = show_input_dialog(
            "Save window layout",
            f"Display config: {desc}\nName this layout:",
        )
        if name and name.strip():
            name = name.strip()
            windows = get_all_windows()
            self.layouts[name] = {
                "windows": windows,
                "display_fingerprint": display_fingerprint(screens),
                "display_description": desc,
                "display_config": screens,
            }
            save_layouts(self.layouts)
            self.rebuild_menu()
            show_alert(
                f"Layout \"{name}\" saved",
                f"{len(windows)} windows · {desc}",
            )

    def _do_restore(self, name, notify=False):
        """Restore a layout by name. If notify=True, show a notification instead of an alert."""
        info = self.layouts.get(name, {})
        layout = info.get("windows", info if isinstance(info, list) else [])
        apps_seen = set()
        for win in layout:
            if win["app"] not in apps_seen:
                subprocess.run(["open", "-a", win["app"]], capture_output=True)
                apps_seen.add(win["app"])
        time.sleep(1.5)
        for win in layout:
            restore_window(
                win["app"], win["title"],
                win["x"], win["y"], win["w"], win["h"],
            )
        msg = f"Layout \"{name}\" restored ({len(layout)} windows)."
        if notify:
            show_notification("WindowLayout", "Auto-restored", msg)
        else:
            show_alert(msg)

    @objc.IBAction
    def restoreLayout_(self, sender):
        name = sender.representedObject()
        self._do_restore(name)

    @objc.IBAction
    def deleteLayout_(self, sender):
        name = sender.representedObject()
        if show_confirm(f"Delete \"{name}\"?", "This cannot be undone."):
            self.layouts.pop(name, None)
            save_layouts(self.layouts)
            self.rebuild_menu()

    # ── Display change ───────────────────────────────────────────

    def displayConfigChanged_(self, notification):
        fp = display_fingerprint()
        if fp != self._last_fingerprint:
            self._last_fingerprint = fp
            self.rebuild_menu()
            matching = [
                n for n, v in self.layouts.items()
                if v.get("display_fingerprint") == fp
            ]
            if len(matching) == 1:
                self._do_restore(matching[0], notify=True)


# ── Main ─────────────────────────────────────────────────────────

def main():
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()


if __name__ == "__main__":
    main()