riding_highlight: 从原始骑行视频到高光视频的完整开源 pipeline
===============================================================

输入: GoPro 骑行视频 (含 GPMF GPS 元数据)
输出: 精选高光片段 + 速度时间曲线图 + 仪表盘 HUD

架构
----
```
原始视频 (MP4, 内嵌GPMF GPS9)
   │
   ▼
┌──────────────┐
│ gpmf_parse   │  纯Python解析GPMF, 提取GPS9 (去掉外部gpmf依赖)
└──────────────┘
   │  lat/lon/alt/spd2d/spd3d (10Hz int32)
   ▼
┌──────────────┐
│ extract_gps  │  缩放, GPS有效掩码, 标注失锁段(frozen)
└──────────────┘
   │  detect/*.gps.json
   ▼
┌──────────────┐
│ accel_filter │  加速度合理性清洗: 绝对速度上限 + 跳变检测 + 中值滤波
└──────────────┘
   │  清洗后速度 (1Hz)
   ▼
┌────────────────┐
│ detect_process │  GPS失锁检测 + 停车段分类 + 过程切割 (0起0止)
└────────────────┘
   │  detect/processes.json
   ▼
┌────────────────┐
│ select_high    │  每文件选均速最高的过程 = 高光候选
└────────────────┘
   │  edl/highlight.json
   ▼
┌──────────────┐
│ render       │  ffmpeg 分段提取 + concat → 高光视频
│ dash_arduino │  (可选) 速度仪表盘 HUD 叠加
└──────────────┘
   │
   ▼
高光视频 + charts/*.png 速度曲线
```

模块分层
--------
- `riding_highlight/gpmf.py`      纯Python GPMF 解析器 (GPS5/GPS9)
- `riding_highlight/extract.py`   从视频提取GPS9数据并标注失锁/停车
- `riding_highlight/clean.py`     加速度合理性滤波
- `riding_highlight/analyze.py`   过程检测 (从0到0, 连续性优先)
- `riding_highlight/select.py`    高光选段 (均速最高)
- `riding_highlight/render.py`    ffmpeg 渲染 (外部编码器)
- `riding_highlight/plot.py`      速度-时间曲线 + 选段标注
- `riding_highlight/dash.py`      仪表盘 HUD 数据生成
- `riding_highlight/cli.py`       命令行入口

EDL (Edit Decision List) 格式
------------------------------
```json
[
  {"file": "GX010070", "start": 850, "end": 1465},
  {"file": "GX020070", "start": 332, "end": 616}
]
```
- `file`: GoPro 文件名（不含扩展名）
- `start`/`end`: 秒，相对该文件起始
- 时间戳精确到秒（可含小数）

核心算法
--------
1. **GPS 失锁检测** (`detect_frozen`)
   坐标完全冻结 ≥3s = GPS 信号丢失（区别于真停车，真停车有漂移）
   关键: 恢复瞬间位置大跳变 (534m/0.5s)

2. **加速度合理性** (`accel_filter`)
   - GPS 速度本质是 1Hz，10Hz 是插值重复 → 加速度只在 1Hz 层计算
   - 物理依据: 自行车加速度极限 ≈ 4 m/s²
   - 清洗: 绝对速度上限(75km/h) + 单样本跳变 + 中值滤波

3. **过程检测** (`detect_processes`)
   - 停车段: 速度<2km/h 持续≥3s
   - 边界停 vs 内部短停: 时长≥20s 或前后非巡航 = 边界
   - 过程 = 边界停之间, 从"进入0"到"回到0"

4. **高光选段** (`select`)
   每文件选均速最高的过程

依赖
----
- Python 3.10+: numpy, matplotlib (绘图)
- ffmpeg + ffprobe (渲染): 建议 libx264 + 输入侧 `-hwaccel vaapi`

安装
----
```bash
pip install -e .
```

使用
----
```bash
# 完整流程
riding highlight --video-dir ~/Videos/骑行 --out-dir ./output --ride GX010070,GX020070

# 预览高光选段
riding plot --detect-dir ./detect --out-dir ./charts

# 渲染
riding render --edl highlight.json --video-dir ~/Videos/骑行
```

致谢
----
数据与算法经过华为通勤 + 夜间骑行（GoPro HERO13, GPS9 10Hz）实测验证。