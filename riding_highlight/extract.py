#!/usr/bin/env python3
"""riding_highlight.extract — 从 GoPro 视频提取 GPS 实时数据

输入: MP4 视频文件 (内嵌 GPMF GPS9/GPS5)
输出: dict 结构化 GPS 数组 + detect/*.gps.json
"""
import struct
import json
import os
import subprocess
import numpy as np

from .gpmf import parse


def extract_gpmd(video_path):
    """从 MP4 中抽取 GPMD track 原始字节 (使用 ffmpeg)
    返回: bytes 或 None
    """
    # GoPro 的 GPMD stream: ffprobe 找 stream, ffmpeg 抽二进制
    cmd = ['ffprobe', '-v', 'error', '-select_streams', 'd',
           '-show_entries', 'stream=index,codec_name',
           '-of', 'json', video_path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        streams = json.loads(r.stdout).get('streams', [])
    except Exception:
        return None
    if not streams:
        return None
    out = video_path + '.gpmd.bin'
    for st in streams:
        if st.get('codec_name') == 'gpmd':
            idx = st.get('index', -1)
            cmd = ['ffmpeg', '-v', 'error', '-dump', '-i', video_path,
                   '-map', f'0:{idx}', '-c', 'copy', out]
            try:
                subprocess.run(cmd, capture_output=True, timeout=60)
                if os.path.exists(out) and os.path.getsize(out) > 0:
                    data = open(out, 'rb').read()
                    os.remove(out)
                    return data
            except Exception:
                pass
    return None


def extract_gps9(gpmd_bytes):
    """解析 GPMF GPS9/GPS5 → 结构化数组 (与 detect 兼容)

    返回 dict:
      n, lat, lon, alt, spd2d, spd3d, valid(掩码), rate_hz
    """
    r = parse(gpmd_bytes)
    gps = r['gps']
    if not gps:
        return None
    arr = np.array(gps, dtype=float)
    n = arr.shape[0]
    if r['gps_key'] == b'GPS9':
        lat, lon, alt, spd2d, spd3d = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]
    else:
        lat, lon, alt, spd2d, spd3d = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]
    # GPS 有效掩码: lat/lon 非零 (未锁定)
    valid = (np.abs(lat) > 0.001) & (np.abs(lon) > 0.001)
    return {
        'n': int(n),
        'lat': lat.astype(float),
        'lon': lon.astype(float),
        'alt': alt.astype(float),
        'spd2d': spd2d.astype(float),
        'spd3d': spd3d.astype(float),
        'valid': valid.astype(bool),
        'rate_hz': r.get('rate_hz'),
        'gps_key': r['gps_key'].decode() if r['gps_key'] else None,
    }


def detect_frozen(gps, frozen_min_s=3.0):
    """检测 GPS 失锁: 坐标完全冻结 >= N 秒

    关键: 真停车时 GPS 会漂移几米, 完全冻结 = 接收机停止输出
    返回: (frozen 掩码, frozen_segs 列表)
    """
    lat, lon = gps['lat'], gps['lon']
    n = len(lat)
    frozen = np.zeros(n, dtype=bool)
    same = np.zeros(n, dtype=bool)
    same[1:] = (lat[1:] == lat[:-1]) & (lon[1:] == lon[:-1])
    min_n = int(frozen_min_s * 10)
    run = 0
    for i in range(n):
        if same[i]:
            run += 1
        else:
            run = 0
        if run >= min_n:
            for j in range(max(0, i - run + 1), i + 1):
                frozen[j] = True
    # 失锁段
    segs = []
    in_s = False
    for i in range(n):
        if frozen[i] and not in_s:
            s = i / 10.0
            in_s = True
        elif not frozen[i] and in_s:
            segs.append((s, i / 10.0))
            in_s = False
    if in_s:
        segs.append((s, n / 10.0))
    segs = [(round(a, 1), round(b, 1)) for a, b in segs]
    return frozen, segs


def detect_static(gps, spd_kmh_max=2.0, min_s=5.0):
    """检测停车段: GPS有效 且 速度 < 阈 持续 >= min_s

    返回: [(start_sec, end_sec)] 内含失锁段会自动被剔除 (见 clean)
    """
    spd = gps['spd2d']  # m/s
    valid = gps['valid']
    min_n = int(min_s * 10)
    static = []
    start = None
    for i in range(len(spd)):
        v = spd[i]
        if valid[i] and v * 3.6 < spd_kmh_max:
            if start is None:
                start = i
        else:
            if start is not None:
                if i - start >= min_n:
                    static.append((start / 10.0, i / 10.0))
                start = None
    if start is not None and len(spd) - start >= min_n:
        static.append((start / 10.0, len(spd) / 10.0))
    return static


def subtract_frozen(stops, frozen_segs, min_keep_s=3.0):
    """从停车段剔除失锁重叠部分 (失锁不是停车)
    返回: 剩余停车段 (保留 >= min_keep_s 的片段)
    """
    clean = []
    for s, e in stops:
        cuts = [(s, e)]
        for fs, fe in frozen_segs:
            new = []
            for a, b in cuts:
                if fe <= a or fs >= b:
                    new.append((a, b))
                else:
                    if fs > a:
                        new.append((a, fs))
                    if fe < b:
                        new.append((fe, b))
            cuts = new
        for a, b in cuts:
            if b - a >= min_keep_s:
                clean.append((round(a, 1), round(b, 1)))
    return clean


def extract_video(video_path, out_detect_json=None):
    """完整提取: GPMD → 结构化数组 → 失锁/停车标注

    返回: gps dict (含 valid, frozen, static_segs, frozen_segs)
    """
    gpmd = extract_gpmd(video_path)
    if not gpmd:
        return None
    gps = extract_gps9(gpmd)
    if gps is None:
        return None
    frozen, frozen_segs = detect_frozen(gps)
    static = detect_static(gps)
    static = subtract_frozen(static, frozen_segs)
    gps['frozen'] = frozen
    gps['frozen_segs'] = frozen_segs
    gps['static_segs'] = static
    gps['valid'] = gps['valid'] & ~frozen  # 失锁样本置无效
    if out_detect_json:
        save_json(gps, out_detect_json)
    return gps


def save_json(gps, path):
    """持久化 gps dict 到 JSON (供后续 analyze/plot 读取)"""
    payload = {
        'n': int(gps['n']),
        'lat': gps['lat'].tolist(),
        'lon': gps['lon'].tolist(),
        'alt': gps['alt'].tolist(),
        'spd2d': gps['spd2d'].tolist(),
        'spd3d': gps['spd3d'].tolist(),
        'valid': gps['valid'].astype(int).tolist(),
        'frozen': gps.get('frozen', np.zeros(gps['n'], bool)).astype(int).tolist(),
        'frozen_segs': gps.get('frozen_segs', []),
        'static_segs': gps.get('static_segs', []),
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(payload, f)


def load_json(path):
    """载入 gps JSON → numpy 数组"""
    d = json.load(open(path))
    return {
        'n': int(d['n']),
        'lat': np.array(d['lat']),
        'lon': np.array(d['lon']),
        'alt': np.array(d['alt']),
        'spd2d': np.array(d['spd2d']),
        'spd3d': np.array(d['spd3d']),
        'valid': np.array(d['valid'], dtype=bool),
        'frozen': np.array(d.get('frozen', []), dtype=bool),
        'frozen_segs': d.get('frozen_segs', []),
        'static_segs': d.get('static_segs', []),
    }