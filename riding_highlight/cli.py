#!/usr/bin/env python3
"""riding_highlight.cli — 命令行入口

用法:
  riding extract <mp4...> [--detect-dir DIR]     提取GPS+失锁/停车
  riding highlight --video-dir DIR --out-dir DIR [--per-file N]
                                                  检测过程+选高光+渲染
  riding plot --detect-dir DIR --out-dir DIR [--edl FILE] [--ride NAME=FILES]
                                                  绘制速度曲线
  riding render --edl FILE --video-dir DIR -o OUT  渲染EDL

示例:
  riding extract ~/Videos/骑行/GX010070.MP4
  riding highlight --video-dir ~/Videos/骑行 --out-dir ./out
  riding plot --detect-dir ./detect --out-dir ./charts
  riding render --edl highlight.json --video-dir ~/Videos/骑行 -o high.mp4
"""
import argparse
import json
import os
import sys

from . import extract as X
from . import clean as C
from . import analyze as A
from . import render as R
from . import plot as P


def cmd_extract(args):
    os.makedirs(args.detect_dir, exist_ok=True)
    for vp in args.videos:
        base = os.path.splitext(os.path.basename(vp))[0]
        out = os.path.join(args.detect_dir, base + '.gps.json')
        gps = X.extract_video(vp, out_detect_json=out)
        if gps is None:
            print(f'{base}: 无 GPS 数据')
            continue
        n = gps['n']
        n_v = int(gps['valid'].sum())
        print(f'{base}: {n} 样本, 有效 {n_v} ({n_v / n * 100:.0f}%), '
              f'失锁 {len(gps["frozen_segs"])} 段, 停车 {len(gps["static_segs"])} 段')
        print(f'  保存: {out}')
    return 0


def _load_all_gps(detect_dir, files):
    """载入并清洗全部文件, 返回 (sec_all, procs_all)"""
    sec_all, procs_all = {}, {}
    for f in files:
        path = os.path.join(detect_dir, f + '.gps.json')
        if not os.path.exists(path):
            print(f'  [跳过] 无 {path}')
            continue
        gps = X.load_json(path)
        spd_raw, valid = C.load_10hz(gps)
        spd_med, _ = C.flag_noise(spd_raw, valid)
        spd_med = C.smooth_median(spd_med)
        sec, sec_v = C.per_second(spd_med, valid, 'first')
        sec_clean = sec.copy()
        sec_clean[~sec_v] = 0
        procs, _, _ = A.detect_processes(sec_clean, sec_v)
        sec_all[f] = sec_clean
        procs_all[f] = procs
    return sec_all, procs_all


def cmd_highlight(args):
    os.makedirs(args.detect_dir, exist_ok=True)
    # 1. 提取GPS
    mp4s = sorted(f for f in os.listdir(args.video_dir)
                  if f.lower().endswith(('.mp4', '.mov')) and not f.startswith('.'))
    for f in mp4s:
        vp = os.path.join(args.video_dir, f)
        base = os.path.splitext(f)[0]
        out = os.path.join(args.detect_dir, base + '.gps.json')
        if not os.path.exists(out):
            gps = X.extract_video(vp, out_detect_json=out)
            if gps is None:
                print(f'{base}: 无 GPS')
    # 2. 过程检测 + 选高光
    files = [os.path.splitext(f)[0] for f in mp4s]
    sec_all, procs_all = _load_all_gps(args.detect_dir, files)
    edl = A.select_highlights(sec_all, procs_all, files, per_file=args.per_file)
    auto_max = None
    if args.max_seconds:
        # 可选: 累计到 max_seconds
        ordered = sorted(edl, key=lambda e: -e['avg_speed'])
        cum, kept = 0, []
        for e in ordered:
            if cum + (e['end'] - e['start']) <= args.max_seconds:
                kept.append(e)
                cum += e['end'] - e['start']
        edl = kept
    os.makedirs(args.out_dir, exist_ok=True)
    edl_path = os.path.join(args.out_dir, 'highlight.json')
    with open(edl_path, 'w') as f:
        json.dump(edl, f, indent=1)
    print(f'高光选段: {len(edl)} 段, 保存 {edl_path}')
    for e in edl:
        print(f"  {e['file']} {int(e['start']) // 60}:{int(e['start']) % 60:02d} "
              f"-> {int(e['end']) // 60}:{int(e['end']) % 60:02d} "
              f"({(e['end'] - e['start']) // 60}:{(e['end'] - e['start']) % 60:02d}, "
              f"均速{e['avg_speed']}km/h)")
    # 3. 渲染
    if args.render:
        out_video = os.path.join(args.out_dir, 'highlight.mp4')
        ok, dur = R.render_edl(edl, args.video_dir, out_video,
                               crf=args.crf, preset=args.preset,
                               hwaccel=args.hwaccel, scale=args.scale)
        if ok:
            print(f'渲染完成: {out_video} ({dur:.0f}s)')
    return 0


def cmd_plot(args):
    os.makedirs(args.out_dir, exist_ok=True)
    edl = []
    if args.edl and os.path.exists(args.edl):
        edl = json.load(open(args.edl))
    # 单文件图
    for g in os.listdir(args.detect_dir):
        if not g.endswith('.gps.json'):
            continue
        base = g[:-len('.gps.json')]
        out = os.path.join(args.out_dir, base + '_speed.png')
        P.draw(base, [(base, [base], args.detect_dir)], edl, out)
    # 合并图
    if args.ride:
        for spec in args.ride.split(';'):
            name, files = spec.split('=')
            fl = files.split(',')
            out = os.path.join(args.out_dir, f'{name}_speed_combined.png')
            # 赋 offset
            edl_off = _apply_offset(edl, fl)
            P.draw(name, [(name, fl, args.detect_dir)], edl_off, out,
                   figsize=(16, 5.5))
    return 0


def _apply_offset(edl, files):
    """给 EDL 赋每文件在合并图的时间偏移"""
    # 这需要 detect 时长; 简化: 若只含单文件则 offset=0
    return edl


def cmd_render(args):
    edl = json.load(open(args.edl))
    ok, dur = R.render_edl(edl, args.video_dir, args.output,
                           crf=args.crf, preset=args.preset,
                           hwaccel=args.hwaccel, scale=args.scale)
    print(f'渲染: {"成功" if ok else "失败"} ' + (f'({dur:.0f}s)' if ok else ''))
    return 0 if ok else 1


def cmd_narrate(args):
    from .narration import gen_narration
    from .audio import build_audio
    gps = X.load_json(args.gps)
    nar = gen_narration(gps, args.ride_name, args.style)
    print('解说词:')
    print('  [intro]', nar['intro'])
    for s in nar['segments']:
        print(f'  [{s["start"] // 60}:{s["start"] % 60:02d}]', s['text'])
    print('  [outro]', nar['outro'])
    bg = args.bg_music if os.path.exists(args.bg_music) else None
    if bg is None and args.bg_music:
        print(f'  [警告] 背景乐不存在: {args.bg_music}')
    if bg:
        out = build_audio(nar, args.output, bg_music=bg)
    else:
        out = build_audio(nar, args.output)
    print(f'解说音频: {out}')
    return 0


def main(argv=None):
    argv = argv or sys.argv[1:]
    ap = argparse.ArgumentParser(prog='riding', description='骑行高光视频 pipeline')
    sub = ap.add_subparsers(dest='cmd', required=True)

    # extract
    p = sub.add_parser('extract', help='提取GPS+失锁/停车标注')
    p.add_argument('videos', nargs='+')
    p.add_argument('--detect-dir', default='detect')
    p.set_defaults(func=cmd_extract)

    # highlight
    p = sub.add_parser('highlight', help='检测+选高光+渲染')
    p.add_argument('--video-dir', required=True)
    p.add_argument('--out-dir', default='output')
    p.add_argument('--detect-dir', default='detect')
    p.add_argument('--per-file', type=int, default=1)
    p.add_argument('--max-seconds', type=int, default=0)
    p.add_argument('--render', action='store_true')
    p.add_argument('--crf', type=int, default=20)
    p.add_argument('--preset', default='medium')
    p.add_argument('--hwaccel', default='vaapi')
    p.add_argument('--scale', default='1920:1080')
    p.set_defaults(func=cmd_highlight)

    # plot
    p = sub.add_parser('plot', help='速度曲线')
    p.add_argument('--detect-dir', default='detect')
    p.add_argument('--out-dir', default='charts')
    p.add_argument('--edl')
    p.add_argument('--ride')
    p.set_defaults(func=cmd_plot)

    # render
    p = sub.add_parser('render', help='渲染EDL')
    p.add_argument('--edl', required=True)
    p.add_argument('--video-dir', default='.')
    p.add_argument('-o', '--output', default='highlight.mp4')
    p.add_argument('--crf', type=int, default=20)
    p.add_argument('--preset', default='medium')
    p.add_argument('--hwaccel', default='vaapi')
    p.add_argument('--scale', default='1920:1080')
    p.set_defaults(func=cmd_render)

    # narrate
    p = sub.add_parser('narrate', help='生成解说音频')
    p.add_argument('--gps', required=True, help='detect/*.gps.json')
    p.add_argument('--ride-name', default='骑行')
    p.add_argument('--style', default='default', choices=['default', 'sporty', 'calm'])
    p.add_argument('--bg-music', default='', help='背景乐路径 (可选)')
    p.add_argument('-o', '--output', default='narration.m4a')
    p.set_defaults(func=cmd_narrate)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())