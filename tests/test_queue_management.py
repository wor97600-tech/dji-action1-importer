import tempfile
import ctypes
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from dji_graft_gui import App
from tests.queue_fixtures import MP4


class QueueManagementTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.inputs = self.root / 'inputs'
        self.inputs.mkdir()
        for name in ('a.mp4', 'b.mp4', 'c.mp4'):
            (self.inputs / name).write_bytes(MP4)
        self.ref = self.root / 'reference.mp4'
        self.ref.touch()
        for name in ('_refresh_ffmpeg_status', '_probe_reference_async'):
            mock = patch.object(App, name, create=True)
            mock.start()
            self.addCleanup(mock.stop)
        with patch('desktop_ui.disclaimer_acknowledged', return_value=True):
            self.app = App()
        self.addCleanup(self.close_app)
        self.app.mode.set('batch')
        self.app._on_mode_change()
        self.app.input_path.set(str(self.inputs))
        self.app.output_path.set(str(self.root / 'out'))
        self.app.ref_path.set(str(self.ref))
        self.app._refresh_batch_queue()

    def close_app(self):
        self.app.update_idletasks()
        self.app._file_drop._destroy(SimpleNamespace(widget=self.app.queue_tree))
        for timer in self.app.tk.call('after', 'info'):
            self.app.after_cancel(timer)
        self.app.destroy()

    def test_dropped_queue_without_input_folder_can_start_and_refresh(self):
        app = self.app
        app.input_path.set('')
        app._refresh_batch_queue()
        app.output_path.set('')
        external = self.root / 'external.mp4'
        external.write_bytes(MP4)
        app._drop_queue_files([str(external)])
        app._refresh_batch_queue()
        self.assertEqual([item.source for item in app._batch_queue], [external])
        self.assertEqual(Path(app.output_path.get()), self.root / 'DJI_Output')
        with patch('desktop_ui.threading.Thread'):
            app._start()
        self.assertTrue(app._running)

    def test_selecting_folder_keeps_files_already_dropped(self):
        app = self.app
        app.input_path.set('')
        app._refresh_batch_queue()
        external = self.root / 'external.mp4'
        external.write_bytes(MP4)
        app._drop_queue_files([str(external)])
        app.input_path.set(str(self.inputs))
        app._refresh_batch_queue()
        self.assertEqual([item.source.name for item in app._batch_queue], ['external.mp4', 'a.mp4', 'b.mp4', 'c.mp4'])

    def test_individual_and_retry_conversion_do_not_require_input_folder(self):
        app = self.app
        app.input_path.set('')
        a = app._batch_queue[0]
        with patch('desktop_ui.threading.Thread'):
            app._convert_single_queue_item(a)
            self.assertEqual(a.status, '转换中')
            app.msg_queue.put(('queue_status', (str(a.source), '失败', 'retry me')))
            app.msg_queue.put(('done', None))
            app._poll_queue()
            app._retry_failed()
            self.assertTrue(app._running)
            self.assertEqual(a.status, '等待重试')

    def test_triangles_are_vertical_and_click_to_move(self):
        app = self.app
        app.update()
        up, down = app._queue_move_buttons[1]
        self.assertEqual(up.winfo_x(), down.winfo_x())
        self.assertLess(up.winfo_y(), down.winfo_y())
        self.assertEqual(up.cget('text'), '▲')
        self.assertEqual(down.cget('text'), '▼')
        up.event_generate('<Button-1>')
        self.assertEqual([item.source.name for item in app._batch_queue], ['b.mp4', 'a.mp4', 'c.mp4'])

    def test_theme_switch_updates_triangles_without_another_click(self):
        from ui_theme import colors_for
        app = self.app
        app.update()
        selected = app._batch_queue[1]
        app.queue_tree.selection_set(str(selected.source))
        app.update()
        with patch('desktop_ui.save_theme_preference'):
            for dark in (True, False):
                app.dark_mode.set(dark)
                app._toggle_theme()
                app.update_idletasks()
                palette = colors_for('dark' if dark else 'light')
                for index, pair in enumerate(app._queue_move_buttons):
                    for triangle in pair:
                        if not triangle.winfo_ismapped(): continue
                        self.assertEqual(str(triangle.cget('background')),
                                         palette['tint'] if index == 1 else palette['surface'])
                        self.assertEqual(str(triangle.cget('foreground')),
                                         palette['muted'] if triangle.instate(['disabled']) else palette['action'])

    def test_sort_heading_has_space_for_label_and_theme_padding(self):
        from tkinter import font, ttk
        app = self.app
        for size in ('1040x680', '1200x760'):
            app.geometry(size)
            app.update()
            heading_font = font.Font(root=app, font=ttk.Style(app).lookup('Treeview.Heading', 'font'))
            label_width = heading_font.measure(app.queue_tree.heading('move', 'text'))
            self.assertGreaterEqual(app.queue_tree.column('move', 'width'), label_width + app.u(24))

    def test_queue_heading_hover_uses_current_theme(self):
        from tkinter import ttk
        from ui_theme import colors_for
        app = self.app
        with patch('desktop_ui.save_theme_preference'):
            for dark in (True, False):
                app.dark_mode.set(dark)
                app._toggle_theme()
                palette = colors_for('dark' if dark else 'light')
                style = ttk.Style(app)
                for state, background in ((('active',), palette['tint']), (('pressed',), palette['border'])):
                    self.assertEqual(style.lookup('Treeview.Heading', 'background', state), background)
                    self.assertEqual(style.lookup('Treeview.Heading', 'foreground', state), palette['text'])

    def test_refresh_preserves_manual_order_and_dropped_files(self):
        app = self.app
        app._move_queue_item(app._batch_queue[1], -1)
        external = self.root / '外部 视频.MP4'
        external.write_bytes(MP4)
        app._drop_queue_files([str(external), str(external), str(self.inputs / 'a.mp4')])
        (self.inputs / 'c.mp4').unlink()
        (self.inputs / 'd.mp4').write_bytes(MP4)
        app._refresh_batch_queue()
        self.assertEqual([i.source.name for i in app._batch_queue],
                         ['b.mp4', 'a.mp4', '外部 视频.MP4', 'd.mp4'])
        self.assertEqual([i.output_name for i in app._batch_queue],
                         ['DJI_0000.MP4', 'DJI_0001.MP4', 'DJI_0002.MP4', 'DJI_0003.MP4'])

    def test_move_and_sort_renumber_but_keep_custom_names(self):
        app = self.app
        app._batch_queue[0].status = '已完成'
        app._batch_queue[2].output_name = 'custom.MP4'
        app._batch_queue[2].custom_name = True
        app._move_queue_item(app._batch_queue[1], -1)
        self.assertEqual(app._batch_queue[1].status, '等待转换')
        app.queue_sort.set('名称 · 降序')
        app._sort_queue()
        self.assertEqual([i.source.name for i in app._batch_queue], ['c.mp4', 'b.mp4', 'a.mp4'])
        self.assertEqual([i.output_name for i in app._batch_queue],
                         ['custom.MP4', 'DJI_0001.MP4', 'DJI_0002.MP4'])

    def test_individual_conversions_wait_and_advance_fifo_without_duplicates(self):
        app = self.app
        a, b, c = app._batch_queue
        with patch('desktop_ui.threading.Thread'):
            app._convert_single_queue_item(a)
            app._convert_single_queue_item(a)
            app._convert_single_queue_item(c)
            app._convert_single_queue_item(b)
            app._convert_single_queue_item(c)
            self.assertEqual([a.status, b.status, c.status], ['转换中', '排队中', '排队中'])
            app.msg_queue.put(('queue_status', (str(a.source), '已完成', '')))
            app.msg_queue.put(('done', None))
            app._poll_queue()
            self.assertEqual([a.status, b.status, c.status], ['已完成', '排队中', '转换中'])
            app.msg_queue.put(('queue_status', (str(c.source), '失败', 'test failure')))
            app.msg_queue.put(('done', None))
            app._poll_queue()
            self.assertEqual(b.status, '转换中')
            app.msg_queue.put(('queue_status', (str(b.source), '已完成', '')))
            app.msg_queue.put(('done', None))
            app._poll_queue()
            self.assertFalse(app._running)

    def test_completed_item_requires_overwrite_consent(self):
        app = self.app
        item = app._batch_queue[0]
        item.status = '已完成'
        output = Path(app.output_path.get()) / item.output_name
        output.parent.mkdir()
        output.write_bytes(b'previous output')
        with patch('desktop_ui.messagebox.askyesno', return_value=False):
            app._convert_single_queue_item(item)
        self.assertFalse(app._running)
        self.assertEqual(item.status, '已完成')
        self.assertEqual(output.read_bytes(), b'previous output')
        with patch('desktop_ui.messagebox.askyesno', return_value=True), patch('desktop_ui.threading.Thread'):
            app._convert_single_queue_item(item)
        self.assertTrue(app._running)
        self.assertEqual(item.status, '转换中')

    def test_cancel_restores_waiting_items_and_finishes_current_only(self):
        app = self.app
        a, b, c = app._batch_queue
        c.status = '已完成'
        with patch('desktop_ui.threading.Thread'):
            app._convert_single_queue_item(a)
            app._convert_single_queue_item(b)
            app._convert_single_queue_item(c)
            app._cancel_tasks()
            self.assertEqual([a.status, b.status, c.status], ['转换中', '等待转换', '已完成'])
            self.assertFalse(app._single_pending)
            app.msg_queue.put(('queue_status', (str(a.source), '已完成', '')))
            app.msg_queue.put(('done', None))
            app._poll_queue()
            self.assertFalse(app._running)
            self.assertNotIn('排队中', [i.status for i in app._batch_queue])
            app._convert_single_queue_item(b)
            self.assertTrue(app._running)
            self.assertFalse(app._stop_after_current.is_set())

    def test_cancel_allows_new_queue_before_current_finishes(self):
        app = self.app
        a, b, c = app._batch_queue
        with patch('desktop_ui.threading.Thread'):
            app._convert_single_queue_item(a)
            app._convert_single_queue_item(b)
            app._cancel_tasks()
            app._convert_single_queue_item(c)
            self.assertEqual([a.status, b.status, c.status], ['转换中', '等待转换', '排队中'])
            app.msg_queue.put(('queue_status', (str(a.source), '已完成', '')))
            app.msg_queue.put(('done', None))
            app._poll_queue()
            self.assertEqual(c.status, '转换中')
            self.assertEqual(b.status, '等待转换')
            self.assertTrue(app._running)

    def test_cancel_batch_allows_new_individual_queue_and_second_cancel(self):
        app = self.app
        a, b, c = app._batch_queue
        with patch('desktop_ui.threading.Thread'):
            app._start()
            app._active_batch_source = str(a.source)
            a.status = '转换中'
            app._cancel_tasks()
            app._convert_single_queue_item(b)
            app._cancel_tasks()
            self.assertEqual(b.status, '等待转换')
            app._convert_single_queue_item(c)
            app.msg_queue.put(('queue_status', (str(a.source), '已完成', '')))
            app.msg_queue.put(('done', None))
            app._poll_queue()
            self.assertEqual(c.status, '转换中')
            self.assertEqual(b.status, '等待转换')

    def test_cancel_bulk_retry_restores_unstarted_failures_and_errors(self):
        app = self.app
        a, b, c = app._batch_queue
        for item in (a, b):
            item.status, item.error = '失败', 'original error'
        app._failed_queue = [a, b]
        with patch('desktop_ui.threading.Thread'):
            app._retry_failed()
            app._active_batch_source = str(a.source)
            app.msg_queue.put(('queue_status', (str(a.source), '转换中', '')))
            app._poll_queue()
            app._cancel_tasks()
            self.assertEqual((b.status, b.error), ('失败', 'original error'))
            self.assertEqual(a.status, '转换中')
            self.assertEqual(c.status, '等待转换')
            app.msg_queue.put(('queue_status', (str(a.source), '已完成', '')))
            app.msg_queue.put(('done', None))
            app._poll_queue()
            self.assertEqual(app._failed_queue, [b])
            self.assertFalse(app._running)

    def test_refresh_icon_spins_and_rescans_once_without_button_chrome(self):
        app = self.app
        new_file = self.inputs / 'added.mp4'
        new_file.write_bytes(MP4)
        icon = app.refresh_queue_btn
        app.update()
        position = (icon.winfo_rootx(), icon.winfo_rooty(), icon.winfo_width(), icon.winfo_height())
        observed_positions = []
        icon._invoke()
        icon._invoke()  # Repeated clicks during animation do not duplicate work.
        self.assertTrue(icon._spinning)
        def wait_for_animation():
            observed_positions.append((icon.winfo_rootx(), icon.winfo_rooty(), icon.winfo_width(), icon.winfo_height()))
            if icon._spinning:
                app.after(25, wait_for_animation)
            else:
                app.quit()
        app.after(25, wait_for_animation)
        app.after(3000, app.quit)
        app.mainloop()
        self.assertFalse(icon._spinning)
        self.assertTrue(all(current == position for current in observed_positions), observed_positions)
        self.assertEqual(float(icon.itemcget(icon._arc, 'start')), 0)
        self.assertEqual([i.source.name for i in app._batch_queue].count('added.mp4'), 1)

    def test_refresh_rotation_keeps_arc_center_fixed(self):
        icon = self.app.refresh_queue_btn
        original_box = icon.coords(icon._arc)
        for angle in (0, -90, -180, -270, -360):
            icon._draw_angle(angle)
            self.assertEqual(icon.coords(icon._arc), original_box)
            points = icon.coords(icon._arrow)
            center_x = (points[2] + points[4]) / 2
            center_y = (points[3] + points[5]) / 2
            # Midpoint between the arrow tip and its base is on the same circle.
            x, y = (points[0] + center_x) / 2, (points[1] + center_y) / 2
            self.assertAlmostEqual((x-icon._center)**2 + (y-icon._center)**2, icon._radius**2)

    def test_running_queue_cannot_be_reordered_or_refreshed(self):
        app = self.app
        before = list(app._batch_queue)
        app._set_running(True)
        app._move_queue_item(before[1], -1)
        (self.inputs / 'a.mp4').unlink()
        app._refresh_batch_queue()
        self.assertEqual(app._batch_queue, before)

    def test_invalid_drop_and_number_overflow_leave_queue_intact(self):
        app = self.app
        before = list(app._batch_queue)
        text_file = self.root / 'notes.txt'
        text_file.touch()
        app._drop_queue_files([str(text_file), str(self.root / 'missing.mp4'), str(self.inputs)])
        self.assertEqual(app._batch_queue, before)
        app.start_number.set('9997')
        extra = self.root / 'extra.mp4'
        extra.write_bytes(MP4)
        with patch('desktop_ui.messagebox.showerror'):
            app._drop_queue_files([str(extra)])
        self.assertEqual(app._batch_queue, before)
        self.assertEqual([i.output_name for i in before], ['DJI_9997.MP4', 'DJI_9998.MP4', 'DJI_9999.MP4'])

    @unittest.skipUnless(sys.platform == 'win32', 'Windows Explorer drop protocol')
    def test_native_drop_message_imports_unicode_multiple_paths(self):
        from ctypes import wintypes
        app = self.app
        paths = [self.root / '中文 视频.MP4', self.root / 'another.mp4']
        for path in paths: path.write_bytes(MP4)
        # Real HDROP memory layout: DROPFILES header followed by UTF-16 names.
        import struct
        data = struct.pack('<IiiII', 20, 0, 0, 0, 1)
        data += ('\0'.join(map(str, paths)) + '\0\0').encode('utf-16-le')
        kernel = ctypes.WinDLL('kernel32')
        kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel.GlobalLock.restype = ctypes.c_void_p
        kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        handle = kernel.GlobalAlloc(0x0042, len(data))
        self.assertTrue(handle)
        pointer = kernel.GlobalLock(handle)
        self.assertTrue(pointer)
        ctypes.memmove(pointer, data, len(data))
        kernel.GlobalUnlock(handle)
        user = ctypes.WinDLL('user32')
        user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user.SendMessageW.restype = ctypes.c_ssize_t
        user.SendMessageW(app.queue_tree.winfo_id(), 0x0233, handle, 0)
        app.after(150, app.quit)
        app.mainloop()
        self.assertEqual([i.source.name for i in app._batch_queue][-2:], ['中文 视频.MP4', 'another.mp4'])

    def test_new_buttons_fit_small_window_and_running_state(self):
        app = self.app
        for width, height in ((1040, 680), (1200, 760)):
            app.geometry(f'{width}x{height}')
            app.update()
            self.assertGreater(len(app._queue_move_buttons), 0)
            controls = [app.refresh_queue_btn, app.queue_sort_box]
            controls += [button for button in app._queue_action_buttons if button.winfo_ismapped()]
            controls += [button for pair in app._queue_move_buttons for button in pair if button.winfo_ismapped()]
            for button in controls:
                self.assertTrue(button.winfo_ismapped())
                parent = button.master
                self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                     parent.winfo_rootx() + parent.winfo_width())
        with patch('desktop_ui.threading.Thread'):
            app._convert_single_queue_item(app._batch_queue[0])
            app.update()
            self.assertEqual(str(app._queue_action_buttons[1].cget('state')), 'normal')
            self.assertEqual(str(app._queue_action_buttons[0].cget('state')), 'disabled')
            self.assertEqual(str(app.refresh_queue_btn.cget('state')), 'disabled')
            self.assertTrue(all(str(button.cget('state')) == 'disabled'
                                for pair in app._queue_move_buttons for button in pair))

    def test_batch_and_single_reject_overwriting_dropped_source(self):
        app = self.app
        out = Path(app.output_path.get())
        out.mkdir()
        for filename in ('DJI_0000.MP4', 'DJI_0000.reencoded_tmp.mp4'):
            with self.subTest(filename=filename):
                original = out / filename
                original.write_bytes(MP4)
                app._drop_queue_files([str(original)])
                with patch('desktop_ui.messagebox.showerror'), \
                     patch('desktop_ui.messagebox.askyesno', return_value=True), \
                     patch('desktop_ui.threading.Thread'):
                    app._start()
                    self.assertFalse(app._running)
                    app._convert_single_queue_item(app._batch_queue[0])
                    self.assertFalse(app._running)
                self.assertEqual(original.read_bytes(), MP4)
                original.unlink()
                app._refresh_batch_queue()

    def test_scan_only_adds_readable_mp4_and_keeps_locked_existing_item(self):
        app = self.app
        item = app._batch_queue[0]
        item.custom_name = True
        item.output_name = '手动名称.MP4'
        item.status = '已完成'
        (self.inputs / 'bad.mp4').write_bytes(b'not video')
        (self.inputs / 'empty.mp4').touch()
        (self.inputs / 'other.mov').write_bytes(MP4)
        (self.inputs / 'new.mp4').write_bytes(MP4)
        original_open = Path.open
        def locked_open(path, *args, **kwargs):
            if path in (item.source, self.inputs / 'new.mp4'):
                raise PermissionError('file temporarily locked')
            return original_open(path, *args, **kwargs)
        with patch.object(Path, 'open', locked_open):
            app._refresh_batch_queue()
        self.assertEqual([i.source.name for i in app._batch_queue], ['a.mp4', 'b.mp4', 'c.mp4'])
        self.assertIs(app._batch_queue[0], item)
        self.assertEqual((item.output_name, item.custom_name, item.status), ('手动名称.MP4', True, '已完成'))
        app._refresh_batch_queue()
        self.assertEqual([i.source.name for i in app._batch_queue], ['a.mp4', 'b.mp4', 'c.mp4', 'new.mp4'])
        app._refresh_batch_queue()
        self.assertEqual(len(app._batch_queue), 4)
