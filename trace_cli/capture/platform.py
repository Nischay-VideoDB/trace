"""Platform dispatcher: import the right capture backend + watchers for the current OS.

Usage in cli.py (replaces the direct imports from service / watchers):

    from trace_cli.capture.platform import (
        start_capture, stop_capture,
        SaveWatcher, WindowPoller,
    )

Linux (Wayland):  wf-recorder + ffmpeg/pulse + inotifywait + hyprctl
macOS:            VideoDB CaptureClient SDK + watchdog FSEvents + osascript
Windows:          VideoDB CaptureClient SDK + watchdog ReadDirectoryChanges + win32gui
"""
from __future__ import annotations

import sys

if sys.platform == "darwin":
    from trace_cli.capture.service_mac import (
        CaptureError,
        CaptureHandles,
        OsascriptWindowPoller as WindowPoller,
        WatchdogSaveWatcher as SaveWatcher,
        start_capture,
        stop_capture,
    )
elif sys.platform == "win32":
    from trace_cli.capture.service_windows import (
        CaptureError,
        CaptureHandles,
        WatchdogSaveWatcher as SaveWatcher,
        Win32WindowPoller as WindowPoller,
        start_capture,
        stop_capture,
    )
else:
    # Linux (default)
    from trace_cli.capture.service import (
        CaptureError,
        CaptureHandles,
        start_capture,
        stop_capture,
    )
    from trace_cli.capture.watchers import (
        HyprctlPoller as WindowPoller,
        InotifyWatcher as SaveWatcher,
    )

__all__ = [
    "CaptureError",
    "CaptureHandles",
    "SaveWatcher",
    "WindowPoller",
    "start_capture",
    "stop_capture",
]
