import os
import queue
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import dji_graft
from dji_graft_gui import App
from dji_preview import replace_camera_preview
from tests.test_dji_preview import samples


class BatchQueueExecutionTests(unittest.TestCase):
    def test_cancel_cannot_observe_old_current_after_next_item_is_claimed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first, second = root / 'first.mp4', root / 'second.mp4'
            first.write_bytes(b'first'); second.write_bytes(b'second')
            checking, release_check, second_started, finish = (threading.Event() for _ in range(4))
            stop = threading.Event()
            class PausedCheck:
                def is_set(self):
                    value = stop.is_set()
                    checking.set()
                    if not release_check.wait(3): raise RuntimeError('test timeout')
                    return value
            ui = SimpleNamespace(msg_queue=queue.Queue(), _stop_after_current=PausedCheck(),
                                 _dispatch_lock=threading.Lock(), _active_batch_source=None)
            observed = []
            def cancel():
                with ui._dispatch_lock:
                    stop.set()
                    observed.append(ui._active_batch_source)
                finish.set()
            def transcode(source, temporary, targets, **kwargs):
                if source == second:
                    second_started.set()
                    if not finish.wait(3): raise RuntimeError('test timeout')
                temporary.write_bytes(source.read_bytes())
            def graft(reference, temporary, destination):
                destination.write_bytes(temporary.read_bytes())
            with patch('dji_graft_gui.get_duration_seconds', return_value=1), \
                 patch('dji_graft_gui.transcode', transcode), patch('dji_graft_gui.graft', graft):
                worker = threading.Thread(target=App._run_batch, args=(ui, root/'ref.mp4', root,
                    root/'out', {}, 0, 23, None, 'DJI_', 'cpu',
                    [(str(first), 'one.MP4'), (str(second), 'two.MP4')]))
                worker.start()
                try:
                    self.assertTrue(checking.wait(3))
                    canceller = threading.Thread(target=cancel)
                    canceller.start()
                    release_check.set()
                    self.assertTrue(second_started.wait(3))
                    canceller.join(3)
                    worker.join(3)
                    self.assertEqual(observed, [str(second)])
                finally:
                    release_check.set(); finish.set(); worker.join(3)

    def test_cancel_finishes_current_output_and_never_starts_next(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first, second = root / 'first.mp4', root / 'second.mp4'
            first.write_bytes(b'first video'); second.write_bytes(b'second video')
            event = threading.Event()
            ui = SimpleNamespace(msg_queue=queue.Queue(), _stop_after_current=event)
            def transcode(source, temporary, targets, **kwargs):
                temporary.write_bytes(source.read_bytes())
                event.set()  # User clicks stop while the first conversion runs.
            def graft(reference, temporary, destination):
                destination.write_bytes(temporary.read_bytes())
            with patch('dji_graft_gui.get_duration_seconds', return_value=1), \
                 patch('dji_graft_gui.transcode', transcode), patch('dji_graft_gui.graft', graft):
                App._run_batch(ui, root / 'ref.mp4', root, root / 'out', {}, 0, 23, None,
                               'DJI_', 'cpu', [(str(first), 'DJI_0000.MP4'), (str(second), 'DJI_0001.MP4')])
            self.assertEqual((root / 'out/DJI_0000.MP4').read_bytes(), b'first video')
            self.assertFalse((root / 'out/DJI_0001.MP4').exists())
            self.assertFalse(list((root / 'out').glob('*.reencoded_tmp.mp4')))
            statuses = [payload for kind, payload in iter_queue(ui.msg_queue) if kind == 'queue_status']
            self.assertEqual([(Path(source).name, status) for source, status, _ in statuses],
                             [('first.mp4', '转换中'), ('first.mp4', '已完成')])

    def test_run_batch_uses_queue_names_and_reports_status(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); inputs = root / 'inputs'; inputs.mkdir(); output = root / 'out'
            first = inputs / 'clip2.mp4'; second = inputs / 'clip10.mp4'
            first.write_bytes(b'one'); second.write_bytes(b'two')
            messages = queue.Queue()
            ui = SimpleNamespace(msg_queue=messages)

            def fake_transcode(source, tmp, targets, **kwargs):
                tmp.write_bytes(source.read_bytes())
                kwargs['progress_details_callback']({
                    'out_time_seconds': 2,
                    'speed': 1.0,
                    'percent': 20,
                    'duration_seconds': kwargs['total_duration'],
                })

            def fake_graft(ref, tmp, dest):
                dest.write_bytes(tmp.read_bytes())

            with patch('dji_graft_gui.get_duration_seconds', side_effect=[10, 20]), \
                 patch('dji_graft_gui.transcode', fake_transcode), \
                 patch('dji_graft_gui.graft', fake_graft):
                App._run_batch(ui, root / 'reference.mp4', inputs, output, {}, 900, 23, None, 'DJI_', 'cpu', [
                    (str(second), 'custom.MP4'), (str(first), 'DJI_0900.MP4')
                ])

            self.assertTrue((output / 'custom.MP4').is_file())
            self.assertTrue((output / 'DJI_0900.MP4').is_file())
            recorded = list(iter_queue(messages))
            statuses = [payload for kind, payload in recorded if kind == 'queue_status']
            self.assertEqual([status for _, status, _ in statuses], ['转换中', '已完成', '转换中', '已完成'])
            detail_messages = [
                payload for kind, payload in recorded if kind == 'progress_details'
            ]
            self.assertEqual([payload[2] for payload in detail_messages], [1, 2])
            self.assertEqual([payload[1]['duration_seconds'] for payload in detail_messages], [10, 20])
            self.assertEqual([payload[4] for payload in detail_messages], [30, 20])


def iter_queue(messages):
    while not messages.empty():
        yield messages.get()


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
