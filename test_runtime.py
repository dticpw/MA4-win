import base64
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from appserver import tcp_address
from runtime import codex_arguments, powershell_command, terminal_arguments, load_config, find_app_browser


class RuntimeTest(unittest.TestCase):
    def test_only_explicit_loopback_endpoint(self):
        self.assertEqual(tcp_address("ws://localhost:8765"), ("127.0.0.1", 8765))
        self.assertEqual(tcp_address("ws://[::1]:8765/"), ("::1", 8765))
        for url in ("ws://0.0.0.0:8765", "ws://example.com:8765", "wss://127.0.0.1:8765",
                    "ws://127.0.0.1:8765/path", "ws://u:p@127.0.0.1:8765",
                    "ws://127.0.0.1:8765/?token=a", "ws://localhost"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                tcp_address(url)

    def test_remote_resume_and_literal_terminal_arguments(self):
        cwd = "E:\\中文 项目\\O'Brien; $HOME"
        binary = "C:\\My Tools\\codex.exe"
        args = codex_arguments(binary, "ws://127.0.0.1:8765", cwd, "thread-id")
        self.assertEqual(args, [binary, "--remote", "ws://127.0.0.1:8765",
                                "resume", "thread-id", "-C", cwd])
        command = powershell_command(args, cwd)
        self.assertIn("'E:\\中文 项目\\O''Brien; $HOME'", command)
        with patch("runtime.os.name", "nt"):
            terminal = terminal_arguments(binary, "ws://127.0.0.1:8765", cwd,
                                          "thread-id", wt="wt.exe")
        self.assertEqual(base64.b64decode(terminal[-1]).decode("utf-16-le"), command)
        self.assertNotIn(cwd, terminal)  # wt never parses path punctuation.
        self.assertEqual(terminal[:6], ["wt.exe", "-w", "new", "new-tab", "--title", "MA4"])

    def test_app_browser_discovery_and_explicit_path(self):
        with tempfile.TemporaryDirectory() as folder:
            chrome = Path(folder) / "Google/Chrome/Application/chrome.exe"
            edge = Path(folder) / "Microsoft/Edge/Application/msedge.exe"
            for exe in (chrome, edge):
                exe.parent.mkdir(parents=True, exist_ok=True)
                exe.touch()
            with patch.dict("os.environ", {"ProgramFiles": folder, "ProgramFiles(x86)": folder,
                                           "LOCALAPPDATA": folder}):
                self.assertEqual(Path(find_app_browser()), chrome)
                self.assertEqual(Path(find_app_browser(str(edge))), edge)
                chrome.unlink()
                self.assertEqual(Path(find_app_browser()), edge)
                with self.assertRaises(ValueError):
                    find_app_browser(str(chrome))

    def test_project_relative_runtime_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.json"
            config.write_text('{"app_server":"ws://localhost:8765","data_dir":"state","codex_home":"home"}',
                              encoding="utf-8")
            value = load_config(config)
            self.assertEqual(value["app_server"], "ws://127.0.0.1:8765")
            self.assertEqual(Path(value["data_dir"]), Path(folder) / "state")
            self.assertEqual(Path(value["codex_home"]), Path(folder) / "home")


if __name__ == "__main__":
    unittest.main()
