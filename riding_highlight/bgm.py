#!/usr/bin/env python3
"""riding_highlight.bgm — 背景音乐混音

把一首背景乐铺满视频时长 (循环或拉伸), 压低音量混入/替换音轨。
用法:
  from riding_highlight.bgm import add_bgm
  add_bgm('video.mp4', 'bgm.mp3', 'out.mp4', bgm_volume=0.35, keep_original=0.5)
"""
import os
import subprocess


def add_bgm(video_path, bgm_path, out_path, bgm_volume=0.35,
            keep_original=0.5, crf=20, preset='medium', hwaccel='vaapi',
            loop=True, offset_sec=0):
    """给视频加背景音乐
    video_path: 视频 (保留画面+原声)
    bgm_path: 背景乐
    bgm_volume: 背景乐音量 (0-1)
    keep_original: 原声音量倍率 (0=替换, 1=原样)
    loop: 背景乐短于视频时循环
    返回: (成功, 输出路径)
    """
    # 探测时长
    def _dur(p):
        r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                            'format=duration', '-of',
                            'default=noprint_wrappers=1:nokey=1', p],
                           capture_output=True, text=True)
        return float(r.stdout.strip() or 0)
    vdur = _dur(video_path)
    bdur = _dur(bgm_path)

    # 背景乐处理: 循环到视频长度
    cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error']
    if hwaccel:
        cmd += ['-hwaccel', hwaccel]
    # 循环用 -stream_loop -1 (输入层循环, 避免 aloop 在静音点循环静音)
    if loop:
        cmd += ['-i', video_path, '-stream_loop', '-1', '-i', bgm_path]
        bgm_fc = (f'[1:a]atrim=0:{vdur + 2:.2f},'
                  f'volume={bgm_volume}[bgm]')
    else:
        cmd += ['-i', video_path, '-i', bgm_path]
        bgm_fc = (f'[1:a]atrim=0:{vdur + offset_sec + 2:.2f},'
                  f'volume={bgm_volume},apad[bgm]')
    # 延迟背景乐 (offset_sec)
    if offset_sec > 0:
        bgm_fc = bgm_fc.replace('[bgm]',
                                 f',adelay={int(offset_sec * 1000)}|{int(offset_sec * 1000)}[bgm]')

    # 原声保留或替换 (normalize=0 避免 amix 压音量)
    if keep_original > 0:
        fc = (f'{bgm_fc};'
              f'[0:a]volume={keep_original}[orig];'
              f'[orig][bgm]amix=inputs=2:duration=first:normalize=0:dropout_transition=3[aout]')
    else:
        fc = f'{bgm_fc};[bgm]aformat=sample_fmts=fltp:channel_layouts=stereo[aout]'

    cmd += ['-filter_complex', fc, '-map', '0:v', '-map', '[aout]',
            '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
            '-movflags', '+faststart', out_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return False, r.stderr[-300:]
    return True, out_path


if __name__ == '__main__':
    import sys
    video = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else
                               '/tmp/riding-test/seg_full_B1.mp4')
    bgm = os.path.expanduser(sys.argv[2] if len(sys.argv) > 2 else
                             '~/骑行剪辑/music/许巍 - 蓝莲花.flac')
    out = sys.argv[3] if len(sys.argv) > 3 else '/tmp/riding-test/bgm_test.mp4'
    ok, res = add_bgm(video, bgm, out, bgm_volume=0.35, keep_original=0.5)
    print(f'配乐: {"成功" if ok else "失败"} → {res}')