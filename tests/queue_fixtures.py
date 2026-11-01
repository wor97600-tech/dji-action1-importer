import struct


def box(kind, payload):
    return struct.pack('>I4s', 8 + len(payload), kind) + payload


# Minimal container metadata for scan tests; codec decoding belongs to FFmpeg.
MP4 = (box(b'ftyp', b'isom\0\0\0\0isom')
       + box(b'moov', box(b'trak', box(b'mdia', box(b'hdlr', b'\0' * 8 + b'vide' + b'\0' * 12))))
       + box(b'mdat', b'video payload'))
