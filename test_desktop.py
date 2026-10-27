"""Windows process integration tests in a disposable, isolated CODEX_HOME."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import desktop
from runtime import ROOT, child_environment, find_codex


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(os.name == "nt", "Windows launcher")
class DesktopTest(unittest.TestCase):
    def setUp(self):
        temp = ROOT / ".agent-tmp"
        temp.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="oneclick-", dir=temp)
        self.folder = Path(self.temp.name) / "中文 配置"
        self.folder.mkdir()
        home = self.folder / "codex-home"
        home.mkdir()
        (home / "config.toml").write_text(
            "[features]\nplugins = false\napps = false\ncode_mode_host = false\n",
            encoding="utf-8", newline="\n")
        self.config = self.folder / "config.json"
        self.value = {"port": free_port(), "app_server": "ws://127.0.0.1:" + str(free_port()),
                      "codex_home": str(home), "data_dir": str(self.folder / "state"),
                      "health": [], "links": []}
        self.config.write_text(json.dumps(self.value), encoding="utf-8")

    def tearDown(self):
        desktop.stop(self.config, include_backend=True)
        self.temp.cleanup()

    def state(self):
        return desktop.context(self.config)[3]

    def test_double_click_entry_reuse_browser_and_safe_stop(self):
        command = [os.environ["COMSPEC"], "/d", "/c", str(ROOT / "启动MA4.cmd"),
                   "--config", str(self.config), "--no-browser"]
        # Two overlapping double-clicks must create only one backend and one web.
        children = [subprocess.Popen(command, cwd=self.folder, stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW) for _ in range(2)]
        for child in children:
            output = child.communicate(timeout=60)[0].decode("utf-8", errors="replace")
            self.assertEqual(child.returncode, 0, output)
        original = self.state()
        self.assertEqual(set(original), {"web", "backend"})
        with patch("desktop.open_app_window") as browser:
            url = desktop.start(self.config)
            browser.assert_called_once_with(url, desktop.find_app_browser())
        self.assertEqual(self.state(), original)
        self.assertFalse(desktop.stop_owned(dict(original["web"], created=original["web"]["created"] + 1)))
        self.assertTrue(desktop.get_json(url + "/api/state")["daemon"]["connected"])
        self.assertEqual(desktop.stop(self.config), ["web"])
        self.assertFalse(desktop.port_open("127.0.0.1", self.value["port"]))
        self.assertTrue(desktop.backend_ready(self.value["app_server"]))
        desktop.start(self.config, browser=False)
        self.assertEqual(self.state()["backend"], original["backend"])
        self.assertNotEqual(self.state()["web"], original["web"])
        self.assertEqual(desktop.stop(self.config, include_backend=True), ["web", "backend"])
        self.assertFalse(desktop.port_open(*desktop.tcp_address(self.value["app_server"])))

    def test_reused_backend_is_not_stopped(self):
        binary = find_codex()
        external = desktop.spawn([binary, "app-server", "--listen", self.value["app_server"]],
                                 child_environment(binary, self.value["codex_home"]))
        try:
            desktop.wait_ready(external, lambda: desktop.backend_ready(self.value["app_server"]), "test")
            desktop.start(self.config, browser=False)
            self.assertEqual(set(self.state()), {"web"})
            self.assertEqual(desktop.stop(self.config, include_backend=True), ["web"])
            self.assertIsNone(external.poll())
            self.assertTrue(desktop.backend_ready(self.value["app_server"]))
        finally:
            external.terminate()
            external.wait(timeout=5)

    def test_foreign_ports_are_preserved_and_no_children_created(self):
        for role in ("web", "backend"):
            with self.subTest(role=role), socket.socket() as other:
                other.bind(("127.0.0.1", 0))
                other.listen()
                config = dict(self.value)
                if role == "web":
                    config["port"] = other.getsockname()[1]
                else:
                    config["app_server"] = "ws://127.0.0.1:" + str(other.getsockname()[1])
                self.config.write_text(json.dumps(config), encoding="utf-8")
                with self.assertRaises(ValueError):
                    desktop.start(self.config, browser=False)
                self.assertEqual(self.state(), {})
                self.assertTrue(desktop.port_open(*other.getsockname()))


if __name__ == "__main__":
    unittest.main()
