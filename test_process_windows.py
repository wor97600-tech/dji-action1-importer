import ast
import importlib
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


class HiddenProcessTests(unittest.TestCase):
    def test_all_media_launches_request_hidden_windows(self):
        count = 0
        for name in ('dji_graft.py', 'dji_preview.py', 'hardware_accel.py', 'ffmpeg_env.py'):
            tree = ast.parse(Path(__file__).with_name(name).read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == 'subprocess'
                        and node.func.attr in ('run', 'Popen')):
                    count += 1
                    self.assertTrue(any(k.arg is None and isinstance(k.value, ast.Call)
                        and isinstance(k.value.func, ast.Name)
                        and k.value.func.id == 'hidden_process_options' for k in node.keywords),
                        f'{name}:{node.lineno} can create a console window')
        self.assertGreaterEqual(count, 8)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows console test')
    def test_child_has_no_console_and_pipes_still_work(self):
        helper = importlib.import_module('process_utils')
        result = subprocess.run([sys.executable, '-c',
            'import ctypes,sys; print(ctypes.windll.kernel32.GetConsoleWindow()); '
            'print("diagnostic",file=sys.stderr); sys.exit(7)'],
            capture_output=True, text=True, **helper.hidden_process_options())
        self.assertEqual(result.stdout.strip(), '0')
        self.assertEqual(result.stderr.strip(), 'diagnostic')
        self.assertEqual(result.returncode, 7)

    def test_non_windows_does_not_receive_windows_flags(self):
        helper = importlib.import_module('process_utils')
        with patch.object(helper.sys, 'platform', 'linux'):
            self.assertEqual(helper.hidden_process_options(), {})


if __name__ == '__main__':
    unittest.main()
