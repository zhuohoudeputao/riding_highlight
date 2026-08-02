#!/usr/bin/env python3
"""riding_highlight.dash — 速度仪表盘 HUD 数据生成

从实时 GPS 派生 HUD 叠加所需的时间序列:
  speed_kmh    速度表 (圆盘或数字)
  altitude     海拔
  cadence?     踏频 (无传感器则不提供)
  时间戳/累计距离

数据格式: 与源视频同帧率对齐前, 输出 1Hz 序列 dict, render 阶段叠加。
"""
import numpy as np

EARTH_R = 6371000.0


def haversine(lat1, lon1, lat2, lon2):
    """两点球面距离 (m)"""
    la1, la2 = np.radians(lat1), np.radians(lat2)
    dla = np.radians(lat2 - lat1)
    dlo = np.radians(lon2 - lon1)
    a = np.sin(dla / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin(dlo / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(a))


def cumulative_distance(lat, lon):
    """累计里程 (m), 忽略无效样本"""
    n = len(lat)
    dist = np.zeros(n)
    prev = None
    prev_eff = None
    for i in range(n):
        if lat[i] == 0 and lon[i] == 0:
            if prev_eff is not None:
                dist[i] = dist[i - 1]
            prev = None
            continue
        if prev is not None and lat[i] != prev[0]:
            d = haversine(prev[0], prev[1], lat[i], lon[i])
            dist[i] = dist[i - 1] + d
        elif i > 0:
            dist[i] = dist[i - 1]
        prev = (lat[i], lon[i])
        prev_eff = i
    return dist


def buildup_hud(gps, sample_rate_hz=None):
    """从 gps dict 派生 HUD 序列 (1Hz)
    返回 dict: speed, alt, dist, valid (均1Hz)
    """
    if sample_rate_hz is None:
        sample_rate_hz = 10
    n_sec = len(gps['spd2d']) // sample_rate_hz
    spd = np.array(gps['spd2d']) * 3.6
    alt = np.array(gps['alt'])
    lat = np.array(gps['lat'])
    lon = np.array(gps['lon'])
    valid = np.array(gps['valid'], dtype=bool)
    speed_sec = np.array([spd[i * sample_rate_hz] for i in range(n_sec)])
    alt_sec = np.array([alt[i * sample_rate_hz] for i in range(n_sec)])
    valid_sec = np.array([valid[i * sample_rate_hz].any()
                          if isinstance(valid[i * sample_rate_hz:(i + 1) * sample_rate_hz].any(), np.bool_)
                          else bool(valid[i * sample_rate_hz:(i + 1) * sample_rate_hz].any())
                          for i in range(n_sec)], dtype=bool)
    # 累计距离 (1Hz间取每10帧)
    lat1 = np.array([lat[i * sample_rate_hz] for i in range(n_sec)])
    lon1 = np.array([lon[i * sample_rate_hz] for i in range(n_sec)])
    dist = cumulative_distance(lat1, lon1)
    return {
        'speed_kmh': speed_sec,
        'altitude': alt_sec,
        'distance_m': dist,
        'valid': valid_sec,
        'rate_hz': 1,
    }


def format_hud_overlay(dash, t):
    """生成第 t 秒的 HUD 文本 (供 ffmpeg drawtext / PIL 叠加)
    返回 dict {param: str} 用于模板
    """
    t = int(t)
    if t >= len(dash['speed_kmh']):
        return None
    spd = dash['speed_kmh'][t]
    alt = dash['altitude'][t]
    dist_km = dash['distance_m'][t] / 1000.0
    mm, ss = divmod(t, 60)
    return {
        'speed': f'{spd:.0f}',
        'alt': f'{alt:.0f}',
        'dist': f'{dist_km:.2f}',
        'time': f'{mm:02d}:{ss:02d}',
    }