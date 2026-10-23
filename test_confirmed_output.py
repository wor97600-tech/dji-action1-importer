import os
import hashlib
import tempfile
import unittest
from pathlib import Path

import dji_graft


class ConfirmedCameraOutputTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('DJI_TEST_CONFIRMED'), 'Requires camera-confirmed output')
    def test_reproduces_camera_confirmed_file_byte_for_byte(self):
        dji_graft.check_tools()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'output.MP4'
            dji_graft.graft(os.environ['DJI_TEST_REFERENCE'], os.environ['DJI_TEST_OUTPUT'], output)
            expected = Path(os.environ['DJI_TEST_CONFIRMED']).read_bytes()
            self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(),
                             hashlib.sha256(expected).hexdigest())


if __name__ == '__main__':
    unittest.main()
