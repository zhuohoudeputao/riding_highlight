#!/usr/bin/env python3
"""riding_highlight.plot — 速度-时间曲线 + 选段标注

颜色体系:
  🔵 速度曲线      🟥 停车段(真实)   ⬜ GPS失锁(nan)
  🟩 高速段(>=25)  🟧 25阈值          🔴 加速度副轴(1Hz)
  深蓝时间线条 = 视频选段 (剪辑软件风格)
"""
import json
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager


def _setup_cjk():
    # 优先精确匹配 Noto Sans CJK SC 字体文件
    for f in font_manager.findSystemFonts():
        if 'NotoSansCJK' in f and 'SC' in f:
            font_manager.fontManager.addfont(f)
    plt.rcParams['font.sans-serif'] = ['Noto Sans CJK SC', 'Noto Sans CJK HK',
                                       'Noto Sans CJK JP', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False


SPEED_THRESH = 25.0


def load_gps(path):
    """载入 gps JSON → (single_sec_speed, acc, static_segs, frozen_segs)"""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from .clean import load_10hz, flag_noise, smooth_median, per_second, accel_1hz
    from .extract import load_json
    gps = load_json(path)
    spd_raw, valid = load_10hz(gps)
    spd_med, _ = flag_noise(spd_raw, valid)
    spd_med = smooth_median(spd_med)
    sec, sec_v = per_second(spd_med, valid, 'first')
    sec[~sec_v] = np.nan
    acc = accel_1hz(sec, sec_v)
    return sec, acc, gps['static_segs'], gps['frozen_segs']


def draw(ride_name, file_desc, edl, out_path, figsize=(16, 5.5)):
    """绘制单文件或合并速度曲线
    file_desc: [(label, files, detect_dir)]  单文件: [(fname, [fname], detect_dir)]
    edl: 选段列表 [{file, start, end}]
    """
    _setup_cjk()
    fig, ax = plt.subplots(figsize=figsize)

    # 图例占位 (真实曲线后覆盖)
    ax.plot([], [], color='#4472C4', lw=1, label='速度 (km/h)')
    ax.axvspan(0, 0, color='red', alpha=0.25, label='停车段')
    ax.axvspan(0, 0, color='gray', alpha=0.35, label='GPS失锁')
    ax.axhline(SPEED_THRESH, color='orange', ls='--', lw=1,
               label=f'{SPEED_THRESH} km/h 阈值')

    # 遍历文件
    all_ts, all_spd, all_acc = [], [], []
    offset = 0.0
    boundaries = []
    for label, files, ddir in _flatten(file_desc):
        for fname in files:
            gpath = os.path.join(ddir, fname + '.gps.json')
            if not os.path.exists(gpath):
                print(f'  [跳过] 无 {gpath}')
                offset += 0
                continue
            sec, acc, stops, frozen = load_gps(gpath)
            n = len(sec)
            ts = np.arange(n) + offset
            all_ts.append(ts); all_spd.append(sec); all_acc.append(acc)
            for a, b in stops:
                ax.axvspan(offset + a, offset + b, color='red', alpha=0.25)
            for a, b in frozen:
                ax.axvspan(offset + a, offset + b, color='gray', alpha=0.35)
            offset += n
            boundaries.append(offset)
            # 给 EDL 赋该文件偏移 (用于时间线条)
            for e in edl:
                if e['file'] == fname and '_offset' not in e:
                    e['_offset'] = offset - n

    # 主体速度曲线
    if all_ts:
        ax.plot(np.concatenate(all_ts), np.concatenate(all_spd),
                lw=0.8, color='#4472C4')
    # 加速度副轴 (1Hz)
    ax2 = ax.twinx()
    if all_acc:
        ax2.fill_between(np.concatenate(all_ts), np.concatenate(all_acc), 0,
                         color='red', alpha=0.10)
        ax2.plot(np.concatenate(all_ts), np.concatenate(all_acc),
                 color='#C00000', lw=0.5, alpha=0.8, label='|加速度| m/s²')
    ax2.axhline(4.0, color='purple', ls=':', lw=1, label='物理上限 4 m/s²')
    ax2.set_ylabel('|加速度| (m/s²)')
    ax2.set_ylim(0, 10)

    # 视频选段时间线条 (顶部)
    if edl:
        _draw_timeline(ax, edl, offset)

    # 合并文件边界虚线
    for b in boundaries[:-1]:
        ax.axvline(b, color='gray', ls=':', lw=1)

    # 轴标签
    ax.set_ylim(0, 54)
    step = 60
    ticks = np.arange(0, offset + step, step)
    ax.set_xticks(ticks)
    ax.set_xticklabels([f'{int(v // 60)}:{int(v % 60):02d}' for v in ticks],
                       fontsize=7, rotation=45)
    ax.set_xlabel('时间 (分:秒)')
    ax.set_ylabel('速度 (km/h)')
    ax.set_title(f'{ride_name} 速度-时间曲线')
    lines1, lab1 = ax.get_legend_handles_labels()
    lines2, lab2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, lab1 + lab2, loc='upper right', fontsize=7)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    print(f'保存: {out_path}')


def _draw_timeline(ax, edl, total_sec):
    """顶部时间线条: 未选段灰, 选段深蓝 + 时长"""
    ax.barh(51.0, total_sec, left=0, height=2.2, color='#D9D9D9',
            edgecolor='none', zorder=1)
    for i, e in enumerate(edl):
        a, b = e.get('_offset', 0) + e['start'], e.get('_offset', 0) + e['end']
        ax.barh(51.0, b - a, left=a, height=2.2, color='#1F4E79',
                edgecolor='none', zorder=2)
        ax.text((a + b) / 2, 51.0, f'{int((b - a) / 60)}:{int((b - a) % 60):02d}',
                ha='center', va='center', fontsize=7, color='white',
                zorder=3, fontweight='bold')
    ax.text(2, 52.5, '视频选段', fontsize=7, color='#1F4E79', va='top',
            fontweight='bold')


def _flatten(file_desc):
    """规整 file_desc → [(label, files, detect_dir)]"""
    out = []
    for item in file_desc:
        if len(item) == 3:
            out.append(tuple(item))
        else:
            raise ValueError('file_desc 每项需 (label, files, detect_dir)')
    return out