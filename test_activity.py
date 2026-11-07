import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from activity import ActivityPoller, NoRedirect, assist_activity, chat_activity, game_activity


def game(key, seats=None):
    return {"game": key, "tables": [{"game": key, "seats": seats or [None, None]}]}


def chat(now, rows=None, total=None):
    rows = rows or []
    return {"window_seconds": 300, "generated_at": now * 1000,
            "total_ips": len(rows) if total is None else total, "visitors": rows,
            "truncated": total is not None and total > len(rows)}


def assist(now=1000, **changes):
    return dict({"service": "xiangqi-assist", "window_seconds": 300, "count": 0,
                 "generated_at": now * 1000, "observed_since": (now - 300) * 1000,
                 "complete_window": True}, **changes)


class ActivityTest(unittest.TestCase):
    def test_defaults_do_not_schedule_or_display_deferred_lobby_or_tcp(self):
        from runtime import load_config
        config = load_config()
        self.assertTrue(config["health"])
        self.assertTrue(all(row.get("type", "http") == "http" for row in config["health"]))
        calls = []
        def fetch(key):
            calls.append(key)
            return chat(1000) if key == "chat" else assist() if key == "xiangqi-assist" else game(key)
        poller = ActivityPoller(config["activity"], fetch=fetch, clock=lambda: 1000, start=False)
        poller.tick()
        self.assertNotIn("xiangqi", calls)
        self.assertEqual([row["key"] for row in poller.snapshot()], ["texas", "ace21", "xiangqi-assist", "chat"])

    def test_credential_cli_unicode_with_non_utf8_child_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            cli = Path(folder) / "credential.py"
            cli.write_text("import json, sys\njson.dump({'credential_status': 'ok', "
                           "'content': '用途：统计\\nPassword: 测试-token'}, sys.stdout, ensure_ascii=False)\n",
                           encoding="utf-8", newline="\n")
            config = {"credential_cli": str(cli), "credential_file": str(Path(folder) / "unused"),
                      "stats_credential": "fixture"}
            with patch.dict(os.environ, {"PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0", "LC_ALL": "C"}):
                poller = ActivityPoller(config, start=False)
                self.assertEqual(poller.credential(), "测试-token")

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
            return chat(now[0]) if key == "chat" else assist(now[0]) if key == "xiangqi-assist" else game(key)

        poller = ActivityPoller({"enabled": True}, fetch=fetch, clock=lambda: now[0], start=False)
        poller.tick()
        self.assertEqual(sorted(calls), ["ace21", "chat", "texas", "xiangqi-assist"])
        self.assertTrue(all(row["count"] == 0 and not row["stale"] for row in poller.snapshot()))
        now[0] += 15
        failed.add("texas")
        poller.tick()
        self.assertEqual(len(calls), 6)
        rows = {r["key"]: r for r in poller.snapshot()}
        self.assertIsNone(rows["texas"]["count"])
        self.assertEqual(rows["ace21"]["count"], 0)
        self.assertNotIn("secret", json.dumps(rows))
        now[0] += 45
        poller.tick()
        self.assertEqual(len(calls), 10)
        self.assertEqual(calls.count("chat"), 2)
        self.assertEqual(calls.count("xiangqi-assist"), 2)
        now[0] += 150  # Even without a new request, old results no longer mean online.
        self.assertTrue(all(r["count"] is None and "visitors" not in r for r in poller.snapshot()))

    def test_failed_chat_does_not_block_game_counts_and_snapshot_is_a_copy(self):
        def fetch(key):
            if key == "chat":
                raise TimeoutError()
            return assist() if key == "xiangqi-assist" else game(key)
        poller = ActivityPoller({"enabled": True}, fetch=fetch, clock=lambda: 1000, start=False)
        poller.tick()
        values = poller.snapshot()
        self.assertEqual([r["count"] for r in values], [0, 0, 0, None])
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

    def test_xiangqi_deduplicates_across_tables_and_excludes_observers(self):
        seat = {"id": "simulated-player", "online": True}
        raw = game("xiangqi", [seat, {"id": "offline", "online": False}])
        raw["tables"].append({"game": "xiangqi", "seats": [None, seat]})
        raw["observers"] = [{"id": "unseated", "online": True}]
        self.assertEqual(game_activity(raw, "xiangqi"), {"count": 1})
        self.assertEqual(game_activity(game("xiangqi"), "xiangqi"), {"count": 0})

    def test_assist_valid_zero_nonzero_and_warmup_strip_extra_fields(self):
        for total in (0, 8):
            with self.subTest(total=total):
                result = assist_activity(assist(count=total, visitorId="SIMULATED-ONLY", visitors=[]), 1000)
                self.assertEqual(result["count"], total)
                self.assertEqual(set(result), {"count", "observed_at", "observed_since", "complete_window"})
        self.assertFalse(assist_activity(assist(observed_since=950_000, complete_window=False), 1000)["complete_window"])

    def test_assist_invalid_missing_stale_and_inconsistent_data(self):
        invalid = [None, [], {}, assist(800), assist(1201)]
        for field, values in {
            "service": ["other", None], "window_seconds": [True, 300.0, 60],
            "count": [True, -1, 1.5, 0.0, "0", None, 2**53],
            "generated_at": [None, True, float("nan"), float("inf")],
            "observed_since": [None, True, 0, 1001_000, float("nan")],
            "complete_window": [None, "true", 1, False],
        }.items():
            invalid.extend(assist(**{field: value}) for value in values)
        for field in assist():
            raw = assist()
            del raw[field]
            invalid.append(raw)
        invalid.append(assist(observed_since=999_000))
        for index, raw in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(ValueError):
                assist_activity(raw, 1000)

    def test_assist_states_pending_collecting_failure_and_cached_expiry(self):
        now = [1000]
        poller = ActivityPoller({"enabled": True}, fetch=lambda _: assist(count=4, observed_since=950_000, complete_window=False),
                                clock=lambda: now[0], start=False)
        row = lambda: next(r for r in poller.snapshot() if r["key"] == "xiangqi-assist")
        self.assertEqual(row()["status"], "pending")
        poller.collect("xiangqi-assist")
        self.assertEqual(row()["status"], "collecting")
        now[0] += 121
        self.assertEqual(row()["status"], "unknown")
        self.assertIsNone(row()["count"])
        now[0] = 1000
        poller.fetch = lambda _: assist(count=8)
        poller.collect("xiangqi-assist")
        self.assertEqual(row()["count"], 8)
        for bad in (TimeoutError(), ValueError("invalid JSON")):
            def failed(_):
                raise bad
            poller.fetch = failed
            poller.collect("xiangqi-assist")
            self.assertEqual(row()["status"], "unknown")
            self.assertIsNone(row()["count"])

    def test_assist_public_get_and_xiangqi_observer_request(self):
        poller = ActivityPoller({"games_url": "https://example.test/ace21-api/"}, start=False)
        with patch.object(poller, "credential", side_effect=AssertionError("credential read")), patch("activity.urllib.request.build_opener") as build:
            build.return_value.open.return_value.__enter__.return_value.read.return_value = b'{}'
            poller.download("xiangqi-assist")
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, "https://example.test/ace21-api/activity/xiangqi-assist")
            self.assertEqual(request.get_method(), "GET")
            self.assertIsNone(request.get_header("Authorization"))
            self.assertIsNone(request.data)
            self.assertEqual(build.return_value.open.call_args.kwargs["timeout"], 10)
            poller.download("xiangqi")
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, "https://example.test/ace21-api/tables/xiangqi")
            self.assertEqual(request.get_header("Authorization"), "Bearer " + poller.observer)
            self.assertEqual(request.get_method(), "GET")


if __name__ == "__main__":
    unittest.main()
