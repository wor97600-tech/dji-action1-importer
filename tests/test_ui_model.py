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

if __name__=='__main__':unittest.main()
