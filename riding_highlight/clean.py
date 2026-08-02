#!/usr/bin/env python3
"""riding_highlight.clean — 加速度合理性清洗

GPS 速度本质是 1Hz 数据, 10Hz 只是插值重复。
因此加速度只在 1Hz 层计算; 清洗针对 10Hz 原始跳变。

物理依据:
  - 自行车加速度极限 ≈ 4 m/s²
  - 绝对速度上限: 75 km/h
  - 10Hz 单样本跳变 > 12 km/h (33 m/s²) 不可能
"""
import numpy as np

ACC_HARD = 8.0      # m/s² 硬噪声阈值 (10Hz 单样本)
V_MAX_KMH = 75.0    # 物理绝对速度上限
V_STEP_KMH = 12.0   # 10Hz 单样本速度跳变阈值 (km/h)
V_1HZ_JUMP_KMH = 20.0  # 1Hz 层速度跳变 (连续双向 = GPS故障簇)


def load_10hz(gps):
    """从 gps dict 取 10Hz 原始速度 (km/h) + valid"""
    spd = np.array(gps['spd2d']) * 3.6   # m/s -> km/h
    valid = np.array(gps['valid'], dtype=bool)
    return spd, valid


def flag_noise(spd, valid, return_noise=False):
    """标记加速度异常样本 (硬噪声->True)
    三层: 绝对速度上限 + 单样本跳变 + 迭代同比跳变簇
    返回: (noise_spd_clean, noise_mask)
    """
    v = spd / 3.6  # km/h -> m/s
    noise = np.zeros(len(v), dtype=bool)
    # 轮1: 绝对速度上限
    noise |= v > V_MAX_KMH / 3.6
    # 轮2: 单样本速度跳变 (孤立点, 两侧正常)
    V_STEP = V_STEP_KMH / 3.6
    dv = np.abs(np.diff(v))
    step_noise = np.zeros(len(v), dtype=bool)
    step_noise[1:] = dv > V_STEP
    for i in range(1, len(v) - 1):
        if step_noise[i] and not step_noise[i - 1] and not step_noise[i + 1]:
            lv, rv = v[i - 1], v[i + 1]
            if abs(v[i] - lv) > V_STEP and abs(rv - v[i]) > V_STEP:
                noise[i] = True
    # 轮3: 1Hz 层连续双向跳变 = GPS故障簇
    V_1HZ = V_1HZ_JUMP_KMH / 3.6
    v1 = v[::10]
    jumps = np.abs(np.diff(v1)) > V_1HZ
    for k in range(1, len(v1) - 1):
        if jumps[k - 1] and jumps[k]:
            for j in range(max(0, (k - 1) * 10), min(len(v), (k + 2) * 10)):
                noise[j] = True
    # 迭代: 剩余加速度跳变 (成对脉冲簇)
    for _ in range(3):
        v_cur = v.copy()
        v_cur[noise] = np.nan
        new = np.zeros(len(v), dtype=bool)
        for i in range(1, len(v) - 1):
            if noise[i]:
                continue
            l = np.where(~noise[:i])[0]
            r = np.where(~noise[i + 1:])[0]
            if len(l) and len(r):
                dl = abs(v[i] - v[l[-1]]) / ((i - l[-1]) * 0.1)
                dr = abs(v[r[0] + i + 1] - v[i]) / ((r[0] + 1) * 0.1)
                if dl > ACC_HARD and dr > ACC_HARD:
                    new[i] = True
        if not new.any():
            break
        noise |= new
    # 清理: 噪声样本用两侧最近有效值中值替代 (窗口自适应扩大)
    spd_clean = spd.copy()
    for i in np.where(noise)[0]:
        lv = rv = None
        lo = hi = 1
        while lo < 200:
            if i - lo >= 0 and not noise[i - lo]:
                lv = spd[i - lo]
                break
            lo += 1
        while hi < 200:
            if i + hi < len(spd) and not noise[i + hi]:
                rv = spd[i + hi]
                break
            hi += 1
        vals = [x for x in (lv, rv) if x is not None]
        if vals:
            spd_clean[i] = np.median(vals)
    return spd_clean, noise


def smooth_median(x, w=5):
    """中值滤波 (去尖峰, 保留阶跃)"""
    out = x.copy()
    half = w // 2
    for i in range(len(x)):
        a = max(0, i - half)
        b = min(len(x), i + half + 1)
        out[i] = np.median(x[a:b])
    return out


def per_second(spd_cleaned, valid, mode='first'):
    """下采样到 1Hz (GPS 本质 1Hz, 取首样本或最大)
    mode: 'first' 每秒首样本 (精确对齐GPS), 'max' 每秒最大值
    """
    n_sec = len(spd_cleaned) // 10
    if mode == 'first':
        sec = np.array([spd_cleaned[i * 10] for i in range(n_sec)])
        sec_v = np.array([valid[i * 10] for i in range(n_sec)])
    else:
        sec = np.array([spd_cleaned[i * 10:(i + 1) * 10].max() for i in range(n_sec)])
        sec_v = np.array([valid[i * 10:(i + 1) * 10].any() for i in range(n_sec)])
    return sec, sec_v


def accel_1hz(sec, sec_v):
    """1Hz 加速度 (m/s²): |dv/dt|, 无效置 NaN"""
    n = len(sec)
    acc = np.zeros(n)
    for i in range(1, n):
        if sec_v[i - 1] and sec_v[i]:
            acc[i] = abs(sec[i] - sec[i - 1]) / 3.6 / 1.0
    acc[~sec_v] = np.nan
    return acc