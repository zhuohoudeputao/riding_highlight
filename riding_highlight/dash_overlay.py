#!/usr/bin/env python3
"""riding_highlight.dash_overlay — 将 HUD 帧叠加到视频 (保留 alpha)

关键: HUD PNG 序列 (RGBA) 直接作为第二输入, overlay 在 filter 内完成,
      避免中间编码成 yuv420p 丢失 alpha 导致黑底盖住视频。
"""
import os
import subprocess
import tempfile

from .dash import render_hud_frames_composed


def overlay_hud_on_video(video_path, hud, start_sec=0, end_sec=None,
                         out_path=None, crf=20, preset='medium',
                         hwaccel='vaapi', tmp_dir=None):
    """预渲染 HUD 帧并叠加到视频 (保留透明, 不黑底)
    video_path: 源视频
    start_sec: HUD 数据中该视频片段的起始秒
    out_path: 输出 (默认 *_hud.mp4)
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

    # 1. 预渲染 HUD 合成帧 (RGBA PNG, 视频尺寸)
    scale = max(1.0, h / 1080.0)
    frames_dir = os.path.join(tmp, 'frames')
    n_frames = render_hud_frames_composed(
        hud, frames_dir, video_w=w, video_h=h,
        start_sec=start_sec, end_sec=start_sec + int(dur) + 1, scale=scale)
    if n_frames == 0:
        raise RuntimeError('无 HUD 帧')

    # 2. overlay: PNG序列(1fps) → fps放大 → overlay
    #    render 已按 start_sec 渲染绝对时间帧, HUD序列第0帧 = 视频第0秒,
    #    无需 tpad (之前 tpad 会把 HUD 再推后 start_sec 秒导致值静止/错位)
    in_cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error']
    if hwaccel:
        in_cmd += ['-hwaccel', hwaccel]
    in_cmd += ['-i', video_path,
               '-framerate', '1', '-i', os.path.join(frames_dir, 'composed_%06d.png')]
    # HUD: fps→30, 保持rgba (No tpad - 帧已按绝对时间渲染)
    hud_fc = '[1:v]fps=30,format=rgba[hud];'
    fc = (f'{hud_fc}'
          f'[0:v][hud]overlay=0:0:format=auto:shortest=1[out]')
    cmd = in_cmd + ['-filter_complex', fc, '-map', '[out]', '-map', '0:a?',
                    '-c:v', 'libx264', '-preset', preset, '-crf', str(crf),
                    '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart',
                    out_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'overlay 失败: {r.stderr[-500:]}')
    return out_path