import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from tools import feature_map


class FeatureMapTest(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get("MA4_TEST_SCRATCH", feature_map.ROOT / ".agent-tmp"))
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="map-tests-", dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "validation").mkdir()
        (self.root / "app.py").write_text("value = 1\n", encoding="utf-8")
        (self.root / "proof.json").write_text('{"result":"passed"}', encoding="utf-8")
        self.map = self.root / "FEATURE-MAP.md"
        self.map.write_text('# Map\n[code](app.py)\n<a id="sessions"></a>\n## Send\nOpen, send, reopen.\n## Other\n', encoding="utf-8")
        text = self.map.read_text(encoding="utf-8")
        self.review = {"version": 1, "features": {"sessions": {
            "recipe_sha256": hashlib.sha256(feature_map.recipe(text, "sessions").encode()).hexdigest(),
            "source_reviewed_at": "2026-11-06", "inputs": {"app.py": feature_map.digest(self.root / "app.py")},
            "evidence": [{"path": "proof.json", "sha256": feature_map.digest(self.root / "proof.json")}],
            "coverage": "one simulated journey", "unverified": ["Linux"]}}}
        self.record = self.root / feature_map.REVIEW
        self.record.write_text(json.dumps(self.review), encoding="utf-8")

    def test_current_does_not_claim_unverified_coverage_or_write_record(self):
        before = self.record.read_bytes()
        result = feature_map.inspect(self.root)
        self.assertEqual(result["result"], "current")
        self.assertEqual(result["features"][0]["unverified"], ["Linux"])
        self.assertEqual(self.record.read_bytes(), before)

    def test_changed_source_recipe_or_evidence_needs_review(self):
        for path in (self.root / "app.py", self.map, self.root / "proof.json"):
            before = path.read_bytes()
            with self.subTest(path=path.name):
                if path == self.map:
                    path.write_bytes(before.replace(b"send, reopen", b"send, skip reopening"))
                else:
                    path.write_bytes(before + b"\nchanged")
                self.assertEqual(feature_map.inspect(self.root)["result"], "needs_review")
            path.write_bytes(before)
        self.assertEqual(feature_map.inspect(self.root)["result"], "current")

    def test_missing_link_is_invalid(self):
        self.map.write_text(self.map.read_text(encoding="utf-8") + "[missing](missing.py)\n", encoding="utf-8")
        self.assertEqual(feature_map.inspect(self.root)["result"], "invalid")

    def test_missing_review_or_outside_input_cannot_be_current(self):
        entry = self.review["features"]["sessions"]
        entry["source_reviewed_at"] = ""
        entry["inputs"] = {"../outside": "not-a-hash"}
        self.record.write_text(json.dumps(self.review), encoding="utf-8")
        self.assertEqual(feature_map.inspect(self.root)["result"], "needs_review")

    def test_missing_anchor_and_unregistered_feature_are_invalid(self):
        original = self.map.read_text(encoding="utf-8")
        for addition in ('[missing](FEATURE-MAP.md#missing)', '<a id="unknown"></a>\n## Unknown\n'):
            self.map.write_text(original + addition, encoding="utf-8")
            self.assertEqual(feature_map.inspect(self.root)["result"], "invalid")


if __name__ == "__main__":
    unittest.main()
