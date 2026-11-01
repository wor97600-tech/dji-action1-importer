import tempfile
import unittest
from pathlib import Path


class FormTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ref = self.root / 'ref.mp4'; self.ref.touch()
        self.src = self.root / 'input.mp4'; self.src.touch()
        self.values = dict(mode='single', ref=str(self.ref), inp=str(self.src),
            out=str(self.root/'DJI_0000.MP4'), crf='23', max_bitrate='',
            prefix='DJI_', start_number='0000', acceleration='cpu')

    def test_bad_numbers_report_validation_errors(self):
        from ui_model import validate_form
        for key, val in (('crf','abc'),('crf','52'),('max_bitrate','0'),('max_bitrate','x')):
            with self.subTest(key=key,val=val):
                with self.assertRaises(ValueError): validate_form(dict(self.values, **{key:val}))

    def test_output_cannot_overwrite_input_or_reference(self):
        from ui_model import validate_form
        for p in (self.src,self.ref):
            with self.assertRaises(ValueError):validate_form(dict(self.values,out=str(p)))

    def test_batch_path_and_number_validation(self):
        from ui_model import validate_form
        values=dict(self.values,mode='batch',inp=str(self.root),out=str(self.root/'result'))
        self.assertEqual(validate_form(values).start_number,0)
        for changes in ({'prefix':'../DJI_'},{'start_number':'-1'},{'start_number':'10000'},
                        {'out':str(self.root)},{'inp':str(self.src)}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):validate_form(dict(values,**changes))

    def test_valid_input_keeps_original_encoding_values(self):
        from ui_model import validate_form
        job=validate_form(dict(self.values,max_bitrate='10000'))
        self.assertEqual((job.crf,job.max_bitrate,job.acceleration),(23,10000000,'cpu'))

    def test_batch_queue_keeps_natural_source_order_and_default_names(self):
        from ui_model import build_batch_queue
        videos = [self.root / name for name in ('clip10.mp4', 'clip2.mp4', 'clip1.mp4')]
        queue = build_batch_queue(videos, 'DJI_', 0)
        self.assertEqual([item.source.name for item in queue], ['clip1.mp4', 'clip2.mp4', 'clip10.mp4'])
        self.assertEqual([item.output_name for item in queue], ['DJI_0000.MP4', 'DJI_0001.MP4', 'DJI_0002.MP4'])

    def test_batch_start_skips_only_completed_items_with_existing_output(self):
        from ui_model import build_batch_queue, pending_batch_items
        output_dir = self.root / 'output'; output_dir.mkdir()
        items = build_batch_queue([self.root / 'a.mp4', self.root / 'b.mp4', self.root / 'c.mp4'], 'DJI_', 0)
        items[0].status = '已完成'
        (output_dir / items[0].output_name).touch()
        items[1].status = '已完成'  # Stale status: file was removed, so it must be converted again.
        pending, skipped = pending_batch_items(items, output_dir)
        self.assertEqual([item.source.name for item in skipped], ['a.mp4'])
        self.assertEqual([item.source.name for item in pending], ['b.mp4', 'c.mp4'])

    def test_queue_action_label_tracks_conversion_state(self):
        from desktop_ui import DesktopUI
        self.assertEqual(DesktopUI._queue_action_text('等待转换'), '单独转换 ▶')
        self.assertEqual(DesktopUI._queue_action_text('转换中'), '转换中…')
        self.assertEqual(DesktopUI._queue_action_text('已完成'), '再次转换 ↻')
        self.assertEqual(DesktopUI._queue_action_text('失败'), '重试转换 ↻')

    def test_batch_queue_allows_custom_names_without_changing_source_order(self):
        from ui_model import build_batch_queue, validate_queue_names
        videos = [self.root / name for name in ('clip2.mp4', 'clip1.mp4')]
        queue = build_batch_queue(videos, 'DJI_', 0)
        queue[0].output_name = 'my_clip.MP4'
        validate_queue_names(queue)
        self.assertEqual([item.source.name for item in queue], ['clip1.mp4', 'clip2.mp4'])
        self.assertEqual(queue[0].output_name, 'my_clip.MP4')

    def test_custom_name_marker_is_independent_per_item(self):
        from ui_model import build_batch_queue
        queue = build_batch_queue([self.root / 'a.mp4', self.root / 'b.mp4'], 'DJI_', 0)
        queue[0].output_name = 'custom.MP4'
        queue[0].custom_name = True
        self.assertTrue(queue[0].custom_name)
        self.assertFalse(queue[1].custom_name)

    def test_batch_queue_rejects_duplicate_or_invalid_names(self):
        from ui_model import build_batch_queue, validate_queue_names
        queue = build_batch_queue([self.root / 'a.mp4', self.root / 'b.mp4'], 'DJI_', 0)
        for name in ('same.MP4', 'same.mp4'):
            queue[0].output_name = name
            queue[1].output_name = name
            with self.assertRaises(ValueError):
                validate_queue_names(queue)
        queue[1].output_name = 'bad/name.MP4'
        with self.assertRaises(ValueError):
            validate_queue_names(queue)

    def test_reference_specs_show_video_and_audio_parameters(self):
        from ui_model import format_reference_specs

        info = {'streams': [
            {'codec_type': 'video', 'codec_name': 'h264', 'width': 3840,
             'height': 2160, 'avg_frame_rate': '30000/1001'},
            {'codec_type': 'audio', 'codec_name': 'aac', 'sample_rate': '48000',
             'channels': 2},
        ]}

        self.assertEqual(
            format_reference_specs(info),
            '3840×2160 · 29.97 fps · H.264 · AAC 48 kHz / 2 ch',
        )

    def test_reference_specs_report_missing_audio_track(self):
        from ui_model import format_reference_specs

        info = {'streams': [
            {'codec_type': 'video', 'codec_name': 'h264', 'width': 1920,
             'height': 1080, 'r_frame_rate': '30/1'},
        ]}

        self.assertEqual(
            format_reference_specs(info),
            '1920×1080 · 30 fps · H.264 · 无音轨',
        )

    def test_rounded_button_redraw_recenters_text_and_smooths_capsule(self):
        from desktop_ui import RoundedActionButton

        class CanvasStub:
            _draw_shape = RoundedActionButton._draw_shape

            def __init__(self):
                self.width = 100
                self.height = 32
                self._shape = 'shape'
                self._label = 'label'
                self.coords_by_item = {}

            def winfo_reqwidth(self):
                return self.width

            def winfo_reqheight(self):
                return self.height

            def winfo_width(self):
                return 1

            def winfo_height(self):
                return 1

            def coords(self, item, *values):
                if values:
                    self.coords_by_item[item] = values
                return self.coords_by_item.get(item)

            def itemconfigure(self, *_args, **_kwargs):
                pass

            def tag_raise(self, *_args):
                pass

        button = CanvasStub()
        button._draw_shape('#00ff00')
        self.assertEqual(button.coords_by_item['label'], (50, 16))
        self.assertGreaterEqual(len(button.coords_by_item['shape']), 140)

        button.width = 180
        button._draw_shape('#00ff00')
        self.assertEqual(button.coords_by_item['label'], (90, 16))

    def test_estimated_remaining_time_uses_media_speed_and_processed_duration(self):
        from ui_model import estimate_remaining_seconds, format_eta

        self.assertEqual(estimate_remaining_seconds(300, 150, 1.5), 100)
        self.assertEqual(format_eta(90), '预计剩余 01:30')

    def test_estimated_remaining_time_waits_for_valid_speed(self):
        from ui_model import estimate_remaining_seconds, format_eta

        self.assertIsNone(estimate_remaining_seconds(300, 150, 0))
        self.assertIsNone(estimate_remaining_seconds(300, 150, None))
        self.assertEqual(format_eta(None), '预计剩余计算中')

if __name__=='__main__':unittest.main()
