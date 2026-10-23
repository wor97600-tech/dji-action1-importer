from dataclasses import dataclass
from pathlib import Path

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
    prefix, number = v['prefix'] or 'DJI_', 900
    if mode == 'batch':
        if any(c in prefix for c in '<>:"/\\|?*') or any(ord(c)<32 for c in prefix):
            raise ValueError('文件名前缀不能包含路径或特殊符号。')
        try:number=int(v['start_number'] or '900')
        except ValueError:raise ValueError('起始编号请输入 0–9999 的整数。') from None
        if not 0 <= number <= 9999:raise ValueError('起始编号必须在 0–9999 之间。')
    if v['acceleration'] not in ('cpu','auto','h264_nvenc','h264_qsv','h264_amf'):
        raise ValueError('请选择有效的编码方式。')
    return Job(mode,v['ref'],v['inp'],v['out'],number,crf,bitrate,prefix,v['acceleration'])
