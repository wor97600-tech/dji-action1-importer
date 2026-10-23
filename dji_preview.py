"""DJI Osmo Action mijd v2 camera previews (little-endian directory)."""
import struct
from process_utils import hidden_process_options
import subprocess


def replace_camera_preview(sample, video_path, ffmpeg):
    """Replace the JPEG/JPEG/full-range NV12 camera preview layout.

    Keep all headers, offsets and lengths exactly as in the camera sample.
    JPEG quality is reduced if needed to fit its original reserved space.
    Unknown non-mijd metadata is left untouched.
    """
    if sample[:4] != b'mijd':
        return sample
    if len(sample) < 72 or struct.unpack_from('<I', sample, 4)[0] != 2:
        raise RuntimeError('不支持此参考文件的 DJI 预览版本，请使用 Osmo Action 参考文件')
    entries = [struct.unpack_from('<IIIHH', sample, 24 + 16*i) for i in range(3)]
    cursor = 72
    for i, (kind, off, size, width, height) in enumerate(entries):
        if (kind != 1 or off != cursor or not size or off+size > len(sample)
                or not 0 < width <= 4096 or not 0 < height <= 4096
                or width % 2 or height % 2):
            raise RuntimeError('参考文件的 DJI 预览目录不符合已验证格式')
        if i < 2 and not sample[off:off+3] == b'\xff\xd8\xff':
            raise RuntimeError('参考文件的 DJI JPEG 预览无效')
        if i == 2 and size != width*height*3//2:
            raise RuntimeError('参考文件的 DJI 原始预览大小无效')
        cursor = off+size
    result = bytearray(sample)
    for i, (kind, off, size, width, height) in enumerate(entries):
        cmd = [str(ffmpeg), '-v', 'error', '-i', str(video_path), '-map', '0:v:0',
               '-frames:v', '1', '-vf', f'scale={width}:{height}:flags=lanczos:out_range=full',
               '-pix_fmt', 'yuvj420p' if i < 2 else 'nv12']
        if i == 2:
            # Camera preview uses Y followed by interleaved U,V. I420's
            # separate U and V planes cause purple/green horizontal regions.
            formats = [['-c:v', 'rawvideo', '-f', 'rawvideo']]
        else:
            formats = [['-c:v', 'mjpeg', '-q:v', str(q), '-huffman', huffman,
                        '-f', 'image2pipe']
                       for huffman in ('default', 'optimal')
                       for q in (2, 5, 8, 12, 16, 20, 24, 28, 31)]
        for options in formats:
            proc = subprocess.run(cmd + options + ['pipe:1'], capture_output=True, **hidden_process_options())
            image = proc.stdout
            if proc.returncode or not image:
                raise RuntimeError('生成相机封面失败：' + proc.stderr.decode('utf-8', errors='replace')[-2000:])
            if i == 2:
                if len(image) != size:
                    raise RuntimeError('生成的相机原始预览大小不正确')
                break
            if len(image) <= size:
                # JPEG fill bytes before EOI preserve the exact slot length
                # without appending another image or moving any camera data.
                if not image.endswith(b'\xff\xd9'):
                    raise RuntimeError('生成的 JPEG 封面缺少结束标记')
                image = image[:-2] + b'\xff' * (size-len(image)) + image[-2:]
                break
        else:
            raise RuntimeError('新封面无法放入参考视频原有空间，请换用画面更丰富的参考视频；未改变容器结构')
        result[off:off+size] = image
    return bytes(result)
