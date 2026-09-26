#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""屏幕交互: 高DPI适配、全屏框选棋盘、透明覆盖窗(边框/落点标记)"""

import ctypes
import sys

import tkinter as tk


def enable_dpi_awareness():
    """Windows 高DPI: 让截图像素坐标与屏幕坐标一致"""
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def select_box(root):
    """全屏半透明遮罩上拖动框选, 返回屏幕坐标 (x1,y1,x2,y2) 或 None(Esc)"""
    ov = tk.Toplevel(root)
    ov.overrideredirect(True)
    ov.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0")
    ov.attributes("-topmost", True)
    ov.attributes("-alpha", 0.28)
    ov.configure(bg="black")
    cv = tk.Canvas(ov, bg="black", highlightthickness=0, cursor="crosshair")
    cv.pack(fill="both", expand=True)
    tip = cv.create_text(root.winfo_screenwidth() // 2, 60,
                         text="按住左键拖动, 框选棋盘区域  (Esc 取消)",
                         fill="white", font=("Microsoft YaHei", 16))
    state = {"box": None, "rect": None, "sx": 0, "sy": 0}

    def press(e):
        state["sx"], state["sy"] = e.x, e.y
        if state["rect"]:
            cv.delete(state["rect"])
        state["rect"] = cv.create_rectangle(e.x, e.y, e.x, e.y,
                                            outline="#00ff88", width=2)

    def drag(e):
        if state["rect"]:
            cv.coords(state["rect"], state["sx"], state["sy"], e.x, e.y)

    def release(e):
        x1, x2 = sorted((state["sx"], e.x))
        y1, y2 = sorted((state["sy"], e.y))
        if x2 - x1 > 30 and y2 - y1 > 30:
            ox, oy = ov.winfo_rootx(), ov.winfo_rooty()
            state["box"] = (ox + x1, oy + y1, ox + x2, oy + y2)
        ov.destroy()

    def esc(_e):
        ov.destroy()

    cv.bind("<ButtonPress-1>", press)
    cv.bind("<B1-Motion>", drag)
    cv.bind("<ButtonRelease-1>", release)
    ov.bind("<Escape>", esc)
    ov.focus_force()
    root.wait_window(ov)
    return state["box"]


def overlay_window(root, w, h, x, y):
    """透明底、可点击穿透的置顶覆盖窗, 返回其 Canvas"""
    key = "#010203"
    tl = tk.Toplevel(root)
    tl.overrideredirect(True)
    tl.attributes("-topmost", True)
    tl.geometry(f"{w}x{h}+{x}+{y}")
    tl.configure(bg=key)
    try:
        tl.attributes("-transparentcolor", key)  # 透明区域点击穿透
        tl.attributes("-disabled", True)         # 边线像素也不吞点击
    except Exception:
        pass
    cv = tk.Canvas(tl, bg=key, highlightthickness=0)
    cv.pack(fill="both", expand=True)
    tl.lift()
    return tl, cv
