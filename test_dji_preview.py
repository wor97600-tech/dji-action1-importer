import os
import struct
import subprocess
import tempfile
import types
import unittest
from pathlib import Path

import dji_graft
from box_tools import find_box, read_box_list
from ffmpeg_env import find_ffmpeg
from dji_preview import replace_camera_preview


def tracks(path):
    data = Path(path).read_bytes()
    moov = find_box(read_box_list(data), b'moov')
    return data, {t['htype']: t for t in (dji_graft.parse_trak(b)
        for b in read_box_list(moov['payload']) if b['type'] == b'trak')}


def samples(path, handler):
    data, ts = tracks(path)
    return b''.join(data[o:o+n] for o, n in
        dji_graft.compute_chunk_byte_ranges(dji_graft.get_stbl_children(ts[handler])))


class CameraPreviewTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('DJI_TEST_OUTPUT') and os.environ.get('DJI_TEST_REFERENCE'),
                         'Set DJI_TEST_OUTPUT and DJI_TEST_REFERENCE for the reported camera file')
    def test_reported_picture_fits_original_preview_slots(self):
        ffmpeg, _ = find_ffmpeg()
        original = samples(os.environ['DJI_TEST_REFERENCE'], b'meta')
        updated = replace_camera_preview(original, os.environ['DJI_TEST_OUTPUT'], ffmpeg)
        self.assertEqual(len(updated), len(original))
        self.assertEqual(updated[:72], original[:72])
        self.assertFalse(updated == original)
        for i in range(2):
            _, off, size, _, _ = struct.unpack_from('<IIIHH', updated, 24+16*i)
            subprocess.run([str(ffmpeg), '-v', 'error', '-i', 'pipe:0', '-f', 'null', '-'],
                input=updated[off:off+size], check=True, capture_output=True)

    @unittest.skipUnless(os.environ.get('DJI_TEST_REFERENCE'), 'Set DJI_TEST_REFERENCE to a camera MP4')
    def test_camera_raw_preview_keeps_colors_in_all_four_quadrants(self):
        ffmpeg, _ = find_ffmpeg()
        reference = samples(os.environ['DJI_TEST_REFERENCE'], b'meta')
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'colors.mp4'
            subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i',
                'color=c=white:s=320x180:r=30:d=0.1', '-vf',
                'drawbox=x=0:y=0:w=160:h=90:color=red:t=fill,'
                'drawbox=x=160:y=0:w=160:h=90:color=blue:t=fill,'
                'drawbox=x=0:y=90:w=160:h=90:color=lime:t=fill',
                '-c:v', 'libx264', '-crf', '0', str(source)], check=True, capture_output=True)
            updated = replace_camera_preview(reference, source, ffmpeg)
            _, off, size, w, h = struct.unpack_from('<IIIHH', updated, 56)
            rgb = subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'rawvideo',
                '-pixel_format', 'nv12', '-video_size', f'{w}x{h}', '-color_range', 'pc',
                '-i', 'pipe:0', '-frames:v', '1', '-vf', 'scale=in_range=full:out_range=full',
                '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1'],
                input=updated[off:off+size], check=True, capture_output=True).stdout
            for x, y, expected in [(w//4,h//4,(255,0,0)), (3*w//4,h//4,(0,0,255)),
                                    (w//4,3*h//4,(0,255,0)), (3*w//4,3*h//4,(255,255,255))]:
                actual = tuple(rgb[(y*w+x)*3:(y*w+x)*3+3])
                with self.subTest(position=(x,y), actual=actual):
                    self.assertTrue(all(abs(a-b)<12 for a,b in zip(actual,expected)),
                                    f'{actual} != {expected}')

    def test_unknown_metadata_is_preserved(self):
        sample = b'opaque camera metadata'
        self.assertEqual(replace_camera_preview(sample, 'unused', 'unused'), sample)

    def test_invalid_mijd_directory_fails_before_running_ffmpeg(self):
        for sample in (b'mijd', b'mijd' + struct.pack('<I', 3) + bytes(64),
                       b'mijd' + struct.pack('<I', 2) + bytes(64)):
            with self.subTest(sample=sample[:8]):
                with self.assertRaises(RuntimeError):
                    replace_camera_preview(sample, 'unused', 'unused')

    @unittest.skipUnless(os.environ.get('DJI_TEST_REFERENCE'), 'Set DJI_TEST_REFERENCE to a camera MP4')
    def test_graft_replaces_all_camera_previews_and_preserves_encoded_media(self):
        ffmpeg, ffprobe = find_ffmpeg()
        self.assertIsNotNone(ffmpeg)
        dji_graft.configure_ffmpeg(ffmpeg, ffprobe)
        reference = Path(os.environ['DJI_TEST_REFERENCE'])
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source, encoded, output = [folder / n for n in ('source.mp4', 'encoded.mp4', 'output.mp4')]
            subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i',
                'color=c=red:s=320x180:r=30:d=0.3', '-f', 'lavfi', '-i',
                'sine=frequency=880:duration=0.3', '-c:v', 'libx264', '-c:a', 'aac',
                '-shortest', str(source)], check=True, capture_output=True)
            dji_graft.transcode(source, encoded, dji_graft.get_ref_targets(reference),
                                show_progress=False, crf=23)
            dji_graft.graft(reference, encoded, output)
            # Use the unmodified v4.0.0 graft as the compatibility oracle.
            legacy = types.ModuleType('legacy_graft')
            legacy_source = subprocess.run(['git', 'show', 'v4.0.0:dji_graft.py'],
                check=True, capture_output=True).stdout
            exec(compile(legacy_source, 'legacy_graft', 'exec'), legacy.__dict__)
            baseline = folder / 'baseline.mp4'
            legacy.graft(reference, encoded, baseline)
            original_bytes = baseline.read_bytes()
            updated_bytes = output.read_bytes()
            self.assertEqual(len(updated_bytes), len(original_bytes),
                             'Cover replacement changed container layout')
            _, baseline_tracks = tracks(baseline)
            meta_ranges = dji_graft.compute_chunk_byte_ranges(
                dji_graft.get_stbl_children(baseline_tracks[b'meta']))
            masked = bytearray(updated_bytes)
            for off, size in meta_ranges:
                masked[off:off+size] = original_bytes[off:off+size]
            self.assertTrue(bytes(masked) == original_bytes,
                            'Bytes outside camera previews changed from original graft')
            original = samples(reference, b'meta')
            updated = samples(output, b'meta')
            self.assertFalse(updated == original, 'Camera preview still copied from reference')
            self.assertEqual(updated[:72], original[:72])
            cursor = 72
            for index in range(3):
                kind, off, size, width, height = struct.unpack_from('<IIIHH', updated, 24+16*index)
                old_kind, _, _, old_w, old_h = struct.unpack_from('<IIIHH', original, 24+16*index)
                self.assertEqual((kind, width, height), (old_kind, old_w, old_h))
                self.assertLessEqual(off+size, len(updated))
                self.assertEqual(off, cursor)
                cursor = off+size
                args = [] if index < 2 else ['-f', 'rawvideo', '-pixel_format', 'nv12',
                                             '-color_range', 'pc', '-video_size', f'{width}x{height}']
                pixels = subprocess.run([str(ffmpeg), '-v', 'error', *args, '-i', 'pipe:0',
                    '-frames:v', '1', '-vf', 'scale=1:1', '-pix_fmt', 'rgb24',
                    '-f', 'rawvideo', 'pipe:1'], input=updated[off:off+size],
                    check=True, capture_output=True).stdout
                self.assertGreater(pixels[0], 220)
                self.assertLess(pixels[1], 30)
                self.assertLess(pixels[2], 30)
            for handler in (b'vide', b'soun'):
                self.assertTrue(samples(output, handler) == samples(encoded, handler))
            self.assertEqual(cursor, len(updated))
            def udta(path):
                moov = find_box(read_box_list(Path(path).read_bytes()), b'moov')
                return find_box(read_box_list(moov['payload']), b'udta')['full']
            self.assertTrue(udta(output) == udta(reference))
            subprocess.run([str(ffmpeg), '-v', 'error', '-i', str(output),
                '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
