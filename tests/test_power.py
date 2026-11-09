import os
from threading import Event
import unittest
from unittest.mock import patch

from twitch_auto_clipper import power


@unittest.skipUnless(os.name == "nt", "Windows only")
class KeepAwakeTests(unittest.TestCase):
    def test_idle_sleep_is_blocked_on_mains_only_and_released_at_the_end(self):
        calls = []
        stop = Event()

        class Kernel:
            def SetThreadExecutionState(self, flags):
                calls.append(flags)
                stop.set()  # one round is enough

        for mains, expected in ((True, power.ES_CONTINUOUS | power.ES_SYSTEM_REQUIRED), (False, power.ES_CONTINUOUS)):
            calls.clear(); stop.clear()
            with patch.object(power.ctypes, "windll") as windll, patch.object(power, "on_mains_power", return_value=mains):
                windll.kernel32 = Kernel()
                power.keep_awake_on_mains(stop)
            self.assertEqual(calls, [expected, power.ES_CONTINUOUS])  # then back to the usual idle sleep


if __name__ == "__main__":
    unittest.main()
