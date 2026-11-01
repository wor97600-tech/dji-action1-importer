"""Exercise a posted Windows drop inside Tk's real mainloop (process isolation)."""
import ctypes
import struct
import tkinter as tk
from ctypes import wintypes
from windows_drop import WindowsFileDrop

root = tk.Tk()
view = tk.Frame(root)
view.pack()
received_paths = []


def received(paths):
    received_paths.extend(paths)
    root.after(10, root.destroy)


drop = WindowsFileDrop(view, received)
kernel = ctypes.WinDLL('kernel32')
user = ctypes.WinDLL('user32')
kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel.GlobalAlloc.restype = wintypes.HGLOBAL
kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel.GlobalLock.restype = ctypes.c_void_p
kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]


def post():
    data = struct.pack('<IiiII', 20, 0, 0, 0, 1)
    data += 'C:/中文 视频.mp4\0C:/another.mp4\0\0'.encode('utf-16-le')
    handle = kernel.GlobalAlloc(0x42, len(data))
    pointer = kernel.GlobalLock(handle)
    ctypes.memmove(pointer, data, len(data))
    kernel.GlobalUnlock(handle)
    user.PostMessageW(view.winfo_id(), 0x233, handle, 0)


root.after(100, post)
root.after(3000, root.destroy)
root.mainloop()
assert received_paths == ['C:/中文 视频.mp4', 'C:/another.mp4'], received_paths
