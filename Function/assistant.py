#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对局助手主体: 截图识谱、着法同步、引擎提示、悬浮面板 GUI"""

import json
import math
import os
import random
import re
import shutil
import threading
import time
import traceback
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk

import xiangqi_recognizer as rec

from engine import UciEngine
from notation import (NAME, OPEN_GRID, apply_move, cn_notation, detect_move,
                      flip_fen, flip_square, parse_square, square_name)
from overlay import overlay_window, select_box

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录

# 高 DPI 适配: 进程声明 DPI 感知后, 系统不再拉伸窗口, 而 tkinter 字体按「磅」
# 会随真实 DPI 放大, 但本文件的布局大量使用「固定像素」(面板宽/按钮高/圆角/
# 内边距等), 这些不会自动放大, 于是在 125%/150% 缩放屏上整体显得偏小。
# UI_SCALE = 系统缩放倍率(96dpi=1.0, 144dpi=1.5), 所有像素常量乘以它。
UI_SCALE = 1.0


def _compute_ui_scale(root):
    """读取系统 DPI, 计算界面缩放倍率(仅影响像素布局, 不动字体磅值)"""
    dpi = 96.0
    try:
        import ctypes
        dpi = float(ctypes.windll.user32.GetDpiForSystem())
    except Exception:
        try:  # 回退: "1i" 即 1 英寸对应的像素数 = 当前 DPI
            dpi = float(root.winfo_fpixels("1i"))
        except Exception:
            dpi = 96.0
    if dpi <= 0:
        dpi = 96.0
    return max(1.0, round(dpi / 96.0, 3))


def P(n):
    """把设计稿(96dpi)像素常量换算为当前系统缩放下的实际像素"""
    return max(1, int(round(n * UI_SCALE)))


# 浅色主题: 灰阶 + 单一强调色(象棋红)
PANEL_BG = "#f5f6f8"  # 悬浮面板底色
CARD = "#ffffff"      # 卡片底
LINE = "#e8eaee"      # 分隔线/描边
FIELD = "#eef0f3"     # 次级按钮/输入框底
TXT = "#2b2f36"       # 主文字
SUB = "#9aa1ab"       # 次要文字
FAINT = "#b6bcc4"     # 弱文字
ACCENT = "#d93a2b"    # 强调红(建议/主按钮)
GREEN = "#34a467"     # 引擎就绪圆点
AMBER = "#e6a23c"     # 引擎思考中圆点
ACCENT_HOVER = "#c33124"   # 主按钮悬停
FIELD_HOVER = "#e3e6ea"    # 次级按钮悬停
ICON_HOVER = "#e9ebef"     # 图标按钮悬停
KEY = "#010203"       # 透明键色: 实现窗口圆角
FONT = "Microsoft YaHei"
HOTKEY_NAMES = {0x36: "右Shift", 0x2A: "左Shift", 0x42: "F8", 0x43: "F9"}
# 棋子价值(用于损子展示排序, 大子在前)
PIECE_VAL = {"K": 10000, "A": 200, "N": 170, "B": 120, "R": 100, "C": 90, "P": 50}


# ---------------- 圆角控件与主题 ----------------
def _round_rect(cv, x1, y1, x2, y2, r, **kw):
    """在 Canvas 上绘制圆角矩形(smooth 多边形)"""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


class Card(tk.Frame):
    """圆角卡片: 自身与画布用父底色「融边」, inner 为内容容器.
    内容内边距 pad >= radius 时, 方角子控件不会溢出圆角轮廓."""

    def __init__(self, master, radius=12, fill=CARD, bg=PANEL_BG, pad=None,
                 border=True):
        super().__init__(master, bg=bg)
        pad = radius if pad is None else pad
        radius, pad = P(radius), P(pad)
        self.cv = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.cv.place(x=0, y=0, relwidth=1, relheight=1)
        self.inner = tk.Frame(self, bg=fill)
        self.inner.pack(fill="both", expand=True, padx=pad, pady=pad)

        def redraw(e):
            self.cv.delete("all")
            _round_rect(self.cv, 0, 0, max(e.width - 1, 2),
                        max(e.height - 1, 2), radius,
                        fill=fill, outline=LINE if border else "", width=1)

        self.cv.bind("<Configure>", redraw)


class RoundButton(tk.Canvas):
    """扁平圆角按钮, 兼容 tk.Button 的 config(state=...) 用法"""

    def __init__(self, master, text="", command=None, bg=ACCENT, fg="#ffffff",
                 hover=ACCENT_HOVER, font=(FONT, 12, "bold"), height=40,
                 radius=12, width=None, disabled_bg=FIELD,
                 disabled_fg=FAINT, frame_bg=None):
        fb = master.cget("bg") if frame_bg is None else frame_bg
        super().__init__(master, bg=fb, highlightthickness=0, bd=0,
                         height=P(height))
        self._text, self._command = text, command
        self._bg, self._fg, self._hover = bg, fg, hover
        self._dbg, self._dfg = disabled_bg, disabled_fg
        self._font, self._radius = font, P(radius)
        self._state = tk.NORMAL
        self._hovering = False
        self._pressed = False
        if width is None:  # measure 返回的已是真实像素, 只需缩放内边距
            width = tkfont.Font(font=font).measure(text) + P(28)
        else:
            width = P(width)
        self.configure(width=width)
        self.bind("<Configure>", self._draw)
        self.bind("<Enter>", lambda e: (setattr(self, "_hovering", True),
                                        self._draw()))
        self.bind("<Leave>", lambda e: (setattr(self, "_hovering", False),
                                        setattr(self, "_pressed", False),
                                        self._draw()))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self._set_cursor()

    def _set_cursor(self):
        self.config(cursor="arrow" if self._state == tk.DISABLED else "hand2")

    def configure(self, cnf=None, **kw):
        if "state" in kw:
            self._state = kw.pop("state")
            self._set_cursor()
        if "text" in kw:
            self._text = kw.pop("text")
        if kw or cnf:
            tk.Canvas.configure(self, cnf, **kw)
        self._draw()

    config = configure

    def _press(self, _e):
        if self._state == tk.DISABLED:
            return
        self._pressed = True
        self._draw()

    def _release(self, e):
        if self._state == tk.DISABLED:
            return
        ok = (self._pressed and self._command
              and 0 <= e.x <= self.winfo_width()
              and 0 <= e.y <= self.winfo_height())
        self._pressed = False
        self._draw()
        if ok:
            self._command()

    def _draw(self, _e=None):
        self.delete("all")
        w = max(self.winfo_width(), int(self.cget("width")), 2)
        h = max(self.winfo_height(), int(self.cget("height")), 2)
        if self._state == tk.DISABLED:
            fill, fg = self._dbg, self._dfg
        elif self._pressed:
            fill, fg = self._hover, self._fg
        elif self._hovering:
            fill, fg = self._hover, self._fg
        else:
            fill, fg = self._bg, self._fg
        _round_rect(self, 0, 0, w - 1, h - 1,
                    min(self._radius, h // 2), fill=fill, outline="")
        self.create_text(w // 2, h // 2, text=self._text, fill=fg,
                         font=self._font)


class Pill(tk.Frame):
    """胶囊标签底: 圆角 FIELD 底 + 居中文本.
    label 必须建在内部 canvas 上(成为其子窗口), 否则会被不透明的画布盖住,
    只显示胶囊底色而看不到文字."""

    def __init__(self, master, text="", fill=FIELD, fg=SUB, font=(FONT, 9),
                 radius=9, padx=9, pady=3, bg=None):
        bg = master.cget("bg") if bg is None else bg
        super().__init__(master, bg=bg)
        self.cv = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        self._fill, self._radius = fill, P(radius)
        self._padx, self._pady = P(padx), P(pady)
        self._pw = self._ph = 1
        self.label = tk.Label(self.cv, text=text, bg=fill, fg=fg, font=font)
        self.label.bind("<Configure>", self.sync)
        self.sync()

    def sync(self, _e=None):
        lw = self.label.winfo_reqwidth()
        lh = self.label.winfo_reqheight()
        self._pw, self._ph = lw + 2 * self._padx, lh + 2 * self._pady
        self.cv.configure(width=self._pw, height=self._ph)
        self._draw()

    def _draw(self):
        self.cv.delete("all")
        _round_rect(self.cv, 0, 0, self._pw - 1, self._ph - 1, self._radius,
                    fill=self._fill, outline="")
        self.cv.create_window(self._pw / 2, self._ph / 2, window=self.label)

    def configure(self, cnf=None, **kw):
        # text/fg 转发给内部 label, 其余按 Frame 选项处理
        sub = {k: kw.pop(k) for k in ("text", "fg", "foreground") if k in kw}
        if cnf:
            for k in ("text", "fg", "foreground"):
                if k in cnf:
                    sub[k] = cnf[k]
                    cnf = {kk: vv for kk, vv in cnf.items() if kk != k}
        if sub:
            self.label.configure(**sub)
        if kw or cnf:
            tk.Frame.configure(self, cnf, **kw)
        self.sync()

    config = configure


def _flat_indicator_imgs(root, style):
    """用 Pillow 生成扁平勾选框/单选圆点图, 替换 clam 自带立体指示器;
    失败(如无 Pillow)返回 False, 由调用方回退原生配色"""
    try:
        from PIL import Image, ImageDraw, ImageTk
    except Exception:
        return False
    s = P(16)   # 指示器图形边长
    gap = P(8)  # 图形与文字间距
    k = 4       # 超采样倍率(缩小抗锯齿)
    keep = []   # 持有 PhotoImage 引用, 防止被垃圾回收

    def mk(kind, on, hover):
        u = s * k  # 超采样后的图形边长
        im = Image.new("RGBA", ((s + gap) * k, u), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        if kind == "check":
            if on:
                d.rounded_rectangle([0, 0, u - 1, u - 1], radius=u * 0.28,
                                    fill=ACCENT_HOVER if hover else ACCENT)
                lw = max(2 * k, int(u * 0.14))
                d.line([(u * 0.24, u * 0.52), (u * 0.42, u * 0.70),
                        (u * 0.76, u * 0.32)], fill="#ffffff", width=lw,
                       joint="curve")
            else:
                d.rounded_rectangle([0, 0, u - 1, u - 1], radius=u * 0.28,
                                    fill="#ffffff",
                                    outline="#b9c0c9" if hover else "#c9ced6",
                                    width=k)
        else:  # radio
            d.ellipse([k // 2, k // 2, u - 1 - k // 2, u - 1 - k // 2],
                      fill="#ffffff",
                      outline=ACCENT if on else
                      ("#aeb6c0" if hover else "#c2c8d1"),
                      width=max(k, int(u * 0.11)))
            if on:
                c, r = u / 2, u * 0.21
                d.ellipse([c - r, c - r, c + r, c + r], fill=ACCENT)
        pi = ImageTk.PhotoImage(im.resize((s + gap, s), Image.LANCZOS),
                                master=root)
        keep.append(pi)
        return pi

    try:
        for cls, kind, ind in (("TCheckbutton", "check", "Card.Checkbox.indicator"),
                               ("TRadiobutton", "radio", "Card.Radio.indicator")):
            style.element_create(ind, "image",
                                 mk(kind, False, False),
                                 ("active", mk(kind, False, True)),
                                 ("selected", mk(kind, True, False)),
                                 ("selected active", mk(kind, True, True)),
                                 sticky="w")
            pfx = cls[1:]  # Checkbutton / Radiobutton
            style.layout(f"Card.{cls}", [
                (f"{pfx}.padding", {
                    "side": "left", "sticky": "", "expand": 1,
                    "children": [
                        (ind, {"side": "left", "sticky": ""}),
                        (f"{pfx}.focus", {
                            "side": "left", "expand": 1,
                            "children": [
                                (f"{pfx}.label",
                                 {"side": "left", "sticky": "nswe"})]})]})])
    except Exception:
        return False
    root._flat_ind_imgs = keep
    return True


def _init_style(root):
    """ttk.Style: 为设置窗口等标准控件配置扁平主题"""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", background=PANEL_BG, font=(FONT, 10))
    style.configure("Panel.TFrame", background=PANEL_BG)
    style.configure("Card.TFrame", background=CARD)
    style.configure("Card.TLabel", background=CARD, foreground=TXT,
                    font=(FONT, 10))
    style.configure("Sub.TLabel", background=CARD, foreground=SUB,
                    font=(FONT, 9))
    # 扁平选项卡: 无背景色无边框, 文字均为黑色; 激活项仅加粗标识;
    # 固定 padding 防止切换时尺寸跳动
    _tab_pad = (P(16), P(9))
    style.configure("TNotebook", background=PANEL_BG, borderwidth=0)
    style.configure("TNotebook.Tab", background=PANEL_BG, foreground=TXT,
                    padding=_tab_pad, font=(FONT, 10), borderwidth=0,
                    lightcolor=PANEL_BG, darkcolor=PANEL_BG)
    style.map("TNotebook.Tab",
              background=[("selected", PANEL_BG), ("active", PANEL_BG)],
              foreground=[("selected", TXT), ("active", TXT)],
              font=[("selected", (FONT, 10, "bold"))],
              lightcolor=[("selected", PANEL_BG), ("active", PANEL_BG)],
              darkcolor=[("selected", PANEL_BG), ("active", PANEL_BG)],
              padding=[("selected", _tab_pad), ("active", _tab_pad)])
    for cls in ("TEntry", "TSpinbox"):
        style.configure(f"Field.{cls}", fieldbackground=FIELD,
                        background=FIELD, foreground=TXT,
                        bordercolor=FIELD, lightcolor=FIELD,
                        darkcolor=FIELD, relief="flat", padding=P(6),
                        arrowcolor=TXT, insertcolor=TXT, font=(FONT, 10))
        style.map(f"Field.{cls}",
                  bordercolor=[("focus", ACCENT)],
                  lightcolor=[("focus", ACCENT)],
                  darkcolor=[("focus", ACCENT)])
    for cls in ("TCheckbutton", "TRadiobutton"):
        style.configure(f"Card.{cls}", background=CARD, foreground=TXT,
                        focuscolor=CARD, font=(FONT, 10), padding=P(4))
        style.map(f"Card.{cls}",
                  background=[("active", CARD)],
                  foreground=[("active", TXT)])
    if not _flat_indicator_imgs(root, style):
        # 无 Pillow 时回退 clam 原生指示器配色
        for cls in ("TCheckbutton", "TRadiobutton"):
            style.map(f"Card.{cls}",
                      indicatorcolor=[("selected", ACCENT),
                                      ("active", "#dfe2e6")])


class Assistant:
    def __init__(self, args, root):
        self.args = args
        if not hasattr(args, "depth"):
            args.depth = 0        # 搜索深度(0=按思考时间)
        self.topmost = True       # 面板/状态栏置顶
        self.hotkey_scan = 0x36   # 「给出建议」快捷键扫描码(0=禁用)
        self.move_mode = 0        # 走子模式: 0无 / 1移动鼠标 / 2自动走子
        self.move_gap_min = 0.5   # 自动走子两次点击随机间隔下限(秒)
        self.move_gap_max = 1.0   # 自动走子两次点击随机间隔上限(秒)
        self.show_loss = True     # 棋盘右侧显示双方损失棋子
        self.hide_on_capture = True  # 设置页截图框选时自动隐藏设置窗口
        self._load_settings()     # 恢复上次保存的设置
        self.root = root
        self.bbox = None          # 框选区域 (x1,y1,x2,y2)
        self.prev = None          # 上次同步的棋盘 (ROWS x COLS)
        self.moves = []           # UCI 着法序列(开局起, 双方)
        self.use_startpos = False
        self.desync = False       # 着法序列不可信时改用 FEN 定位
        self.pending = None       # 上次建议着法 (frm,to), 供下次自动同步
        self.side = None          # 我方执子颜色 "red"/"black"(首次同步时确定)
        self.history = []         # [(红方/黑方, 中文着法)]
        self.initial = None       # 首次同步的局面(用于统计双方损子)
        self.lost_red = []        # 红方被吃棋子字符列表(棋盘右侧竖排展示)
        self.lost_black = []      # 黑方被吃棋子字符列表
        self.cur_grid = None      # 最近一次同步展示的局面(设置变更后重绘用)
        self.score_hist = []      # 引擎评分历史(供曲线图)
        self.engine = None
        self._log_count = 0       # 引擎日志累计行数(标题计数用)
        self.log_translate = True  # 引擎日志转译为中文(可在设置中关闭)
        self._log_ctx = None      # 思考中的局面上下文, 供日志转译着法用
        self.busy = False
        self.border = None
        self.markers = None
        self.statusbar = None
        self.bar_hint_lbl = None
        self._set_win = None      # 引擎设置窗口
        self._drag_off = None
        self._drag_win = None

    # ---------------- 线程/状态工具 ----------------
    def _rounded_window(self, p, w, x, y, radius=16, scale=True):
        """透明键色实现真正的圆角悬浮窗: 高度随内容自适应, 位置自动钳制
        scale=False 时 w/x/y 已是真实屏幕像素(如状态栏跟随框选区域)"""
        if scale:
            w = P(w)
        radius = P(radius)
        p.overrideredirect(True)
        p.attributes("-topmost", bool(self.topmost))
        p.configure(bg=KEY)
        try:
            p.attributes("-transparentcolor", KEY)
        except Exception:
            pass
        cv = tk.Canvas(p, bg=KEY, highlightthickness=0, bd=0, width=w,
                       height=P(200))
        cv.pack(fill="both", expand=True)
        content = tk.Frame(cv, bg=PANEL_BG)
        cv.create_window(1, 1, anchor="nw", window=content, width=w - 2)
        state = {"h": 0}

        def layout(_e=None):
            content.update_idletasks()
            h = max(content.winfo_reqheight() + 2, P(48))
            if h == state["h"]:
                return
            first = state["h"] == 0
            state["h"] = h
            cv.configure(width=w, height=h)
            cv.delete("bg")
            _round_rect(cv, 0, 0, w - 1, h - 1, radius, fill=PANEL_BG,
                        outline=LINE, width=1, tags="bg")
            cv.tag_lower("bg")
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            px, py = (x, y) if first else (p.winfo_x(), p.winfo_y())
            p.geometry(f"{w}x{h}+{max(P(4), min(px, sw - w - P(4)))}"
                       f"+{max(P(4), min(py, sh - h - P(4)))}")

        content.bind("<Configure>", lambda e: p.after_idle(layout))
        p.after_idle(layout)
        return cv, content

    def post(self, fn):
        self.root.after(0, fn)

    def set_status(self, s):
        self.post(lambda: self.status_var.set(s))

    def set_engine_dot(self, text, color):
        """更新标题栏引擎状态胶囊(可从工作线程调用)"""
        self.post(lambda: self.engine_dot.config(text=text, fg=color))

    def append_log(self, line):
        """引擎日志回显(可从工作线程调用), 展示在「引擎日志」折叠卡片中"""
        self.post(lambda: self._append_log_ui(line))

    def _append_log_ui(self, line):
        t = getattr(self, "log_text", None)
        if t is None or not t.winfo_exists():
            return
        if self._log_count == 0:  # 首条日志到达, 清掉占位提示
            t.delete("1.0", "end")
        self._log_count += 1
        self.log_title_var.set(f"引擎日志 ({self._log_count})")
        at_bottom = t.yview()[1] >= 0.999  # 用户未上翻才自动滚到底
        t.configure(state="normal")
        t.insert("end", line + "\n")
        excess = int(t.index("end-1c").split(".")[0]) - 300
        if excess > 0:  # 只保留最近 300 行
            t.delete("1.0", f"{excess}.0")
        t.configure(state="disabled")
        if at_bottom:
            t.see("end")

    def _clear_engine_log(self):
        """清空引擎日志卡片, 恢复占位提示"""
        self._log_count = 0
        self.log_title_var.set("引擎日志")
        t = getattr(self, "log_text", None)
        if t is not None and t.winfo_exists():
            t.configure(state="normal")
            t.delete("1.0", "end")
            t.insert("1.0", "等待引擎输出...\n")
            t.tag_add("ph", "1.0", "end")
            t.configure(state="disabled")

    def on_engine_line(self, line):
        """引擎输出回调: 按设置转译为中文, 或原样展示(可从工作线程调用)"""
        if not self.log_translate:
            self.append_log(line)
            return
        txt = self._translate_engine_line(line)
        if txt:
            self.append_log(txt)

    def _pv_text(self, moves):
        """UCI 着法序列 -> 中文纵线记谱(利用思考时的局面上下文);
        无上下文或局面不一致时回退为 h2→e2 坐标形式"""
        ctx = self._log_ctx
        if not ctx:
            return " ".join(f"{m[:2]}→{m[2:4]}"
                            for m in moves if len(m) >= 4)
        g = [row[:] for row in ctx["grid"]]
        flipped = ctx["flipped"]
        parts = []
        for mv in moves:
            if len(mv) < 4:
                break
            frm, to = parse_square(mv[:2]), parse_square(mv[2:4])
            if flipped:  # 引擎方向(黑上红下)坐标转回屏幕方向
                frm, to = flip_square(frm), flip_square(to)
            ch = g[frm[0]][frm[1]]
            if not ch:  # 上下文与引擎脱节, 剩余着法用坐标表示
                parts.append(f"{mv[:2]}→{mv[2:4]}")
                break
            parts.append(cn_notation(ch, frm, to, g))
            g = apply_move(g, frm, to)
        return " ".join(parts)

    def _translate_engine_line(self, line):
        """引擎原始输出 -> 中文; 返回 None 表示该行无需展示(噪音行)"""
        if line.startswith("> "):  # 发送给引擎的命令
            cmd = line[2:]
            if cmd == "uci":
                return "→ 连接引擎..."
            if cmd == "isready":
                return "→ 检查引擎就绪..."
            if cmd == "ucinewgame":
                return "→ 通知引擎: 开始新对局"
            if cmd == "quit":
                return "→ 通知引擎: 退出"
            if cmd.startswith("position"):
                if cmd.startswith("position startpos"):
                    n = max(0, len(cmd.split()) - 3)
                    return f"→ 发送局面: 开局起已走 {n} 步"
                return "→ 发送局面: 当前 FEN"
            if cmd.startswith("go depth"):
                return f"→ 开始思考: 深度 {cmd.split()[-1]}"
            if cmd.startswith("go movetime"):
                return f"→ 开始思考: 限时 {cmd.split()[-1]}ms"
            return None
        if "uciok" in line:
            return "引擎握手成功 (uciok)"
        if "readyok" in line:
            return "引擎准备完成 (readyok)"
        if line.startswith("bestmove"):
            parts = line.split()
            mv = parts[1] if len(parts) > 1 else ""
            if mv in ("", "(none)", "0000"):
                return "最佳着法: 无 (对局可能已结束)"
            return f"✔ 最佳着法: {self._pv_text([mv])}"
        if line.startswith("info"):
            d = re.search(r"depth (\d+)", line)
            pv = re.search(r" pv (.+)$", line)
            if pv is None:  # currmove 等搜索中间信息, 不展示
                return None
            pm = re.search(r"score cp (-?\d+)", line)
            mm = re.search(r"score mate (-?\d+)", line)
            if pm is not None:
                sc = f"评分 {int(pm.group(1)) / 100:+.2f}"
            elif mm is not None:
                v = int(mm.group(1))
                sc = f"{'我方' if v > 0 else '对方'}{abs(v)}步杀!"
            else:
                sc = None
            parts = [f"深度{d.group(1) if d else '?'}"]
            if sc:
                parts.append(sc)
            parts.append("主线: " + self._pv_text(pv.group(1).split()))
            return " | ".join(parts)
        return None  # 其余原始行不展示

    def sync_view(self, grid):
        """线程安全地刷新损子统计与局面图"""
        def job():
            self.cur_grid = grid
            self.refresh_loss(grid)
            self.draw_board(grid)
        self.post(job)

    def run_task(self, fn):
        if self.busy:
            return
        self.busy = True
        self.refresh_capture_ui()
        self.set_status("处理中...")
        self.clear_markers()

        def work():
            name = getattr(fn, "__name__", "任务")  # partial 无 __name__
            try:
                fn()
            except Exception as e:
                print(f"[错误] {name} 执行失败:")
                traceback.print_exc()  # 控制台输出完整报错信息
                self.append_log(f"[错误] {name}: {e}")  # 面板日志卡片可见
                self.set_status(f"出错: {e}")
            finally:
                self.busy = False
                self.post(self.refresh_capture_ui)

        threading.Thread(target=work, daemon=True).start()

    # ---------------- 截图 + 识别 ----------------
    def _hide_overlays(self):
        for w in (self.markers, self.border):
            if w is not None:
                w.withdraw()
        self.root.update()

    def _show_overlays(self):
        if self.border is not None:
            self.border.deiconify()
            self.border.lift()
        self.root.update()

    def _grab(self, bbox=None):
        """按框选区域截图到 board_capture.png, 返回路径"""
        from PIL import ImageGrab
        path = os.path.join(BASE, "templates", "board_capture.png")
        self._hide_overlays()  # 避免边框/标记被截进图里
        try:
            time.sleep(0.15)
            ImageGrab.grab(bbox=bbox or self.bbox,
                           all_screens=True).save(path)
        finally:
            self._show_overlays()
        return path

    def capture_and_recognize(self):
        path = self._grab()
        try:
            if not os.path.exists(rec.CALIB_PATH):
                self.set_status("首次截图, 正在按开局自动标定...")
                rec.calibrate(path)
            grid, fen = rec.recognize(path, thr=self.args.thr,
                                      debug=self.args.debug)
        except Exception as e:
            # 识别失败: 在面板棋盘区域提示用户
            self.post(lambda: self.draw_board(None, warn=f"识别失败: {e}"))
            raise
        return [[c for c in row] for row in grid], fen, path

    def _select_bbox(self):
        """全屏框选棋盘, 区域过小则提示重选; 取消返回 None(主线程调用)"""
        while True:
            box = select_box(self.root)
            if box is None:
                return None
            if box[2] - box[0] >= 150 and box[3] - box[1] >= 150:
                return box
            messagebox.showwarning("提示", "框选区域过小, 请重新框选棋盘")

    def on_capture(self):
        """面板按钮: 未初始化 -> 打开设置页「棋盘识别」完成标定;
        已初始化 -> 框选棋盘开始对弈辅助"""
        if self.busy:
            return
        if not os.path.exists(rec.CALIB_PATH):
            self.open_settings(tab="棋盘识别")
            return
        box = self._select_bbox()
        if box is None:
            return
        # 重新框选: 先销毁旧的边框/状态栏/落点标记
        for w in (self.border, self.statusbar):
            if w is not None:
                try:
                    w.destroy()
                except Exception:
                    pass
        self.border = None
        self.statusbar = None
        self.bar_hint_lbl = None
        self.clear_markers()
        self.bbox = box
        self.make_border()
        self.make_statusbar()
        pw, px, py = self._panel_pos()  # 面板移到棋盘右侧
        try:
            self.panel.geometry(f"+{px}+{py}")
        except Exception:
            pass
        self.refresh_capture_ui()
        self.run_task(self.task_initial_scan)

    def task_initial_scan(self):
        """框选完成后自动识别一次棋盘并渲染(不同步对局状态);
        失败时保留框选区域, 可在面板点「识别」重试或「重新截图」更换"""
        try:
            grid, _fen, _path = self.capture_and_recognize()
        except Exception:
            self.set_status("识别失败, 可点「识别」重试, 或「重新截图」更换区域")
            return
        n = sum(1 for row in grid for ch in row if ch)
        if not n:
            self.post(lambda: self.draw_board(
                None, warn="未识别到棋子, 请检查框选区域"))
            self.set_status("未识别到棋子, 可点「识别」重试, 或「重新截图」更换区域")
            return
        self.sync_view(grid)
        self.set_status(f"棋盘识别完成(共{n}枚棋子), 点「给出建议」同步对局")

    def on_re_recognize(self):
        """「识别」按钮: 不重新框选, 按当前框选区域重新识别一次"""
        if self.busy or self.bbox is None:
            return
        self.run_task(self.task_initial_scan)

    # ---------------- 两个主按钮 ----------------
    def on_opponent(self):
        if self.bbox is None:  # 尚未截图, 快捷键忽略
            return
        self.run_task(self.task_opponent)

    def on_manual(self):
        if self.bbox is None:
            return
        self.run_task(self.task_manual)

    def ensure_side(self, grid):
        """确定我方执子颜色: 玩家始终在屏幕下方, 下半区红子居多 -> 我执红"""
        if self.side is not None:
            return ""
        if self.args.side != "auto":
            self.side = self.args.side
            return f", 我执{'红' if self.side == 'red' else '黑'}"
        red = sum(1 for r in range(5, rec.ROWS) for c in range(rec.COLS)
                  if grid[r][c] and grid[r][c].isupper())
        black = sum(1 for r in range(5, rec.ROWS) for c in range(rec.COLS)
                    if grid[r][c] and grid[r][c].islower())
        self.side = "red" if red >= black else "black"
        print(f"[识别] 下方红子 {red} 枚 / 黑子 {black} 枚 -> 我执"
              f"{'红' if self.side == 'red' else '黑'}")
        return (f", 我执{'红' if self.side == 'red' else '黑'}"
                f"(下方红子{red}/黑子{black})")

    def _is_mine(self, ch):
        """判断棋子是否为我方执子颜色"""
        return ((ch.isupper() and self.side == "red")
                or (ch.islower() and self.side == "black"))

    def task_opponent(self):
        """「给出建议」: 默认已按上次建议走子, 自动同步双方着法并给出新建议"""
        first = self.prev is None
        grid, fen, path = self.capture_and_recognize()
        if first:
            self.initial = [row[:] for row in grid]
            self.use_startpos = grid == OPEN_GRID
            side_txt = self.ensure_side(grid)
            self.prev = grid
            self.sync_view(grid)
            self.set_status("局面已同步"
                            + ("(开局)" if self.use_startpos else "")
                            + side_txt)
            self.hint(fen, grid, path)
            return
        if grid == self.prev:
            self.set_status("局面未变化, 按当前局面给出建议")
            self.hint(fen, grid, path)
            return
        # 优先按「已采纳上次建议」尝试自动同步
        if self.pending is not None:
            pfrm, pto = self.pending
            expected = apply_move(self.prev, pfrm, pto)
            if grid == expected:
                # 仅我方按建议走子, 对方尚未回子
                ch = self.prev[pfrm[0]][pfrm[1]]
                cap = self.prev[pto[0]][pto[1]]
                self.record_move(ch, pfrm, pto, cap)
                self.pending = None
                self.prev = grid
                self.sync_view(grid)
                self.set_status("已同步建议着法, 对方走子后再次点「给出建议」")
                return
            frm2, to2, ch2, cap2 = detect_move(expected, grid)
            if frm2 is not None:
                # 我方按建议走子 + 对方已回子 -> 一次点击完成同步并出新建议
                ch = self.prev[pfrm[0]][pfrm[1]]
                cap = self.prev[pto[0]][pto[1]]
                self.record_move(ch, pfrm, pto, cap)
                self.prev = expected
                self.record_move(ch2, frm2, to2, cap2)
                self.pending = None
                self.prev = grid
                self.sync_view(grid)
                self.hint(fen, grid, path)
                return
        # 常规单步变化
        frm, to, ch, cap = detect_move(self.prev, grid)
        if frm is None:
            self.pending = None
            self.desync = True
            self.prev = grid
            self.sync_view(grid)
            self.set_status("识别到多处变化, 局面已同步但着法存疑")
            self.hint(fen, grid, path)
        elif self._is_mine(ch):
            # 只检测到我方走子(未按建议): 同步后等待对方
            self.record_move(ch, frm, to, cap)
            self.pending = None
            self.prev = grid
            self.sync_view(grid)
            self.set_status("已同步您的走子, 对方走子后点「给出建议」")
        else:
            # 对方走子 -> 记录并给出建议
            self.record_move(ch, frm, to, cap)
            self.pending = None
            self.prev = grid
            self.sync_view(grid)
            self.hint(fen, grid, path)

    def task_manual(self):
        """「未采纳AI建议」: 手动同步实际着法(无走子则仅放弃当前建议)"""
        grid, fen, path = self.capture_and_recognize()
        if self.prev is None:
            self.initial = [row[:] for row in grid]
            self.use_startpos = grid == OPEN_GRID
            self.set_status("局面已同步" + self.ensure_side(grid))
            self.prev = grid
            self.sync_view(grid)
            return
        if grid == self.prev:
            self.pending = None
            self.set_status("未检测到走子, 已放弃当前建议; 对方走子后点「给出建议」")
            return
        frm, to, ch, cap = detect_move(self.prev, grid)
        self.pending = None
        self.prev = grid
        self.sync_view(grid)
        if frm is None:
            self.desync = True
            self.set_status("识别到多处变化, 局面已同步但着法存疑")
        else:
            self.record_move(ch, frm, to, cap)
            if self._is_mine(ch):
                self.set_status("已同步您的走子, 对方走子后点「给出建议」")
            else:
                self.set_status("已同步对方着法, 点「给出建议」获取建议")

    def record_move(self, ch, frm, to, cap):
        self.moves.append(square_name(*frm) + square_name(*to))
        note = cn_notation(ch, frm, to, self.prev)
        if cap:
            note += f"(吃{NAME[cap]})"
        self.history.append(("红" if ch.isupper() else "黑", note))
        self.post(self.refresh_history)
        self.set_status(f"{'红方' if ch.isupper() else '黑方'}走子: {note}")

    # ---------------- 引擎提示 ----------------
    def hint(self, fen, grid, path):
        if self.engine is None:
            self.set_status("引擎未就绪, 无法给出建议")
            return
        side = "w" if self.side == "red" else "b"  # 轮到我方走(UCI: w=红方)
        # 引擎固定按黑上红下解析 FEN; 我执黑时屏幕为红上黑下, 须旋转180°再发
        flipped = self.side == "black"
        if flipped:
            fen = flip_fen(fen)
        self.set_status("引擎思考中...")
        self.set_engine_dot("● 引擎思考中", AMBER)
        # 日志转译上下文: 引擎输出的 pv 主线按此局面逐着转成中文记谱
        self._log_ctx = {"grid": [row[:] for row in grid], "flipped": flipped}
        if self.use_startpos and not self.desync and self.moves:
            self.engine.position("startpos moves " + " ".join(self.moves))
        else:
            self.engine.position(f"fen {fen} {side} - - 0 1")
        try:
            mv, score, mate = self.engine.go(self.args.movetime,
                                             depth=getattr(self.args, "depth", 0))
        finally:
            if self.engine is not None:  # 思考被异常打断也恢复状态
                self.set_engine_dot("● 引擎就绪", GREEN)
        if not mv or mv in ("(none)", "0000"):
            self.set_status("无建议(对局可能已结束)")
            self.pending = None
            self.post(self.clear_hint)
            return
        frm, to = parse_square(mv[:2]), parse_square(mv[2:4])
        if flipped:  # 引擎方向(黑上红下)的建议坐标转回屏幕方向
            frm, to = flip_square(frm), flip_square(to)
        self.pending = (frm, to)  # 记录建议, 供下次「给出建议」自动同步
        ch = grid[frm[0]][frm[1]]
        cn = cn_notation(ch, frm, to, grid) if ch else mv
        txt = f"{cn}   [{mv[:2]}→{mv[2:4]}]"
        sc_txt = ""
        if mate is not None:
            who = "我方" if mate > 0 else "对方"
            txt += f"\n{who}{abs(mate)}步杀!"
            sc_txt = f"杀棋 {mate:+d}"
        elif score is not None:
            sc_txt = f"我方得分 {score / 100:+.2f}"
        if mate is not None:
            # 绝杀: 取引擎评分上限 ±99999, 不做人为压缩
            val = 99999.0 if mate > 0 else -99999.0
        else:
            val = float(score) if score is not None else None
        if val is not None:
            self.score_hist.append(val)  # 记录评分, 供曲线图展示
            self.post(self.draw_score_chart)
        self.post(lambda: self.show_hint(txt, sc_txt))
        self.show_markers(frm, to, path)
        if self.move_mode:
            self.auto_act(frm, to, path, self.move_mode)
        self.set_status("按建议走子后点「我已下子」")

    def show_hint(self, txt, score):
        lines = txt.split("\n", 1)
        self.hint_var.set(lines[0])  # 建议着法显示在棋盘下方状态栏
        if getattr(self, "bar_hint_lbl", None) is not None:
            self.bar_hint_lbl.config(fg=ACCENT)
        if len(lines) > 1:  # 杀棋提示与评分合并为单行, 给曲线图留空间
            self.score_var.set(f"{lines[1]}  {score}")
            self.score_lbl.config(fg=ACCENT)
        else:
            self.score_var.set(score)
            self.score_lbl.config(fg=TXT)

    def clear_hint(self):
        self.hint_var.set("暂无建议")
        if getattr(self, "bar_hint_lbl", None) is not None:
            self.bar_hint_lbl.config(fg=SUB)
        self.score_var.set("—")
        self.score_lbl.config(fg=TXT)

    def show_markers(self, frm, to, path):
        """在棋盘上圈出建议的起点(青)/落点(红)"""
        try:
            with open(rec.CALIB_PATH, encoding="utf-8") as f:
                cal = json.load(f)
            img = rec.imread(path)
            img_r = rec.resize_to_width(img, cal["width"])
            bx, by, bw, bh = rec.board_bbox(img_r)
            x0 = bx + cal["fx0"] * bw
            dx = cal["fdx"] * bw
            y0 = by + cal["fy0"] * bh
            dy = cal["fdy"] * bh
            f = img.shape[1] / cal["width"]  # 截图与标定宽度不一致时的缩放
            pt = lambda rc: (self.bbox[0] + (x0 + rc[1] * dx) * f,
                             self.bbox[1] + (y0 + rc[0] * dy) * f)
            (x1, y1), (x2, y2) = pt(frm), pt(to)
            rad = max(6, int(cal["r"] * f * 0.95))
            geo = (int(self.bbox[0] + bx * f), int(self.bbox[1] + by * f),
                   int(bw * f), int(bh * f))
            self.post(lambda: self.create_markers(geo, (x1, y1, rad), (x2, y2, rad)))
        except Exception:
            print("[提示] 标记绘制失败:")
            traceback.print_exc()

    def create_markers(self, geo, a, b):
        self.clear_markers()
        gx, gy, gw, gh = geo
        tl, cv = overlay_window(self.root, gw, gh, gx, gy)
        (xa, ya, ra), (xb, yb, rb) = a, b
        # 起点圆 -> 落点圆的箭头(两端留出圆的空隙)
        dx, dy = xb - xa, yb - ya
        d = math.hypot(dx, dy) or 1.0
        ux, uy = dx / d, dy / d
        cv.create_line(xa + ux * (ra + P(4)) - gx, ya + uy * (ra + P(4)) - gy,
                       xb - ux * (rb + P(14)) - gx,
                       yb - uy * (rb + P(14)) - gy,
                       fill="#ffd76a", width=P(5), capstyle="round",
                       arrow=tk.LAST, arrowshape=(P(16), P(22), P(8)))
        for (x, y, r), color in ((a, "#00e5ff"), (b, "#ff3b30")):
            cv.create_oval(x - gx - r, y - gy - r, x - gx + r, y - gy + r,
                           outline=color, width=P(3))
        self.markers = tl

    def clear_markers(self):
        if self.markers is not None:
            try:
                self.markers.destroy()
            except Exception:
                pass
            self.markers = None

    # ---------------- 自动走子 ----------------
    @staticmethod
    def _click(x, y, user32):
        """在屏幕坐标 (x, y) 单击左键"""
        user32.SetCursorPos(x, y)
        time.sleep(random.uniform(0.05, 0.15))
        user32.mouse_event(0x0002, 0, 0, 0, 0)   # 左键按下
        time.sleep(random.uniform(0.03, 0.08))
        user32.mouse_event(0x0004, 0, 0, 0, 0)   # 左键松开

    def auto_act(self, frm, to, path, mode):
        """走子设置: 1=鼠标自动移到推荐起点, 2=自动点击走子(点起点→点落点)"""
        try:
            import ctypes
            with open(rec.CALIB_PATH, encoding="utf-8") as f:
                cal = json.load(f)
            img = rec.imread(path)
            img_r = rec.resize_to_width(img, cal["width"])
            bx, by, bw, bh = rec.board_bbox(img_r)
            x0 = bx + cal["fx0"] * bw
            dx = cal["fdx"] * bw
            y0 = by + cal["fy0"] * bh
            dy = cal["fdy"] * bh
            f = img.shape[1] / cal["width"]  # 截图与标定宽度不一致时的缩放
            pt = lambda rc: (int(self.bbox[0] + (x0 + rc[1] * dx) * f),
                             int(self.bbox[1] + (y0 + rc[0] * dy) * f))
            (fx, fy), (tx, ty) = pt(frm), pt(to)
            user32 = ctypes.windll.user32
            user32.SetCursorPos(fx, fy)
            if mode != 2:
                return
            time.sleep(random.uniform(0.15, 0.3))
            self._click(fx, fy, user32)          # 第一次点击: 起点
            lo = min(self.move_gap_min, self.move_gap_max)
            hi = max(self.move_gap_min, self.move_gap_max)
            time.sleep(random.uniform(lo, hi))   # 两次点击随机间隔
            self._click(tx, ty, user32)          # 第二次点击: 落点
        except Exception:
            print("[自动走子] 执行失败:")
            traceback.print_exc()

    # ---------------- 重置/按钮 ----------------
    def on_reset(self):
        """重置对局: 清空同步状态/记录/日志, 重启引擎并重新识别棋盘"""
        if self.busy:
            return
        self.prev = None
        self.moves = []
        self.use_startpos = False
        self.desync = False
        self.pending = None
        self.history = []
        self.initial = None
        self.side = None          # 执子颜色一并清空, 新对局重新判定
        self.cur_grid = None
        self._log_ctx = None
        self.clear_hint()
        self.lost_red = []
        self.lost_black = []
        self.score_hist = []
        self.draw_score_chart()
        self.clear_markers()
        self.refresh_history()
        self._clear_engine_log()  # 日志清空, 一切重来
        self.draw_board(None)     # 先清掉旧局面展示
        self.run_task(self.task_reset)

    def task_reset(self):
        """重置任务: 退出旧引擎并重新连接, 再按当前框选区域重新识别棋盘"""
        eng, self.engine = self.engine, None
        if eng is not None:
            try:
                eng.quit()
            except Exception:
                pass
        self.init_engine()
        if self.bbox is not None:
            self.task_initial_scan()
        else:
            self.set_status("已重置, 请先框选棋盘")

    def refresh_capture_ui(self):
        """按「是否已标定 / 是否已截图」更新截图引导与按钮;
        已完成初始化配置时隐藏「棋盘截图」区域, 改用局面评估标题栏小按钮"""
        calibrated = os.path.exists(rec.CALIB_PATH)
        # 对弈区域仅在初始化配置完成后显示
        if calibrated:
            if not self.play_area.winfo_ismapped():
                self.play_area.pack(fill="x")
            self.sec_cap.pack_forget()
            self.cap_card.pack_forget()
        else:
            self.play_area.pack_forget()
            if not self.sec_cap.winfo_ismapped():
                self.sec_cap.pack(fill="x")
                self.cap_card.pack(fill="x", after=self.sec_cap)
        if self.busy:
            self.btn_capture.config(state=tk.DISABLED)
            self.btn_cap_mini.config(state=tk.DISABLED)
        else:
            self.btn_capture.config(state=tk.NORMAL)
            self.btn_capture.config(text="重新截图" if self.bbox else
                                    ("截图" if calibrated else "初始化配置"))
            self.btn_cap_mini.config(state=tk.NORMAL)
        # 局面评估标题栏文字按钮固定为引导文案; 棋盘内嵌按钮同步忙碌状态
        self.btn_cap_mini.config(text="识别有误？重新截图")
        if self.bbox is None:  # 未截图: 棋盘内已有大号「截图」引导, 标题栏不显示
            self.btn_cap_mini.pack_forget()
        elif not self.btn_cap_mini.winfo_ismapped():
            self.btn_cap_mini.pack(side="right")
        for b in getattr(self, "_board_btns", []):
            try:
                b.config(state=tk.DISABLED if self.busy else tk.NORMAL)
            except tk.TclError:
                pass
        if not calibrated:
            self.cap_hint_lbl.config(
                text="首次使用: 请把棋盘调到开局局面(32 枚棋子), 点「初始化配置」"
                     "截图标定棋盘")
        elif self.bbox:
            self.cap_hint_lbl.config(
                text="已框选棋盘, 对弈中可点「重新截图」更换区域")
        else:
            self.cap_hint_lbl.config(
                text="点「截图」框选棋盘区域, 开始对弈辅助")
        self.refresh_buttons()

    def refresh_buttons(self):
        # 未截图(无框选区域)时, 对弈相关按钮禁用
        if getattr(self, "btn_opp", None) is None:
            return
        st = tk.DISABLED if (self.busy or self.bbox is None) else tk.NORMAL
        for b in (self.btn_opp, self.btn_me, self.btn_reset):
            b.config(state=st)
        self.refresh_hotkey_hint()

    def refresh_hotkey_hint(self):
        """主按钮文字附带当前「给出建议」快捷键提示(禁用时不显示)"""
        if getattr(self, "btn_opp", None) is None:
            return
        hk = HOTKEY_NAMES.get(self.hotkey_scan)
        self.btn_opp.config(text="给出建议" + (f"（{hk}）" if hk else ""))

    def refresh_history(self):
        """在滚动列表中显示完整对局记录, 每行一个回合(红/黑各一着)"""
        n = len(self.history)
        self.hist_title_var.set(f"对局记录 ({n})" if n else "对局记录")
        for w in self.hist_inner.winfo_children():
            w.destroy()

        def cell(parent, mv):
            red = mv[0] == "红"
            tk.Label(parent, text="●", bg=CARD,
                     fg=ACCENT if red else TXT,
                     font=("Microsoft YaHei", 7)).pack(side="left",
                                                       padx=(0, P(5)))
            tk.Label(parent, text=mv[1], bg=CARD,
                     fg=ACCENT if red else TXT,
                     font=("Microsoft YaHei", 11, "bold" if red else "normal")
                     ).pack(side="left")

        if not n:
            tk.Label(self.hist_inner, text="对方走子后, 棋步会记录在这里",
                     bg=CARD, fg=FAINT,
                     font=("Microsoft YaHei", 10)).pack(anchor="w",
                                                        padx=P(16),
                                                        pady=P(12))
        else:
            for i in range(0, n, 2):
                if i:
                    tk.Frame(self.hist_inner, bg="#f0f1f3", height=1
                             ).pack(fill="x", padx=P(14))
                row = tk.Frame(self.hist_inner, bg=CARD)
                row.pack(fill="x", padx=P(16), pady=P(5))
                tk.Label(row, text=f"{i // 2 + 1}.", bg=CARD, fg=FAINT,
                         font=("Microsoft YaHei", 10), width=3,
                         anchor="w").pack(side="left")
                cell(row, self.history[i])
                if i + 1 < n:
                    cell(row, self.history[i + 1])
        self.hist_canvas.update_idletasks()
        self.hist_canvas.yview_moveto(1.0)  # 新棋步出现时滚动到底部

    def refresh_loss(self, grid):
        """对比首次同步局面, 统计双方被吃掉的棋子(竖排展示在棋盘右侧)"""
        if self.initial is None:
            self.lost_red = []
            self.lost_black = []
            return

        def lost(upper):
            names = []
            for ch in ("KABNRCP" if upper else "kabnrcp"):
                a = sum(row.count(ch) for row in self.initial)
                b = sum(row.count(ch) for row in grid)
                names += [ch] * max(0, a - b)
            names.sort(key=lambda ch: PIECE_VAL[ch.upper()], reverse=True)
            return names

        self.lost_red = lost(True)
        self.lost_black = lost(False)

    def draw_board(self, grid, warn=None):
        """在「局面评估」卡片中绘制识别出的当前局面(简约棋盘),
        棋盘右侧竖排展示双方被吃掉的棋子(直接画小棋子, 不用 ×N 计数)"""
        cv = self.board_cv
        cv.delete("all")
        cell, m = P(30), P(16)                   # 格距 / 边距
        lw = P(60) if self.show_loss else m      # 右侧损子条宽度(两列)/右边距
        W = (rec.COLS - 1) * cell + m + lw
        H = (rec.ROWS - 1) * cell + 2 * m
        cv.configure(width=W, height=H)

        def x(c):
            return m + c * cell

        def y(r):
            return m + r * cell

        G, R = "#d9dce1", cell * 0.44
        # 横线
        for r in range(rec.ROWS):
            cv.create_line(x(0), y(r), x(rec.COLS - 1), y(r),
                           fill=G, width=P(2))
        # 竖线(中间各线在楚河汉界处断开)
        for c in range(rec.COLS):
            if c in (0, rec.COLS - 1):
                cv.create_line(x(c), y(0), x(c), y(rec.ROWS - 1),
                               fill=G, width=P(2))
            else:
                cv.create_line(x(c), y(0), x(c), y(4), fill=G, width=P(2))
                cv.create_line(x(c), y(5), x(c), y(rec.ROWS - 1),
                               fill=G, width=P(2))
        # 九宫斜线
        for r0 in (0, rec.ROWS - 3):
            cv.create_line(x(3), y(r0), x(5), y(r0 + 2), fill=G, width=P(2))
            cv.create_line(x(5), y(r0), x(3), y(r0 + 2), fill=G, width=P(2))
        # 炮/兵位标记
        def ticks(r, c):
            for sx in (-1, 1):
                for sy in (-1, 1):
                    if (sx < 0 and c == 0) or (sx > 0 and c == rec.COLS - 1):
                        continue  # 边线外侧不画
                    x0, y0 = x(c) + sx * P(3), y(r) + sy * P(3)
                    cv.create_line(x0, y0, x0 + sx * P(5), y0, fill=G)
                    cv.create_line(x0, y0, x0, y0 + sy * P(5), fill=G)
        for r, c in ((2, 1), (2, 7), (7, 1), (7, 7), (3, 0), (3, 2), (3, 4),
                     (3, 6), (3, 8), (6, 0), (6, 2), (6, 4), (6, 6), (6, 8)):
            ticks(r, c)
        # 空局面: 占位文字 / 识别失败警示 + 截图引导按钮
        bw = (rec.COLS - 1) * cell + 2 * m       # 棋盘本体宽度(不含损子条)
        if grid is None:
            if warn:
                cv.create_text(bw / 2, y(3.5), text=f"⚠ {warn}", fill=ACCENT,
                               font=("Microsoft YaHei", 10, "bold"),
                               justify="center", width=bw - P(24))
            else:
                cv.create_text(bw / 2, y(3.5), text="尚未同步局面", fill=SUB,
                               font=("Microsoft YaHei", 11))
            self._empty_guide_buttons(cv, bw, y(4.9))
            self._draw_loss_strip(cv, W, m, cell)
            return
        # 楚河汉界
        cv.create_text(x(2), y(4.5), text="楚 河", fill="#c9ced6",
                       font=("Microsoft YaHei", 10))
        cv.create_text(x(6), y(4.5), text="汉 界", fill="#c9ced6",
                       font=("Microsoft YaHei", 10))
        # 棋子: 红子红底白字 / 黑子墨底白字
        for r in range(rec.ROWS):
            for c in range(rec.COLS):
                ch = grid[r][c]
                if not ch:
                    continue
                px, py = x(c), y(r)
                col = ACCENT if ch.isupper() else TXT
                cv.create_oval(px - R, py - R, px + R, py + R,
                               fill=col, outline=col)
                cv.create_text(px, py, text=NAME[ch], fill="#ffffff",
                               font=("Microsoft YaHei", 12, "bold"))
        # 右侧竖排展示被吃棋子
        self._draw_loss_strip(cv, W, m, cell)

    def _empty_guide_buttons(self, cv, bw, cy):
        """「尚未同步局面」下方的引导按钮(嵌入画布, 随重绘重建):
        未截图 → 大号「截图」; 已截图 → 「重新截图」+「识别」"""
        for w in getattr(self, "_board_btns", []):  # 清掉上一轮嵌入的按钮
            try:
                w.destroy()
            except tk.TclError:
                pass
        self._board_btns = []
        st = tk.DISABLED if self.busy else tk.NORMAL

        def add(btn, cx):
            btn.config(state=st)
            self._board_btns.append(btn)
            cv.create_window(cx, cy, window=btn, anchor="center")

        if self.bbox is None:
            add(RoundButton(cv, text="截图", command=self.on_capture,
                            height=42, radius=12, width=132,
                            font=(FONT, 13, "bold"), frame_bg=CARD), bw / 2)
        else:
            cap_b = RoundButton(cv, text="重新截图", command=self.on_capture,
                                height=36, radius=10, bg=FIELD, fg=TXT,
                                hover=FIELD_HOVER, font=(FONT, 11),
                                frame_bg=CARD)
            rec_b = RoundButton(cv, text="识别", command=self.on_re_recognize,
                                height=36, radius=10,
                                font=(FONT, 11, "bold"), frame_bg=CARD)
            gap = P(14)
            wc, wr = int(cap_b.cget("width")), int(rec_b.cget("width"))
            add(cap_b, bw / 2 - gap / 2 - wc / 2)   # 左: 重新截图
            add(rec_b, bw / 2 + gap / 2 + wr / 2)   # 右: 识别

    def _draw_loss_strip(self, cv, W, m, cell):
        """棋盘右侧竖排展示双方损失棋子: 每侧两列、按价值降序, 红方自顶部
        向下、黑方自底部向上, 与棋盘上下半区对应"""
        if not self.show_loss:  # 设置中关闭了损子显示
            return
        H = m * 2 + (rec.ROWS - 1) * cell
        r = max(7, int(cell * 0.32))         # 小棋子半径(比单列时更大)
        gap = r * 2 + P(3)                   # 棋子纵向间距
        half = (H - P(10)) / 2               # 单侧可用半高
        x1, x2 = W - P(45), W - P(15)        # 左右两列中心线
        # 分隔竖线
        cv.create_line(W - P(60), m, W - P(60), H - m, fill=LINE, width=1)

        def col(items, base_y, step):
            """两列排布: 先按行填充(第i个 -> 列 i%2, 行 i//2)"""
            rows = (len(items) + 1) // 2
            g = gap if rows < 2 else min(gap, (half - r * 2) / max(rows - 1, 1))
            for i, ch in enumerate(items):
                cx = x1 if i % 2 == 0 else x2
                cy = base_y + (i // 2) * g * step
                colr = ACCENT if ch.isupper() else TXT
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill=colr,
                               outline=colr)
                cv.create_text(cx, cy, text=NAME[ch], fill="#ffffff",
                               font=("Microsoft YaHei", 9, "bold"))

        col(self.lost_red, m + r, 1)      # 上半区: 红方损失, 自顶向下
        col(self.lost_black, H - m - r, -1)  # 下半区: 黑方损失, 自底向上

    def redraw_board(self):
        """设置变更(如损子显隐开关)后按最近同步的局面重绘"""
        self.draw_board(self.cur_grid)

    def draw_score_chart(self):
        """绘制评分曲线: 横轴(0 基线)居中, 纵轴在左; 量程自适应不限幅"""
        cv = self.score_cv
        cv.delete("all")
        W, H = P(310), P(140)
        cv.configure(width=W, height=H)
        ml, mr, mt, mb = P(40), P(8), P(10), P(14)   # 绘图区留白
        pw, ph = W - ml - mr, H - mt - mb            # 绘图区尺寸
        mid, G = mt + ph / 2, "#d9dce1"
        AX = "#c3c9d1"
        # 纵轴 + 居中的横轴(0 基线)
        cv.create_line(ml, mt, ml, mt + ph, fill=AX, width=1)
        cv.create_line(ml, mid, ml + pw, mid, fill=G, width=1)
        hist = self.score_hist[-40:]
        if len(hist) < 2:
            cv.create_text(ml + pw / 2, mid - P(10),
                           text="评分曲线将随每次建议更新",
                           fill=FAINT, font=("Microsoft YaHei", 9))
            return
        span = max(300.0, max((abs(v) for v in hist if abs(v) < 99999),
                              default=300.0))  # 量程随评分自适应, 绝杀点不计入
        n = len(hist)
        off = len(self.score_hist) - n  # 本段起点对应的建议序号(从1计)

        def px(i):
            return ml + pw * i / (n - 1)

        def py(v):
            t = max(-1.0, min(1.0, v / span))  # 绝杀点(±99999)画在顶/底边缘
            return mid - t * (ph / 2 - P(6))
        # 纵轴刻度: 顶/0/底
        for val, lab in ((span, f"+{span / 100:.0f}" if span >= 1000
                          else f"+{span / 100:.1f}"),
                         (0, "0"),
                         (-span, f"-{span / 100:.0f}" if span >= 1000
                          else f"-{span / 100:.1f}")):
            yy = py(val)
            cv.create_line(ml - P(3), yy, ml, yy, fill=AX)
            cv.create_text(ml - P(6), yy, text=lab, anchor="e", fill=SUB,
                           font=("Microsoft YaHei", 8))
        cv.create_text(ml - P(6), mt - P(2), text="分", anchor="e",
                       fill=FAINT, font=("Microsoft YaHei", 8))
        pts = [(px(i), py(v)) for i, v in enumerate(hist)]
        flat = [c for p in pts for c in p]
        cv.create_polygon([pts[0][0], mid] + flat + [pts[-1][0], mid],
                          fill="#f8e3e0", outline="")
        cv.create_line(flat, fill=ACCENT, width=P(2), smooth=True,
                       capstyle="round", joinstyle="round")
        # 横轴刻度: 建议序号(标在 0 基线下方)
        for i in sorted({0, (n - 1) // 2, n - 1}):
            xx = px(i)
            cv.create_line(xx, mid, xx, mid + P(3), fill=AX)
            cv.create_text(xx, mid + P(9), text=str(off + i + 1),
                           fill=SUB, font=("Microsoft YaHei", 8))
        cv.create_text(ml + pw - P(10), mid - P(8), text="步", anchor="e",
                       fill=FAINT, font=("Microsoft YaHei", 8))
        lx, ly = pts[-1]
        r = P(3)
        cv.create_oval(lx - r, ly - r, lx + r, ly + r, fill=ACCENT,
                       outline=CARD)  # 最新评分点

    def quit(self):
        try:
            if self.engine is not None:
                self.engine.quit()
        finally:
            self.root.destroy()

    # ---------------- 引擎 ----------------
    def init_engine(self):
        path = self.args.engine
        if not os.path.isfile(path):
            eng_dir = os.path.join(BASE, "engine")
            cands = sorted(
                (f for f in os.listdir(eng_dir)
                 if f.lower().startswith("pikafish") and f.lower().endswith(".exe")),
                key=lambda s: ("avxvnni" not in s, s)) if os.path.isdir(eng_dir) else []
            if cands:
                path = os.path.join(eng_dir, cands[0])
            else:
                which = shutil.which("pikafish")
                path = which or path
        try:
            self.append_log(f"[引擎] 启动 {path}")
            self.engine = UciEngine(path, self.args.threads, self.args.hash,
                                    log=self.on_engine_line)
            self.append_log("[引擎] 就绪")
            self.post(lambda: self.engine_dot.config(
                text="● 引擎就绪", fg=GREEN))
            self.set_status(f"引擎就绪: {os.path.basename(path)}")
        except Exception as e:
            self.engine = None
            self.append_log(f"[引擎] 启动失败: {e}")
            self.post(lambda: self.engine_dot.config(
                text="● 引擎未就绪", fg=ACCENT))
            self.set_status(f"引擎未就绪: {e}")

    def task_restart_engine(self):
        """应用新的引擎路径/线程/置换表后重启引擎"""
        if self.engine is not None:
            try:
                self.engine.quit()
            except Exception:
                pass
            self.engine = None
        self.init_engine()

    # ---------------- 全局热键 ----------------
    def start_hotkey(self):
        """全局监听自定义快捷键触发「给出建议」(Windows 低级键盘钩子)"""
        import ctypes
        from ctypes import wintypes

        WH_KEYBOARD_LL = 13
        LLKHF_UP = 0x80
        WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
        WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105

        user32 = ctypes.windll.user32
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                          wintypes.WPARAM, wintypes.LPARAM]
        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                      wintypes.WPARAM, wintypes.LPARAM)

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD),
                        ("scanCode", wintypes.DWORD),
                        ("flags", wintypes.DWORD),
                        ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        down = [False]  # 过滤按住不放的重复触发

        def proc(n_code, w_param, l_param):
            if n_code >= 0:
                kb = ctypes.cast(l_param,
                                 ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                # self.hotkey_scan 运行时可改(0=禁用), 无需重装钩子
                if self.hotkey_scan and kb.scanCode == self.hotkey_scan:
                    if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        if not kb.flags & LLKHF_UP and not down[0]:
                            down[0] = True
                            self.post(self.on_opponent)
                    elif w_param in (WM_KEYUP, WM_SYSKEYUP):
                        down[0] = False
            return user32.CallNextHookEx(None, n_code, w_param, l_param)

        def loop():
            proc_ref = HOOKPROC(proc)  # 保持引用防止被 GC
            # 低级钩子无需模块句柄(64位下 GetModuleHandleW 返回值截断会导致安装失败)
            user32.SetWindowsHookExW(WH_KEYBOARD_LL, proc_ref, None, 0)
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        threading.Thread(target=loop, daemon=True).start()

    # ---------------- 设置(实现见 settings_window.py) ----------------
    def _load_settings(self):
        from settings_window import load_settings
        load_settings(self)

    def _save_settings(self):
        from settings_window import save_settings
        save_settings(self)

    def open_settings(self, tab=None):
        """弹出设置窗口(棋盘识别/常规/界面设置/引擎/走子),
        tab 指定要激活的选项卡标题"""
        from settings_window import open_settings
        open_settings(self, tab)

    # ---------------- GUI ----------------
    def run(self):
        global UI_SCALE
        UI_SCALE = _compute_ui_scale(self.root)  # 先算缩放, 再建主题与面板
        _init_style(self.root)
        self.root.withdraw()
        # 先进入主界面: 不自动截图/框选, 由用户在面板点「截图」开始
        self.make_panel()
        self.start_hotkey()
        self.init_engine()
        self.root.mainloop()

    def make_border(self):
        x1, y1, x2, y2 = self.bbox
        tl, cv = overlay_window(self.root, x2 - x1, y2 - y1, x1, y1)
        cv.create_rectangle(1, 1, x2 - x1 - 2, y2 - y1 - 2,
                            outline="#ffcc00", width=P(3))
        self.border = tl

    def _panel_pos(self):
        """面板位置: 已框选->棋盘右侧(放不下则左侧); 未框选->屏幕居中"""
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        pw = P(360)
        if self.bbox is None:
            return pw, (sw - pw) // 2, max(P(8), (sh - P(560)) // 2)
        x1, y1, x2, y2 = self.bbox
        px = x2 + P(12)
        if px + pw > sw - P(8):  # 右侧放不下则移到棋盘左侧
            px = max(P(8), x1 - pw - P(12))
        py = max(P(8), min(y1, sh - P(560)))
        return pw, px, py

    def make_panel(self):
        pw, px, py = self._panel_pos()
        p = tk.Toplevel(self.root)
        # pw 已在 make_panel 中按缩放换算, 位置为真实屏幕像素
        _cv, content = self._rounded_window(p, pw, px, py, scale=False)
        self.panel = p

        self.status_var = tk.StringVar(
            value="先点「截图」框选棋盘, 再开始对弈辅助")
        self.hint_var = tk.StringVar(value="暂无建议")
        self.score_var = tk.StringVar(value="—")
        self.hist_title_var = tk.StringVar(value="对局记录")
        self.log_title_var = tk.StringVar(value="引擎日志")

        # ---- 标题栏 ----
        header = tk.Frame(content, bg=PANEL_BG)
        header.pack(fill="x", padx=P(6), pady=(P(6), 0))
        tk.Label(header, text="♞ 象棋助手", bg=PANEL_BG, fg=TXT,
                 font=(FONT, 13, "bold")).pack(side="left", padx=P(12),
                                               pady=P(8))
        RoundButton(header, text="✕", command=self.quit, bg=PANEL_BG, fg=SUB,
                    hover=ICON_HOVER, font=(FONT, 11, "bold"), height=28,
                    radius=8, width=28, frame_bg=PANEL_BG).pack(
            side="right", padx=(0, P(2)))
        RoundButton(header, text="⚙", command=self.open_settings, bg=PANEL_BG,
                    fg=SUB, hover=ICON_HOVER, font=(FONT, 11), height=28,
                    radius=8, width=28, frame_bg=PANEL_BG).pack(
            side="right", padx=(0, P(2)))
        # 引擎状态胶囊: pack(side="right") 逆序排列, 最后 pack 的在最左,
        # 即位于「⚙ 设置」按钮左侧
        self.engine_dot = Pill(header, text="● 引擎启动中", fg=SUB,
                               font=(FONT, 9), bg=PANEL_BG)
        self.engine_dot.pack(side="right", padx=(0, P(6)))

        body = tk.Frame(content, bg=PANEL_BG)
        body.pack(fill="x", padx=P(14), pady=(0, P(16)))

        def section(title, var=None, parent=None):
            """分区标题: 小号灰字"""
            f = tk.Frame(parent or body, bg=PANEL_BG)
            f.pack(fill="x", pady=(P(10), P(5)))
            if var is not None:
                tk.Label(f, textvariable=var, bg=PANEL_BG, fg=SUB,
                         font=(FONT, 10, "bold")).pack(side="left", padx=P(2))
            else:
                tk.Label(f, text=title, bg=PANEL_BG, fg=SUB,
                         font=(FONT, 10, "bold")).pack(side="left", padx=P(2))
            return f

        def attach_toggle(head, target, expanded=True):
            """分区标题可点击, 折叠/展开下方内容; expanded=False 默认折叠"""
            arrow = tk.Label(head, text="▾" if expanded else "▸",
                             bg=PANEL_BG, fg=FAINT, font=(FONT, 11))
            arrow.pack(side="left", padx=(P(2), 0))
            st = {"open": expanded}
            if not expanded:
                target.pack_forget()

            def flip(_e=None):
                st["open"] = not st["open"]
                if st["open"]:
                    target.pack(fill="x", after=head)
                    arrow.config(text="▾")
                else:
                    target.pack_forget()
                    arrow.config(text="▸")

            for w in (head, arrow) + tuple(head.winfo_children()):
                w.bind("<Button-1>", flip)
                try:
                    w.config(cursor="hand2")
                except tk.TclError:
                    pass

        # ---- 截图 / 初始化配置(完成标定后整体隐藏, 改用局面评估标题栏小按钮) ----
        self.sec_cap = section("棋盘截图")
        self.cap_card = Card(body, pad=10)
        self.cap_card.pack(fill="x")
        ci = self.cap_card.inner
        self.cap_hint_lbl = tk.Label(ci, bg=CARD, fg=SUB, font=(FONT, 10),
                                     justify="left", anchor="w", wraplength=pw - P(60))
        self.cap_hint_lbl.pack(fill="x")
        self.btn_capture = RoundButton(ci, text="初始化配置",
                                       command=self.on_capture,
                                       height=44, radius=12,
                                       font=(FONT, 13, "bold"), frame_bg=CARD)
        self.btn_capture.pack(fill="x", pady=(P(10), 0))

        # ---- 对弈区域(局面评估/记录/按钮): 未完成初始化配置前整体隐藏 ----
        self.play_area = tk.Frame(body, bg=PANEL_BG)

        # ---- 局面评估: 局面图 + 得分 ----
        sec_eval = section("局面评估", parent=self.play_area)
        self.btn_cap_mini = RoundButton(sec_eval, text="识别有误？重新截图",
                                        command=self.on_capture,
                                        height=24, radius=8,
                                        bg=PANEL_BG, fg=SUB, hover=FIELD,
                                        disabled_bg=PANEL_BG,
                                        disabled_fg=FAINT,
                                        font=(FONT, 9), frame_bg=PANEL_BG)
        self.btn_cap_mini.pack(side="right")
        card = Card(self.play_area, pad=8)  # 内边距随缩放, 内部宽度容纳评分曲线
        card.pack(fill="x")
        inner = card.inner
        self.board_cv = tk.Canvas(inner, bg=CARD, bd=0, highlightthickness=0)
        self.board_cv.pack(anchor="center", pady=(P(4), P(6)))
        tk.Frame(inner, bg=LINE, height=1).pack(fill="x")
        self.score_lbl = tk.Label(inner, textvariable=self.score_var, bg=CARD,
                                  fg=TXT, font=(FONT, 11, "bold"),
                                  wraplength=pw - P(88), justify="left",
                                  anchor="w")
        self.score_lbl.pack(fill="x", pady=(P(8), 0))
        # 评分曲线
        self.score_cv = tk.Canvas(inner, bg=CARD, bd=0, highlightthickness=0)
        self.score_cv.pack(anchor="center", pady=(P(2), P(4)))
        self.draw_score_chart()

        # ---- 对局记录(可滚动, 可折叠) ----
        sec_hist = section("", var=self.hist_title_var, parent=self.play_area)
        holder = Card(self.play_area, pad=8)
        holder.pack(fill="x")
        hbar = tk.Frame(holder.inner, bg=CARD)
        hbar.pack(fill="both", expand=True)
        self.hist_canvas = tk.Canvas(hbar, bg=CARD, height=P(150), bd=0,
                                     highlightthickness=0,
                                     yscrollincrement=P(28))
        bar = tk.Scrollbar(hbar, orient="vertical", width=P(8),
                           troughcolor=CARD, bg=LINE, activebackground=SUB,
                           bd=0, elementborderwidth=0,
                           command=self.hist_canvas.yview)
        self.hist_canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.hist_canvas.pack(side="left", fill="both", expand=True)
        self.hist_inner = tk.Frame(self.hist_canvas, bg=CARD)
        win = self.hist_canvas.create_window((0, 0), window=self.hist_inner,
                                             anchor="nw")
        self.hist_inner.bind("<Configure>", lambda e: self.hist_canvas.
                             configure(scrollregion=self.hist_canvas.
                                       bbox("all")))
        self.hist_canvas.bind(
            "<Configure>",
            lambda e: self.hist_canvas.itemconfigure(win, width=e.width))

        def hist_wheel(e):
            # 仅当鼠标位于列表区域时才滚动
            c = self.hist_canvas
            mx, my = c.winfo_pointerxy()
            rx, ry = c.winfo_rootx(), c.winfo_rooty()
            if (rx <= mx < rx + c.winfo_width()
                    and ry <= my < ry + c.winfo_height()):
                c.yview_scroll(-1 if e.delta > 0 else 1, "units")

        self.hist_canvas.bind_all("<MouseWheel>", hist_wheel)
        attach_toggle(sec_hist, holder, expanded=False)  # 默认折叠

        # ---- 引擎日志(只读文本, 可折叠) ----
        sec_log = section("", var=self.log_title_var, parent=self.play_area)
        log_card = Card(self.play_area, pad=8)
        log_card.pack(fill="x")
        lbar = tk.Frame(log_card.inner, bg=CARD)
        lbar.pack(fill="both", expand=True)
        self.log_text = tk.Text(
            lbar, bg=CARD, fg=SUB, bd=0, highlightthickness=0, height=8,
            wrap="word", font=(FONT, 9), state="disabled", cursor="arrow",
            padx=P(10), pady=P(8))
        lscroll = tk.Scrollbar(lbar, orient="vertical", width=P(8),
                               troughcolor=CARD, bg=LINE, activebackground=SUB,
                               bd=0, elementborderwidth=0,
                               command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=lscroll.set)
        lscroll.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_text.insert("1.0", "等待引擎输出...\n")
        self.log_text.tag_add("ph", "1.0", "end")
        self.log_text.tag_configure("ph", foreground=FAINT)
        self.log_text.bind("<Button-1>", lambda e: None)  # 保留选择, 不绑拖动
        attach_toggle(sec_log, log_card, expanded=False)  # 默认折叠

        # ---- 操作按钮: 红色主按钮 + 浅灰次按钮 ----
        btns = tk.Frame(self.play_area, bg=PANEL_BG)
        btns.pack(fill="x", pady=(P(14), P(14)))
        self.btn_opp = RoundButton(btns, text="给出建议",
                                   command=self.on_opponent, height=46,
                                   radius=14, font=(FONT, 14, "bold"),
                                   frame_bg=PANEL_BG)
        self.btn_opp.pack(fill="x")
        self.refresh_hotkey_hint()  # 文字附带当前快捷键提示
        row = tk.Frame(btns, bg=PANEL_BG)
        row.pack(fill="x", pady=(P(10), 0))
        self.btn_me = RoundButton(row, text="未采纳AI建议",
                                  command=self.on_manual, height=38,
                                  radius=12, bg=FIELD, fg=TXT,
                                  hover=FIELD_HOVER, font=(FONT, 11),
                                  frame_bg=PANEL_BG)
        self.btn_me.pack(side="left", expand=True, fill="x")
        self.btn_reset = RoundButton(row, text="重置", command=self.on_reset,
                                     height=38, radius=12, bg=FIELD, fg=TXT,
                                     hover=FIELD_HOVER, font=(FONT, 11),
                                     frame_bg=PANEL_BG)
        self.btn_reset.pack(side="left", expand=True, fill="x",
                            padx=(P(10), 0))
        self.draw_board(None)  # 初始空局面占位
        self.refresh_capture_ui()  # 初始按标定状态显示/隐藏对弈区域
        self._bind_drag(content)  # 除按钮/滚动列表外整体可拖动

    def make_statusbar(self):
        """棋盘框正下方(空间不足则上方)的悬浮状态栏: 着法建议 + 状态 + 关闭"""
        x1, y1, x2, y2 = self.bbox
        sh = self.root.winfo_screenheight()
        h = P(46)
        by = y2 + P(3)
        if by + h > sh - P(8):
            by = max(P(8), y1 - h - P(3))
        p = tk.Toplevel(self.root)
        # 宽度用框选真实像素(x2-x1), 不参与缩放
        _cv, inner = self._rounded_window(p, x2 - x1, x1, by, radius=14,
                                          scale=False)
        self.statusbar = p
        self.bar_hint_lbl = tk.Label(inner, textvariable=self.hint_var,
                                     bg=PANEL_BG, fg=SUB,
                                     font=(FONT, 15, "bold"), anchor="w")
        self.bar_hint_lbl.pack(side="left", padx=P(16), fill="x", expand=True)
        RoundButton(inner, text="✕", command=self.quit, bg=PANEL_BG, fg=SUB,
                    hover=ICON_HOVER, font=(FONT, 11, "bold"), height=28,
                    radius=8, width=28, frame_bg=PANEL_BG).pack(
            side="right", padx=(0, P(10)))
        tk.Label(inner, textvariable=self.status_var, bg=PANEL_BG, fg=SUB,
                 font=(FONT, 9), anchor="e").pack(side="right", padx=(0, P(4)))
        # 状态栏整体可拖动(关闭按钮除外)
        for w in (inner, self.bar_hint_lbl) + tuple(inner.winfo_children()):
            if isinstance(w, (tk.Button, tk.Canvas)):
                continue
            if w.bind("<Button-1>"):
                continue
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)

    def _drag_start(self, e):
        self._drag_win = e.widget.winfo_toplevel()
        self._drag_off = (e.x_root - self._drag_win.winfo_x(),
                          e.y_root - self._drag_win.winfo_y())

    def _drag_move(self, e):
        if self._drag_off and self._drag_win is not None:
            self._drag_win.geometry(f"+{e.x_root - self._drag_off[0]}"
                                    f"+{e.y_root - self._drag_off[1]}")

    def _bind_drag(self, w):
        """递归给容器/标签绑定拖动, 按钮与滚动列表除外"""
        if isinstance(w, (tk.Button, tk.Canvas, tk.Scrollbar)):
            return
        if not w.bind("<Button-1>"):  # 不覆盖已有点击绑定(分区折叠头)
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
        for c in w.winfo_children():
            self._bind_drag(c)
