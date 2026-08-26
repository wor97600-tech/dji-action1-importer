#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dji_graft.py — 把第三方视频"移植"进大疆 Action 系列相机原生 MP4 的容器结构里，
使相机固件能够识别、回放它。

原理：
    1. 用 ffmpeg 把第三方视频转码成和"参考原生文件"一致的编码参数
       （分辨率/帧率/H.264 High Profile/单参考帧/无 B 帧/无多余 SEI，
       这些是运动相机硬件解码芯片能稳定解码的关键限制）。
    2. 解析参考原生文件的 MP4 box 树（ftyp / mdat / moov，以及 moov 下的
       video / audio / DJI.Meta 三条 trak）。
    3. 只替换 video、audio 两条 trak 的 sample table（stsd/stts/stsz/stco 等）
       和媒体数据本身；DJI.Meta 轨道和 udta（含机型、序列号等信息）原封不动。
    4. 重新计算所有 chunk 在新文件中的物理偏移，重建 mdat，patch 时长字段。
    5. 输出的文件在容器结构和元数据层面与参考文件高度一致，编码芯片可以正常解码。

用法：
    python3 dji_graft.py --ref DJI_0819.MP4 --input my_video.mp4 --output DJI_0900.MP4

依赖：系统需要已安装 ffmpeg / ffprobe（本工具通过 subprocess 调用，不再依赖网络下载任何库）。

注意事项：
    - 仅在你自己拥有的相机 / 视频素材上使用；产出文件只是"容器伪装"，
      并不能让相机识别出它并没有拍摄过这段视频，仅用于个人娱乐/兼容性目的。
    - 不同固件版本、不同相机型号的校验严格程度可能不同，如果播放依然失败，
      需要用 --ref 参数换一个更新固件下拍摄的参考文件重新尝试。
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dji_graft.py — 流式移植 + 体积控制版
"""
import argparse
import json
import shutil
import struct
import subprocess
import sys
import threading
from pathlib import Path

from box_tools import (
    read_box_list, find_box, build_box, parse_hdlr_type,
    read_box_list_from_file, read_box_payload, read_box_full,
)


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")


def ffprobe_json(path):
    cmd = ["ffprobe", "-v", "error", "-show_format", "-show_streams",
           "-of", "json", str(path)]
    r = run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {r.stderr}")
    return json.loads(r.stdout)


def check_tools():
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            print(f"错误：未找到 {tool}，请先安装 ffmpeg。", file=sys.stderr)
            sys.exit(1)


# --------------------------------------------------------------------------
# 第一步：读取参数
# --------------------------------------------------------------------------
def get_ref_targets(ref_path):
    info = ffprobe_json(ref_path)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next(s for s in info["streams"] if s["codec_type"] == "audio")
    fr = v["r_frame_rate"]
    return {
        "width": v["width"],
        "height": v["height"],
        "fps": fr,
        "level": v.get("level", 50),
        "sample_rate": int(a["sample_rate"]),
        "channels": int(a["channels"]),
        "video_bitrate": int(v.get("bit_rate") or info["format"].get("bit_rate", 35_000_000)),
        "audio_bitrate": int(a.get("bit_rate", 190_000)),
    }


def get_input_video_bitrate(path):
    """获取输入文件的视频码率（bps），失败返回 0"""
    try:
        info = ffprobe_json(path)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        return int(v.get("bit_rate") or 0)
    except Exception:
        return 0


def get_duration_seconds(path):
    info = ffprobe_json(path)
    try:
        return float(info["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        return 0.0


def format_bar(percent, width=30):
    percent = max(0.0, min(100.0, percent))
    filled = int(width * percent / 100)
    return "[" + "#" * filled + "-" * (width - filled) + f"] {percent:5.1f}%"


def _parse_time_str(s):
    try:
        h, m, sec = s.split(":")
        return int(h) * 3600 + int(m) * 60 + float(sec)
    except ValueError:
        return None


def run_ffmpeg_with_progress(cmd, total_duration, label="", progress_callback=None):
    cmd = cmd[:-1] + ["-progress", "pipe:1", "-nostats"] + [cmd[-1]]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding="utf-8", errors="replace", bufsize=1)
    stderr_chunks = []

    def _drain_stderr():
        for chunk in proc.stderr:
            stderr_chunks.append(chunk)

    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()

    for line in proc.stdout:
        line = line.strip()
        if line.startswith("out_time="):
            secs = _parse_time_str(line.split("=", 1)[1])
            if secs is not None:
                percent = (secs / total_duration * 100) if total_duration > 0 else 0
                if progress_callback:
                    progress_callback(min(100.0, percent))
                else:
                    bar = format_bar(percent) if total_duration > 0 else f"{secs:6.1f}s"
                    print(f"\r    {label} {bar}", end="", flush=True)
        elif line.startswith("progress=") and line.endswith("end"):
            if progress_callback:
                progress_callback(100.0)
            else:
                print(f"\r    {label} {format_bar(100)}", flush=True)

    proc.wait()
    t.join(timeout=5)
    if proc.returncode != 0:
        if not progress_callback:
            print()
        raise RuntimeError(f"ffmpeg 失败:\n{''.join(stderr_chunks)[-3000:]}")


def transcode(input_path, out_path, targets, show_progress=True, label="",
              progress_callback=None, crf=None, max_video_bitrate=None):
    """
    crf: 0-51，越小画质越好体积越大。推荐 23（默认）或 26（更小体积）。
         None 表示使用固定码率（兼容旧行为）。
    max_video_bitrate: 手动限制峰值码率（bps），覆盖参考文件码率。
    """
    ab = max(targets["audio_bitrate"], 128_000)
    
    ref_vb = targets["video_bitrate"]
    if max_video_bitrate:
        vb = max_video_bitrate
    else:
        vb = ref_vb

    x264_params = "ref=1:bframes=0:b-adapt=0:scenecut=0:cabac=1:aud=0"
    video_cmd = [
        "-c:v", "libx264", "-profile:v", "high", "-level", str(targets["level"] / 10),
        "-tag:v", "avc1",
        "-x264-params", x264_params,
        "-bsf:v", "filter_units=remove_types=6",
        "-pix_fmt", "yuv420p",
    ]

    if crf is not None:
        video_cmd += [
            "-crf", str(crf),
            "-maxrate", str(vb),
            "-bufsize", str(int(vb * 2)),
        ]
    else:
        video_cmd += [
            "-b:v", str(vb),
            "-maxrate", str(int(vb * 1.15)),
            "-bufsize", str(int(vb * 1.15)),
        ]

    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-vf", f"scale={targets['width']}:{targets['height']}:flags=lanczos,"
               f"fps={targets['fps']},format=yuv420p",
    ] + video_cmd + [
        "-c:a", "aac", "-ar", str(targets["sample_rate"]), "-ac", str(targets["channels"]),
        "-b:a", str(ab),
        "-movflags", "+faststart",
        str(out_path),
    ]

    if progress_callback is not None:
        total_duration = get_duration_seconds(input_path)
        run_ffmpeg_with_progress(cmd, total_duration, label=label, progress_callback=progress_callback)
    elif show_progress:
        total_duration = get_duration_seconds(input_path)
        run_ffmpeg_with_progress(cmd, total_duration, label=label)
    else:
        r = run(cmd)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg 转码失败:\n{r.stderr[-3000:]}")


# --------------------------------------------------------------------------
# 第二步：box 辅助函数
# --------------------------------------------------------------------------
def parse_trak(trak):
    tc = read_box_list(trak['payload'])
    tkhd = find_box(tc, b'tkhd')
    edts = find_box(tc, b'edts')
    mdia = find_box(tc, b'mdia')
    mc = read_box_list(mdia['payload'])
    hdlr = find_box(mc, b'hdlr')
    htype = parse_hdlr_type(hdlr['payload'])
    mdhd = find_box(mc, b'mdhd')
    minf = find_box(mc, b'minf')
    minfc = read_box_list(minf['payload'])
    stbl = find_box(minfc, b'stbl')
    return dict(trak=trak, tc=tc, tkhd=tkhd, edts=edts, mdia=mdia, mc=mc,
                hdlr=hdlr, htype=htype, mdhd=mdhd, minf=minf, minfc=minfc, stbl=stbl)


def get_stbl_children(info):
    return {b['type']: b for b in read_box_list(info['stbl']['payload'])}


def parse_stco(box):
    p = box['payload']
    ec = struct.unpack('>I', p[4:8])[0]
    return list(struct.unpack('>%dI' % ec, p[8:8 + 4 * ec]))


def parse_stsc(box):
    p = box['payload']
    ec = struct.unpack('>I', p[4:8])[0]
    entries = []
    off = 8
    for _ in range(ec):
        first_chunk, spc, sdi = struct.unpack('>III', p[off:off + 12])
        entries.append((first_chunk, spc, sdi))
        off += 12
    return entries


def parse_stsz(box):
    p = box['payload']
    sample_size, count = struct.unpack('>II', p[4:12])
    if sample_size != 0:
        return [sample_size] * count
    return list(struct.unpack('>%dI' % count, p[12:12 + 4 * count]))


def samples_per_chunk_list(stsc_entries, num_chunks):
    result = []
    for idx, (first_chunk, spc, _sdi) in enumerate(stsc_entries):
        next_first = stsc_entries[idx + 1][0] if idx + 1 < len(stsc_entries) else num_chunks + 1
        for _c in range(first_chunk, next_first):
            result.append(spc)
    return result


def compute_chunk_byte_ranges(stbl_children):
    stco = parse_stco(stbl_children[b'stco'])
    stsc = parse_stsc(stbl_children[b'stsc'])
    stsz = parse_stsz(stbl_children[b'stsz'])
    spc_list = samples_per_chunk_list(stsc, len(stco))
    ranges, sample_idx = [], 0
    for i, chunk_offset in enumerate(stco):
        n = spc_list[i]
        ranges.append((chunk_offset, sum(stsz[sample_idx:sample_idx + n])))
        sample_idx += n
    assert sample_idx == len(stsz), "sample 数量不匹配，stsc/stsz 解析有误"
    return ranges


def build_stco(offsets):
    payload = struct.pack('>I', 0) + struct.pack('>I', len(offsets))
    payload += struct.pack('>%dI' % len(offsets), *offsets)
    return build_box(b'stco', payload)


def read_mdhd_ts_dur(mdhd_box):
    p = mdhd_box['payload']
    if p[0] == 0:
        return struct.unpack('>II', p[12:20])
    return struct.unpack('>QQ', p[20:36])


def patch_u32(payload, offset, value):
    return payload[:offset] + struct.pack('>I', value) + payload[offset + 4:]


def patch_tkhd_duration(tkhd_box, new_dur):
    p = tkhd_box['payload']
    assert p[0] == 0, "仅支持 version 0 的 tkhd（DJI 相机文件均为此格式）"
    return build_box(b'tkhd', patch_u32(p, 20, new_dur))


def patch_mdhd_duration(mdhd_box, new_dur):
    p = mdhd_box['payload']
    assert p[0] == 0, "仅支持 version 0 的 mdhd"
    return build_box(b'mdhd', patch_u32(p, 16, new_dur))


def patch_elst_full_span(edts_box, new_dur):
    ec_ = read_box_list(edts_box['payload'])
    elst = find_box(ec_, b'elst')
    p = elst['payload']
    if p[0] != 0:
        return edts_box['full']
    p2 = p[:8] + struct.pack('>I', new_dur) + p[12:]
    return build_box(b'edts', build_box(b'elst', p2))


# --------------------------------------------------------------------------
# 流式复制辅助
# --------------------------------------------------------------------------
def _stream_copy(src_f, dst_f, size, chunk=1024 * 1024):
    remaining = size
    while remaining > 0:
        to_read = min(chunk, remaining)
        data = src_f.read(to_read)
        if not data:
            raise RuntimeError(f"流式复制时源文件提前结束，预期复制 {size} 字节")
        dst_f.write(data)
        remaining -= len(data)


# --------------------------------------------------------------------------
# 第三步：主移植逻辑（流式版 + 修复 meta_size 计算）
# --------------------------------------------------------------------------
def graft(ref_path, reencoded_path, output_path, chunk_size=1024 * 1024):
    with open(ref_path, 'rb') as ref_f, open(reencoded_path, 'rb') as re_f:
        ref_top = read_box_list_from_file(ref_f)

        ftyp_info = find_box(ref_top, b'ftyp')
        wide_info = find_box(ref_top, b'wide')
        mdat_info = find_box(ref_top, b'mdat')
        moov_info = find_box(ref_top, b'moov')

        if not ftyp_info or not mdat_info or not moov_info:
            raise RuntimeError("参考文件缺少必需的 ftyp/mdat/moov box")

        prefix = read_box_full(ref_f, ftyp_info)
        if wide_info:
            prefix += read_box_full(ref_f, wide_info)

        mdat_header_len = mdat_info['payload_start'] - mdat_info['start']
        meta_sample_start = len(prefix) + mdat_header_len

        moov_payload = read_box_payload(ref_f, moov_info)
        moov_children = read_box_list(moov_payload)
        mvhd = find_box(moov_children, b'mvhd')
        udta_full = find_box(moov_children, b'udta')
        udta_full = udta_full['full'] if udta_full else b''
        traks = [b for b in moov_children if b['type'] == b'trak']

        trak_info = {}
        for t in traks:
            info = parse_trak(t)
            trak_info[info['htype']] = info

        if b'vide' not in trak_info or b'soun' not in trak_info:
            raise RuntimeError("参考文件里没找到 video/audio 轨道，结构和预期不符")

        video_o, audio_o = trak_info[b'vide'], trak_info[b'soun']
        meta_o = trak_info.get(b'meta')

        # ---- 修复：正确计算 meta 轨道的总 sample 大小 ----
        meta_sample_bytes = b''
        meta_size = 0
        if meta_o is not None:
            meta_stbl_children = read_box_list(meta_o['stbl']['payload'])
            sp = find_box(meta_stbl_children, b'stsz')['payload']
            sample_size, count = struct.unpack('>II', sp[4:12])
            if sample_size != 0:
                meta_size = sample_size * count
            else:
                if count > 0:
                    sizes = struct.unpack('>%dI' % count, sp[12:12 + 4 * count])
                    meta_size = sum(sizes)
            if meta_size > 0:
                ref_f.seek(meta_sample_start)
                meta_sample_bytes = ref_f.read(meta_size)

        re_top = read_box_list_from_file(re_f)
        re_moov_info = find_box(re_top, b'moov')
        if not re_moov_info:
            raise RuntimeError("转码后文件缺少 moov box")

        re_moov_payload = read_box_payload(re_f, re_moov_info)
        re_moov_children = read_box_list(re_moov_payload)
        re_traks = [b for b in re_moov_children if b['type'] == b'trak']
        re_trak_info = {}
        for t in re_traks:
            info = parse_trak(t)
            re_trak_info[info['htype']] = info

        if b'vide' not in re_trak_info or b'soun' not in re_trak_info:
            raise RuntimeError("转码后文件缺少 video/audio 轨道")

        video_r, audio_r = re_trak_info[b'vide'], re_trak_info[b'soun']
        vr_stbl, ar_stbl = get_stbl_children(video_r), get_stbl_children(audio_r)

        video_chunks = compute_chunk_byte_ranges(vr_stbl)
        audio_chunks = compute_chunk_byte_ranges(ar_stbl)

        tagged = [(off, size, 'v', i) for i, (off, size) in enumerate(video_chunks)]
        tagged += [(off, size, 'a', i) for i, (off, size) in enumerate(audio_chunks)]
        tagged.sort(key=lambda x: x[0])

        v_ts, v_dur = read_mdhd_ts_dur(video_r['mdhd'])
        a_ts, a_dur = read_mdhd_ts_dur(audio_r['mdhd'])
        movie_ts = struct.unpack('>I', mvhd['payload'][12:16])[0]
        video_dur_movie = round(v_dur * movie_ts / v_ts)
        audio_dur_movie = round(a_dur * movie_ts / a_ts)
        overall_dur = max(video_dur_movie, audio_dur_movie)

        new_video_offsets = [None] * len(video_chunks)
        new_audio_offsets = [None] * len(audio_chunks)

        new_mdat_payload_size = meta_size + sum(size for _, size, _, _ in tagged)
        mdat_total_size = 8 + new_mdat_payload_size

        if mdat_total_size >= 2 ** 32:
            mdat_header = struct.pack('>I4sQ', 1, b'mdat', mdat_total_size + 8)
            new_mdat_header_len = 16
        else:
            mdat_header = struct.pack('>I4s', mdat_total_size, b'mdat')
            new_mdat_header_len = 8

        cursor = len(prefix) + new_mdat_header_len + meta_size
        for off, size, tag, idx in tagged:
            (new_video_offsets if tag == 'v' else new_audio_offsets)[idx] = cursor
            cursor += size

        assert None not in new_video_offsets and None not in new_audio_offsets

        new_video_stco = build_stco(new_video_offsets)
        new_audio_stco = build_stco(new_audio_offsets)

        def bx(d, key):
            return d[key]['full'] if key in d else b''

        video_stbl_payload = (
            bx(vr_stbl, b'stsd') + bx(vr_stbl, b'stts') + bx(vr_stbl, b'ctts') +
            bx(vr_stbl, b'stsc') + bx(vr_stbl, b'stsz') + new_video_stco + bx(vr_stbl, b'stss')
        )
        audio_stbl_payload = (
            bx(ar_stbl, b'stsd') + bx(ar_stbl, b'stts') +
            bx(ar_stbl, b'stsc') + bx(ar_stbl, b'stsz') + new_audio_stco
        )
        video_stbl_full = build_box(b'stbl', video_stbl_payload)
        audio_stbl_full = build_box(b'stbl', audio_stbl_payload)

        video_minfc = {c['type']: c for c in video_o['minfc']}
        audio_minfc = {c['type']: c for c in audio_o['minfc']}
        video_minf_full = build_box(
            b'minf', video_minfc[b'vmhd']['full'] + video_minfc[b'dinf']['full'] + video_stbl_full)
        audio_minf_full = build_box(
            b'minf', audio_minfc[b'smhd']['full'] + audio_minfc[b'dinf']['full'] + audio_stbl_full)

        video_mdia_full = build_box(
            b'mdia', patch_mdhd_duration(video_o['mdhd'], v_dur) + video_o['hdlr']['full'] + video_minf_full)
        audio_mdia_full = build_box(
            b'mdia', patch_mdhd_duration(audio_o['mdhd'], a_dur) + audio_o['hdlr']['full'] + audio_minf_full)

        video_trak_full = build_box(b'trak',
            patch_tkhd_duration(video_o['tkhd'], video_dur_movie) +
            (patch_elst_full_span(video_o['edts'], overall_dur) if video_o['edts'] else b'') +
            video_mdia_full)
        audio_trak_full = build_box(b'trak',
            patch_tkhd_duration(audio_o['tkhd'], audio_dur_movie) + audio_mdia_full)
        meta_trak_full = meta_o['trak']['full'] if meta_o else b''

        mvhd_full_new = build_box(b'mvhd', patch_u32(mvhd['payload'], 16, overall_dur))
        moov_full = build_box(
            b'moov', mvhd_full_new + udta_full + video_trak_full + audio_trak_full + meta_trak_full)

        with open(output_path, 'wb') as out_f:
            out_f.write(prefix)
            out_f.write(mdat_header)
            if meta_sample_bytes:
                out_f.write(meta_sample_bytes)
            for off, size, tag, idx in tagged:
                re_f.seek(off)
                _stream_copy(re_f, out_f, size, chunk_size)
            out_f.write(moov_full)

    return output_path


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="把第三方视频移植进大疆 Action 原生 MP4 容器结构")
    ap.add_argument("--ref", required=True, help="一个相机原生拍摄的参考 MP4 文件")
    ap.add_argument("--input", required=True, help="要导入的第三方视频文件")
    ap.add_argument("--output", required=True, help="输出文件路径（建议按 DJI_XXXX.MP4 命名）")
    ap.add_argument("--keep-temp", action="store_true", help="保留中间转码文件，便于排查问题")
    ap.add_argument("--crf", type=int, default=None,
                    help="使用 CRF 质量模式（推荐 23~28），体积通常比固定码率小 30%%-60%%")
    ap.add_argument("--max-bitrate", type=int, default=None,
                    help="手动限制视频峰值码率（bps），例如 20000000 表示 20Mbps")
    args = ap.parse_args()

    check_tools()

    ref_path = Path(args.ref)
    input_path = Path(args.input)
    output_path = Path(args.output)
    tmp_path = output_path.with_suffix(".reencoded_tmp.mp4")

    print(f"[1/3] 读取参考文件编码参数: {ref_path}")
    targets = get_ref_targets(ref_path)
    
    input_vb = get_input_video_bitrate(input_path)
    if input_vb > 0 and targets["video_bitrate"] > input_vb * 3 and args.crf is None:
        print(f"      提示：参考文件码率 {targets['video_bitrate']//1000}kbps 远高于输入文件 "
              f"{input_vb//1000}kbps，建议加 --crf 23 以减小体积")

    print(f"      目标规格: {targets['width']}x{targets['height']} @ {targets['fps']}fps, "
          f"音频 {targets['sample_rate']}Hz/{targets['channels']}ch")

    print(f"[2/3] 转码第三方视频: {input_path}")
    transcode(input_path, tmp_path, targets, show_progress=True, label=input_path.name,
              crf=args.crf, max_video_bitrate=args.max_bitrate)

    print(f"[3/3] 移植容器结构，生成最终文件: {output_path}")
    graft(ref_path, tmp_path, output_path)

    if not args.keep_temp:
        tmp_path.unlink(missing_ok=True)

    out_size = output_path.stat().st_size
    in_size = input_path.stat().st_size
    ratio = out_size / in_size if in_size > 0 else 0
    print(f"完成 ✅  输出文件: {output_path} ({out_size/1024/1024:.1f} MB, 体积比 {ratio:.2f}x)")
    print("下一步：复制到相机 microSD 卡的 DCIM/DJI_XXX 目录下，文件名改成符合相机命名规则的样式，"
          "装卡上机测试播放。")


if __name__ == "__main__":
    main()
