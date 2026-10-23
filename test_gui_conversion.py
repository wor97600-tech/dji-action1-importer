import os
import queue
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import dji_graft
from dji_graft_gui import App
from dji_preview import replace_camera_preview
from test_dji_preview import samples


@unittest.skipUnless(os.environ.get('DJI_TEST_REFERENCE'), 'Requires reference MP4')
class GuiConversionTests(unittest.TestCase):
    def test_single_and_batch_generate_input_previews(self):
        self.exercise_conversion('cpu')

    @unittest.skipUnless(os.environ.get('DJI_TEST_GPU'), 'Requires hardware encoder')
    def test_automatic_gpu_single_and_batch_keep_cover_pipeline(self):
        self.exercise_conversion('auto')

    def exercise_conversion(self, acceleration):
        dji_graft.check_tools()
        ref = Path(os.environ['DJI_TEST_REFERENCE'])
        targets = dji_graft.get_ref_targets(ref)
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            inputs = folder / 'inputs'
            inputs.mkdir()
            source = inputs / 'red.mp4'
            subprocess.run([dji_graft.FFMPEG_BIN, '-v', 'error', '-f', 'lavfi', '-i',
                'color=c=red:s=320x180:r=30:d=0.3', '-f', 'lavfi', '-i',
                'sine=frequency=880:duration=0.3', '-c:v', 'libx264', '-c:a', 'aac',
                '-shortest', str(source)], check=True, capture_output=True)
            ui = SimpleNamespace(msg_queue=queue.Queue())
            single = folder / 'single.MP4'
            App._run_single(ui, ref, source, single, targets, 23, None, acceleration)
            App._run_batch(ui, ref, inputs, folder / 'batch', targets, 900, 23, None, 'DJI_', acceleration)
            original = samples(ref, b'meta')
            for output in (single, folder / 'batch' / 'DJI_0900.MP4'):
                with self.subTest(output=output.name):
                    self.assertTrue(output.is_file())
                    preview = samples(output, b'meta')
                    self.assertEqual(len(preview), len(original))
                    self.assertEqual(preview[:72], original[:72])
                    self.assertFalse(preview == original)
                    self.assertTrue(preview == replace_camera_preview(
                        original, output, dji_graft.FFMPEG_BIN))
                    self.assertFalse(output.with_suffix('.reencoded_tmp.mp4').exists())
                    result = subprocess.run([dji_graft.FFMPEG_BIN, '-v', 'error', '-i',
                        str(output), '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'],
                        capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
            logs = []
            while not ui.msg_queue.empty():
                logs.append(ui.msg_queue.get())
            self.assertFalse(any(k == 'error' for k, _ in logs))
            self.assertTrue(any(k == 'log' and '成功 1 个，失败 0 个' in v for k, v in logs))
            if acceleration == 'auto':
                self.assertEqual(sum(k == 'log' and '硬件编码完成' in v for k, v in logs), 2, logs)
