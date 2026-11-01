import os
import tempfile
import unittest
from pathlib import Path

from ui_model import BatchQueueItem


class QueueSortTests(unittest.TestCase):
    def test_natural_name_order_and_reverse_preserve_items(self):
        from ui_model import sort_batch_queue
        items = [BatchQueueItem(Path(name), 'custom.MP4', '失败', 'error', True)
                 for name in ('video10.mp4', 'video2.mp4', 'video1.mp4')]
        ordered = sort_batch_queue(items, 'name_asc')
        self.assertEqual([x.source.name for x in ordered],
                         ['video1.mp4', 'video2.mp4', 'video10.mp4'])
        self.assertIs(ordered[0], items[2])
        self.assertEqual(ordered[0].output_name, 'custom.MP4')
        self.assertEqual(ordered[0].status, '失败')
        self.assertEqual(sort_batch_queue(items, 'name_desc'), list(reversed(ordered)))

    def test_file_times_sort_both_directions_and_missing_files_last(self):
        from ui_model import sort_batch_queue
        with tempfile.TemporaryDirectory() as folder:
            items = []
            for name, timestamp in [('b.mp4', 100), ('a.mp4', 200)]:
                path = Path(folder) / name
                path.touch()
                os.utime(path, (timestamp, timestamp))
                items.append(BatchQueueItem(path, name))
            missing = BatchQueueItem(Path(folder) / 'missing.mp4', 'missing.MP4')
            self.assertEqual(sort_batch_queue(items + [missing], 'modified_asc'), items + [missing])
            self.assertEqual(sort_batch_queue(items + [missing], 'modified_desc'), items[::-1] + [missing])
            for descending in (False, True):
                expected = sorted(items, key=lambda x: (x.source.stat().st_ctime, x.source.name), reverse=descending)
                key = 'created_desc' if descending else 'created_asc'
                self.assertEqual(sort_batch_queue(items + [missing], key), expected + [missing])
