#!/usr/bin/env python3
"""riding_highlight.dash — 仪表盘 HUD 数据与渲染

HUD 设计 (右下角):
  ┌──────────────────────────┐
  │  ⏱ 16:40   📏 3.48km    │  右上: 时间/里程
  │        ╱                 │
  │   ────╱────  ┌────────┐  │
  │      ╱  40   │  31    │  │  速度表盘: 半圆刻度+指针
  │  ──╱──     km/h      │  │
  │ ╱                    │  │
  └──────────────────────────┘
"""
import os
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

EARTH_R = 6371000.0
ALT_MAX_JUMP = 150.0

# 中文字体 (自动探测)
def _find_cjk_font(size):
    candidates = [
        '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/noto-cjk/NotoSansCJK-Light.ttc',
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _find_bold_font(size):
    """数字用等宽/粗体 (速度数字可读性)"""
    candidates = [
        '/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return _find_cjk_font(size)


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

GAUGE_W, GAUGE_H = 300, 190      # 表盘画布
GAUGE_R = 118                     # 表盘半径
GAUGE_MAX = 60                    # 表盘满刻度 (km/h)
CX, CY = GAUGE_W // 2, 140        # 圆心 (底部留数字)


def _gauge_point(angle_deg):
    """角度(0=正上, 顺时针) → 画布坐标"""
    a = math.radians(angle_deg - 90)
    return CX + GAUGE_R * math.cos(a), CY + GAUGE_R * math.sin(a)


def draw_gauge(speed_kmh, filename):
    """绘制速度表盘 PNG (半圆 180° → 60km/h)"""
    img = Image.new('RGBA', (GAUGE_W, GAUGE_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 半圆底 (深灰半透明)
    d.pieslice([CX - GAUGE_R, CY - GAUGE_R, CX + GAUGE_R, CY + GAUGE_R],
               180, 360, fill=(20, 24, 32, 200))

    # 刻度: 0-60 km/h 映射 180°-360°
    f_bold = _find_bold_font(16)
    for v in range(0, GAUGE_MAX + 5, 5):
        ang = 180 + (v / GAUGE_MAX) * 180  # 0→180, 60→360
        p1 = _gauge_point(ang)
        r_in = GAUGE_R - (10 if v % 10 == 0 else 6)
        a2 = math.radians(ang - 90)
        p2 = (CX + r_in * math.cos(a2), CY + r_in * math.sin(a2))
        w = 3 if v % 10 == 0 else 1
        col = (255, 255, 255, 220) if v % 10 == 0 else (255, 255, 255, 120)
        d.line([p1, p2], fill=col, width=w)
        if v % 10 == 0:
            r_txt = GAUGE_R - 26
            tx = CX + r_txt * math.cos(a2)
            ty = CY + r_txt * math.sin(a2)
            t = f'{v}'
            bbox = d.textbbox((0, 0), t, font=f_bold)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            d.text((tx - tw / 2, ty - th / 2), t, font=f_bold,
                   fill=(255, 255, 255, 200))

    # 指针 (限幅到表盘范围)
    v = max(0, min(speed_kmh, GAUGE_MAX))
    ang = 180 + (v / GAUGE_MAX) * 180
    a = math.radians(ang - 90)
    tip = (CX + (GAUGE_R - 14) * math.cos(a), CY + (GAUGE_R - 14) * math.sin(a))
    # 指针尾部加粗
    d.line([(CX, CY), tip], fill=(255, 80, 80, 255), width=4)
    d.ellipse([CX - 5, CY - 5, CX + 5, CY + 5], fill=(255, 80, 80, 255))

    # 速度数字 (表盘下方)
    f_num = _find_bold_font(44)
    txt = f'{speed_kmh:.0f}'
    bbox = d.textbbox((0, 0), txt, font=f_num)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text((CX - tw / 2, GAUGE_H - th - 8), txt, font=f_num, fill=(255, 255, 255, 255))
    f_unit = _find_cjk_font(14)
    d.text((CX + tw / 2 + 8, GAUGE_H - th - 4), 'km/h', font=f_unit,
           fill=(200, 200, 200, 220))

    img.save(filename)
    return filename


def draw_info_panel(hud, t, filename):
    """绘制右上信息面板: 时间/海拔/里程"""
    W, H = 260, 120
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 半透明底
    d.rounded_rectangle([0, 0, W, H], radius=14, fill=(10, 14, 20, 180))

    f_time = _find_bold_font(28)
    f_small = _find_cjk_font(18)
    mm, ss = divmod(t, 60)
    hh, mm = divmod(mm, 60)
    time_s = f'{hh:02d}:{mm:02d}:{ss:02d}'
    d.text((16, 10), time_s, font=f_time, fill=(255, 255, 255, 255))

    alt = hud['altitude'][t] if t < len(hud['altitude']) else 0
    dist = hud['distance_m'][t] / 1000.0 if t < len(hud['distance_m']) else 0
    d.text((16, 52), f'海拔 {alt:.0f} m', font=f_small, fill=(180, 220, 255, 230))
    d.text((16, 80), f'里程 {dist:.2f} km', font=f_small, fill=(180, 220, 255, 230))
    img.save(filename)
    return filename


def compose_hud_frame(gauge_path, panel_path, video_w, video_h, out_path,
                      scale=1.0):
    """将表盘+面板合成到视频尺寸画布 (右下角/右上角)
    gauge: 右下角, panel: 右上角
    scale: HUD 缩放系数 (4K视频=2.0 保持与1080p一致的视觉占比)
    """
    canvas = Image.new('RGBA', (video_w, video_h), (0, 0, 0, 0))
    gauge = Image.open(gauge_path)
    panel = Image.open(panel_path)
    if scale != 1.0:
        gw, gh = int(gauge.width * scale), int(gauge.height * scale)
        pw, ph = int(panel.width * scale), int(panel.height * scale)
        gauge = gauge.resize((gw, gh), Image.LANCZOS)
        panel = panel.resize((pw, ph), Image.LANCZOS)
    # 右下角表盘, 右上角面板
    m = int(16 * scale)
    canvas.paste(gauge, (video_w - gauge.width - m, video_h - gauge.height - m), gauge)
    canvas.paste(panel, (m, m), panel)
    canvas.save(out_path)
    return out_path


def render_hud_frames(hud, out_dir, step=1):
    """预渲染 HUD 帧序列 (表盘+信息面板), 供 ffmpeg overlay
    out_dir: 输出目录, 每帧 hud_XXXXXX.png
    step: 每N秒一帧 (默认1, 与视频帧率无关, ffmpeg 端做时间缩放)
    返回: (n_frames, fps_equiv)
    """
    os.makedirs(out_dir, exist_ok=True)
    n = len(hud['speed_kmh'])
    # 表盘底 (每次重画有指针, 不能复用)
    for t in range(0, n, step):
        g = os.path.join(out_dir, f'hud_{t:06d}.png')
        draw_gauge(hud['speed_kmh'][t], g)
    return n // step + (1 if n % step else 0)


def render_hud_frames_composed(hud, out_dir, video_w=1920, video_h=1080,
                               start_sec=0, end_sec=None, step=1, scale=1.0):
    """预渲染合成 HUD 帧 (表盘+面板, 视频尺寸), 供 ffmpeg overlay
    帧命名: composed_%06d.png 连续编号 (0,1,2...), 帧i对应时间 start_sec+i
    scale: HUD 缩放 (1080p=1.0, 4K=2.0)
    返回: 帧数
    """
    os.makedirs(out_dir, exist_ok=True)
    n = len(hud['speed_kmh'])
    if end_sec is None:
        end_sec = n
    frames = 0
    for t in range(start_sec, min(end_sec, n), step):
        g = os.path.join(out_dir, f'g_{frames:06d}.png')
        p = os.path.join(out_dir, f'p_{frames:06d}.png')
        draw_gauge(hud['speed_kmh'][t], g)
        draw_info_panel(hud, t, p)
        compose_hud_frame(g, p, video_w, video_h,
                          os.path.join(out_dir, f'composed_{frames:06d}.png'),
                          scale=scale)
        os.remove(g)
        os.remove(p)
        frames += 1
    return frames


if __name__ == '__main__':
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from .extract import load_json
    gps = load_json(os.path.expanduser('~/骑行剪辑/detect/GX010070.gps.json'))
    hud = buildup_hud(gps)
    draw_gauge(hud['speed_kmh'][1000], '/tmp/gauge_test.png')
    draw_info_panel(hud, 1000, '/tmp/panel_test.png')
    print('测试帧已生成: /tmp/gauge_test.png /tmp/panel_test.png')
    print(f't=1000s: 速度{hud["speed_kmh"][1000]:.0f}km/h, '
          f'海拔{hud["altitude"][1000]:.0f}m, 里程{hud["distance_m"][1000]/1000:.2f}km')
