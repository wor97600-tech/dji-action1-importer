import hashlib
import os
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import dji_graft


class AccelerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dji_graft.check_tools()
        cls.folder = tempfile.TemporaryDirectory()
        cls.root = Path(cls.folder.name)
        cls.source = cls.root / 'source.mp4'
        subprocess.run([dji_graft.FFMPEG_BIN, '-v', 'error', '-f', 'lavfi', '-i',
            'testsrc2=s=320x180:r=30:d=0.5', '-f', 'lavfi', '-i',
            'sine=frequency=880:duration=0.5', '-c:v', 'libx264', '-c:a', 'aac',
            '-shortest', str(cls.source)], check=True, capture_output=True)
        cls.targets = dict(width=320, height=180, fps='30/1', level=40,
                           sample_rate=48000, channels=2, video_bitrate=1000000,
                           audio_bitrate=128000, video_timescale=30000)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_cpu_mode_passes_original_encoding_command_unchanged(self):
        legacy = types.ModuleType('original_encoder')
        code = subprocess.run(['git', 'show', 'v4.0.0:dji_graft.py'],
                              capture_output=True, check=True).stdout
        exec(compile(code, 'original_encoder', 'exec'), legacy.__dict__)
        legacy.configure_ffmpeg(dji_graft.FFMPEG_BIN, dji_graft.FFPROBE_BIN)
        for crf in (None, 23):
            with self.subTest(crf=crf):
                expected, actual = self.root / 'expected.mp4', self.root / 'cpu.mp4'
                # Threaded ABR encoding need not be byte-identical across runs.
                # Run both real commands and compare the encoder arguments.
                with patch.object(legacy, 'run', wraps=legacy.run) as original_run:
                    legacy.transcode(self.source, expected, self.targets, show_progress=False, crf=crf)
                with patch.object(dji_graft, 'run', wraps=dji_graft.run) as current_run:
                    dji_graft.transcode(self.source, actual, self.targets, show_progress=False,
                                        crf=crf, acceleration='cpu')
                self.assertEqual(current_run.call_args.args[0][:-1], original_run.call_args.args[0][:-1])
                self.assertEqual(dji_graft.ffprobe_json(actual)['streams'][0]['codec_name'], 'h264')

    def test_unavailable_hardware_finishes_using_cpu(self):
        import hardware_accel
        output = self.root / 'fallback.mp4'
        messages = []
        with patch.object(hardware_accel, 'probe_encoder', return_value=(False, 'test unavailable')):
            dji_graft.transcode(self.source, output, self.targets, show_progress=False,
                crf=23, acceleration='auto', status_callback=messages.append)
        info = dji_graft.ffprobe_json(output)
        self.assertEqual(info['streams'][0]['codec_name'], 'h264')
        self.assertTrue(any('CPU' in message for message in messages))

    def test_failed_hardware_conversion_replaces_partial_output_with_cpu(self):
        import hardware_accel
        output = self.root / 'partial.mp4'
        messages = []
        def fail_conversion(cmd, *args, **kwargs):
            Path(cmd[-1]).write_bytes(b'partial hardware output')
            raise RuntimeError('test driver failure')
        with patch.object(hardware_accel, 'probe_encoder', return_value=(True, '')), \
             patch.object(hardware_accel, 'run_conversion', side_effect=fail_conversion):
            dji_graft.transcode(self.source, output, self.targets, show_progress=False,
                crf=23, acceleration='h264_amf', status_callback=messages.append)
        self.assertEqual(dji_graft.ffprobe_json(output)['streams'][0]['codec_name'], 'h264')
        self.assertTrue(any('CPU' in message for message in messages))

    @unittest.skipUnless(os.environ.get('DJI_TEST_GPU'), 'Set DJI_TEST_GPU to an available encoder')
    def test_real_hardware_output_has_compatible_video_and_audio(self):
        output = self.root / 'hardware.mp4'
        messages = []
        dji_graft.transcode(self.source, output, self.targets, show_progress=False,
            acceleration=os.environ['DJI_TEST_GPU'], status_callback=messages.append)
        info = dji_graft.ffprobe_json(output)
        video = next(s for s in info['streams'] if s['codec_type'] == 'video')
        audio = next(s for s in info['streams'] if s['codec_type'] == 'audio')
        self.assertEqual((video['codec_name'], video['pix_fmt'], video['has_b_frames']),
                         ('h264', 'yuv420p', 0))
        self.assertEqual(video['time_base'], '1/30000')
        self.assertEqual(audio['codec_name'], 'aac')
        self.assertTrue(any('硬件编码完成' in message for message in messages), messages)
        subprocess.run([dji_graft.FFMPEG_BIN, '-v', 'error', '-i', str(output),
                        '-f', 'null', '-'], check=True, capture_output=True)

    @unittest.skipUnless(os.environ.get('DJI_TEST_GPU') == 'h264_amf', 'Requires AMD hardware')
    def test_invalid_amf_headers_fall_back_to_original_cpu(self):
        import hardware_accel
        output = self.root / 'header_fallback.mp4'
        messages = []
        with patch.object(hardware_accel, 'normalize_amf_headers',
                          side_effect=RuntimeError('test incomplete SPS')):
            dji_graft.transcode(self.source, output, self.targets, show_progress=False,
                crf=23, acceleration='h264_amf', status_callback=messages.append)
        video = next(s for s in dji_graft.ffprobe_json(output)['streams']
                     if s['codec_type'] == 'video')
        self.assertIn('libx264', video['tags']['encoder'])
        self.assertTrue(any('test incomplete SPS' in m for m in messages), messages)
        self.assertFalse(any('硬件编码完成' in m for m in messages), messages)
