import tempfile
import unittest
from pathlib import Path


class FirstRunTests(unittest.TestCase):
    def test_first_launch_requires_acknowledgement_then_remembers(self):
        from app_info import disclaimer_acknowledged, acknowledge_disclaimer
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'prefs' / 'disclaimer.txt'
            self.assertFalse(disclaimer_acknowledged(path))
            acknowledge_disclaimer(path)
            self.assertTrue(disclaimer_acknowledged(path))

    def test_invalid_marker_does_not_skip_notice(self):
        from app_info import disclaimer_acknowledged
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'disclaimer.txt'
            path.write_bytes(b'\xffbroken')
            self.assertFalse(disclaimer_acknowledged(path))
