"""Hardware-independent integration coverage; not a physical GPU certification."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dji_graft
import hardware_accel as hw
from tests.test_amf_headers import payload_digest, trace


class MultiVendorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dji_graft.check_tools()
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / 'source.mp4'
        subprocess.run([dji_graft.FFMPEG_BIN, '-v', 'error', '-f', 'lavfi', '-i',
            'testsrc2=s=320x180:r=30:d=0.4', '-f', 'lavfi', '-i',
            'sine=frequency=880:duration=0.4', '-c:v', 'libx264',
            '-x264-params', 'bframes=0:ref=1:aud=1:repeat-headers=1',
            '-bsf:v', 'filter_units=remove_types=6',
            '-c:a', 'aac', '-ar', '48000', '-ac', '2',
            '-video_track_timescale', '30000', '-shortest', str(cls.source)],
            check=True, capture_output=True)
        cls.targets = dict(width=320, height=180, fps='30/1', level=40,
            video_bitrate=1000000, video_timescale=30000,
            sample_rate=48000, channels=2, audio_bitrate=128000)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def simulated_encoding(self, cmd, *args):
        # Only replace the absent physical encoder. The real normalization,
        # validation, temporary file handling and fallback must still run.
        import shutil
        shutil.copyfile(self.source, cmd[-1])

    def test_nvenc_and_qsv_pass_through_real_header_normalization(self):
        import re
        for encoder in ('h264_nvenc', 'h264_qsv'):
            with self.subTest(encoder=encoder):
                output = self.root / (encoder + '.mp4')
                messages = []
                with patch.object(hw, 'probe_encoder', return_value=(True, '')), \
                     patch.object(hw, 'run_conversion', side_effect=self.simulated_encoding):
                    dji_graft.transcode(self.source, output, self.targets,
                        acceleration=encoder, show_progress=False, status_callback=messages.append)
                packet = trace(output).split('Packet:', 1)[1]
                self.assertEqual(re.findall(r'nal_unit_type\s+[01]+ = (\d+)', packet), ['5'])
                self.assertEqual(payload_digest(self.source), payload_digest(output))
                self.assertEqual(payload_digest(self.source, True), payload_digest(output, True))
                self.assertTrue(any('硬件编码完成' in m for m in messages), messages)

    def test_automatic_tries_next_vendor_after_header_rejection(self):
        output = self.root / 'auto.mp4'
        messages = []
        original = hw.normalize_hardware_headers
        attempts = []
        def reject_first(*args):
            attempts.append(args[-1])
            if args[-1] == 'h264_nvenc':
                raise RuntimeError('test invalid NVIDIA SPS')
            return original(*args)
        with patch.object(hw, 'probe_encoder', return_value=(True, '')), \
             patch.object(hw, 'run_conversion', side_effect=self.simulated_encoding), \
             patch.object(hw, 'normalize_hardware_headers', side_effect=reject_first):
            dji_graft.transcode(self.source, output, self.targets, acceleration='auto',
                show_progress=False, status_callback=messages.append)
        self.assertEqual(attempts, ['h264_nvenc', 'h264_qsv'])
        self.assertIn('硬件编码完成：Intel Quick Sync', messages)
        self.assertTrue(any('test invalid NVIDIA SPS' in m for m in messages))

    def test_explicit_vendor_rejection_falls_back_to_original_cpu(self):
        for encoder in ('h264_nvenc', 'h264_qsv'):
            with self.subTest(encoder=encoder):
                output = self.root / ('fallback_' + encoder + '.mp4')
                messages = []
                with patch.object(hw, 'probe_encoder', return_value=(True, '')), \
                     patch.object(hw, 'run_conversion', side_effect=self.simulated_encoding), \
                     patch.object(hw, 'normalize_hardware_headers', side_effect=RuntimeError('bad SPS')):
                    dji_graft.transcode(self.source, output, self.targets, acceleration=encoder,
                        show_progress=False, status_callback=messages.append)
                self.assertTrue(any('自动回退原版 CPU' in m for m in messages), messages)
                self.assertFalse(any('硬件编码完成' in m for m in messages), messages)
                self.assertTrue(output.is_file())

    def test_vendor_options_explicitly_disable_adaptive_b_frames_and_aud(self):
        nv = hw.video_options('h264_nvenc', self.targets, None)
        qsv = hw.video_options('h264_qsv', self.targets, None)
        for opts in (nv, qsv):
            self.assertEqual(opts[opts.index('-aud') + 1], '0')
            self.assertEqual(opts[opts.index('-bf') + 1], '0')
        self.assertEqual(nv[nv.index('-b_ref_mode') + 1], 'disabled')
        self.assertEqual(qsv[qsv.index('-adaptive_b') + 1], '0')
        self.assertEqual(qsv[qsv.index('-idr_interval') + 1], '0')


if __name__ == '__main__':
    unittest.main()
