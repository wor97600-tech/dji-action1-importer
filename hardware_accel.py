"""Optional Windows H.264 encoders; no changes to graft or preview handling."""
import json
import re
from process_utils import hidden_process_options
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

ENCODERS = {
    'h264_nvenc': 'NVIDIA NVENC',
    'h264_qsv': 'Intel Quick Sync',
    'h264_amf': 'AMD AMF',
}


def video_options(encoder, targets, max_video_bitrate):
    bitrate = max_video_bitrate or targets['video_bitrate']
    # The GPU path uses bitrate control: x264 CRF is not portable to these APIs.
    opts = ['-c:v', encoder, '-profile:v', 'high', '-level', str(targets['level']/10),
            '-tag:v', 'avc1', '-bf', '0', '-refs', '1', '-pix_fmt', 'nv12',
            '-g', str(max(1, round(float(Fraction(targets['fps'])) * 2))),
            '-b:v', str(bitrate), '-maxrate', str(bitrate), '-bufsize', str(bitrate*2),
            '-bsf:v', 'filter_units=remove_types=6']
    if encoder == 'h264_nvenc':
        opts += ['-preset', 'p4', '-rc', 'vbr', '-coder', 'cabac',
                 '-rc-lookahead', '0', '-b_ref_mode', 'disabled', '-aud', '0',
                 '-dpb_size', '1']
    elif encoder == 'h264_qsv':
        opts += ['-preset', 'medium', '-look_ahead', '0',
                 '-adaptive_i', '0', '-adaptive_b', '0', '-b_strategy', '0',
                 '-idr_interval', '0', '-cavlc', '0', '-aud', '0', '-repeat_pps', '0']
    elif encoder == 'h264_amf':
        opts += ['-usage', 'transcoding', '-quality', 'balanced',
                 '-rc', 'vbr_peak', '-coder', 'cabac']
    else:
        raise ValueError('Unknown hardware encoder: ' + encoder)
    return opts


def probe_encoder(ffmpeg, encoder, targets, max_video_bitrate):
    """Actually initialize hardware with the requested dimensions and rate."""
    cmd = [str(ffmpeg), '-hide_banner', '-v', 'error', '-f', 'lavfi', '-i',
           f"color=s={targets['width']}x{targets['height']}:r={targets['fps']}",
           '-frames:v', '4', *video_options(encoder, targets, max_video_bitrate),
           '-f', 'null', '-']
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=20, **hidden_process_options())
        reason = result.stderr.decode('utf-8', errors='replace').strip()
        return result.returncode == 0, (reason.splitlines() or ['编码器初始化失败'])[0][:250]
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def run_conversion(cmd, duration, label, progress_callback, show_progress):
    from dji_graft import run_ffmpeg_with_progress, run
    if progress_callback is not None or show_progress:
        run_ffmpeg_with_progress(cmd, duration, label, progress_callback)
    else:
        result = run(cmd)
        if result.returncode:
            raise RuntimeError(result.stderr[-2000:])


def normalize_amf_headers(ffmpeg, source, output, targets):
    """Keep the camera-confirmed AMD path using the same filter chain."""
    return normalize_hardware_headers(ffmpeg, source, output, targets, 'h264_amf')


def normalize_hardware_headers(ffmpeg, source, output, targets, encoder):
    """Move complete SPS/PPS to avcC without re-encoding coded pictures.

    Some AMF drivers return global extradata without VUI timing, while the
    first IDR carries a different, complete SPS with the same parameter ID.
    Put complete initialization data before the IDR for camera compatibility.
    Do not copy x264/reference SPS: those describe different coded slices.
    """
    vendor = ENCODERS[encoder]
    filters = ('h264_mp4toannexb,'
               'h264_metadata=zero_new_constraint_set_flags=1:aud=remove,'
               'extract_extradata=remove=1')
    cmd = [str(ffmpeg), '-v', 'error', '-y', '-i', str(source),
           '-map', '0:v:0', '-map', '0:a:0', '-c', 'copy', '-bsf:v', filters,
           '-video_track_timescale', str(targets['video_timescale']),
           '-movflags', '+faststart', str(output)]
    result = subprocess.run(cmd, capture_output=True, **hidden_process_options())
    if result.returncode:
        raise RuntimeError(vendor + ' 码流头整理失败：' +
                           result.stderr.decode('utf-8', errors='replace')[-1500:])
    validate_hardware_headers(ffmpeg, output, targets, encoder)


def validate_hardware_headers(ffmpeg, output, targets, encoder):
    """Inspect actual SPS; ffprobe refs may be one even when SPS declares two."""
    vendor = ENCODERS[encoder]
    # A successful mux and ffprobe frame rate alone missed the original bug.
    # Check the actual global SPS before the result reaches the DJI graft.
    result = subprocess.run([str(ffmpeg), '-v', 'verbose', '-i', str(output),
        '-map', '0:v:0', '-c', 'copy', '-bsf:v', 'trace_headers',
        '-frames:v', '1', '-f', 'null', '-'], capture_output=True, timeout=30, **hidden_process_options())
    header = result.stderr.decode('utf-8', errors='replace').split('Packet:', 1)[0]
    def field(name):
        match = re.search(r'\b' + name + r'\s+[01]+ = (\d+)', header)
        return int(match[1]) if match else None
    tick, scale = field('num_units_in_tick'), field('time_scale')
    if (result.returncode or field('timing_info_present_flag') != 1
            or not tick or not scale
            or Fraction(scale, tick) != Fraction(targets['fps']) * 2
            or field('constraint_set4_flag') != 0
            or field('constraint_set5_flag') != 0):
        raise RuntimeError(vendor + ' 全局 SPS 头未通过帧率/兼容标志检查')
    if encoder == 'h264_nvenc':
        # Do not rewrite these values in a finished bitstream: the encoder
        # must generate compliant pictures. Reject and fall back if it did not.
        def values(name):
            return [int(v) for v in re.findall(
                r'\b' + name + r'\s+[01]+ = (\d+)', header)]
        refs = values('max_num_ref_frames')
        buffers = values('max_dec_frame_buffering')
        reorder = values('max_num_reorder_frames')
        if (not refs or any(v > 1 for v in refs)
                or not buffers or any(v > 1 for v in buffers)
                or not reorder or any(v != 0 for v in reorder)):
            raise RuntimeError('NVIDIA SPS 参考帧/解码缓冲不符合单帧要求：'
                f'refs={refs}, dpb={buffers}, reorder={reorder}；拒绝移植该硬件结果')


def validate_output(ffprobe, output, targets):
    result = subprocess.run([str(ffprobe), '-v', 'error', '-show_streams',
        '-of', 'json', str(output)], capture_output=True, timeout=20, check=True, **hidden_process_options())
    streams = json.loads(result.stdout)['streams']
    video = next(s for s in streams if s['codec_type'] == 'video')
    audio = next(s for s in streams if s['codec_type'] == 'audio')
    expected_ts = int(targets['video_timescale'])
    if (video['codec_name'] != 'h264' or video['pix_fmt'] != 'yuv420p'
            or video['profile'] != 'High' or video['has_b_frames'] != 0
            or video.get('refs', 1) > 1 or video['level'] > targets['level']
            or video['width'] != targets['width'] or video['height'] != targets['height']
            or Fraction(video['time_base']) != Fraction(1, expected_ts)
            or abs(float(Fraction(video['r_frame_rate']) - Fraction(targets['fps']))) > 0.001
            or audio['codec_name'] != 'aac' or int(audio['sample_rate']) != targets['sample_rate']
            or audio['channels'] != targets['channels']):
        raise RuntimeError('硬件输出不满足参考视频的编码、分辨率或时间基要求')


def try_hardware(input_path, out_path, targets, ffmpeg, ffprobe, acceleration,
                 max_video_bitrate, duration, label, progress_callback, show_progress, status):
    if acceleration not in ('auto', *ENCODERS):
        raise ValueError('未知显卡加速选项：' + str(acceleration))
    if not targets.get('video_timescale'):
        status('参考视频时间基未知，使用原版 CPU 编码。')
        return False
    candidates = list(ENCODERS) if acceleration == 'auto' else [acceleration]
    for encoder in candidates:
        status('检测 ' + ENCODERS[encoder] + ' ...')
        available, reason = probe_encoder(ffmpeg, encoder, targets, max_video_bitrate)
        if not available:
            status(ENCODERS[encoder] + ' 不可用：' + reason)
            continue
        status('使用 ' + ENCODERS[encoder] + ' 硬件编码（按码率控制，CRF 不参与）。')
        # Encode in a private directory: failures cannot leak a partial output
        # into the graft stage or replace an existing valid output.
        with tempfile.TemporaryDirectory(prefix='dji_gpu_', dir=Path(out_path).parent) as folder:
            temporary = Path(folder) / 'encoded.mp4'
            cmd = [str(ffmpeg), '-y', '-i', str(input_path), '-vf',
                   f"scale={targets['width']}:{targets['height']}:flags=lanczos,"
                   f"fps={targets['fps']},format=yuv420p",
                   *video_options(encoder, targets, max_video_bitrate),
                   '-c:a', 'aac', '-ar', str(targets['sample_rate']), '-ac', str(targets['channels']),
                   '-b:a', str(max(targets['audio_bitrate'], 128000)),
                   '-video_track_timescale', str(targets['video_timescale']),
                   '-movflags', '+faststart', str(temporary)]
            try:
                run_conversion(cmd, duration, label, progress_callback, show_progress)
                status('整理 ' + ENCODERS[encoder] + ' 相机兼容码流头（不重新编码画面和音频）...')
                normalized = Path(folder) / 'normalized.mp4'
                if encoder == 'h264_amf':
                    normalize_amf_headers(ffmpeg, temporary, normalized, targets)
                else:
                    normalize_hardware_headers(ffmpeg, temporary, normalized, targets, encoder)
                normalized.replace(temporary)
                validate_output(ffprobe, temporary, targets)
                temporary.replace(out_path)
                status('硬件编码完成：' + ENCODERS[encoder])
                return True
            except (RuntimeError, OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError) as exc:
                status(ENCODERS[encoder] + ' 编码或校验失败：' + str(exc)[-500:])
                if progress_callback is not None:
                    progress_callback(0)
    status('无可用硬件编码结果，自动回退原版 CPU 编码。')
    return False
