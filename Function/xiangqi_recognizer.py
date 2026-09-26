#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""象棋棋盘截图识别

流程:
  1. calibrate : 用开局截图自动标定棋盘网格(9x10=90 个交叉点),
                 并裁出 14 种棋子(红黑各 7 种)的匹配模板
  2. recognize : 对任意同窗口截图, 自动定位棋盘(抗截图偏移) ->
                 按 90 个交叉点切格 -> OpenCV 模板匹配识别棋子种类 + 空位

用法:
  python xiangqi_recognizer.py calibrate 开局.png
  python xiangqi_recognizer.py recognize 棋局1.png --debug
  python xiangqi_recognizer.py capture --window 窗口标题   # 截屏并识别(需 pillow)
"""

import argparse
import json
import os
import sys

import cv2
import numpy as np

COLS, ROWS = 9, 10
# 项目根目录(本文件位于 Function/ 子目录内)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALIB_PATH = os.path.join(ROOT, "settings", "calibration.json")
TPL_DIR = os.path.join(ROOT, "templates")

# FEN 字符 -> 中文显示 (大写=红方, 小写=黑方)
CHAR = {
    "R": "车", "N": "马", "B": "相", "A": "仕", "K": "帅", "C": "炮", "P": "兵",
    "r": "车", "n": "马", "b": "象", "a": "士", "k": "将", "c": "炮", "p": "卒",
}
# 各棋子数量上限, 用于识别结果自检
MAX_COUNT = {"K": 1, "k": 1, "A": 2, "a": 2, "B": 2, "b": 2, "N": 2, "n": 2,
             "R": 2, "r": 2, "C": 2, "c": 2, "P": 5, "p": 5}

# 标准开局布局: (row, col, FEN字符), row0 = 黑方底线(图顶部)
_back = "rnbakabnr"
OPENING = [(0, c, ch) for c, ch in enumerate(_back)]
OPENING += [(2, 1, "c"), (2, 7, "c")]
OPENING += [(3, c, "p") for c in (0, 2, 4, 6, 8)]
OPENING += [(6, c, "P") for c in (0, 2, 4, 6, 8)]
OPENING += [(7, 1, "C"), (7, 7, "C")]
OPENING += [(9, c, ch) for c, ch in enumerate(_back.upper())]


# ---------------------------------------------------------------- 基础工具

def imread(path):
    """支持中文路径读图"""
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"无法读取图片: {path}")
    return img


def imwrite_cn(path, img):
    """支持中文路径写图"""
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise IOError(f"图片编码失败: {path}")
    buf.tofile(path)


def resize_to_width(img, width):
    if img.shape[1] == width:
        return img
    s = width / img.shape[1]
    size = (width, max(1, round(img.shape[0] * s)))
    return cv2.resize(img, size, interpolation=cv2.INTER_AREA)


def board_bbox(img):
    """按木纹颜色分割定位棋盘区域, 返回 (x, y, w, h)"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (8, 40, 110), (38, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n <= 1:
        raise RuntimeError("未找到棋盘区域(木纹色块), 请检查截图")
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h = stats[i, 0], stats[i, 1], stats[i, 2], stats[i, 3]
    return int(x), int(y), int(w), int(h)


def cluster1d(vals, tol):
    """一维聚类, 返回按值排序的 [(均值, 数量), ...]"""
    vals = sorted(float(v) for v in vals)
    groups = []
    for v in vals:
        if groups and v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [(float(np.mean(g)), len(g)) for g in groups]


def piece_centers(gray):
    """霍夫圆检测棋子, 返回 (中心数组 Nx2, 中位半径)"""
    r_est = 0.042 * gray.shape[1]
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    circles = cv2.HoughCircles(
        blurred, cv2.HOUGH_GRADIENT, dp=1, minDist=r_est * 1.5,
        param1=120, param2=28,
        minRadius=int(r_est * 0.75), maxRadius=int(r_est * 1.35),
    )
    if circles is None:
        return np.zeros((0, 2)), int(round(r_est))
    c = circles[0].astype(float)
    return c[:, :2], int(round(np.median(c[:, 2])))


def refine_offset(vals, base, d, n_lines, max_off=8.0):
    """微调网格相位: 让检测到的棋子圆心尽量贴合网格线, 抗截图整体偏移"""
    if len(vals) == 0:
        return 0.0
    lines = base + np.arange(n_lines, dtype=float) * d
    best, best_cost = 0.0, None
    for delta in np.arange(-max_off, max_off + 0.001, 0.5):
        dist = np.abs(vals[:, None] - (lines + delta)[None, :]).min(axis=1)
        cost = float(np.minimum(dist, d * 0.35).sum())
        if best_cost is None or cost < best_cost:
            best, best_cost = float(delta), cost
    return best


# ---------------------------------------------------------------- 标定

def calibrate(img_path):
    """用开局截图标定网格并生成 14 种棋子模板"""
    print(f"[标定] 读取 {img_path}")
    img = imread(img_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bx, by, bw, bh = board_bbox(img)
    centers, r_med = piece_centers(gray)
    # 只保留棋盘区域内的圆心, 防止画面其他位置的误检圆污染行/列聚类
    if len(centers):
        keep = ((centers[:, 0] >= bx) & (centers[:, 0] <= bx + bw)
                & (centers[:, 1] >= by) & (centers[:, 1] <= by + bh))
        centers = centers[keep]
    print(f"[标定] 棋盘区域 x={bx} y={by} w={bw} h={bh}, 检测到棋子圆 {len(centers)} 个, 半径≈{r_med}")
    if len(centers) < 20:
        raise RuntimeError("棋子检测过少, 标定请使用开局(32 子)截图")

    tol = r_med * 0.35
    xs = [g for g in cluster1d(centers[:, 0], tol) if g[1] >= 2]
    ys = [g for g in cluster1d(centers[:, 1], tol) if g[1] >= 2]
    if len(xs) != COLS:
        raise RuntimeError(f"列聚类数 {len(xs)} != {COLS}, 请确认使用的是开局截图")
    if len(ys) < 2:
        raise RuntimeError("行聚类异常, 无法标定")

    x0, x8 = xs[0][0], xs[-1][0]
    dx = (x8 - x0) / (COLS - 1)
    y0, y9 = ys[0][0], ys[-1][0]
    dy = (y9 - y0) / (ROWS - 1)
    # 校验: 网格间距必须落在图片范围内, 且纵横比例接近象棋棋盘(纵略高)
    if dx <= 0 or dy <= 0 or dy / dx < 0.85 or dy / dx > 1.35:
        raise RuntimeError(
            f"网格间距异常 (dx={dx:.1f}, dy={dy:.1f}), "
            "截图可能包含棋盘以外的内容, 请使用干净的棋盘截图重新标定")
    if x0 < 0 or y0 < 0 or x8 >= gray.shape[1] or y9 >= gray.shape[0]:
        raise RuntimeError("网格超出图片边界, 请重新截取棋盘区域标定")
    # 校验: 开局所有行/列均应贴合整数网格
    for m, _ in xs:
        k = round((m - x0) / dx)
        assert 0 <= k < COLS and abs(x0 + k * dx - m) < tol * 1.6, f"列贴合校验失败: {m}"
    for m, _ in ys:
        k = round((m - y0) / dy)
        assert 0 <= k < ROWS and abs(y0 + k * dy - m) < tol * 1.6, f"行贴合校验失败: {m}"
    print(f"[标定] 网格: x0={x0:.1f} dx={dx:.2f} | y0={y0:.1f} dy={dy:.2f}")

    # 从开局已知布局裁出每种棋子的模板 (棋子直径 2r)
    half = int(round(r_med * 1.02))
    side = 2 * half
    os.makedirs(TPL_DIR, exist_ok=True)
    seen = set()
    for row, col, ch in OPENING:
        if ch in seen:
            continue
        seen.add(ch)
        cx, cy = int(round(x0 + col * dx)), int(round(y0 + row * dy))
        patch = gray[cy - half:cy + half, cx - half:cx + half]
        assert patch.shape == (side, side), "开局棋子模板裁切越界"
        # Windows 文件名大小写不敏感, 必须加颜色前缀区分红黑
        tag = "red" if ch.isupper() else "blk"
        out = os.path.join(TPL_DIR, f"tpl_{tag}_{ch}.png")
        imwrite_cn(out, patch)

    cal = {
        "width": int(img.shape[1]),
        "r": int(r_med),
        # 网格坐标相对棋盘外框的比例 (随窗口平移/等比缩放自适应)
        "fx0": (x0 - bx) / bw, "fdx": dx / bw,
        "fy0": (y0 - by) / bh, "fdy": dy / bh,
    }
    with open(CALIB_PATH, "w", encoding="utf-8") as f:
        json.dump(cal, f, ensure_ascii=False, indent=2)
    print(f"[标定] 完成: 模板 {len(seen)} 种 -> {TPL_DIR}, 标定 -> {CALIB_PATH}")


def migrate_calib(cal):
    """旧版标定(绝对坐标) -> 新版比例坐标, 并回写文件"""
    if "fx0" in cal or "x0" not in cal:
        return cal
    bw, bh = cal["bw"], cal["bh"]
    cal["fx0"] = (cal["x0"] - cal["bx"]) / bw
    cal["fdx"] = cal["dx"] / bw
    cal["fy0"] = (cal["y0"] - cal["by"]) / bh
    cal["fdy"] = cal["dy"] / bh
    with open(CALIB_PATH, "w", encoding="utf-8") as f:
        json.dump(cal, f, ensure_ascii=False, indent=2)
    print(f"[标定] 检测到旧版标定格式, 已转换为新格式 -> {CALIB_PATH}")
    return cal


def load_calib_and_templates():
    if not os.path.exists(CALIB_PATH):
        print("未找到标定文件, 先用 开局.png 自动标定 ...")
        calibrate("开局.png")
    with open(CALIB_PATH, encoding="utf-8") as f:
        cal = migrate_calib(json.load(f))
    tpls = {}
    for ch in CHAR:
        tag = "red" if ch.isupper() else "blk"
        p = os.path.join(TPL_DIR, f"tpl_{tag}_{ch}.png")
        data = np.fromfile(p, dtype=np.uint8)
        t = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
        if t is None:
            raise RuntimeError(f"缺少模板 {p}, 请重新执行 calibrate")
        tpls[ch] = t
    return cal, tpls


# ---------------------------------------------------------------- 识别

def recognize(img_path, thr=0.55, debug=False, debug_out=None):
    cal, tpls = load_calib_and_templates()
    img = resize_to_width(imread(img_path), cal["width"])
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = gray.shape
    r, slack = cal["r"], max(6, int(cal["r"] * 0.45))
    pad = r + slack + 2

    # 1) 定位棋盘外框 -> 换算网格 (随窗口偏移自适应)
    bx, by, bw, bh = board_bbox(img)
    x0 = bx + cal["fx0"] * bw
    dx = cal["fdx"] * bw
    y0 = by + cal["fy0"] * bh
    dy = cal["fdy"] * bh

    # 2) 用棋子圆心对网格相位微调, 抵抗截图微小偏移
    centers, _ = piece_centers(gray)
    x0 += refine_offset(centers[:, 0], x0, dx, COLS)
    y0 += refine_offset(centers[:, 1], y0, dy, ROWS)
    print(f"[识别] 棋盘外框=({bx},{by},{bw},{bh}), 网格 x0={x0:.1f} dx={dx:.2f} y0={y0:.1f} dy={dy:.2f}")

    # 标定数据失效保护: 网格必须完整落在图片内, 否则切格越界会导致模板匹配崩溃
    if dx <= 0 or dy <= 0 or x0 < 0 or y0 < 0 \
            or x0 + (COLS - 1) * dx > W - 1 or y0 + (ROWS - 1) * dy > H - 1:
        raise RuntimeError(
            "网格坐标超出截图范围, 标定数据可能已失效, 请删除 settings/calibration.json 重新标定")

    # 3) 逐交叉点切格 + 模板匹配
    gp = cv2.copyMakeBorder(gray, pad, pad, pad, pad, cv2.BORDER_REPLICATE)  # 边缘棋子保护
    side = 2 * r
    win = side + 2 * slack
    grid = [[None] * COLS for _ in range(ROWS)]
    score_map = np.zeros((ROWS, COLS))

    for row in range(ROWS):
        for col in range(COLS):
            cx = int(round(x0 + col * dx)) + pad
            cy = int(round(y0 + row * dy)) + pad
            region = gp[cy - r - slack:cy + r + slack, cx - r - slack:cx + r + slack]
            best_ch, best_s = None, -1.0
            for ch, tpl in tpls.items():
                # 模板在窗口内滑动, 取归一化相关系数峰值 (容忍微小偏移)
                res = cv2.matchTemplate(region, tpl, cv2.TM_CCOEFF_NORMED)
                s = float(res.max())
                if s > best_s:
                    best_s, best_ch = s, ch
            score_map[row, col] = best_s
            if best_s >= thr:
                grid[row][col] = best_ch

    # 4) 结果自检: 棋子数量是否超上限
    counts = {}
    for rowline in grid:
        for ch in rowline:
            if ch:
                counts[ch] = counts.get(ch, 0) + 1
    warn = [f"{CHAR[ch]}({ch}) x{n} 超上限{MAX_COUNT[ch]}"
            for ch, n in sorted(counts.items()) if n > MAX_COUNT.get(ch, 99)]

    # 5) 输出
    print(f"\n识别结果 ({img_path}, 阈值={thr}):")
    print("    " + " ".join(str(c) for c in range(COLS)))
    for row in range(ROWS):
        cells = [CHAR[ch] if ch else "．" for ch in grid[row]]
        side_tag = "黑" if row < 5 else "红"
        print(f" {row}{side_tag} " + " ".join(cells))
    fen_rows = []
    for row in range(ROWS):
        s, emp = "", 0
        for ch in grid[row]:
            if ch is None:
                emp += 1
            else:
                if emp:
                    s += str(emp)
                    emp = 0
                s += ch
        if emp:
            s += str(emp)
        fen_rows.append(s)
    fen = "/".join(fen_rows)
    print(f"\nFEN(局面): {fen}")
    total = sum(counts.values())
    print(f"棋子总数: {total}")
    if warn:
        print("警告: " + "; ".join(warn))

    if debug or debug_out:
        show = draw_debug(img, grid, x0, y0, dx, dy, r, bx, by, bw, bh, score_map, thr)
        out = debug_out or (os.path.splitext(img_path)[0] + "_debug.png")
        imwrite_cn(out, show)
        print(f"标注图已保存: {out}")
    return grid, fen


def draw_debug(img, grid, x0, y0, dx, dy, r, bx, by, bw, bh, score_map, thr):
    show = img.copy()
    cv2.rectangle(show, (bx, by), (bx + bw, by + bh), (255, 0, 0), 2)
    for row in range(ROWS):
        for col in range(COLS):
            cx, cy = int(round(x0 + col * dx)), int(round(y0 + row * dy))
            ch = grid[row][col]
            color = (0, 200, 0) if ch else (160, 160, 160)
            cv2.circle(show, (cx, cy), 2, color, -1)
            if ch:
                cv2.circle(show, (cx, cy), r, (0, 200, 0), 1)
                red = ch.isupper()
                cv2.putText(show, ch, (cx - 10, cy - r - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                            (0, 0, 255) if red else (0, 0, 0), 2)
    return show


# ---------------------------------------------------------------- 截屏入口

def capture(window=None, thr=0.55, debug=False):
    try:
        from PIL import ImageGrab
    except ImportError:
        print("需要 pillow: pip install pillow")
        return 1
    bbox = None
    if window:
        try:
            import pygetwindow as gw
            wins = [w for w in gw.getAllWindows() if window in w.title and w.width > 100]
            if wins:
                w = wins[0]
                bbox = (w.left, w.top, w.right, w.bottom)
                print(f"[截屏] 窗口 '{w.title}' {bbox}")
            else:
                print(f"[截屏] 未找到含 '{window}' 的窗口, 改为全屏截取")
        except ImportError:
            print("窗口定位需 pygetwindow: pip install pygetwindow (已改为全屏截取)")
    out = "screen.png"
    ImageGrab.grab(bbox=bbox, all_screens=True).save(out)
    print(f"[截屏] 已保存 {out}")
    recognize(out, thr=thr, debug=debug)
    return 0


def main():
    ap = argparse.ArgumentParser(description="象棋棋盘截图识别")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("calibrate", help="用开局截图标定网格并生成模板")
    c.add_argument("image")
    r = sub.add_parser("recognize", help="识别棋局截图")
    r.add_argument("image")
    r.add_argument("--thr", type=float, default=0.55, help="棋子判定阈值")
    r.add_argument("--debug", action="store_true", help="输出标注图")
    p = sub.add_parser("capture", help="截屏(可指定窗口)并识别")
    p.add_argument("--window", default=None, help="窗口标题关键字")
    p.add_argument("--thr", type=float, default=0.55)
    p.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    if args.cmd == "calibrate":
        calibrate(args.image)
    elif args.cmd == "recognize":
        recognize(args.image, thr=args.thr, debug=args.debug)
    elif args.cmd == "capture":
        capture(args.window, thr=args.thr, debug=args.debug)


if __name__ == "__main__":
    sys.exit(main() or 0)
