"""Conservative, bounded MP4 container checks for adding queue entries."""
import os
import stat
import struct
from pathlib import Path

from ui_model import BatchQueueItem
from utils import natural_sort_key


def _boxes(stream, start, end):
    position = start
    count = 0
    while position < end:
        count += 1
        if count > 10000 or end - position < 8:
            raise ValueError('Invalid MP4 box list')
        stream.seek(position)
        header = stream.read(8)
        if len(header) != 8: raise ValueError('Incomplete MP4 header')
        size, kind = struct.unpack('>I4s', header)
        header_size = 8
        if size == 1:
            extra = stream.read(8)
            if len(extra) != 8: raise ValueError('Incomplete MP4 extended header')
            size = struct.unpack('>Q', extra)[0]
            header_size = 16
        elif size == 0:
            size = end - position
        if size < header_size or position + size > end:
            raise ValueError('Invalid MP4 box size')
        yield kind, position + header_size, position + size
        position += size


def readable_mp4(path):
    """Check readable, stable MP4 structure and a video handler, not codec support.

    OSError remains distinct from invalid content so existing queue entries can
    be retained when a drive or file is temporarily inaccessible.
    """
    path = Path(path)
    if path.suffix.lower() != '.mp4': return False
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size < 24: return False
    try:
        with path.open('rb') as stream:
            before = os.fstat(stream.fileno())
            boxes = list(_boxes(stream, 0, before.st_size))
            kinds = {kind for kind, _, _ in boxes}
            if not {b'ftyp', b'moov', b'mdat'} <= kinds: return False
            video = False
            for kind, start, end in boxes:
                if kind != b'moov': continue
                for child, ts, te in _boxes(stream, start, end):
                    if child != b'trak': continue
                    for child, ms, me in _boxes(stream, ts, te):
                        if child != b'mdia': continue
                        for child, hs, he in _boxes(stream, ms, me):
                            if child == b'hdlr' and he - hs >= 12:
                                stream.seek(hs + 8)
                                video = video or stream.read(4) == b'vide'
            after = os.fstat(stream.fileno())
            return video and (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    except (ValueError, struct.error):
        return False


def definitely_missing(path):
    try:
        path.stat()
    except FileNotFoundError:
        return True
    except OSError:
        pass  # Access denied is not evidence that the file was deleted.
    return False


def refresh_mp4_items(folder, previous):
    # Complete enumeration before mutating any queue state. A missing/offline
    # folder must leave the old queue intact instead of silently emptying it.
    paths = sorted(folder.iterdir(), key=natural_sort_key) if folder is not None else []
    known = {item.source for item in previous}
    items = [item for item in previous if not definitely_missing(item.source)]
    skipped = 0
    for path in paths:
        if path in known or path.suffix.lower() != '.mp4': continue
        try:
            valid = readable_mp4(path)
        except OSError:
            valid = False
        if valid:
            items.append(BatchQueueItem(path, ''))
        else:
            skipped += 1
    return items, skipped
