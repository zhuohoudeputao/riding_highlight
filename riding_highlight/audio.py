#!/usr/bin/env python3
"""riding_highlight.audio — 配音合成 (解说TTS + 背景乐 + 原声混音)

流程:
  1. narration.gen_narration 生成解说词时间轴
  2. 每段 TTS → wav (外部 TTS 命令, 默认 Hermes kaltsit 或 edge)
  3. ffmpeg 混音: 原声 + 背景乐(低音量) + 解说(按时间点插入)
"""
import json
import os
import subprocess
import tempfile

from .narration import gen_narration


def tts_segment(text, out_wav, engine='hermes'):
    """生成一段 TTS 音频
    engine:
      hermes - 调用 hermes TTS (当前 provider: kaltsit)
      edge   - edge-tts (zh-CN-XiaoxiaoNeural)
    返回: wav 路径
    """
    if engine == 'edge':
        r = subprocess.run(['edge-tts', '--voice', 'zh-CN-XiaoxiaoNeural',
                            '--text', text, '--write-media', out_wav],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f'edge-tts 失败: {r.stderr[-200:]}')
        return out_wav
    # hermes: 通过 hermes CLI 或直接调用 TTS API
    # 方案: 用 hermes tts 子命令 (若存在)
    r = subprocess.run(['hermes', 'tts', '--text', text, '--out', out_wav],
                       capture_output=True, text=True)
    if r.returncode == 0 and os.path.exists(out_wav):
        return out_wav
    # 回退: 尝试直接调用 (若 hermes 无 tts 子命令则抛错由上层处理)
    raise RuntimeError('hermes tts 命令不可用, 请手动生成 TTS 音频')


def build_audio(narration, out_m4a, bg_music=None, tts_func=None,
                bg_volume=0.25, orig_volume=1.0, pad_ms=2000):
    """合成完整音轨: 原声 + 背景乐 + 解说
    narration: gen_narration 输出 (intro/segments/outro)
    bg_music: 背景乐路径 (可选)
    tts_func: callable(text) -> wav路径 (默认 tts_segment)
    返回: 输出路径 (未混视频的独立音轨, 供后续 mux)
    """
    tmp = tempfile.mkdtemp(prefix='rh_audio_')
    # 1. 生成 TTS 段
    tts = tts_func or (lambda t: tts_segment(t, os.path.join(tmp, 's.wav')))
    pieces = []  # [(wav, delay_ms)]
    delay = pad_ms
    intro_wav = tts(narration['intro'])
    pieces.append((intro_wav, delay))
    delay += pad_ms
    for seg in narration['segments']:
        seg_wav = tts(seg['text'])
        pieces.append((seg_wav, delay))
        delay += pad_ms
    outro_wav = tts(narration['outro'])
    pieces.append((outro_wav, delay))

    # 2. ffmpeg 混音 (无原声: 只有 TTS + 背景乐, 供"配音版")
    # 总时长 = 最后一段 TTS 结束 + 收尾静音
    # 先探测各 TTS 时长
    def _dur(p):
        r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                            'format=duration', '-of',
                            'default=noprint_wrappers=1:nokey=1', p],
                           capture_output=True, text=True)
        return float(r.stdout.strip() or 0)
    tts_durs = [_dur(w) for w, _ in pieces]
    total_ms = delay + int(tts_durs[-1] * 1000) + 1500  # 尾静音1.5s

    inputs = []
    fcs = []
    for i, (wav, d) in enumerate(pieces):
        inputs += ['-i', wav]
        fcs.append(f'[{i}:a]adelay={d}|{d},apad[tts{i}]')
    n_in = len(pieces)
    if bg_music:
        inputs += ['-i', bg_music]
        fcs.append(f'[{n_in}:a]atrim=0:{total_ms / 1000:.3f},volume={bg_volume},apad[bg]')
        mix_in = ''.join(f'[tts{i}]' for i in range(n_in)) + '[bg]'
        n_mix = n_in + 1
    else:
        mix_in = ''.join(f'[tts{i}]' for i in range(n_in))
        n_mix = n_in
    fcs.append(f'{mix_in}amix=inputs={n_mix}:duration=first:dropout_transition=3[aout]')
    fcs.append(f'[aout]atrim=0:{total_ms / 1000:.3f}[aout2]')
    cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error'] + inputs
    cmd += ['-filter_complex', ';'.join(fcs), '-map', '[aout2]',
            '-c:a', 'aac', '-b:a', '192k', out_m4a]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'混音失败: {r.stderr[-400:]}')
    return out_m4a


def mux_audio(video_path, audio_path, out_path, crf=20, preset='medium'):
    """把合成音轨混入视频 (替换原声)"""
    cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
           '-i', video_path, '-i', audio_path,
           '-map', '0:v', '-map', '1:a',
           '-c:v', 'libx264', '-preset', preset, '-crf', str(crf),
           '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart',
           out_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'mux失败: {r.stderr[-300:]}')
    return out_path


if __name__ == '__main__':
    import sys
    gps_path = os.path.expanduser(sys.argv[1]) if len(sys.argv) > 1 else \
        '~/骑行剪辑/detect/GX010070.gps.json'
    from .extract import load_json
    gps = load_json(gps_path)
    nar = gen_narration(gps, '夜骑')
    print(json.dumps(nar, ensure_ascii=False, indent=1)[:500])
    print('\n使用说明: tts_segment() 依赖 hermes tts 或 edge-tts')