"""Desktop notifications for alerts. Best effort, never raises.

macOS uses osascript, Linux uses notify-send, Windows uses a PowerShell toast.
Anything missing simply logs at debug level.
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess

log = logging.getLogger(__name__)


def notify(title: str, message: str) -> bool:
    system = platform.system()
    try:
        if system == "Darwin":
            script = f'display notification "{_esc(message)}" with title "{_esc(title)}"'
            subprocess.run(["osascript", "-e", script], check=True, timeout=5, capture_output=True)
            return True
        if system == "Linux" and shutil.which("notify-send"):
            subprocess.run(
                ["notify-send", title, message], check=True, timeout=5, capture_output=True
            )
            return True
        if system == "Windows":
            ps = (
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null;"
                "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(1);"
                f"$t.GetElementsByTagName('text')[0].AppendChild($t.CreateTextNode('{_esc(title)}: {_esc(message)}')) | Out-Null;"
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('email-agent').Show($t)"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                check=True,
                timeout=10,
                capture_output=True,
            )
            return True
    except Exception as e:  # noqa: BLE001 - notifications must never break processing
        log.debug("desktop notification failed: %s", e)
    return False


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("'", "’")[:200]
