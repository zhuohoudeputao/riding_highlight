#!/usr/bin/env python3
"""riding_highlight.narration — 从 HUD/GPS 数据自动生成解说词

策略:
  1. 统计全程: 里程, 时长, 最高速, 均速
  2. 按过程分段: 每段生成一句 (起点/亮点)
  3. 输出: narration.json [{start, end, text}] + 拼接 TTS 文本
"""
import os
import sys
import json
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from .extract import load_json
from .clean import load_10hz, flag_noise, smooth_median, per_second
from .analyze import detect_processes
from .dash import buildup_hud


def ride_stats(hud, procs=None):
    """全程统计 (最高速限幅: GPS噪声剔除)"""
    spd = np.array(hud['speed_kmh'])
    valid = np.array(hud['valid'])
    spd_v = spd[valid & (spd > 0)]
    total_km = float(hud['distance_m'][-1] / 1000.0) if len(hud['distance_m']) else 0
    # 最高速: 取 p99.5 防止 GPS 噪声尖峰 (自行车下坡极限 ~75km/h)
    max_kmh = 0.0
    if len(spd_v):
        v99 = np.percentile(spd_v, 99.5)
        max_kmh = float(min(v99, 75.0))
    return {
        'total_km': total_km,
        'duration_min': len(spd) / 60.0,
        'max_kmh': max_kmh,
        'avg_kmh': float(spd_v.mean()) if len(spd_v) else 0,
        'max_alt_gain': float(np.max(hud['altitude']) - np.min(hud['altitude'])) if len(hud['altitude']) else 0,
    }


def gen_narration(gps, ride_name='骑行', style='default'):
    """生成解说词时间轴
    style: default | sporty | calm
    返回: {'intro': str, 'segments': [{start, end, text}], 'outro': str}
    """
    hud = buildup_hud(gps)
    stats = ride_stats(hud)

    # 过程检测 (用于分段解说)
    spd_raw, valid = load_10hz(gps)
    spd_med, _ = flag_noise(spd_raw, valid)
    spd_med = smooth_median(spd_med)
    sec, sec_v = per_second(spd_med, valid, 'first')
    sec_clean = sec.copy()
    sec_clean[~sec_v] = 0
    procs, _, _ = detect_processes(sec_clean, sec_v)

    if style == 'sporty':
        intro = (f'出发！全程 {stats["total_km"]:.1f} 公里，'
                 f'最高时速 {stats["max_kmh"]:.0f} 公里，'
                 f'平均 {stats["avg_kmh"]:.0f}。这段夜骑，一个字，爽。')
    elif style == 'calm':
        intro = (f'夜晚的骑行，{stats["duration_min"]:.0f} 分钟，'
                 f'{stats["total_km"]:.1f} 公里。'
                 f'风从耳边掠过，最高 {stats["max_kmh"]:.0f} 公里每小时。')
    else:
        intro = (f'这是{ride_name}，全程 {stats["total_km"]:.1f} 公里，'
                 f'耗时 {stats["duration_min"]:.0f} 分钟，'
                 f'平均速度 {stats["avg_kmh"]:.0f} 公里每小时，'
                 f'最高冲到 {stats["max_kmh"]:.0f}。')

    # 每段: 挑最精彩的 (时长>=30s)
    segs = []
    for a, b in procs:
        if b - a < 30:
            continue
        seg_spd = sec_clean[a:b]
        seg_spd = seg_spd[seg_spd > 5]
        if len(seg_spd) == 0:
            continue
        mx = min(float(np.percentile(seg_spd, 99)), 75.0)
        avg = seg_spd.mean()
        if mx >= 25:
            segs.append({
                'start': int(a),
                'end': int(b),
                'text': (f'这一段，平均 {avg:.0f} 公里每小时，'
                         f'最高 {mx:.0f}。')
            })
    if len(segs) > 3:
        segs = segs[:3]  # 保持简洁

    outro = ('保持热爱，继续前进。')
    return {'intro': intro, 'segments': segs, 'outro': outro, 'stats': stats}


def render_narration_json(gps_path, out_path, ride_name='骑行', style='default'):
    gps = load_json(gps_path)
    nar = gen_narration(gps, ride_name, style)
    with open(out_path, 'w') as f:
        json.dump(nar, f, ensure_ascii=False, indent=1)
    return nar


if __name__ == '__main__':
    gps_path = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1
                                  else '~/骑行剪辑/detect/GX010070.gps.json')
    nar = render_narration_json(gps_path, '/tmp/narration.json')
    print('解说词:')
    print('  [intro]', nar['intro'])
    for s in nar['segments']:
        print(f'  [{s["start"]//60}:{s["start"]%60:02d}-{s["end"]//60}:{s["end"]%60:02d}]', s['text'])
    print('  [outro]', nar['outro'])