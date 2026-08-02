#!/usr/bin/env python3
"""riding_highlight.dash — 仪表盘 HUD 数据与渲染

HUD 设计 (右侧竖排精简面板):
  ┌──────────────┐
  │    33        │   ← 大号速度数字 (动态变化)
  │   km/h       │
  │ ──────────   │
  │ ⏱ 0:16:40    │
  │ ⛰ 海拔 138m   │
  │ 📍 里程 3.48km │
  └──────────────┘
"""
import os
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

EARTH_R = 6371000.0
ALT_MAX_JUMP = 150.0


# ---------- 字体 ----------
def _font(size, bold=False):
    """Noto Sans CJK 字体 (bold 优先粗体)"""
    paths = [
        '/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc' if bold else
        '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc' if bold else
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/noto-cjk/NotoSansCJK-Light.ttc',
    ]
    for c in paths:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ---------- 数据 ----------
def haversine(lat1, lon1, lat2, lon2):
    la1, la2 = math.radians(lat1), math.radians(lat2)
    dla = math.radians(lat2 - lat1)
    dlo = math.radians(lon2 - lon1)
    a = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def smooth_alt(alt, win=5):
    alt = np.asarray(alt, dtype=float)
    out = alt.copy()
    n = len(alt)
    half = win // 2
    for i in range(n):
        a, b = max(0, i - half), min(n, i + half + 1)
        out[i] = np.median(alt[a:b])
    for i in range(1, n):
        if abs(out[i] - out[i - 1]) > ALT_MAX_JUMP:
            out[i] = out[i - 1]
    return out


def cumulative_distance(lat, lon, valid=None, jump_m=50.0):
    n = len(lat)
    dist = np.zeros(n)
    if valid is None:
        valid = np.ones(n, dtype=bool)
    prev = None
    for i in range(n):
        if not valid[i] or (lat[i] == 0 and lon[i] == 0):
            if i > 0:
                dist[i] = dist[i - 1]
            prev = None
            continue
        if prev is not None:
            d = haversine(prev[0], prev[1], lat[i], lon[i])
            dist[i] = dist[i - 1] + (d if d < jump_m else 0.0)
        elif i > 0:
            dist[i] = dist[i - 1]
        prev = (lat[i], lon[i])
    return dist


def buildup_hud(gps, sample_rate_hz=10):
    """从 gps dict 派生 1Hz HUD 序列
    返回: dict{speed_kmh, altitude, distance_m, valid}
    """
    n_sec = len(gps['spd2d']) // sample_rate_hz
    spd = np.array(gps['spd2d']) * 3.6
    alt = np.array(gps['alt'])
    lat = np.array(gps['lat'])
    lon = np.array(gps['lon'])
    valid = np.array(gps['valid'], dtype=bool)
    speed_sec = np.array([spd[i * sample_rate_hz] for i in range(n_sec)])
    alt_sec = smooth_alt(np.array([alt[i * sample_rate_hz] for i in range(n_sec)]))
    valid_sec = np.array([bool(valid[i * sample_rate_hz:(i + 1) * sample_rate_hz].any())
                          for i in range(n_sec)], dtype=bool)
    a_eff = alt_sec[valid_sec]
    if len(a_eff):
        alt_sec = alt_sec - a_eff[0]
    lat1 = np.array([lat[i * sample_rate_hz] for i in range(n_sec)])
    lon1 = np.array([lon[i * sample_rate_hz] for i in range(n_sec)])
    valid1 = np.array([bool(valid[i * sample_rate_hz]) for i in range(n_sec)])
    dist = cumulative_distance(lat1, lon1, valid1)
    return {
        'speed_kmh': speed_sec,
        'altitude': alt_sec,
        'distance_m': dist,
        'valid': valid_sec,
    }


# ---------- 渲染 ----------
PANEL_W, PANEL_H = 200, 220   # 面板基础尺寸 (scale=1 时)


def draw_obj(panel_path):
    """绘制精简速度面板 (大数字 + 时间/海拔/里程小字)"""
    img = Image.new('RGBA', (PANEL_W, PANEL_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 半透明底
    d.rounded_rectangle([0, 0, PANEL_W, PANEL_H], radius=16,
                        fill=(10, 14, 20, 170))

    # 大号速度数字
    f_speed = _font(64, bold=True)
    txt = '0'
    bbox = d.textbbox((0, 0), txt, font=f_speed)
    d.text(((PANEL_W - (bbox[2] - bbox[0])) / 2, 10), txt,
           font=f_speed, fill=(255, 255, 255, 255))

    # km/h
    f_unit = _font(16)
    d.text((PANEL_W / 2 - 20, 82), 'km/h', font=f_unit,
           fill=(200, 200, 200, 220))

    # 分隔线
    d.line([20, 118, PANEL_W - 20, 118], fill=(255, 255, 255, 40), width=1)

    # 时间/海拔/里程
    f_info = _font(18)
    y = 128
    info_lines = [
        ('⏱ 00:00:00', 235, 235, 255),
        ('⛰ 海拔 0 m', 180, 220, 255),
        ('📍 里程 0.00 km', 180, 220, 255),
    ]
    for text, r, g, b in info_lines:
        d.text((16, y), text, font=f_info, fill=(r, g, b, 235))
        y += 30
    img.save(panel_path)
    return panel_path


def draw_panel(hud, t, panel_path):
    """渲染 t 时刻的面板 (速度/时间/海拔/里程)"""
    img = Image.new('RGBA', (PANEL_W, PANEL_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, PANEL_W, PANEL_H], radius=16,
                        fill=(10, 14, 20, 175))

    # 速度 (限幅)
    spd = int(hud['speed_kmh'][t]) if t < len(hud['speed_kmh']) else 0
    spd = max(0, min(spd, 99))
    f_speed = _font(64, bold=True)
    txt = f'{spd}'
    bbox = d.textbbox((0, 0), txt, font=f_speed)
    d.text(((PANEL_W - (bbox[2] - bbox[0])) / 2, 8), txt,
           font=f_speed, fill=(255, 255, 255, 255))
    f_unit = _font(16)
    d.text((PANEL_W / 2 - 20, 80), 'km/h', font=f_unit,
           fill=(200, 200, 200, 220))

    d.line([16, 116, PANEL_W - 16, 116], fill=(255, 255, 255, 40), width=1)

    f_info = _font(18)
    y = 126
    t_sec = t
    hh, rem = divmod(t_sec, 3600)
    mm, ss = divmod(rem, 60)
    alt = hud['altitude'][t] if t < len(hud['altitude']) else 0
    dist = hud['distance_m'][t] / 1000.0 if t < len(hud['distance_m']) else 0
    d.text((16, y), f'时间 {hh:02d}:{mm:02d}:{ss:02d}', font=f_info, fill=(235, 235, 255, 240))
    d.text((16, y + 30), f'海拔 {alt:.0f} m', font=f_info,
           fill=(180, 220, 255, 235))
    d.text((16, y + 60), f'里程 {dist:.2f} km', font=f_info,
           fill=(180, 220, 255, 235))
    img.save(panel_path)
    return panel_path


def compose_hud_frame(hud, t, video_w, video_h, out_path, scale=1.0):
    """渲染 t 时刻完整合成帧 (面板置于右下角)"""
    pw, ph = int(PANEL_W * scale), int(PANEL_H * scale)
    img = Image.new('RGBA', (video_w, video_h), (0, 0, 0, 0))
    panel = Image.new('RGBA', (PANEL_W, PANEL_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(panel)
    d.rounded_rectangle([0, 0, PANEL_W, PANEL_H], radius=16,
                        fill=(10, 14, 20, 175))
    # 速度
    spd = int(hud['speed_kmh'][t]) if t < len(hud['speed_kmh']) else 0
    spd = max(0, min(spd, 99))
    f_speed = _font(64, bold=True)
    txt = f'{spd}'
    dd = ImageDraw.Draw(panel)
    bbox = dd.textbbox((0, 0), txt, font=f_speed)
    dd.text(((PANEL_W - (bbox[2] - bbox[0])) / 2, 8), txt, font=f_speed,
            fill=(255, 255, 255, 255))
    f_unit = _font(16)
    ImageDraw.Draw(panel).text((PANEL_W / 2 - 20, 80), 'km/h', font=f_unit,
                               fill=(200, 200, 200, 220))
    ImageDraw.Draw(panel).line([16, 116, PANEL_W - 16, 116],
                               fill=(255, 255, 255, 40), width=1)
    f_info = _font(18)
    y = 126
    hh, rem = divmod(t, 3600)
    mm, ss = divmod(rem, 60)
    alt = hud['altitude'][t] if t < len(hud['altitude']) else 0
    dist = hud['distance_m'][t] / 1000.0 if t < len(hud['distance_m']) else 0
    ImageDraw.Draw(panel).text((16, y), f'时间 {hh:02d}:{mm:02d}:{ss:02d}',
                               font=f_info, fill=(235, 235, 255, 240))
    ImageDraw.Draw(panel).text((16, y + 30), f'海拔 {alt:.0f} m',
                               font=f_info, fill=(180, 220, 255, 235))
    ImageDraw.Draw(panel).text((16, y + 60), f'里程 {dist:.2f} km',
                               font=f_info, fill=(180, 220, 255, 235))
    if scale != 1.0:
        panel = panel.resize((pw, ph), Image.LANCZOS)
    m = int(16 * scale)
    img.paste(panel, (video_w - pw - m, video_h - ph - m), panel)
    img.save(out_path)
    return out_path


def render_hud_frames_composed(hud, out_dir, video_w=1920, video_h=1080,
                               start_sec=0, end_sec=None, step=1, scale=1.0):
    """预渲染合成帧序列 (连续编号, 供 ffmpeg overlay)
    帧i 对应时间 start_sec + i*step
    返回: 帧数
    """
    os.makedirs(out_dir, exist_ok=True)
    n = len(hud['speed_kmh'])
    if end_sec is None:
        end_sec = n
    frames = 0
    for t in range(start_sec, min(end_sec, n), step):
        out_path = os.path.join(out_dir, f'composed_{frames:06d}.png')
        compose_hud_frame(hud, t, video_w, video_h, out_path, scale)
        frames += 1
    return frames