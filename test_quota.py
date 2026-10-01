import json
from pathlib import Path
import tempfile
import unittest

from quota import INTERVAL, QuotaPoller, normalize

DETAIL = {
    "families": [
        {"key": "codex", "label": "Codex", "account": {"d7_used": 29, "d7_reset": 1791046749, "h5_used": None,
                                                       "h5_reset": 0, "updated": "2026-10-01T03:00:06Z"}},
        {"key": "claude", "label": "Claude", "account": {"h5_used": 12, "h5_reset": 1790838600, "d7_used": 21,
                                                         "d7_reset": 1791298800, "fable_used": 0, "fable_reset": 1791298800}},
    ],
    "generated_at": "2026-10-01T03:08:12Z",
}


class QuotaTest(unittest.TestCase):
    def test_detail_format(self):
        value = normalize(DETAIL)
        codex, claude = value["families"]
        self.assertEqual([w["key"] for w in codex["windows"]], ["d7"])  # null 5h window is dropped
        self.assertEqual([(w["key"], w["used"]) for w in claude["windows"]], [("h5", 12), ("d7", 21), ("fable", 0)])
        self.assertEqual(claude["windows"][0]["reset_at"], 1790838600)
        self.assertTrue(value["updated"].startswith("2026-10-01T03:08:12"))

    def test_legacy_format_and_bad_values(self):
        value = normalize({"d7_used": 38, "d7_reset": 0, "updated": "nope"})
        self.assertEqual(value["families"][0]["windows"], [{"key": "d7", "label": "7 天", "used": 38, "reset_at": None}])
        with self.assertRaises(ValueError):
            normalize({"d7_used": 140})
        with self.assertRaises(ValueError):
            normalize({"families": [{"key": "x", "account": {"h5_used": True}}]})

    def test_poller_caches_and_hides_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = [1000.0]
            calls = []

            def fetch():
                calls.append(1)
                if len(calls) > 1:
                    raise OSError("https://secret?k=KEY failed")
                return DETAIL

            poller = QuotaPoller(Path(tmp), fetch=fetch, clock=lambda: now[0], start=False)
            poller.tick()
            poller.tick()  # within the interval: no second fetch
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(poller.snapshot()["families"]), 2)
            now[0] += INTERVAL + 1
            poller.tick()
            snap = poller.snapshot()
            self.assertNotIn("KEY", json.dumps(snap))
            self.assertTrue(snap["stale"])
            self.assertEqual(len(snap["families"]), 2)  # last good figures are kept
            again = QuotaPoller(Path(tmp), fetch=fetch, clock=lambda: now[0], start=False)
            self.assertEqual(len(again.snapshot()["families"]), 2)

    def test_old_cache_is_discarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "quota-cache.json").write_text(json.dumps({"used": 28, "next_poll": 9e12}))
            poller = QuotaPoller(Path(tmp), fetch=lambda: DETAIL, clock=lambda: 1.0, start=False)
            poller.tick()
            self.assertIn("families", poller.snapshot())


if __name__ == "__main__":
    unittest.main()
