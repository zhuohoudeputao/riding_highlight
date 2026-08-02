#!/usr/bin/env python3
"""riding_highlight.render — ffmpeg 渲染 (分段提取 + concat)

硬件加速仅用于输入侧 (-hwaccel vaapi); 输出用 libx264 软件路径
(VAAPI 帧上 fps 丢帧不可靠)。可选 -hwaccel cuda/auto。
"""
import json
import os
import subprocess
import tempfile


def extract_seg(src, start_sec, duration, dest, crf=20, preset='medium',
                hwaccel='vaapi', scale='1920:1080', extra_vf=''):
    """输入级 seek 提取单段
    src: 视频文件
    start_sec/duration: 秒
    返回: bool
    """
    vf = f'scale={scale}' + (f',{extra_vf}' if extra_vf else '')
    cmd = ['ffmpeg', '-y', '-hide_banner']
    if hwaccel:
        cmd += ['-hwaccel', hwaccel]
    cmd += ['-ss', f'{start_sec:.3f}', '-i', src, '-t', f'{duration:.3f}',
            '-vf', vf,
            '-c:v', 'libx264', '-preset', preset, '-crf', str(crf),
            '-c:a', 'aac', '-b:a', '192k',
            '-movflags', '+faststart', dest]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return r.stderr[-300:]
    return None


def render_edl(edl, video_dir, out_path, crf=20, preset='medium',
               hwaccel='vaapi', scale='1920:1080', extra_vf='',
               tmp_dir=None):
    """渲染 EDL: 逐段提取 → concat 拼接
    edl: [{file, start, end}, ...]
    video_dir: 视频所在目录
    out_path: 输出 mp4
    返回: (ok, 时长秒)
    """
    if not edl:
        return False, 0
    tmp = tmp_dir or tempfile.mkdtemp(prefix='riding_')
    seg_files = []
    stop_ok = []
    for i, seg in enumerate(edl):
        f, s, e = seg['file'], seg['start'], seg['end']
        # 尝试 .MP4 或 .mp4
        candidate = os.path.join(video_dir, f + '.MP4')
        if not os.path.exists(candidate):
            candidate = os.path.join(video_dir, f + '.mp4')
            if not os.path.exists(candidate):
                print(f'  段{i} 源不存在: {f}')
                return False, 0
        dest = os.path.join(tmp, f'seg_{i:03d}.mp4')
        err = extract_seg(candidate, s, e - s, dest, crf, preset, hwaccel,
                          scale, extra_vf)
        if err:
            print(f'  段{i}失败 {f}@{s}: {err}')
            return False, 0
        seg_files.append(dest)
        stop_ok.append((f, s, e))
    # concat
    lst = os.path.join(tmp, 'concat.lst')
    with open(lst, 'w') as f:
        for p in seg_files:
            f.write(f"file '{p}'\n")
    r = subprocess.run(['ffmpeg', '-y', '-hide_banner', '-f', 'concat', '-safe', '0',
                        '-i', lst, '-c', 'copy', '-movflags', '+faststart', out_path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return False, 0
    dur = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                          'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
                          out_path],
                         capture_output=True, text=True).stdout.strip()
    return True, float(dur) if dur else 0.0