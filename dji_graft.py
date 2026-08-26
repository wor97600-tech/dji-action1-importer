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
"""
import argparse
import json
import shutil
import struct
import subprocess
import sys
import threading
from pathlib import Path

from box_tools import read_box_list, find_box, build_box, parse_hdlr_type


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
    import os
    import shutil
    import sys

    # 如果是打包后的 EXE，获取 EXE 所在目录；否则用当前工作目录
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.getcwd()

    # 检查 ffmpeg 和 ffprobe
    for tool in ("ffmpeg", "ffprobe"):
        # 1. 先看同目录下是否有对应的 .exe 文件
        local_path = os.path.join(base_dir, tool + ".exe")
        if os.path.isfile(local_path):
            # 将该目录临时添加到 PATH 中（让 subprocess 能找到）
            os.environ["PATH"] = base_dir + os.pathsep + os.environ.get("PATH", "")
            continue  # 找到了，继续检查下一个
        # 2. 如果同目录没有，再检查系统 PATH
        if shutil.which(tool) is None:
            print(f"错误：未找到 {tool}，请安装 ffmpeg 并添加到 PATH，或将 {tool}.exe 放在本程序同目录。", file=sys.stderr)
            sys.exit(1)

# --------------------------------------------------------------------------
# 第一步：读取参考文件的目标编码参数，转码第三方视频
# --------------------------------------------------------------------------
def get_ref_targets(ref_path):
    info = ffprobe_json(ref_path)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next(s for s in info["streams"] if s["codec_type"] == "audio")
    fr = v["r_frame_rate"]  # e.g. "60000/1001"
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
    # "HH:MM:SS.microseconds"
    try:
        h, m, sec = s.split(":")
        return int(h) * 3600 + int(m) * 60 + float(sec)
    except ValueError:
        return None


def run_ffmpeg_with_progress(cmd, total_duration, label=""):
    """执行 ffmpeg 命令，并在同一行打印可刷新的进度条。"""
    cmd = cmd[:-1] + ["-progress", "pipe:1", "-nostats"] + [cmd[-1]]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding="utf-8", errors="replace", bufsize=1)

    # ffmpeg 平时的日志走 stderr，输出量很大，如果没人读会把管道缓冲区塞满，
    # 导致 ffmpeg 卡住写不出去、我们又在等它退出——互相等待，程序假死。
    # 用一个后台线程持续把 stderr 读走（只是丢弃/缓存，不占什么 CPU）。
    stderr_chunks = []

    def _drain_stderr():
        for chunk in proc.stderr:
            stderr_chunks.append(chunk)

    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()

    last_line = ""
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("out_time="):
            secs = _parse_time_str(line.split("=", 1)[1])
            if secs is not None:
                if total_duration > 0:
                    bar = format_bar(secs / total_duration * 100)
                else:
                    bar = f"{secs:6.1f}s"
                last_line = f"    {label} {bar}"
                print(f"\r{last_line}", end="", flush=True)
        elif line.startswith("progress=") and line.endswith("end"):
            print(f"\r    {label} {format_bar(100)}", flush=True)

    proc.wait()
    t.join(timeout=5)
    if proc.returncode != 0:
        print()  # 换行，避免报错信息和进度条粘在一起
        raise RuntimeError(f"ffmpeg 失败:\n{''.join(stderr_chunks)[-3000:]}")


def transcode(input_path, out_path, targets, show_progress=True, label=""):
    vb = targets["video_bitrate"]
    ab = max(targets["audio_bitrate"], 128_000)
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-vf", f"scale={targets['width']}:{targets['height']}:flags=lanczos,"
               f"fps={targets['fps']},format=yuv420p",
        "-c:v", "libx264", "-profile:v", "high", "-level", str(targets["level"] / 10),
        "-tag:v", "avc1",
        # 保守码流结构：单参考帧、不用 B 帧、关闭多余 SEI —— 这是运动相机
        # 硬件解码芯片能稳定解码的关键。
        "-x264-params", "ref=1:bframes=0:b-adapt=0:scenecut=0:cabac=1:aud=0",
        "-bsf:v", "filter_units=remove_types=6",
        "-b:v", str(vb), "-maxrate", str(int(vb * 1.15)), "-bufsize", str(int(vb * 1.15)),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", str(targets["sample_rate"]), "-ac", str(targets["channels"]),
        "-b:a", str(ab),
        "-movflags", "+faststart",
        str(out_path),
    ]
    if show_progress:
        total_duration = get_duration_seconds(input_path)
        run_ffmpeg_with_progress(cmd, total_duration, label=label)
    else:
        r = run(cmd)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg 转码失败:\n{r.stderr[-3000:]}")


# --------------------------------------------------------------------------
# 第二步：box 级别解析辅助函数
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
        return edts_box['full']  # version1 edts 不处理，原样保留
    p2 = p[:8] + struct.pack('>I', new_dur) + p[12:]
    return build_box(b'edts', build_box(b'elst', p2))


# --------------------------------------------------------------------------
# 第三步：主移植逻辑
# --------------------------------------------------------------------------
def graft(ref_path, reencoded_path, output_path):
    ref_data = open(ref_path, 'rb').read()
    ref_top = read_box_list(ref_data)

    ftyp_full = find_box(ref_top, b'ftyp')['full']
    wide_box = find_box(ref_top, b'wide')
    wide_full = wide_box['full'] if wide_box else b''
    prefix = ftyp_full + wide_full
    mdat_ref = find_box(ref_top, b'mdat')
    mdat_header_len = mdat_ref['payload_start'] - mdat_ref['start']
    meta_sample_start = len(prefix) + mdat_header_len
    if meta_sample_start != mdat_ref['payload_start']:
        raise RuntimeError("参考文件的 ftyp/wide/mdat 布局和预期不符，无法安全保留 DJI.Meta 偏移")

    moov = find_box(ref_top, b'moov')
    moov_children = read_box_list(moov['payload'])
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
    meta_o = trak_info.get(b'meta')  # DJI.Meta 轨道，可能不存在

    meta_sample_bytes = b''
    meta_size = 0
    if meta_o is not None:
        meta_stbl_children = read_box_list(meta_o['stbl']['payload'])
        sp = find_box(meta_stbl_children, b'stsz')['payload']
        sample_size, _count = struct.unpack('>II', sp[4:12])
        meta_size = sample_size if sample_size != 0 else struct.unpack('>I', sp[12:16])[0]
        meta_sample_bytes = ref_data[meta_sample_start:meta_sample_start + meta_size]

    # ---- 读取转码后文件 ----
    re_data = open(reencoded_path, 'rb').read()
    re_top = read_box_list(re_data)
    re_moov = find_box(re_top, b'moov')
    re_moov_children = read_box_list(re_moov['payload'])
    re_traks = [b for b in re_moov_children if b['type'] == b'trak']
    re_trak_info = {}
    for t in re_traks:
        info = parse_trak(t)
        re_trak_info[info['htype']] = info
    video_r, audio_r = re_trak_info[b'vide'], re_trak_info[b'soun']
    vr_stbl, ar_stbl = get_stbl_children(video_r), get_stbl_children(audio_r)

    video_chunks = compute_chunk_byte_ranges(vr_stbl)
    audio_chunks = compute_chunk_byte_ranges(ar_stbl)

    tagged = [(off, size, 'v', i) for i, (off, size) in enumerate(video_chunks)]
    tagged += [(off, size, 'a', i) for i, (off, size) in enumerate(audio_chunks)]
    tagged.sort(key=lambda x: x[0])

    new_video_offsets = [None] * len(video_chunks)
    new_audio_offsets = [None] * len(audio_chunks)
    cursor = meta_sample_start + meta_size
    mdat_pieces = [meta_sample_bytes]
    for off, size, tag, idx in tagged:
        mdat_pieces.append(re_data[off:off + size])
        (new_video_offsets if tag == 'v' else new_audio_offsets)[idx] = cursor
        cursor += size
    new_mdat_payload = b''.join(mdat_pieces)
    assert None not in new_video_offsets and None not in new_audio_offsets

    new_video_stco = build_stco(new_video_offsets)
    new_audio_stco = build_stco(new_audio_offsets)

    # ---- 时长计算 ----
    v_ts, v_dur = read_mdhd_ts_dur(video_r['mdhd'])
    a_ts, a_dur = read_mdhd_ts_dur(audio_r['mdhd'])
    movie_ts = struct.unpack('>I', mvhd['payload'][12:16])[0]
    video_dur_movie = round(v_dur * movie_ts / v_ts)
    audio_dur_movie = round(a_dur * movie_ts / a_ts)
    overall_dur = max(video_dur_movie, audio_dur_movie)

    mvhd_full_new = build_box(b'mvhd', patch_u32(mvhd['payload'], 16, overall_dur))
    video_tkhd_new = patch_tkhd_duration(video_o['tkhd'], video_dur_movie)
    audio_tkhd_new = patch_tkhd_duration(audio_o['tkhd'], audio_dur_movie)
    video_mdhd_new = patch_mdhd_duration(video_o['mdhd'], v_dur)
    audio_mdhd_new = patch_mdhd_duration(audio_o['mdhd'], a_dur)
    video_edts_new = patch_elst_full_span(video_o['edts'], overall_dur) if video_o['edts'] else b''

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
        b'mdia', video_mdhd_new + video_o['hdlr']['full'] + video_minf_full)
    audio_mdia_full = build_box(
        b'mdia', audio_mdhd_new + audio_o['hdlr']['full'] + audio_minf_full)

    video_trak_full = build_box(b'trak', video_tkhd_new + video_edts_new + video_mdia_full)
    audio_trak_full = build_box(b'trak', audio_tkhd_new + audio_mdia_full)
    meta_trak_full = meta_o['trak']['full'] if meta_o else b''

    moov_full = build_box(
        b'moov', mvhd_full_new + udta_full + video_trak_full + audio_trak_full + meta_trak_full)
    mdat_full = build_box(b'mdat', new_mdat_payload)

    final_bytes = prefix + mdat_full + moov_full
    Path(output_path).write_bytes(final_bytes)
    return output_path


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="把第三方视频移植进大疆 Action 原生 MP4 容器结构")
    ap.add_argument("--ref", required=True, help="一个相机原生拍摄的参考 MP4 文件")
    ap.add_argument("--input", required=True, help="要导入的第三方视频文件")
    ap.add_argument("--output", required=True, help="输出文件路径（建议按 DJI_XXXX.MP4 命名）")
    ap.add_argument("--keep-temp", action="store_true", help="保留中间转码文件，便于排查问题")
    args = ap.parse_args()

    check_tools()

    ref_path = Path(args.ref)
    input_path = Path(args.input)
    output_path = Path(args.output)
    tmp_path = output_path.with_suffix(".reencoded_tmp.mp4")

    print(f"[1/3] 读取参考文件编码参数: {ref_path}")
    targets = get_ref_targets(ref_path)
    print(f"      目标规格: {targets['width']}x{targets['height']} @ {targets['fps']}fps, "
          f"音频 {targets['sample_rate']}Hz/{targets['channels']}ch")

    print(f"[2/3] 转码第三方视频（保守码流结构，兼容硬件解码器）: {input_path}")
    transcode(input_path, tmp_path, targets, show_progress=True, label=input_path.name)

    print(f"[3/3] 移植容器结构，生成最终文件: {output_path}")
    graft(ref_path, tmp_path, output_path)

    if not args.keep_temp:
        tmp_path.unlink(missing_ok=True)

    print(f"完成 ✅  输出文件: {output_path}")
    print("下一步：复制到相机 microSD 卡的 DCIM/DJI_XXX 目录下，文件名改成符合相机命名规则的样式，"
          "装卡上机测试播放。")


if __name__ == "__main__":
    main()
