#!/usr/bin/env python3
"""riding_highlight.analyze — 过程检测与高光选段

核心算法: "从0开始到0结束"
  1. 停车段: 速度<STOP_KMH 持续>=STOP_MIN_S
  2. 分类: 边界停(时长>=LONG_STOP 或前后非巡航) vs 内部短停(吸收保留)
  3. 过程 = 边界停之间, 起点=进入0, 终点=回到0
  4. 高光选段: 每文件选均速最高的过程
"""
import numpy as np

STOP_KMH = 2.0
STOP_MIN_S = 3
LONG_STOP_S = 20
CRUISE_KMH = 20.0
CRUISE_WIN = 10      # 停车前后巡航统计窗口(秒)
MIN_PROCESS_S = 20


def find_stops(sec, sec_v, n):
    """停车段: 速度<STOP_KMH 持续>=STOP_MIN_S → [(a,b)]"""
    stops = []
    in_s = False
    for i in range(n):
        if not sec_v[i]:
            if in_s:
                stops.append((start, i))
                in_s = False
            continue
        if sec[i] < STOP_KMH:
            if not in_s:
                start = i
                in_s = True
        else:
            if in_s:
                if i - start >= STOP_MIN_S:
                    stops.append((start, i))
                in_s = False
    if in_s and n - start >= STOP_MIN_S:
        stops.append((start, n))
    return stops


def win_avg(sec, sec_v, a, b):
    seg = sec[a:b][sec_v[a:b]]
    return seg.mean() if len(seg) >= 3 else 0.0


def plausible_start(sec, sec_v, s, n):
    """验证起点起步物理合理: 平均加速度<=4 m/s² 且无>8m/s²跳变"""
    if s + 5 > n:
        return True
    seg = sec[s:s + 6]
    v = seg[sec_v[s:s + 6]]
    if len(v) < 3:
        return True
    a = (v[-1] - v[0]) / 3.6 / (len(v) - 1)
    max_step = np.abs(np.diff(v)).max() / 3.6
    return a <= 4.0 and max_step <= 8.0


def detect_processes(sec, sec_v):
    """过程检测: 边界停之间, 从0到0
    返回: procs [(start,end)], boundaries [边界停], absorbed [内部短停]
    """
    n = len(sec)
    stops = find_stops(sec, sec_v, n)
    boundaries = []
    absorbed = []
    for a, b in stops:
        dur = b - a
        pre = win_avg(sec, sec_v, max(0, a - CRUISE_WIN), a)
        post = win_avg(sec, sec_v, b, min(n, b + CRUISE_WIN))
        if dur >= LONG_STOP_S or pre < CRUISE_KMH or post < CRUISE_KMH:
            boundaries.append((a, b))
        else:
            absorbed.append((a, b))

    procs = []
    first_valid = np.where(sec_v)[0]
    fv = first_valid[0] if len(first_valid) else 0
    lv = first_valid[-1] if len(first_valid) else n - 1
    if boundaries and boundaries[0][0] - fv >= MIN_PROCESS_S:
        procs.append((fv, boundaries[0][0]))
    for i in range(len(boundaries) - 1):
        s = boundaries[i][0]
        e = boundaries[i + 1][0]
        b_end = boundaries[i][1]
        # 加速度合理性: 边界停后起步不合理则起点顺延
        if not plausible_start(sec, sec_v, b_end, n):
            for t in range(b_end + 1, min(b_end + 20, n)):
                if sec[t] >= 5.0 and plausible_start(sec, sec_v, t, n):
                    s = t
                    break
        if e - s >= MIN_PROCESS_S:
            procs.append((s, e))
    if boundaries and lv - boundaries[-1][1] >= MIN_PROCESS_S:
        procs.append((boundaries[-1][1], lv))
    elif not boundaries:
        if lv - fv >= MIN_PROCESS_S:
            procs.append((fv, lv))
    return procs, boundaries, absorbed


def process_speed(sec, proc):
    """计算过程段内均速 (km/h)"""
    a, b = proc
    return float(sec[a:b].mean())


def select_highlights(sec_all, procs_all, files, per_file=1):
    """从多文件过程中选高光片段
    sec_all:  {file: 1Hz sec 数组}
    procs_all: {file: [(s,e),...]}
    per_file: 每文件选几个 (默认1=均速最高)
    返回: EDL 列表 [{file, start, end, avg_speed}]
    """
    edl = []
    for f in files:
        if f not in procs_all:
            continue
        procs = procs_all[f]
        sec = sec_all[f]
        if not procs:
            continue
        # 按均速降序
        ranked = sorted(procs, key=lambda p: process_speed(sec, p), reverse=True)
        for s, e in ranked[:per_file]:
            edl.append({
                'file': f,
                'start': int(s),
                'end': int(e),
                'avg_speed': round(process_speed(sec, (s, e)), 1),
            })
    return edl