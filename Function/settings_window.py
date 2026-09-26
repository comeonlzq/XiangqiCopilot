#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设置窗口: 棋盘识别 / 常规 / 界面设置 / 引擎 / 走子 选项卡 + 设置持久化"""

import json
import os
import traceback
from functools import partial

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import xiangqi_recognizer as rec

from assistant import (P, ACCENT, CARD, FIELD, FIELD_HOVER, FONT, GREEN,
                       PANEL_BG, SUB, TXT, RoundButton)
from notation import OPEN_GRID

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录
SETTINGS_PATH = os.path.join(BASE, "settings", "engine_settings.json")  # 引擎设置持久化
# 初始化配置标注图(每颗棋子的识别结果)保存在模板目录, 供设置页回显
SETUP_ANN_PATH = os.path.join(BASE, "templates", "init_annotated.png")


# ---------------- 设置持久化 ----------------
def load_settings(app):
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            s = json.load(f)
    except Exception:
        return
    for k in ("engine", "movetime", "depth", "threads", "hash"):
        if k in s:
            setattr(app.args, k, s[k])
    app.topmost = bool(s.get("topmost", True))
    app.hotkey_scan = int(s.get("hotkey_scan", 0x36))
    app.move_mode = int(s.get("move_mode", 0))
    app.move_gap_min = float(s.get("move_gap_min", 0.5))
    app.move_gap_max = float(s.get("move_gap_max", 1.0))
    app.log_translate = bool(s.get("log_translate", True))
    app.show_loss = bool(s.get("show_loss", True))
    app.hide_on_capture = bool(s.get("hide_on_capture", True))


def save_settings(app):
    try:
        data = {k: getattr(app.args, k) for k in
                ("engine", "movetime", "depth", "threads", "hash")}
        data.update({"topmost": app.topmost,
                     "hotkey_scan": app.hotkey_scan,
                     "move_mode": app.move_mode,
                     "move_gap_min": app.move_gap_min,
                     "move_gap_max": app.move_gap_max,
                     "log_translate": app.log_translate,
                     "show_loss": app.show_loss,
                     "hide_on_capture": app.hide_on_capture})
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        print("[设置] 保存失败:")
        traceback.print_exc()


# ---------------- 棋盘识别选项卡 ----------------
def show_image(app, path):
    """把标注图缩放后显示在设置页画布上"""
    try:
        from PIL import Image, ImageTk
        im = Image.open(path)
        maxw, maxh = P(320), P(360)
        s = min(maxw / im.width, maxh / im.height, 1.0)
        im = im.resize((max(1, int(im.width * s)),
                        max(1, int(im.height * s))))
        app._setup_photo = ImageTk.PhotoImage(im)
        cv = app._setup_cv
        cv.delete("all")
        cv.configure(width=im.width, height=im.height)
        cv.create_image(0, 0, anchor="nw", image=app._setup_photo)
    except Exception:
        print("[棋盘识别] 标注图显示失败:")
        traceback.print_exc()


def show_result(app, img_path, msg, ok):
    """在设置页「棋盘识别」展示标注图与识别结论(主线程)"""
    lbl = getattr(app, "_setup_status_lbl", None)
    if lbl is None:
        return
    try:
        if not lbl.winfo_exists():  # 设置窗口已关闭, 忽略结果回显
            return
        lbl.config(text=msg, fg=GREEN if ok else ACCENT)
    except tk.TclError:
        return
    if img_path and os.path.exists(img_path):
        show_image(app, img_path)


def task_setup_capture(app, box):
    """设置页「棋盘识别」: 框选开局棋盘 -> 标定 -> 识别并生成标注图"""
    path = app._grab(box)
    app.set_status("正在标定棋盘...")
    try:
        rec.calibrate(path)
    except Exception as e:
        app.post(lambda: show_result(app, None, f"标定失败: {e}", False))
        return
    try:
        grid, _fen = rec.recognize(path, thr=app.args.thr,
                                   debug_out=SETUP_ANN_PATH)
    except Exception as e:
        app.post(lambda: show_result(app, None, f"识别失败: {e}", False))
        return
    grid = [[c for c in row] for row in grid]
    expect = sum(1 for r in OPEN_GRID for c in r if c)
    got = sum(1 for r in grid for c in r if c)
    wrong = sum(1 for r in range(rec.ROWS) for c in range(rec.COLS)
                if grid[r][c] != OPEN_GRID[r][c])
    if wrong == 0:
        msg = f"识别成功: 开局 {got} 枚棋子全部匹配"
    else:
        msg = (f"识别到 {got}/{expect} 枚棋子, 有 {wrong} 处与开局不符, "
               "请确认棋盘为开局局面后重新截图")
    app.post(lambda: show_result(app, SETUP_ANN_PATH, msg, wrong == 0))
    app.post(app.refresh_capture_ui)  # 标定完成 -> 面板切换到「截图」


def take_screenshot(app):
    """设置页「截图」: (可配)隐藏窗口 -> 全屏框选 -> 后台标定+识别"""
    if app.busy:
        return
    w = app._set_win
    if w is not None and w.winfo_exists():
        w.grab_release()
        if app.hide_on_capture:  # 隐藏设置窗口, 避免被截进框选区域
            w.withdraw()
    try:
        box = app._select_bbox()
    finally:
        if w is not None and w.winfo_exists():
            if app.hide_on_capture:
                w.deiconify()
                w.lift()
            w.grab_set()
    if box is None:
        return
    app.run_task(partial(task_setup_capture, app, box))


# ---------------- 设置窗口 ----------------
def open_settings(app, tab=None):
    """弹出设置窗口: 棋盘识别 / 常规 / 界面设置 / 引擎 / 走子 选项卡
    (ttk 扁平主题), tab 指定要激活的选项卡标题"""
    if app._set_win is not None and app._set_win.winfo_exists():
        app._set_win.deiconify()
        app._set_win.lift()
        f = getattr(app._set_win, "_set_tabs", {}).get(tab)
        if f is not None:
            try:
                app._set_win._nb.select(f)
            except Exception:
                pass
        return
    w = tk.Toplevel(app.root)
    w.title("设置")
    w.configure(bg=PANEL_BG)
    w.resizable(False, False)
    w.attributes("-topmost", True)
    app._set_win = w

    # ---- 选项卡 ----
    nb = ttk.Notebook(w)
    nb.pack(fill="both", expand=True, padx=P(14), pady=(P(14), 0))
    w._nb = nb

    def tab_frame(title):
        f = ttk.Frame(nb, style="Card.TFrame",
                      padding=(P(18), P(10), P(18), P(16)))
        nb.add(f, text=title, sticky="nsew")
        w._set_tabs[title] = f
        return f

    w._set_tabs = {}

    def grow(parent):
        f = ttk.Frame(parent, style="Card.TFrame")
        f.pack(fill="x", pady=(P(10), 0))
        return f

    # ---- 棋盘识别(初始化配置) ----
    bi = tab_frame("棋盘识别")
    ttk.Label(bi, text="首次使用需截取一张「开局局面」图完成标定: "
                       "双方 32 枚棋子就位后点「截图」框选棋盘区域。",
              style="Sub.TLabel", wraplength=P(340),
              justify="left").pack(fill="x")
    r = grow(bi)
    RoundButton(r, text="截图", command=lambda: take_screenshot(app),
                height=34, radius=10, font=(FONT, 11, "bold"),
                frame_bg=CARD).pack(side="left")
    app._setup_status_lbl = tk.Label(bi, bg=CARD, fg=SUB,
                                     font=(FONT, 10), justify="left",
                                     anchor="w", wraplength=P(340))
    app._setup_status_lbl.pack(fill="x", pady=(P(8), 0))
    app._setup_cv = tk.Canvas(bi, bg=CARD, bd=0, highlightthickness=0,
                              width=P(320), height=P(360))
    app._setup_cv.pack(pady=(P(8), 0))
    if os.path.exists(rec.CALIB_PATH):
        if os.path.exists(SETUP_ANN_PATH):
            app._setup_status_lbl.config(
                text="已完成标定, 下图为最近一次初始化识别结果", fg=GREEN)
            show_image(app, SETUP_ANN_PATH)
        else:
            app._setup_status_lbl.config(
                text="已完成标定, 可点「截图」重新标定", fg=GREEN)
    else:
        app._setup_status_lbl.config(
            text="尚未完成初始化配置, 请先截图", fg=ACCENT)

    # ---- 常规设置 ----
    g = tab_frame("常规")
    hotkey_v = tk.IntVar(value=app.hotkey_scan)
    r = grow(g)
    ttk.Label(r, text="建议快捷键", style="Card.TLabel", width=9).pack(
        side="left")
    for text, val in (("右 Shift", 0x36), ("左 Shift", 0x2A),
                      ("F8", 0x42), ("F9", 0x43), ("禁用", 0)):
        ttk.Radiobutton(r, text=text, variable=hotkey_v, value=val,
                        style="Card.TRadiobutton").pack(
            side="left", padx=(0, P(10)))
    ttk.Label(g, text="快捷键全局生效, 任意窗口在前台时均可触发",
              style="Sub.TLabel").pack(anchor="w", pady=(P(10), P(4)))

    # ---- 界面设置 ----
    ui = tab_frame("界面设置")
    topmost_v = tk.BooleanVar(value=app.topmost)
    show_loss_v = tk.BooleanVar(value=app.show_loss)
    hide_cap_v = tk.BooleanVar(value=app.hide_on_capture)
    loss_before = app.show_loss  # 用于「应用」后判断是否需要重绘局面图
    r = grow(ui)
    ttk.Label(r, text="窗口置顶", style="Card.TLabel", width=9).pack(
        side="left")
    ttk.Checkbutton(r, text="面板与状态栏保持在最前", variable=topmost_v,
                    style="Card.TCheckbutton").pack(side="left")
    r = grow(ui)
    ttk.Label(r, text="损失棋子", style="Card.TLabel", width=9).pack(
        side="left")
    ttk.Checkbutton(r, text="在局面图右侧显示双方被吃掉的棋子",
                    variable=show_loss_v,
                    style="Card.TCheckbutton").pack(side="left")
    r = grow(ui)
    ttk.Label(r, text="截图隐藏", style="Card.TLabel", width=9).pack(
        side="left")
    ttk.Checkbutton(r, text="标定截图框选时自动隐藏设置窗口",
                    variable=hide_cap_v,
                    style="Card.TCheckbutton").pack(side="left")
    ttk.Label(ui, text="以上选项点击「应用」后生效, 无需重启引擎",
              style="Sub.TLabel").pack(anchor="w", pady=(P(10), P(4)))

    # ---- 引擎设置 ----
    a = app.args
    e = tab_frame("引擎")
    path_v = tk.StringVar(value=str(a.engine))
    mt_v = tk.StringVar(value=str(a.movetime))
    dp_v = tk.StringVar(value=str(getattr(a, "depth", 0)))
    th_v = tk.StringVar(value=str(a.threads))
    hs_v = tk.StringVar(value=str(a.hash))

    def row(label):
        f = ttk.Frame(e, style="Card.TFrame")
        f.pack(fill="x", pady=(P(10), 0))
        ttk.Label(f, text=label, style="Card.TLabel", width=9).pack(
            side="left")
        return f

    def spin(parent, var, lo, hi):
        ttk.Spinbox(parent, textvariable=var, from_=lo, to=hi, width=7,
                    style="Field.TSpinbox").pack(side="left")

    r = row("引擎路径")
    ttk.Entry(r, textvariable=path_v, style="Field.TEntry").pack(
        side="left", fill="x", expand=True)
    RoundButton(r, text="浏览...", height=28, radius=8, bg=FIELD, fg=TXT,
                hover=FIELD_HOVER, font=(FONT, 9), frame_bg=CARD,
                command=lambda: path_v.set(
                    filedialog.askopenfilename(
                        title="选择 UCI 引擎",
                        filetypes=[("可执行文件", "*.exe"),
                                   ("所有文件", "*.*")])
                    or path_v.get())).pack(side="left", padx=(P(10), 0))
    r = row("思考时间")
    spin(r, mt_v, 0, 60000)
    ttk.Label(r, text="ms (0=引擎默认)", style="Sub.TLabel").pack(
        side="left", padx=(P(6), 0))
    r = row("搜索深度")
    spin(r, dp_v, 0, 60)
    ttk.Label(r, text="层 (0=按思考时间)", style="Sub.TLabel").pack(
        side="left", padx=(P(6), 0))
    r = row("线程数")
    spin(r, th_v, 1, 128)
    r = row("置换表")
    spin(r, hs_v, 16, 4096)
    ttk.Label(r, text="MB", style="Sub.TLabel").pack(side="left",
                                                     padx=(P(6), 0))
    log_lt_v = tk.BooleanVar(value=app.log_translate)
    r = row("日志转译")
    ttk.Checkbutton(r, text="思考过程转译为中文(关闭则显示原始输出)",
                    variable=log_lt_v,
                    style="Card.TCheckbutton").pack(side="left")
    ttk.Label(e, text="深度 > 0 时按深度搜索, 否则按思考时间; "
                      "修改路径/线程/置换表会重启引擎",
              style="Sub.TLabel", wraplength=P(320),
              justify="left").pack(fill="x", pady=(P(10), P(4)))

    # ---- 走子设置 ----
    mv = tab_frame("走子")
    move_v = tk.IntVar(value=app.move_mode)
    for text, val, desc in (
            ("无", 0, "仅显示建议与棋盘标记, 手动走子"),
            ("自动移动鼠标", 1, "给出建议后, 鼠标自动移到推荐起点"),
            ("自动走子", 2, "给出建议后, 自动点击起点再点击落点")):
        r = grow(mv)
        ttk.Radiobutton(r, text=text, variable=move_v, value=val,
                        style="Card.TRadiobutton").pack(side="top",
                                                        anchor="w")
        ttk.Label(r, text="        " + desc, style="Sub.TLabel").pack(
            side="top", anchor="w")
    gap_min_v = tk.StringVar(value=f"{app.move_gap_min:g}")
    gap_max_v = tk.StringVar(value=f"{app.move_gap_max:g}")
    r = grow(mv)
    ttk.Label(r, text="点击间隔范围", style="Card.TLabel", width=9).pack(
        side="left")
    ttk.Spinbox(r, textvariable=gap_min_v, from_=0.1, to=30.0,
                increment=0.1, format="%.1f", width=5,
                style="Field.TSpinbox").pack(side="left")
    ttk.Label(r, text="~", style="Sub.TLabel").pack(side="left",
                                                    padx=P(6))
    ttk.Spinbox(r, textvariable=gap_max_v, from_=0.1, to=30.0,
                increment=0.1, format="%.1f", width=5,
                style="Field.TSpinbox").pack(side="left")
    ttk.Label(r, text="秒 (两次点击间的随机等待)",
              style="Sub.TLabel").pack(side="left", padx=(P(6), 0))
    ttk.Label(mv, text="自动走子通过模拟鼠标两次点击完成(起点→落点), 请勿遮挡棋盘窗口",
              style="Sub.TLabel").pack(anchor="w", pady=(P(10), P(4)))

    def apply():
        path = path_v.get().strip().strip('"')
        if not path:
            messagebox.showerror("设置", "请填写引擎路径")
            return
        try:
            mt, dp = int(mt_v.get()), int(dp_v.get())
            th, hs = int(th_v.get()), int(hs_v.get())
            gmin, gmax = float(gap_min_v.get()), float(gap_max_v.get())
        except ValueError:
            messagebox.showerror("设置", "数值格式不正确")
            return
        if gmin <= 0 or gmax <= 0:
            messagebox.showerror("设置", "点击间隔须大于 0 秒")
            return
        if app.busy:
            messagebox.showinfo("设置", "正在计算中, 请稍后再应用")
            return
        restart = (app.engine is None or path != a.engine
                   or th != a.threads or hs != a.hash)
        a.engine, a.movetime, a.depth = path, max(0, mt), max(0, dp)
        a.threads, a.hash = max(1, th), max(16, hs)
        app.topmost = bool(topmost_v.get())
        app.hotkey_scan = int(hotkey_v.get())
        app.move_mode = int(move_v.get())
        app.move_gap_min = min(gmin, gmax)
        app.move_gap_max = max(gmin, gmax)
        app.log_translate = bool(log_lt_v.get())
        app.show_loss = bool(show_loss_v.get())
        app.hide_on_capture = bool(hide_cap_v.get())
        save_settings(app)
        app.refresh_hotkey_hint()  # 按钮快捷键提示即时更新
        for win in (app.panel, app.statusbar):  # 置顶即时生效
            if win is not None:
                try:
                    win.wm_attributes("-topmost", app.topmost)
                except Exception:
                    pass
        if app.show_loss != loss_before:  # 损子显隐即时重绘局面图
            app.redraw_board()
        w.destroy()
        if restart:
            app.run_task(app.task_restart_engine)
        else:
            app.set_status("设置已应用: "
                           + (f"深度{dp}" if dp else f"思考{mt}ms"))

    btns = ttk.Frame(w, style="Panel.TFrame")
    btns.pack(fill="x", padx=P(18), pady=(P(12), P(16)))
    RoundButton(btns, text="应用", command=apply, height=36, radius=10,
                width=92, font=(FONT, 11, "bold"),
                frame_bg=PANEL_BG).pack(side="right")
    RoundButton(btns, text="取消", command=w.destroy, height=36,
                radius=10, width=92, bg=FIELD, fg=TXT,
                hover=FIELD_HOVER, font=(FONT, 11),
                frame_bg=PANEL_BG).pack(side="right", padx=(0, P(10)))

    w.update_idletasks()
    w.geometry(f"+{app.panel.winfo_x() + P(40)}"
               f"+{app.panel.winfo_y() + P(40)}")
    w.grab_set()
    w.focus_set()
