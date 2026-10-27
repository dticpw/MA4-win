import json
import unittest
from unittest.mock import patch
import urllib.error

from activity import ActivityPoller, NoRedirect, chat_activity, game_activity


def game(key, seats=None):
    return {"game": key, "tables": [{"game": key, "seats": seats or [None, None]}]}


def chat(now, rows=None, total=None):
    rows = rows or []
    return {"window_seconds": 300, "generated_at": now * 1000,
            "total_ips": len(rows) if total is None else total, "visitors": rows,
            "truncated": total is not None and total > len(rows)}


class ActivityTest(unittest.TestCase):
    def test_only_connected_seats_count_and_private_fields_are_removed(self):
        seat = {"id": "p1", "online": True, "name": "private", "token": "secret"}
        raw = game("texas", [None, seat, seat, {"id": "p2", "online": False}])
        self.assertEqual(game_activity(raw, "texas"), {"count": 1})
        self.assertEqual(game_activity(game("ace21"), "ace21"), {"count": 0})

    def test_bad_upstream_is_unknown_not_zero(self):
        for raw in ({}, {"game": "texas", "tables": []}, game("ace21"),
                    game("texas", [{"id": "p", "online": "true"}])):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                game_activity(raw, "texas")

    def test_chat_window_completeness_and_no_old_location_guessing(self):
        row = dict(ip="192.0.2.1", last_seen=990_000, requests=2, city=None, region=None, country="JP")
        value = chat_activity(chat(1000, [row], total=205), 1000)
        self.assertEqual(value["count"], 205)
        self.assertTrue(value["truncated"])
        self.assertEqual(value["visitors"][0]["city"], "")
        for raw in ({"recent": [row]}, chat(700), chat(1000, [dict(row, last_seen=699_000)]),
                    chat(1000, [row, row]), dict(chat(1000, [row]), truncated=True)):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                chat_activity(raw, 1000)

    def test_schedules_are_independent_and_failure_hides_old_counts_and_ips(self):
        now = [1000]
        failed, calls = set(), []

        def fetch(key):
            calls.append(key)
            if key in failed:
                raise RuntimeError("secret credential must not escape")
            return chat(now[0]) if key == "chat" else game(key)

        poller = ActivityPoller({"enabled": True}, fetch=fetch, clock=lambda: now[0], start=False)
        poller.tick()
        self.assertEqual(sorted(calls), ["ace21", "chat", "texas"])
        self.assertTrue(all(row["count"] == 0 and not row["stale"] for row in poller.snapshot()))
        now[0] += 15
        failed.add("texas")
        poller.tick()
        self.assertEqual(len(calls), 5)
        rows = {r["key"]: r for r in poller.snapshot()}
        self.assertIsNone(rows["texas"]["count"])
        self.assertEqual(rows["ace21"]["count"], 0)
        self.assertNotIn("secret", json.dumps(rows))
        now[0] += 150  # Even without a new request, old results no longer mean online.
        self.assertTrue(all(r["count"] is None and "visitors" not in r for r in poller.snapshot()))

    def test_failed_chat_does_not_block_game_counts_and_snapshot_is_a_copy(self):
        def fetch(key):
            if key == "chat":
                raise TimeoutError()
            return game(key)
        poller = ActivityPoller({"enabled": True}, fetch=fetch, clock=lambda: 1000, start=False)
        poller.tick()
        values = poller.snapshot()
        self.assertEqual([r["count"] for r in values], [0, 0, None])
        values[0]["count"] = 99
        self.assertEqual(poller.snapshot()[0]["count"], 0)
        self.assertEqual(ActivityPoller(None, start=False).snapshot(), [])

    def test_credentials_use_header_not_url_and_redirects_are_refused(self):
        poller = ActivityPoller({"stats_url": "https://example.test/api/stats"}, start=False)
        poller.password = "test-private-secret"
        with patch("activity.urllib.request.build_opener") as build:
            build.return_value.open.side_effect = urllib.error.HTTPError("private-url", 401, "denied", {}, None)
            with self.assertRaises(urllib.error.HTTPError):
                poller.download("chat")
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, "https://example.test/api/stats?view=active")
            self.assertEqual(request.get_header("Authorization"), "Bearer test-private-secret")
            self.assertIsNone(poller.password)
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere.test"))


if __name__ == "__main__":
    unittest.main()
