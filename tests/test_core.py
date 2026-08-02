#!/usr/bin/env python3
"""riding_highlight 核心算法自检"""
import os
import sys
import numpy as np
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from riding_highlight import gpmf, clean, analyze


def test_gpmf_empty():
    r = gpmf.parse(b'')
    assert r['gps'] == [], '空数据应返回空列表'
    print('  [OK] gpmf.parse 空数据处理')


def test_clean_noise():
    # 构造含尖峰的速度序列 (10Hz, 1s=10样本, 5s)
    spd = np.array([20.0] * 50)  # 20km/h 恒速
    spd[30:31] = 120.0  # 一帧虚高 (>V_MAX)
    valid = np.ones(50, dtype=bool)
    cleaned, noise = clean.flag_noise(spd, valid)
    assert noise.sum() >= 1, '应标记出虚高样本'
    assert cleaned[30] != 120.0, '虚高样本应被修正'
    print(f'  [OK] flag_noise 剔除虚高样本 (noise={noise.sum()}, cleaned[30]={cleaned[30]:.1f})')


def test_analyze_stops():
    # 构造: 0-3s 停车, 3-25s 加速到30巡航, 25-29s 停车 (总29s)
    sec = np.array([0,0,0, 10,15,22,27,30,30,30,30,30,30,30,30,30,30,30,30,30,
                    30,30,30,30,30, 0,0,0,0], dtype=float)
    sec_v = np.ones(len(sec), dtype=bool)
    procs, bounds, absorbed = analyze.detect_processes(sec, sec_v)
    assert procs, '应检测到过程'
    # 过程应覆盖 0-25 (从0开始到0结束)
    a, b = procs[0]
    assert a == 0 and b == 25, f'过程应为(0,25), got ({a},{b})'
    print(f'  [OK] detect_processes 过程: {[(a,b) for a,b in procs]}')
    print(f'       边界停{len(bounds)}, 内部短停{len(absorbed)}')


def test_select():
    sec_all = {'A': np.array([30.0]*20), 'B': np.array([15.0]*20)}
    procs_all = {'A': [(0, 15)], 'B': [(0, 15)]}
    edl = analyze.select_highlights(sec_all, procs_all, ['A', 'B'])
    assert len(edl) == 2
    assert edl[0]['file'] == 'A'  # 均速高者优先
    print(f'  [OK] select_highlights: {edl}')


def test_accel_1hz():
    sec = np.array([0, 36, 72])  # 每秒+36 km/h = 10 m/s²
    sec_v = np.ones(3, dtype=bool)
    acc = clean.accel_1hz(sec, sec_v)
    assert abs(acc[1] - 10.0) < 1e-6, f'accel应=10, got {acc[1]}'
    print('  [OK] accel_1hz 1Hz差分')


if __name__ == '__main__':
    test_gpmf_empty()
    test_clean_noise()
    test_analyze_stops()
    test_select()
    test_accel_1hz()
    print('\n全部自检通过 ✓')
    # 用真实数据做一次端到端验证
    det = os.path.expanduser('~/骑行剪辑/detect')
    if os.path.exists(det):
        from riding_highlight import extract as X
        g = X.load_json(os.path.join(det, 'GX010070.gps.json'))
        spd_raw, valid = clean.load_10hz(g)
        print(f'\n真实数据 GX010070: {len(spd_raw)} 样本, 有效 {int(valid.sum())}')