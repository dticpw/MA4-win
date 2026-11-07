"""Cross-system regressions, including real subprocess pipe lifetime tests."""
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
from urllib.parse import quote

from controllers import overlap, checked_scope
from paths import path_key, is_link, file_path_for_platform, resolve_file_reference
from runtime import load_config, codex_arguments, ensure_daemon
from hub import Hub
from os_adapters.windows import ProxyStream
from os_adapters import windows


class PlatformTest(unittest.TestCase):
    def test_file_links_map_shared_drives_in_both_platform_modes(self):
        for drive in "cdef":
            for letter in (drive, drive.upper()):
                for slash in ("/", "\\"):
                    for tail in ("", "中文 目录/报告.txt", "中文 目录/报告.txt:12:3", "报告.txt#L2-L4"):
                        windows_path = letter + ":/" + tail
                        mount_path = "/mnt/" + letter + "/" + tail
                        for value in (windows_path, "/" + windows_path, mount_path):
                            value = value.replace("/", slash)
                            with self.subTest(value=value):
                                self.assertEqual(file_path_for_platform(value, windows=True), drive.upper() + ":/" + tail)
                                self.assertEqual(file_path_for_platform(value, windows=False), "/mnt/" + drive + "/" + tail)
            self.assertEqual(file_path_for_platform("/mnt/" + drive, windows=True), drive.upper() + ":/")
        for drive in "aghz":
            self.assertEqual(file_path_for_platform(drive + ":/本机 文件.txt", windows=True), drive.upper() + ":/本机 文件.txt")
            self.assertEqual(file_path_for_platform(drive + ":/本机 文件.txt", windows=False), "/mnt/" + drive + "/本机 文件.txt")

    def test_file_link_mapping_rejects_network_and_unknown_linux_roots(self):
        for value in ("//server/share", r"\\server\share", r"/\server/share", "E:", "E:relative", "/E:"):
            for windows_mode in (True, False):
                with self.subTest(value=value, windows=windows_mode), self.assertRaises(ValueError):
                    file_path_for_platform(value, windows=windows_mode)
        for value in ("/home/user/a.txt", r"\home\user\a.txt", "/mnt/g/a.txt", "/mnt/ef/a.txt", "/tmp/a"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Linux 绝对路径"):
                file_path_for_platform(value, windows=True)
        self.assertEqual(file_path_for_platform("/home/user/a.txt", windows=False), "/home/user/a.txt")

    def test_linux_file_links_with_simulated_posix_filesystem(self):
        # Pure simulation on Windows: this does not claim Linux desktop/mount QA.
        files = {"/mnt/" + drive + "/中文 空格.txt" for drive in "cdef"}
        files.update({"/home/user/中文 空格.txt", "/home/user/report:12", "/home/user/report#L12",
                      "/home/user/literal%20.txt", "/home/user/literal .txt", r"/home/user/literal\name.txt",
                      "/mnt/E/real.txt"})
        class LocalPath(PurePosixPath):
            def expanduser(self):
                return LocalPath(str(self).replace("~/", "/home/user/", 1)) if str(self).startswith("~/") else self
            def resolve(self):
                return LocalPath(posixpath.normpath(str(self)))
            def exists(self):
                return str(self) in files or str(self) in {"/", "/home/user", "/mnt/e"}
            def is_file(self):
                return str(self) in files
            def is_dir(self):
                return self.exists() and not self.is_file()
        cases = []
        for drive in "cdef":
            expected = "/mnt/" + drive + "/中文 空格.txt"
            for letter in (drive, drive.upper()):
                for ref in (letter + ":/中文 空格.txt", "/" + letter + ":/中文 空格.txt",
                            "/mnt/" + letter + "/中文 空格.txt"):
                    for spelling in (ref, ref.replace("/", "\\"), "file:///" + quote(ref.lstrip("/"))):
                        for suffix in ("", ":12:3", "#L2-L4"):
                            cases.append((spelling + suffix, expected))
        cases += [(name, name) for name in files]
        cases += [("中文 空格.txt", "/home/user/中文 空格.txt"), ("~/中文 空格.txt", "/home/user/中文 空格.txt"),
                  ("file:///home/user/report%3A12", "/home/user/report:12"),
                  ("file:///home/user/report%23L12", "/home/user/report#L12"),
                  ("file:///home/user/literal%2520.txt", "/home/user/literal%20.txt"),
                  ("/E:/", "/mnt/e"), ("/", "/")]
        with patch("paths.os", SimpleNamespace(name="posix")), patch("paths.Path", LocalPath):
            for ref, expected in cases:
                with self.subTest(ref=ref):
                    self.assertEqual(str(resolve_file_reference(ref, "/home/user")), expected)
            for ref in ("file://remote/home/user/中文 空格.txt", "//remote/share", "file:///home/user/report%23L99",
                        "file:///home/user/literal%252520.txt"):
                with self.subTest(ref=ref), self.assertRaises(ValueError):
                    resolve_file_reference(ref, "/home/user")

    def test_windows_default_application_never_runs_script_links(self):
        with patch.object(os, 'startfile', create=True) as start:
            for extension in ('.cmd', '.lnk', '.ps1', '.py', '.hta', '.exe'):
                with self.subTest(extension=extension), self.assertRaises(ValueError):
                    windows.open_file(Path('file' + extension))
            start.assert_not_called()
            windows.open_file(Path('中文 报告.html'))
            start.assert_called_once_with(str(Path('中文 报告.html')))

    @unittest.skipUnless(os.name == 'nt', 'Windows real Junction')
    def test_real_junction_is_refused_as_authorized_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, junction = root / '真实目录', root / 'junction'
            target.mkdir()
            subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(junction), str(target)],
                           check=True, capture_output=True)
            try:
                self.assertTrue(is_link(junction))
                with self.assertRaises(ValueError):
                    checked_scope(str(junction), [])
            finally:
                junction.rmdir()  # remove only this task's pointer, not the target
            self.assertTrue(target.is_dir())

    def test_windows_conflicts_respect_case_slashes_and_directory_boundaries(self):
        self.assertTrue(overlap([r'E:\PG\Game'], ['e:/pg/game/src']))
        self.assertFalse(overlap([r'E:\PG\Game'], ['E:/PG/Game2']))
        if os.name != 'nt':
            self.assertFalse(overlap(['/mnt/e/PG/Game'], ['/mnt/e/PG/game']))
        self.assertTrue(overlap(['/'], ['/home/test']))
        self.assertEqual(path_key(r'\\server\Share\path'), path_key(r'\\SERVER\share\PATH'))

    def test_junction_is_a_link_even_without_python312_is_junction(self):
        info = Mock(st_mode=stat.S_IFDIR | 0o755, st_file_attributes=0x400)
        with patch('paths.Path.lstat', return_value=info):
            self.assertTrue(is_link('junction'))
        with tempfile.TemporaryDirectory() as directory, patch('controllers.has_link', return_value=True):
            with self.assertRaises(ValueError):
                checked_scope(directory, [])

    def test_runtime_data_and_codex_home_are_config_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.json'
            config.write_text(json.dumps({'codex_home': '独立 home'}), encoding='utf-8')
            value = load_config(config)
            self.assertEqual(Path(value['data_dir']), Path(directory) / '.ma4')
            scheme = 'proxy://' if os.name == 'nt' else 'unix://'
            self.assertEqual(value['app_server'], scheme + str(Path(directory) / '独立 home/app-server-control/app-server-control.sock'))
        self.assertEqual(codex_arguments('codex', 'proxy://C:/home/control.sock', 'E:/PG', 'tid'),
                         ['codex', '--remote', 'unix://C:/home/control.sock', 'resume', 'tid', '-C', 'E:/PG'])

    def test_tcp_failure_does_not_start_native_daemon(self):
        with tempfile.TemporaryDirectory() as directory:
            hub = Hub(directory, 'codex', 'ws://127.0.0.1:1', connect=Mock(side_effect=OSError('offline')))
            with patch('hub.ensure_daemon') as ensure:
                hub.try_connect()
                ensure.assert_not_called()
            hub.close()

    def test_running_daemon_is_never_restarted(self):
        result = Mock(stdout=b'{"status":"running"}', returncode=0)
        with patch('runtime.subprocess.run', return_value=result) as run:
            ensure_daemon('codex', 'unix:///tmp/control')
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0], ['codex', 'app-server', 'daemon', 'version'])

    def test_proxy_bytes_timeout_and_close_only_own_child(self):
        real_popen = subprocess.Popen
        children = []
        def spawn(*args, **kwargs):
            child = real_popen([sys.executable, '-u', '-c',
                'import sys; data=sys.stdin.buffer.read(5); sys.stdout.buffer.write(data); sys.stdout.buffer.flush(); sys.stdin.buffer.read()'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
            children.append(child)
            return child
        with patch('os_adapters.windows.subprocess.Popen', side_effect=spawn):
            stream = ProxyStream('codex', 'control', timeout=.05)
            try:
                with self.assertRaises(TimeoutError):
                    stream.recv(5)
                stream.settimeout(5)
                stream.sendall(b'\x00\xffABC')
                self.assertEqual(stream.recv(2) + stream.recv(10), b'\x00\xffABC')
            finally:
                stream.close()
                stream.close()
            self.assertIsNotNone(children[0].poll())
            self.assertFalse(stream.reader.is_alive())


if __name__ == '__main__':
    unittest.main()
