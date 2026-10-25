from dataclasses import dataclass
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


def build_batch_queue(videos, prefix='DJI_', start_number=0):
    """Build the editable batch queue while preserving natural source order."""
    ordered = sorted((Path(video) for video in videos), key=natural_sort_key)
    return [
        BatchQueueItem(source=video, output_name=f'{prefix}{start_number + index:04d}.MP4')
        for index, video in enumerate(ordered)
    ]


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

def validate_form(values):
    v = {k: str(x).strip() for k, x in values.items()}
    mode = v['mode']
    if mode not in ('single', 'batch'): raise ValueError('请选择单个视频或批量转换。')
    if not v['ref'] or not Path(v['ref']).is_file(): raise ValueError('请选择相机拍摄的参考视频。')
    if not v['inp']: raise ValueError('请选择待转换视频或文件夹。')
    inp, ref = Path(v['inp']), Path(v['ref'])
    if not (inp.is_file() if mode == 'single' else inp.is_dir()):
        raise ValueError('输入路径无效，请重新选择视频。' if mode == 'single' else '批量模式需要选择文件夹。')
    if not v['out']: raise ValueError('请选择输出位置。')
    out = Path(v['out'])
    if out.resolve() in (inp.resolve(), ref.resolve()): raise ValueError('输出位置不能与输入或参考文件相同。')
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
