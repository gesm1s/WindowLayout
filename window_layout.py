#!/usr/bin/env python3
"""
WindowLayout – save and restore window layouts via a menu bar icon.
Automatically detects display configuration (work / home / laptop).
Requirements: pip install pyobjc
"""

import json
import hashlib
import logging
import os
import subprocess
import time
import threading

import objc
import AppKit
import Quartz
from Quartz import CGDisplayBounds
from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementCopyAttributeValue,
    AXUIElementSetAttributeValue,
    AXValueCreate,
    AXValueGetValue,
    AXIsProcessTrusted,
    AXIsProcessTrustedWithOptions,
    kAXValueTypeCGPoint,
    kAXValueTypeCGSize,
)

LOG_FILE = os.path.expanduser("~/.window_layout.log")
_log_handler = logging.FileHandler(LOG_FILE)
_log_handler.setFormatter(logging.Formatter(
    "%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
log = logging.getLogger("WindowLayout")
log.setLevel(logging.DEBUG)
log.addHandler(_log_handler)

SAVE_FILE = os.path.expanduser("~/.window_layouts.json")
SETTINGS_FILE = os.path.expanduser("~/.window_layouts_settings.json")
STARTUP_DELAY = 30
RESTORE_RETRIES = 1
RESTORE_RETRY_DELAY = 0.3
RESTORE_PASSES = 2
RESTORE_PASS_DELAY = 1.0
DISPLAY_SETTLE_DELAY = 5.0
SUBPROCESS_TIMEOUT = 3

SKIP_APPS = frozenset((
    "Dock", "Window Server", "SystemUIServer", "Control Center",
    "Notification Center", "WindowLayout", "loginwindow", "Spotlight",
    "AutoFill", "Autoutfyll", "Open and Save Panel Service",
    "CursorUIViewService", "GlobalProtect",
))

# Apps where localizedName() differs from the name in CGWindowListCopyWindowInfo
APP_NAME_ALIASES = {
    "Visual Studio Code": "Code",
    "Code": "Visual Studio Code",
}


# ── Display detection ────────────────────────────────────────────

def get_display_config():
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
    if screens is None:
        screens = get_display_config()
    desc = "|".join(
        f"{s['width']}x{s['height']}@{s['x']},{s['y']}"
        for s in screens
    )
    return hashlib.sha256(desc.encode()).hexdigest()[:12]


def describe_displays(screens=None):
    if screens is None:
        screens = get_display_config()
    if len(screens) <= 1:
        return "Laptop only"
    external = [s for s in screens if not s["is_builtin"]]
    parts = [f"{s['width']}x{s['height']}" for s in external]
    return f"Laptop + {', '.join(parts)}" if parts else f"{len(screens)} displays"


# ── Windows ──────────────────────────────────────────────────────

def get_all_windows():
    option = Quartz.kCGWindowListExcludeDesktopElements
    win_list = Quartz.CGWindowListCopyWindowInfo(option, Quartz.kCGNullWindowID)
    windows = []
    seen = set()
    for w in win_list:
        if w.get("kCGWindowLayer", 99) != 0:
            continue
        owner = w.get("kCGWindowOwnerName", "")
        if not owner or owner in SKIP_APPS:
            continue
        bounds = w.get("kCGWindowBounds", {})
        width = int(bounds.get("Width", 0))
        height = int(bounds.get("Height", 0))
        if width < 200 or height < 200:
            continue
        if width == 500 and height == 500:
            continue
        x = int(bounds.get("X", 0))
        y = int(bounds.get("Y", 0))
        key = (owner, x, y, width, height)
        if key in seen:
            continue
        seen.add(key)
        windows.append({
            "app": owner,
            "title": w.get("kCGWindowName", ""),
            "x": x, "y": y, "w": width, "h": height,
        })
    return windows


def format_window_capture_summary(windows, max_lines=30):
    grouped = {}
    for win in windows:
        grouped.setdefault(win.get("app", "Unknown"), []).append(win)
    lines = [f"Total: {len(windows)} windows", ""]
    for app in sorted(grouped):
        app_wins = grouped[app]
        lines.append(f"{app}: {len(app_wins)}")
        for win in app_wins[:3]:
            title = (win.get("title") or "(untitled)").strip()
            if len(title) > 60:
                title = title[:57] + "..."
            lines.append(f"  - {title} [{win['x']},{win['y']} {win['w']}x{win['h']}]")
        if len(app_wins) > 3:
            lines.append(f"  - ... +{len(app_wins) - 3} more")
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + ["... (truncated)"]
    return "\n".join(lines)


# ── Window restore ───────────────────────────────────────────────

_ax_available = None  # None = untested, True/False = cached result


def check_ax_permission():
    """Test if we have Accessibility permission. Prompt if not granted."""
    global _ax_available
    try:
        trusted = AXIsProcessTrusted()
        if not trusted:
            # Show macOS permission dialog automatically
            opts = {"AXTrustedCheckOptionPrompt": True}
            trusted = AXIsProcessTrustedWithOptions(opts)
        _ax_available = bool(trusted)
        if _ax_available:
            log.info("Accessibility permission: GRANTED")
        else:
            log.warning("Accessibility permission: DENIED")
            log.warning("   Fix: System Settings > Privacy & Security > Accessibility > enable WindowLayout")
    except Exception as e:
        # Fall back to probe method
        _ax_available = _probe_ax_permission()
    _log_handler.flush()
    return _ax_available


def _probe_ax_permission():
    """Fallback: test AX permission by probing Finder."""
    for app in AppKit.NSWorkspace.sharedWorkspace().runningApplications():
        if app.bundleIdentifier() == "com.apple.finder":
            app_ref = AXUIElementCreateApplication(app.processIdentifier())
            err, _ = AXUIElementCopyAttributeValue(app_ref, "AXWindows", None)
            if err == -25211:
                log.warning("Accessibility permission: DENIED (probe)")
                log.warning("   Fix: System Settings > Privacy & Security > Accessibility > enable WindowLayout")
                return False
            else:
                log.info("Accessibility permission: GRANTED (probe)")
                return True
    log.info("Accessibility permission: assumed OK (Finder not found)")
    return True


def _find_running_app_pid(app_name):
    for app in AppKit.NSWorkspace.sharedWorkspace().runningApplications():
        if app.localizedName() == app_name:
            return app.processIdentifier()
    # Try alias if direct match fails
    alias = APP_NAME_ALIASES.get(app_name)
    if alias:
        for app in AppKit.NSWorkspace.sharedWorkspace().runningApplications():
            if app.localizedName() == alias:
                return app.processIdentifier()
    return None


def _restore_window_ax(pid, x, y, w, h, app_name="?"):
    try:
        app_ref = AXUIElementCreateApplication(pid)
        err, windows = AXUIElementCopyAttributeValue(app_ref, "AXWindows", None)
        if err != 0:
            log.debug("AX no windows for %s (pid %s, err=%s)", app_name, pid, err)
            return False
        if not windows or len(windows) == 0:
            log.debug("AX empty window list for %s (pid %s)", app_name, pid)
            return False

        # Find the window that best matches the target size (w×h).
        # This avoids accidentally targeting notification popups or small dialogs.
        best_win = windows[0]
        best_score = float('inf')
        for candidate in windows:
            try:
                cerr, csize_val = AXUIElementCopyAttributeValue(candidate, "AXSize", None)
                if cerr == 0 and csize_val:
                    ok, csize = AXValueGetValue(csize_val, kAXValueTypeCGSize, None)
                    if ok:
                        score = abs(csize.width - w) + abs(csize.height - h)
                        if score < best_score:
                            best_score = score
                            best_win = candidate
            except Exception:
                pass
        win = best_win
        pos_val = AXValueCreate(kAXValueTypeCGPoint, Quartz.CGPointMake(x, y))
        size_val = AXValueCreate(kAXValueTypeCGSize, Quartz.CGSizeMake(w, h))
        err1 = AXUIElementSetAttributeValue(win, "AXPosition", pos_val)
        err2 = AXUIElementSetAttributeValue(win, "AXSize", size_val)
        if err1 == 0 and err2 == 0:
            return True
        if err1 == 0 and err2 != 0:
            log.debug("AX pos OK but size failed for %s (size err=%s) — position-only restore", app_name, err2)
            return True  # partial success: at least position was set
        log.debug("AX set failed for %s: pos=%s size=%s", app_name, err1, err2)
        return False
    except Exception as e:
        log.debug("AX exception for %s (pid %s): %s", app_name, pid, e)
        return False


def _applescript_string(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _restore_window_applescript(app, x, y, w, h):
    app_str = _applescript_string(app)
    script = (
        f'tell application {app_str}\n'
        f'  if (count of windows) > 0 then\n'
        f'    try\n'
        f'      set bounds of window 1 to {{{x}, {y}, {x+w}, {y+h}}}\n'
        f'      return "ok"\n'
        f'    on error\n'
        f'      return "error"\n'
        f'    end try\n'
        f'  else\n'
        f'    return "notfound"\n'
        f'  end if\n'
        f'end tell'
    )
    log.debug("AS trying: %s", app)
    _log_handler.flush()
    proc = None
    try:
        proc = subprocess.Popen(
            ["osascript", "-e", script],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = proc.communicate(timeout=SUBPROCESS_TIMEOUT)
        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        return stdout.strip().lower() == "ok"
    except subprocess.TimeoutExpired:
        log.warning("AppleScript timed out for %s — killing process", app)
        _log_handler.flush()
        if proc:
            proc.kill()
            proc.wait()
        return False
    except Exception as e:
        log.warning("AppleScript error for %s: %s", app, e)
        if proc:
            try:
                proc.kill()
                proc.wait()
            except Exception:
                pass
        return False


def restore_window(app, title, x, y, w, h, cancel_check=None):
    for attempt in range(RESTORE_RETRIES):
        if cancel_check and cancel_check():
            log.debug("Restore cancelled for %s", app)
            return False
        pid = _find_running_app_pid(app)
        if pid:
            if _restore_window_ax(pid, x, y, w, h, app_name=app):
                log.debug("AX OK: %s -> (%d,%d %dx%d)", app, x, y, w, h)
                _log_handler.flush()
                return True

        if _restore_window_applescript(app, x, y, w, h):
            log.debug("AS OK: %s -> (%d,%d %dx%d)", app, x, y, w, h)
            _log_handler.flush()
            return True

        if attempt < RESTORE_RETRIES - 1:
            time.sleep(RESTORE_RETRY_DELAY)

    log.warning("FAILED: %s (all %d attempts)", app, RESTORE_RETRIES)
    _log_handler.flush()
    return False


# ── Storage ──────────────────────────────────────────────────────

def load_layouts():
    if os.path.exists(SAVE_FILE):
        with open(SAVE_FILE) as f:
            return json.load(f)
    return {}

def save_layouts(data):
    with open(SAVE_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    return {"auto_restore": True, "diagnostics": False}

def save_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Dialogs ──────────────────────────────────────────────────────

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
    field = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 300, 24))
    field.setStringValue_(default_text)
    alert.setAccessoryView_(field)
    alert.window().setInitialFirstResponder_(field)
    if alert.runModal() == AppKit.NSAlertFirstButtonReturn:
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
    AppKit.NSUserNotificationCenter.defaultUserNotificationCenter().deliverNotification_(notification)

def copy_to_clipboard(text):
    pb = AppKit.NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, AppKit.NSPasteboardTypeString)

def show_diagnostics_dialog(report_text):
    alert = AppKit.NSAlert.alloc().init()
    alert.setMessageText_("Saved windows (diagnostics)")
    alert.setInformativeText_(report_text)
    alert.addButtonWithTitle_("Copy to clipboard")
    alert.addButtonWithTitle_("Close")
    if alert.runModal() == AppKit.NSAlertFirstButtonReturn:
        copy_to_clipboard(report_text)
        show_notification("WindowLayout", "Diagnostics", "Report copied to clipboard")


# ── App delegate ─────────────────────────────────────────────────

class AppDelegate(AppKit.NSObject):

    def applicationDidFinishLaunching_(self, notification):
        log.info("=== WindowLayout started ===")
        _log_handler.flush()
        check_ax_permission()
        self.layouts = load_layouts()
        self.settings = load_settings()
        self._last_fingerprint = display_fingerprint()
        self._restore_generation = 0  # bumped on each new restore to cancel old ones
        self._last_auto_restored_fp = None  # fingerprint we last auto-restored to

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

        AppKit.NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self,
            objc.selector(self.displayConfigChanged_, signature=b"v@:@"),
            AppKit.NSApplicationDidChangeScreenParametersNotification,
            None,
        )

        if self.settings.get("auto_restore", True):
            self.performSelector_withObject_afterDelay_(
                "startupRestore:", None, STARTUP_DELAY,
            )

    def startupRestore_(self, _ignored):
        fp = display_fingerprint()
        log.info("Startup restore check: fp=%s", fp)
        matching = [n for n, v in self.layouts.items() if v.get("display_fingerprint") == fp]
        if len(matching) == 1:
            log.info("Startup: restoring '%s'", matching[0])
            self._last_auto_restored_fp = fp
            self._do_restore(matching[0], notify=True, open_apps=False)
        else:
            log.info("Startup: %d matches, skipping", len(matching))
        _log_handler.flush()

    def _refresh_icon(self):
        btn = self.status_item.button()
        icon = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "macwindow.on.rectangle", "WindowLayout"
        )
        if icon:
            btn.setImage_(icon)
        else:
            btn.setTitle_("WL")

    def rebuild_menu(self):
        self.layouts = load_layouts()
        menu = AppKit.NSMenu.alloc().init()
        screens = get_display_config()
        fp = display_fingerprint(screens)
        desc = describe_displays(screens)

        header = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(desc, None, "")
        header.setEnabled_(False)
        header.setImage_(AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_("display", None))
        menu.addItem_(header)
        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        save_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Save layout...", "saveLayout:", "")
        save_item.setTarget_(self)
        save_item.setImage_(AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_("square.and.arrow.down", None))
        menu.addItem_(save_item)
        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        matching = [n for n, v in self.layouts.items() if v.get("display_fingerprint") == fp]
        other = [n for n in self.layouts if n not in matching]

        if matching:
            s = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("── Matching current displays ──", None, "")
            s.setEnabled_(False)
            menu.addItem_(s)
            for name in matching:
                count = len(self.layouts[name].get("windows", []))
                item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    f"{name}  ({count} windows)", "restoreLayout:", "")
                item.setTarget_(self)
                item.setRepresentedObject_(name)
                item.setImage_(AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_("arrow.counterclockwise", None))
                menu.addItem_(item)

        if other:
            s = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("── Other layouts ──", None, "")
            s.setEnabled_(False)
            menu.addItem_(s)
            for name in other:
                info = self.layouts[name]
                label = info.get("display_description", "")
                count = len(info.get("windows", []))
                item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    f"{name}  ({label}, {count} windows)", "restoreLayout:", "")
                item.setTarget_(self)
                item.setRepresentedObject_(name)
                item.setImage_(AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_("arrow.counterclockwise", None))
                menu.addItem_(item)

        if self.layouts:
            menu.addItem_(AppKit.NSMenuItem.separatorItem())
            del_menu = AppKit.NSMenu.alloc().init()
            for name in self.layouts:
                d = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(name, "deleteLayout:", "")
                d.setTarget_(self)
                d.setRepresentedObject_(name)
                del_menu.addItem_(d)
            dp = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Delete layout", None, "")
            dp.setImage_(AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_("trash", None))
            menu.addItem_(dp)
            menu.setSubmenu_forItem_(del_menu, dp)

        menu.addItem_(AppKit.NSMenuItem.separatorItem())
        ai = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Auto-restore on startup", "toggleAutoRestore:", "")
        ai.setTarget_(self)
        ai.setState_(AppKit.NSControlStateValueOn if self.settings.get("auto_restore", True) else AppKit.NSControlStateValueOff)
        menu.addItem_(ai)

        di = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Diagnostics after save", "toggleDiagnostics:", "")
        di.setTarget_(self)
        di.setState_(AppKit.NSControlStateValueOn if self.settings.get("diagnostics", False) else AppKit.NSControlStateValueOff)
        menu.addItem_(di)

        menu.addItem_(AppKit.NSMenuItem.separatorItem())
        qi = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit", "terminate:", "q")
        qi.setImage_(AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_("xmark.circle", None))
        menu.addItem_(qi)

        self.menu = menu
        self.status_item.setMenu_(self.menu)
        self._refresh_icon()

    # ── Actions ──────────────────────────────────────────────────

    @objc.IBAction
    def saveLayout_(self, sender):
        screens = get_display_config()
        desc = describe_displays(screens)
        name = show_input_dialog("Save window layout", f"Display config: {desc}\nName this layout:")
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
            show_alert(f'Layout "{name}" saved', f"{len(windows)} windows · {desc}")
            if self.settings.get("diagnostics", False):
                show_diagnostics_dialog(format_window_capture_summary(windows))

    def _do_restore(self, name, notify=False, open_apps=True):
        info = self.layouts.get(name, {})
        layout = info.get("windows", info if isinstance(info, list) else [])
        self._restore_generation += 1
        gen = self._restore_generation
        log.info("_do_restore '%s': %d windows, notify=%s, open_apps=%s, gen=%d", name, len(layout), notify, open_apps, gen)
        _log_handler.flush()

        def _cancelled():
            return self._restore_generation != gen

        def _work():
            if _cancelled():
                log.info("Restore '%s' cancelled before start (gen %d)", name, gen)
                _log_handler.flush()
                return
            if open_apps:
                apps_seen = set()
                for win in layout:
                    if win["app"] not in apps_seen:
                        try:
                            subprocess.run(["open", "-a", win["app"]], capture_output=True, timeout=SUBPROCESS_TIMEOUT)
                        except subprocess.TimeoutExpired:
                            pass
                        apps_seen.add(win["app"])
                time.sleep(2.0)
            for p in range(RESTORE_PASSES):
                if _cancelled():
                    log.info("Restore '%s' cancelled at pass %d (gen %d)", name, p + 1, gen)
                    _log_handler.flush()
                    return
                log.debug("Restore pass %d/%d for '%s'", p + 1, RESTORE_PASSES, name)
                _log_handler.flush()
                for win in layout:
                    restore_window(win["app"], win["title"], win["x"], win["y"], win["w"], win["h"],
                                   cancel_check=_cancelled)
                if p < RESTORE_PASSES - 1:
                    time.sleep(RESTORE_PASS_DELAY)
            log.info("_do_restore '%s' completed (gen %d)", name, gen)
            _log_handler.flush()
            if notify:
                msg = f'Layout "{name}" restored ({len(layout)} windows).'
                AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
                    lambda: show_notification("WindowLayout", "Auto-restored", msg)
                )

        if notify:
            threading.Thread(target=_work, daemon=True).start()
        else:
            _work()
            show_alert(f'Layout "{name}" restored ({len(layout)} windows).')

    @objc.IBAction
    def restoreLayout_(self, sender):
        self._do_restore(sender.representedObject())

    @objc.IBAction
    def deleteLayout_(self, sender):
        name = sender.representedObject()
        if show_confirm(f'Delete "{name}"?', "This cannot be undone."):
            self.layouts.pop(name, None)
            save_layouts(self.layouts)
            self.rebuild_menu()

    @objc.IBAction
    def toggleAutoRestore_(self, sender):
        self.settings["auto_restore"] = not self.settings.get("auto_restore", True)
        save_settings(self.settings)
        self.rebuild_menu()

    @objc.IBAction
    def toggleDiagnostics_(self, sender):
        self.settings["diagnostics"] = not self.settings.get("diagnostics", False)
        save_settings(self.settings)
        self.rebuild_menu()

    # ── Display change (using performSelector for reliable delayed dispatch) ──

    def displayConfigChanged_(self, notification):
        log.info("Display config changed")
        _log_handler.flush()
        # Cancel any pending delayed restore, reschedule with fresh delay
        AppKit.NSObject.cancelPreviousPerformRequestsWithTarget_selector_object_(
            self, "delayedDisplayRestore:", None,
        )
        self.performSelector_withObject_afterDelay_(
            "delayedDisplayRestore:", None, DISPLAY_SETTLE_DELAY,
        )

    def delayedDisplayRestore_(self, _ignored):
        fp = display_fingerprint()
        log.info("Display settled: fp=%s, last=%s", fp, self._last_fingerprint)
        _log_handler.flush()
        if fp != self._last_fingerprint:
            self._last_fingerprint = fp
            self.rebuild_menu()

        if not self.settings.get("auto_restore", True):
            log.info("Auto-restore disabled")
            _log_handler.flush()
            return

        matching = [n for n, v in self.layouts.items() if v.get("display_fingerprint") == fp]
        log.info("Matching layouts: %s", matching)
        _log_handler.flush()

        if len(matching) == 1:
            if fp == self._last_auto_restored_fp:
                log.info("Skipping auto-restore for '%s' – already restored to this display config", matching[0])
                _log_handler.flush()
                return
            log.info("Auto-restoring '%s'", matching[0])
            _log_handler.flush()
            self._last_auto_restored_fp = fp
            self._do_restore(matching[0], notify=True, open_apps=True)
        else:
            log.info("No unique match (%d), skipping", len(matching))
            _log_handler.flush()


# ── Main ─────────────────────────────────────────────────────────

def main():
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()

if __name__ == "__main__":
    main()
