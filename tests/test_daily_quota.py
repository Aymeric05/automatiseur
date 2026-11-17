from pathlib import Path
import tempfile
from threading import Thread

from twitch_auto_clipper.daily_quota import DailyQuota


def test_requests_counted_at_the_same_time_by_several_workers_are_all_kept():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "gemini_quota_model.json"
        threads = [Thread(target=lambda: [DailyQuota(path, 1000).record_use() for _ in range(25)]) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert DailyQuota(path, 1000).remaining() == 1000 - 100
