"""Cross-system regressions, including real subprocess pipe lifetime tests."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

from controllers import overlap, checked_scope
from paths import path_key, is_link
from runtime import load_config, codex_arguments, ensure_daemon
from hub import Hub
from os_adapters.windows import ProxyStream
from os_adapters import windows


class PlatformTest(unittest.TestCase):
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
