from dataclasses import dataclass
from fractions import Fraction
import math
from pathlib import Path
import re

from utils import natural_sort_key

@dataclass(frozen=True)
class Job:
    mode: str
    ref: str
    inp: str
    out: str
    start_number: int
    crf: int | None
    max_bitrate: int | None
    prefix: str
    acceleration: str


@dataclass
class BatchQueueItem:
    source: Path
    output_name: str
    status: str = '等待转换'
    error: str = ''
    custom_name: bool = False
    added_manually: bool = False


def renumber_batch_queue(items, prefix='DJI_', start_number=0):
    """Assign automatic names from visible positions; retain explicit names."""
    if start_number < 0 or start_number + len(items) - 1 > 9999:
        raise ValueError('批量编号必须在 0–9999 之间，请调整起始编号或队列数量。')
    for index, item in enumerate(items):
        if item.custom_name:
            continue
        name = f'{prefix}{start_number + index:04d}.MP4'
        if item.output_name != name:
            item.output_name = name
            item.status, item.error = '等待转换', ''


def build_batch_queue(videos, prefix='DJI_', start_number=0):
    """Build the editable batch queue while preserving natural source order."""
    ordered = sorted((Path(video) for video in videos), key=natural_sort_key)
    return [
        BatchQueueItem(source=video, output_name=f'{prefix}{start_number + index:04d}.MP4')
        for index, video in enumerate(ordered)
    ]


def sort_batch_queue(items, order='name_asc'):
    """Reorder existing items without changing names or conversion state."""
    reverse = order.endswith('_desc')
    if order.startswith('name_'):
        return sorted(items, key=lambda item: natural_sort_key(item.source), reverse=reverse)
    dated, missing = [], []
    for item in items:
        try:
            stat = item.source.stat()
            timestamp = stat.st_ctime if order.startswith('created_') else stat.st_mtime
            dated.append((timestamp, natural_sort_key(item.source), item))
        except OSError:
            missing.append(item)
    dated.sort(key=lambda entry: (entry[0], entry[1]), reverse=reverse)
    return [entry[2] for entry in dated] + sorted(missing, key=lambda item: natural_sort_key(item.source))


def validate_queue_names(items):
    """Validate user-edited output names before a batch starts."""
    invalid = re.compile(r'[<>:"/\\|?*]')
    seen = set()
    for item in items:
        name = str(item.output_name).strip()
        if not name or Path(name).name != name or invalid.search(name) or any(ord(c) < 32 for c in name):
            raise ValueError(f'输出文件名无效：{name or "空名称"}')
        if Path(name).suffix.lower() != '.mp4':
            raise ValueError(f'输出文件名必须以 .MP4 结尾：{name}')
        key = name.casefold()
        if key in seen:
            raise ValueError(f'输出文件名重复：{name}')
        seen.add(key)


def pending_batch_items(items, output_dir):
    """Return unfinished items and completed items whose outputs still exist."""
    output_dir = Path(output_dir)
    skipped = [
        item for item in items
        if item.status == '已完成' and (output_dir / item.output_name).is_file()
    ]
    skipped_sources = {str(item.source) for item in skipped}
    pending = [item for item in items if str(item.source) not in skipped_sources]
    return pending, skipped


def estimate_remaining_seconds(total_duration, processed_duration, speed):
    """Estimate wall-clock time from remaining media duration and FFmpeg speed."""
    try:
        total = float(total_duration)
        processed = float(processed_duration)
        multiplier = float(speed)
    except (TypeError, ValueError):
        return None
    if total < 0 or processed < 0 or multiplier <= 0:
        return None
    return max(0.0, total - processed) / multiplier


def format_eta(seconds):
    if seconds is None:
        return '预计剩余计算中'
    try:
        remaining = max(0, math.ceil(float(seconds)))
    except (TypeError, ValueError):
        return '预计剩余计算中'
    minutes, seconds = divmod(remaining, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f'预计剩余 {hours:02d}:{minutes:02d}:{seconds:02d}'
    return f'预计剩余 {minutes:02d}:{seconds:02d}'


def format_reference_specs(info):
    """Format the video and audio parameters read from a reference MP4."""
    streams = info.get('streams', [])
    video = next((stream for stream in streams if stream.get('codec_type') == 'video'), None)
    if video is None:
        return '未检测到视频轨道'

    width, height = video.get('width'), video.get('height')
    resolution = f'{width}×{height}' if width and height else '未知分辨率'
    rate = video.get('avg_frame_rate') or video.get('r_frame_rate')
    try:
        fps = float(Fraction(str(rate)))
        fps_label = f'{fps:.2f}'.rstrip('0').rstrip('.') if fps > 0 else '未知'
    except (ValueError, ZeroDivisionError, TypeError):
        fps_label = '未知'

    video_codec = str(video.get('codec_name') or '未知视频编码').lower()
    video_codec = {'h264': 'H.264', 'hevc': 'H.265/HEVC'}.get(video_codec, video_codec.upper())
    parts = [resolution, f'{fps_label} fps', video_codec]

    audio = next((stream for stream in streams if stream.get('codec_type') == 'audio'), None)
    if audio is None:
        parts.append('无音轨')
    else:
        audio_codec = str(audio.get('codec_name') or '未知音频编码').upper()
        try:
            sample_rate = int(audio.get('sample_rate') or 0)
            rate_label = f'{sample_rate // 1000} kHz' if sample_rate >= 1000 and sample_rate % 1000 == 0 else f'{sample_rate} Hz'
        except (ValueError, TypeError):
            rate_label = '采样率未知'
        channels = audio.get('channels') or '未知'
        parts.append(f'{audio_codec} {rate_label} / {channels} ch')
    return ' · '.join(parts)

def validate_form(values, queue_items=None):
    v = {k: str(x).strip() for k, x in values.items()}
    mode = v['mode']
    if mode not in ('single', 'batch'): raise ValueError('请选择单个视频或批量转换。')
    if not v['ref'] or not Path(v['ref']).is_file(): raise ValueError('请选择相机拍摄的参考视频。')
    queued_batch = mode == 'batch' and bool(queue_items)
    if mode == 'batch' and queue_items is not None and not queue_items:
        raise ValueError('请先向队列添加 MP4 视频。')
    if not v['inp'] and not queued_batch: raise ValueError('请选择待转换视频或文件夹。')
    inp, ref = Path(v['inp']), Path(v['ref'])
    if not queued_batch and not (inp.is_file() if mode == 'single' else inp.is_dir()):
        raise ValueError('输入路径无效，请重新选择视频。' if mode == 'single' else '批量模式需要选择文件夹。')
    if not v['out']: raise ValueError('请选择输出位置。')
    out = Path(v['out'])
    if out.resolve() == ref.resolve() or (not queued_batch and out.resolve() == inp.resolve()):
        raise ValueError('输出位置不能与输入或参考文件相同。')
    if mode == 'single' and (out.suffix.lower() != '.mp4' or out.is_dir()):
        raise ValueError('输出文件名必须以 .MP4 结尾。')
    if mode == 'batch' and out.exists() and not out.is_dir():raise ValueError('批量输出必须是文件夹。')
    try: crf = int(v['crf']) if v['crf'] else None
    except ValueError: raise ValueError('CRF 请输入 0–51 的整数，或留空。') from None
    if crf is not None and not 0 <= crf <= 51:raise ValueError('CRF 必须在 0–51 之间。')
    try: bitrate = int(v['max_bitrate']) * 1000 if v['max_bitrate'] else None
    except ValueError:raise ValueError('码率请输入正整数，单位 kbps，或留空。') from None
    if bitrate is not None and bitrate < 1000:raise ValueError('码率必须是正整数，单位 kbps。')
    prefix, number = v.get('prefix') or 'DJI_', 0
    if mode == 'batch':
        if any(c in prefix for c in '<>:"/\\|?*') or any(ord(c)<32 for c in prefix):
            raise ValueError('文件名前缀不能包含路径或特殊符号。')
        try:number=int(v['start_number'] or '0')
        except ValueError:raise ValueError('起始编号请输入 0–9999 的整数。') from None
        if not 0 <= number <= 9999:raise ValueError('起始编号必须在 0–9999 之间。')
    if v['acceleration'] not in ('cpu','auto','h264_nvenc','h264_qsv','h264_amf'):
        raise ValueError('请选择有效的编码方式。')
    return Job(mode,v['ref'],v['inp'],v['out'],number,crf,bitrate,prefix,v['acceleration'])
