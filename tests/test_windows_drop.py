import subprocess
import sys
import unittest
from pathlib import Path

from process_utils import hidden_process_options


@unittest.skipUnless(sys.platform == 'win32', 'Windows drop protocol')
class WindowsDropTests(unittest.TestCase):
    def test_posted_drop_survives_real_tk_event_loop(self):
        result = subprocess.run([sys.executable, '-X', 'faulthandler', '-m', 'tests.drop_process_probe'],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                timeout=15, **hidden_process_options())
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
