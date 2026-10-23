"""Validate actual NVIDIA SPS, not ffprobe's decoder-side refs summary."""
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import dji_graft
import hardware_accel as hw


class NvidiaSpsTests(unittest.TestCase):
    def test_nvenc_explicitly_limits_decoded_picture_buffer(self):
        opts = hw.video_options('h264_nvenc', dict(
            video_bitrate=10000000, fps='24000/1001', level=40), None)
        self.assertIn('-dpb_size', opts)
        self.assertEqual(opts[opts.index('-dpb_size') + 1], '1')

    def test_missing_or_multiple_sps_reference_values_are_rejected(self):
        base = ('[trace_headers] Extradata\n'
                '[trace_headers] 0 timing_info_present_flag 1 = 1\n'
                '[trace_headers] 0 num_units_in_tick 1 = 1001\n'
                '[trace_headers] 0 time_scale 1 = 48000\n'
                '[trace_headers] 0 constraint_set4_flag 0 = 0\n'
                '[trace_headers] 0 constraint_set5_flag 0 = 0\n')
        for extra in ('',
            '[trace_headers] 0 max_num_ref_frames 1 = 2\n',
            '[trace_headers] 0 max_num_ref_frames 1 = 1\n'
            '[trace_headers] 0 max_num_ref_frames 1 = 2\n'):
            with self.subTest(extra=extra):
                result = subprocess.CompletedProcess([], 0, b'', (base+extra).encode())
                with patch.object(hw.subprocess, 'run', return_value=result):
                    with self.assertRaisesRegex(RuntimeError, 'SPS'):
                        hw.validate_hardware_headers('ffmpeg', 'unused.mp4',
                            {'fps':'24000/1001'}, 'h264_nvenc')

    @unittest.skipUnless(os.environ.get('DJI_TEST_BAD_NVENC'), 'Requires supplied NVIDIA sample')
    def test_camera_crashing_sample_is_rejected_even_when_ffprobe_refs_is_one(self):
        dji_graft.check_tools()
        source = Path(os.environ['DJI_TEST_BAD_NVENC'])
        targets = dji_graft.get_ref_targets(source)
        video = next(s for s in dji_graft.ffprobe_json(source)['streams']
                     if s['codec_type'] == 'video')
        self.assertEqual(video['refs'], 1)
        # This was allowed by the old validator; actual SPS says two.
        hw.validate_output(dji_graft.FFPROBE_BIN, source, targets)
        with self.assertRaisesRegex(RuntimeError, 'SPS.*参考帧'):
            hw.validate_hardware_headers(dji_graft.FFMPEG_BIN, source, targets, 'h264_nvenc')


if __name__ == '__main__':
    unittest.main()
