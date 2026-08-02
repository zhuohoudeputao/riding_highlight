#!/usr/bin/env python3
"""riding_highlight.gpmf — 纯Python GPMF 解析器 (无外部依赖)

从 GoPro GPMD 流递归解析 KLV 结构, 提取 GPS 样本。
支持:
  - GPS5 (HERO5-9): 20字节/样本, 5×int32 (lat,lon,alt,spd2d,spd3d)
  - GPS9 (HERO13):  32字节/样本, 8×int32 (lat,lon,alt,spd2d,spd3d,days,secs,var)

GPMF 二进制布局:
  4字节 类型标识 (b'DEVC', b'STRM', b'GPS5', b'GPS9', b'SCAL'...)
  2字节 size   (payload 字节数)
  2字节 count  (样本数)
  payload, 4字节对齐
"""
import struct

# GPMF 四字符类型 → 单样本字节数
SIZE_MAP = {
    b'GPS5': 20,   # 5×int32
    b'GPS9': 32,   # 8×int32
    b'GPSU': 8,    # microsecond timestamp
    b'SCAL': 4,    # scale factor (float32)
    b'ACCL': 12, b'GYRO': 12, b'GRAV': 12,
    b'CORI': 12, b'ORIN': 12,
    b'ISOE': 4, b'SHUT': 8, b'WBAL': 8,
    b'DVNM': 0, b'DVMF': 0, b'DVID': 8, b'DVIN': 0,
}

# GPS5: lat,lon,alt,spd2d,spd3d 都是 int32, 缩放 /scale
GPS5_FIELDS = ('lat', 'lon', 'alt', 'spd2d', 'spd3d')
# GPS9: lat,lon,alt,spd2d,spd3d 用 GPS9 缩放 (lat/lon 1e7, 其余除 SCAL),
#       后3个 (days,secs,var) 原样
GPS9_FIELDS = ('lat', 'lon', 'alt', 'spd2d', 'spd3d', 'days', 'secs', 'var')


class GPMFError(Exception):
    """GPMF 解析错误"""


def _align(pos):
    return (pos + 3) & ~3


def iter_klv(data):
    """生成器: 递归遍历 GPMF KLV, 产出 (key, value)
    value: bytes 样本载荷 (若为容器类型则是生成器)
    """
    n = len(data)
    pos = 0
    while pos + 8 <= n:
        typ = data[pos:pos + 4]
        size = struct.unpack('>H', data[pos + 4:pos + 6])[0]
        count = struct.unpack('>H', data[pos + 6:pos + 8])[0]
        body = pos + 8
        end = body + size
        if end > n:
            break
        payload = data[body:end]
        if typ in (b'DEVC', b'STRM', b'DEV', b'EMBD'):
            yield typ, iter_klv(payload)
        else:
            yield typ, payload
        pos = _align(end)


def extract_samples(gpmd_bytes, key=b'GPS9'):
    """提取指定 GPS 键的样本原始字节帧 (不缩放)
    返回: list[bytes] 每帧 = SIZE_MAP[key] 字节
    """
    frames = []

    def walk(items):
        for k, v in items:
            if k == key and isinstance(v, bytes):
                s = SIZE_MAP.get(k)
                if s:
                    for i in range(len(v) // s):
                        frames.append(v[i * s:(i + 1) * s])
            elif hasattr(v, '__iter__'):
                walk(v)

    walk(iter_klv(gpmd_bytes))
    return frames


def parse(data):
    """解析 GPMF 数据, 返回 GPS 样本结构化数组与缩放系数

    返回: {'gps': [(lat,lon,alt,spd2d,spd3d,...), ...], 'scale': float,
           'gps_key': b'GPS5'|b'GPS9'}
    """
    gps_frames = extract_samples(data, b'GPS9')
    gps_key = b'GPS9'
    if not gps_frames:
        gps_frames = extract_samples(data, b'GPS5')
        gps_key = b'GPS5'
    if not gps_frames:
        return {'gps': [], 'scale': 1000.0, 'gps_key': None,
                'rate_hz': None}

    # 归一化: 先解全部 int32
    raw_int = []
    for fr in gps_frames:
        n32 = len(fr) // 4
        raw_int.append(struct.unpack(f'>{n32}i', fr[:n32 * 4]))

    # 找 SCAL (仅 GPS5 需要; GPS9 经纬度固定 1e7)
    scale = 1000.0
    for k, v in iter_klv(data):
        if k == b'SCAL' and isinstance(v, bytes) and len(v) >= 4:
            scale = struct.unpack('>f', v[:4])[0]
            break

    # 解码
    gps = []
    for vals in raw_int:
        if gps_key == b'GPS9':
            # lat/lon 固定 /1e7, alt/spd /1000, days/secs 原样
            lat, lon, alt, s2, s3 = vals[0] / 1e7, vals[1] / 1e7, \
                vals[2] / 1000.0, vals[3] / 1000.0, vals[4] / 1000.0
            days, secs = vals[5], vals[6]
            gps.append((lat, lon, alt, s2, s3, days, secs))
        else:
            lat, lon, alt, s2, s3 = [v / scale for v in vals[:5]]
            gps.append((lat, lon, alt, s2, s3))

    # 采样率: 推断 (帧数/时长未知, 常见 10Hz 或 18Hz)
    rate_hz = None
    return {'gps': gps, 'scale': scale, 'gps_key': gps_key,
            'rate_hz': rate_hz}


# 兼容旧调用
parse_gpmf = parse