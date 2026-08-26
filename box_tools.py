"""
box_tools.py
最小化的 ISOBMFF (MP4/MOV) box 解析与构建工具。
只做本工具需要的事：扁平化解析同一层级的 box 列表、按类型查找、重新打包成 box 字节。
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
    # version(1) flags(3) pre_defined(4) handler_type(4) reserved(12) name...
    return hdlr_payload[8:12]
