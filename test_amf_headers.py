"""Regressions for AMF's incomplete global SPS versus its in-band SPS."""
import hashlib
import os
import re
import subprocess
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

import dji_graft
import hardware_accel


def trace(path):
    result = subprocess.run([dji_graft.FFMPEG_BIN, '-v', 'verbose', '-i', str(path),
        '-map', '0:v:0', '-c', 'copy', '-bsf:v', 'trace_headers',
        '-frames:v', '1', '-f', 'null', '-'], capture_output=True, check=True,
        text=True, encoding='utf-8', errors='replace')
    return result.stderr


def payload_digest(path, audio=False):
    # Compare actual coded slices, not a decoder's tolerance for bad headers.
    args = ['-map', '0:a:0', '-c', 'copy', '-f', 'adts'] if audio else [
        '-map', '0:v:0', '-c', 'copy', '-bsf:v',
        'h264_mp4toannexb,filter_units=pass_types=1-5', '-f', 'h264']
    result = subprocess.run([dji_graft.FFMPEG_BIN, '-v', 'error', '-i', str(path),
        *args, '-'], capture_output=True, check=True)
    return hashlib.sha256(result.stdout).hexdigest()


class AmfHeaderTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('DJI_TEST_BAD_AMF'), 'Requires failing camera sample')
    def test_repair_real_sample_preserves_coded_video_and_audio(self):
        dji_graft.check_tools()
        source = Path(os.environ['DJI_TEST_BAD_AMF'])
        targets = dji_graft.get_ref_targets(source)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'repaired.mp4'
            hardware_accel.normalize_amf_headers(dji_graft.FFMPEG_BIN, source, output, targets)
            self.assert_clean_headers(output, targets)
            self.assertEqual(payload_digest(source), payload_digest(output))
            self.assertEqual(payload_digest(source, True), payload_digest(output, True))
            for kind in ('video', 'audio'):
                old = next(s for s in dji_graft.ffprobe_json(source)['streams'] if s['codec_type'] == kind)
                new = next(s for s in dji_graft.ffprobe_json(output)['streams'] if s['codec_type'] == kind)
                for field in ('nb_frames', 'duration_ts', 'time_base', 'start_pts'):
                    self.assertEqual(old[field], new[field], (kind, field))

    @unittest.skipUnless(os.environ.get('DJI_TEST_GPU') == 'h264_amf', 'Requires AMD hardware')
    def test_new_amf_conversion_has_complete_global_headers(self):
        dji_graft.check_tools()
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / 'source.mp4', Path(folder) / 'output.mp4'
            subprocess.run([dji_graft.FFMPEG_BIN, '-v', 'error', '-f', 'lavfi', '-i',
                'testsrc2=s=320x180:r=30000/1001:d=0.5', '-f', 'lavfi', '-i',
                'sine=frequency=880:duration=0.5', '-c:v', 'libx264', '-c:a', 'aac',
                '-shortest', str(source)], capture_output=True, check=True)
            targets = dict(width=320, height=180, fps='30000/1001', level=40,
                sample_rate=48000, channels=2, video_bitrate=1000000,
                audio_bitrate=128000, video_timescale=30000)
            messages = []
            dji_graft.transcode(source, output, targets, show_progress=False,
                acceleration='h264_amf', status_callback=messages.append)
            self.assertTrue(any('硬件编码完成' in m for m in messages), messages)
            self.assert_clean_headers(output, targets)

    def assert_clean_headers(self, output, targets):
        header, packet = trace(output).split('Packet:', 1)
        def field(name):
            match = re.search(r'\b' + name + r'\s+[01]+ = (\d+)', header)
            self.assertIsNotNone(match, name)
            return int(match[1])
        self.assertEqual(field('timing_info_present_flag'), 1)
        self.assertEqual(Fraction(field('time_scale'), field('num_units_in_tick')),
                         Fraction(targets['fps']) * 2)
        self.assertEqual(field('constraint_set4_flag'), 0)
        self.assertEqual(field('constraint_set5_flag'), 0)
        self.assertEqual(re.findall(r'nal_unit_type\s+[01]+ = (\d+)', packet), ['5'])


if __name__ == '__main__':
    unittest.main()
