"""Keep the computer from falling asleep on its own while the app works, on mains power only.

Windows' SetThreadExecutionState only stops the idle sleep: the screen still turns off,
and the owner can always sleep, shut down or restart the computer (closing the app
also lets it sleep again). On battery, idle sleep is left alone.
"""

from __future__ import annotations

import ctypes
import os
from threading import Event

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
CHECK_SECONDS = 60


class _PowerStatus(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte), ("BatteryLifePercent", ctypes.c_byte),
                ("SystemStatusFlag", ctypes.c_byte), ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]


def on_mains_power() -> bool:
    status = _PowerStatus()
    return bool(ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status))) and status.ACLineStatus == 1


def keep_awake_on_mains(stop: Event) -> None:
    """Run in its own thread until ``stop``: the idle sleep is blocked while plugged in."""
    if os.name != "nt":
        return
    kernel32 = ctypes.windll.kernel32
    try:
        while not stop.is_set():
            kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on_mains_power() else 0))
            stop.wait(CHECK_SECONDS)
    finally:
        kernel32.SetThreadExecutionState(ES_CONTINUOUS)  # back to Windows' usual idle sleep
