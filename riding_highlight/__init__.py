"""riding_highlight — 从原始骑行视频到高光视频的完整 pipeline

模块:
  gpmf    纯Python GPMF 解析器 (GPS5/GPS9, 无外部依赖)
  extract 从视频提取GPS9 + 失锁/停车标注
  clean   加速度合理性滤波
  analyze 过程检测 + 高光选段
  render  ffmpeg 渲染
  plot    速度-时间曲线 + 选段标注
  dash    速度仪表盘 HUD 数据
"""
__version__ = '0.1.0'

from .gpmf import parse, iter_klv, extract_samples  # noqa: F401
from .extract import (extract_video, extract_gps9, detect_frozen,  # noqa: F401
                      detect_static, subtract_frozen, load_json, save_json)
from .clean import (flag_noise, smooth_median, per_second,  # noqa: F401
                    accel_1hz, load_10hz)
from .analyze import (detect_processes, select_highlights,  # noqa: F401
                      process_speed)
from .render import render_edl, extract_seg  # noqa: F401
from .dash import buildup_hud, draw_gauge, draw_info_panel  # noqa: F401
from .narration import gen_narration, ride_stats  # noqa: F401

__all__ = [
    'parse', 'iter_klv', 'extract_samples',
    'extract_video', 'extract_gps9', 'detect_frozen',
    'detect_static', 'subtract_frozen', 'load_json', 'save_json',
    'flag_noise', 'smooth_median', 'per_second', 'accel_1hz', 'load_10hz',
    'detect_processes', 'select_highlights', 'process_speed',
    'render_edl', 'extract_seg',
    'buildup_hud', 'draw_gauge', 'draw_info_panel',
    'gen_narration', 'ride_stats',
]