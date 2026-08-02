#!/usr/bin/env python3
"""riding_highlight.dash_overlay — 将 HUD 帧叠加到视频

流程:
  1. dash.render_hud_frames_composed 预渲染合成帧 (1fps, 视频尺寸)
  2. ffmpeg: 主视频 + HUD帧视频 → overlay (HUD 起始秒对齐)

用法 (模块):
  from riding_highlight import dash as D
  from riding_highlight.dash_overlay import overlay_hud_on_video
  hud = D.buildup_hud(gps)
  overlay_hud_on_video('seg.mp4', hud, start_sec=0, out='seg_hud.mp4')
"""
import os
import subprocess
import tempfile

from .dash import render_hud_frames_composed


def overlay_hud_on_video(video_path, hud, start_sec=0, end_sec=None,
                         out_path=None, crf=20, preset='medium',
                         hwaccel='vaapi', tmp_dir=None):
    """预渲染 HUD 帧并叠加到视频
    video_path: 源视频 (需与 hud 数据时间对齐: 视频第0秒 = hud[start_sec])
    start_sec: HUD 数据中该视频片段的起始秒
    out_path: 输出 (默认 video_path 同目录 *_hud.mp4)
    返回: 输出路径
    """
    if out_path is None:
        base, ext = os.path.splitext(video_path)
        out_path = base + '_hud' + ext
    tmp = tmp_dir or tempfile.mkdtemp(prefix='hud_')
    # 探测视频尺寸/时长
    probe = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'stream=width,height', '-of', 'csv=s=x:p=0',
         video_path], capture_output=True, text=True).stdout.strip()
    w, h = probe.split('x')
    w, h = int(w), int(h)
    dur = float(subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
        capture_output=True, text=True).stdout.strip())

    # 1. 预渲染合成帧 (覆盖视频时长)
    scale = max(1.0, h / 1080.0)  # 4K→2.0, 1080p→1.0
    n_frames = render_hud_frames_composed(
        hud, os.path.join(tmp, 'frames'), video_w=w, video_h=h,
        start_sec=start_sec, end_sec=start_sec + int(dur) + 1, scale=scale)
    if n_frames == 0:
        raise RuntimeError('无 HUD 帧')

    # 2. HUD 帧序列 → 视频 (1fps), 前面 pad 到 start_sec
    hud_seq = os.path.join(tmp, 'hud_seq.mp4')
    pad = start_sec
    cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
           '-framerate', '1', '-i', os.path.join(tmp, 'frames', 'composed_%06d.png')]
    # 用 filter 处理: 放大到30fps + 起始 pad
    fc = (f'[0:v]fps=30,format=rgba'
          + (f',tpad=start_duration={pad}:start_mode=clone' if pad > 0 else '')
          + f'[hud]')
    cmd += ['-filter_complex', fc, '-map', '[hud]',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '30',
            '-pix_fmt', 'yuv420p', hud_seq]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'HUD 序列失败: {r.stderr[-300:]}')

    # 3. overlay
    cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error']
    if hwaccel:
        cmd += ['-hwaccel', hwaccel]
    cmd += ['-i', video_path, '-i', hud_seq,
            '-filter_complex', '[0:v][1:v]overlay=0:0:format=auto[out]',
            '-map', '[out]', '-map', '0:a?',
            '-c:v', 'libx264', '-preset', preset, '-crf', str(crf),
            '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart',
            out_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'overlay 失败: {r.stderr[-400:]}')
    return out_path