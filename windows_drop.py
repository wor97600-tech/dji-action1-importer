"""Windows Explorer file drops for a Tk widget, without a Tcl extension."""
import ctypes
import sys
import queue
from ctypes import wintypes


class WindowsFileDrop:
    def __init__(self, widget, callback):
        self.widget = widget
        self.callback = callback
        self.hwnd = None
        self.pending = queue.SimpleQueue()
        self._poll_id = None
        if sys.platform != 'win32':
            return
        self.shell = ctypes.WinDLL('shell32', use_last_error=True)
        self.controls = ctypes.WinDLL('comctl32', use_last_error=True)
        uint_ptr = ctypes.c_size_t
        result_type = ctypes.c_ssize_t
        self.proc_type = ctypes.WINFUNCTYPE(result_type, wintypes.HWND, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM, uint_ptr, uint_ptr)
        self.controls.SetWindowSubclass.argtypes = [wintypes.HWND, self.proc_type, uint_ptr, uint_ptr]
        self.controls.SetWindowSubclass.restype = wintypes.BOOL
        self.controls.RemoveWindowSubclass.argtypes = [wintypes.HWND, self.proc_type, uint_ptr]
        self.controls.RemoveWindowSubclass.restype = wintypes.BOOL
        self.controls.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.controls.DefSubclassProc.restype = result_type
        self.shell.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        self.shell.DragAcceptFiles.restype = None
        self.shell.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
        self.shell.DragQueryFileW.restype = wintypes.UINT
        self.shell.DragFinish.argtypes = [wintypes.HANDLE]
        self.shell.DragFinish.restype = None
        self._proc = self.proc_type(self._window_proc)
        hwnd = widget.winfo_id()
        if not self.controls.SetWindowSubclass(hwnd, self._proc, 1, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        self.hwnd = hwnd
        self.shell.DragAcceptFiles(hwnd, True)
        widget.bind('<Destroy>', self._destroy, add='+')
        self._poll_id = widget.after(50, self._poll)

    def _poll(self):
        self._poll_id = None
        try:
            while True:
                paths = self.pending.get_nowait()
                self.callback(paths)
        except queue.Empty:
            pass
        except Exception:
            self.widget.report_callback_exception(*sys.exc_info())
        finally:
            if self.hwnd is not None:
                self._poll_id = self.widget.after(50, self._poll)

    def _window_proc(self, hwnd, message, wparam, lparam, subclass_id, data):
        if message == 0x0233:  # WM_DROPFILES; this handler owns the HDROP.
            paths = []
            try:
                count = self.shell.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                for index in range(count):
                    length = self.shell.DragQueryFileW(wparam, index, None, 0)
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    self.shell.DragQueryFileW(wparam, index, buffer, length + 1)
                    paths.append(buffer.value)
            finally:
                self.shell.DragFinish(wparam)
            # Never call Tk from a native window procedure: nested Tcl entry
            # corrupts _tkinter's saved thread state during real OS dispatch.
            self.pending.put(paths)
            return 0
        if message == 0x0082:  # WM_NCDESTROY
            self.controls.RemoveWindowSubclass(hwnd, self._proc, 1)
            self.hwnd = None
        return self.controls.DefSubclassProc(hwnd, message, wparam, lparam)

    def _destroy(self, event):
        if event.widget is self.widget and self.hwnd is not None:
            if self._poll_id is not None:
                self.widget.after_cancel(self._poll_id)
                self._poll_id = None
            self.shell.DragAcceptFiles(self.hwnd, False)
            self.controls.RemoveWindowSubclass(self.hwnd, self._proc, 1)
            self.hwnd = None
