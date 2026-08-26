"""
box_tools.py
最小化的 ISOBMFF (MP4/MOV) box 解析与构建工具。
"""
import struct


def read_box_list(buf):
    """解析 buf 中同一层级的所有 box，返回 dict 列表。"""
    boxes = []
    pos = 0
    n = len(buf)
    while pos < n:
        if n - pos < 8:
            break
        size = struct.unpack('>I', buf[pos:pos + 4])[0]
        btype = buf[pos + 4:pos + 8]
        header_size = 8
        if size == 1:
            largesize = struct.unpack('>Q', buf[pos + 8:pos + 16])[0]
            header_size = 16
            box_size = largesize
        elif size == 0:
            box_size = n - pos
        else:
            box_size = size
        payload_start = pos + header_size
        payload_end = pos + box_size
        boxes.append({
            'type': btype,
            'start': pos,
            'size': box_size,
            'header_size': header_size,
            'payload_start': payload_start,
            'payload_end': payload_end,
            'payload': buf[payload_start:payload_end],
            'full': buf[pos:payload_end],
        })
        pos = payload_end
    return boxes


def find_box(boxes, btype):
    for b in boxes:
        if b['type'] == btype:
            return b
    return None


def build_box(btype, payload):
    size = 8 + len(payload)
    if size < 2 ** 32:
        return struct.pack('>I4s', size, btype) + payload
    else:
        return struct.pack('>I4sQ', 1, btype, size + 8) + payload


def parse_hdlr_type(hdlr_payload):
    return hdlr_payload[8:12]


# ------------------------------------------------------------------
# 新增：基于文件对象的流式解析（不一次性读入整个文件）
# ------------------------------------------------------------------

def read_box_list_from_file(f, start=0, end=None):
    """从文件对象解析同一层级的所有 box，返回 dict 列表（不读取 payload）。"""
    boxes = []
    pos = start
    if end is None:
        f.seek(0, 2)
        end = f.tell()

    while pos < end:
        f.seek(pos)
        header = f.read(8)
        if len(header) < 8:
            break
        size = struct.unpack('>I', header[0:4])[0]
        btype = header[4:8]
        header_size = 8
        if size == 1:
            extra = f.read(8)
            if len(extra) < 8:
                break
            largesize = struct.unpack('>Q', extra)[0]
            header_size = 16
            box_size = largesize
        elif size == 0:
            box_size = end - pos
        else:
            box_size = size

        boxes.append({
            'type': btype,
            'start': pos,
            'size': box_size,
            'header_size': header_size,
            'payload_start': pos + header_size,
            'payload_end': pos + box_size,
        })
        pos += box_size
    return boxes


def read_box_payload(f, box_info):
    """根据 box_info 从文件读取 payload 字节。"""
    f.seek(box_info['payload_start'])
    return f.read(box_info['payload_end'] - box_info['payload_start'])


def read_box_full(f, box_info):
    """根据 box_info 从文件读取完整 box 字节。"""
    f.seek(box_info['start'])
    return f.read(box_info['size'])
