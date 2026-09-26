#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""天天象棋 对局助手(框选棋盘 -> 截图识谱 -> 皮卡鱼 UCI 引擎提示) - 程序入口

流程:
  1. 启动后直接进入主界面(悬浮面板), 不自动截图
  2. 若尚未生成棋局识别配置(calibration.json): 面板仅显示截图引导,
     点 [初始化配置] 进入设置页「棋盘识别」选项卡 -> 截图框选开局棋盘
     -> 自动标定并识别, 展示标注图与识别结果(保存至 templates/)
  3. 完成初始化后: 面板显示局面评估/对局记录/操作按钮,
     点 [截图] 全屏框选棋盘区域 -> 截图识别, 开始对弈辅助
  4. 点 [给出建议]: 默认已按上次建议走子, 自动同步双方着法 -> 皮卡鱼(UCI 协议)计算
     -> 面板给出中文着法提示, 并在棋盘上用圆圈+箭头标出起点/落点
  5. 若未按建议走子, 点 [未采纳AI建议] 手动同步实际局面

模块划分:
  - Function/notation.py    棋谱工具(UCI 坐标、中文记谱、走子检测)
  - Function/engine.py      皮卡鱼 UCI 引擎封装
  - Function/overlay.py     屏幕交互(DPI 适配、框选、覆盖窗)
  - Function/assistant.py   助手主体(识谱同步、引擎提示、悬浮面板 GUI)
  - Function/settings_window.py  设置窗口(选项卡 UI、设置持久化)
  - settings/               配置持久化(engine_settings.json、calibration.json)
  - auto_play.py            本文件: 命令行入口(根目录唯一入口)

注意:
  - 多显示器时请把游戏放在主屏; 悬浮面板可拖动, 不遮挡棋盘截图(截图时自动隐藏标记)
  - 需要依赖: opencv-python, numpy, pillow; tkinter 为 Python 自带

用法:
  python auto_play.py                        # 我执红(默认), 引擎自动查找 pikafish*.exe
  python auto_play.py --side black           # 我执黑
  python auto_play.py --engine 引擎路径 --movetime 2000 --depth 12
  python auto_play.py --debug                # 每次截图保存识别标注图
"""

import argparse
import os
import sys
import tkinter as tk

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "Function"))  # 功能模块位于 Function/ 目录

from assistant import Assistant
from overlay import enable_dpi_awareness


def _set_app_icon(root):
    """设置窗口图标(pic/logo.png), 对主窗及所有 Toplevel 生效"""
    icon = os.path.join(BASE, "pic", "logo.png")
    if os.path.exists(icon):
        try:
            root._app_icon = tk.PhotoImage(file=icon)  # 持有引用防止图片被回收
            root.iconphoto(True, root._app_icon)
        except tk.TclError:
            pass


def main():
    ap = argparse.ArgumentParser(description="天天象棋对局助手(识谱+皮卡鱼提示)")
    ap.add_argument("--engine", default=os.path.join(BASE, "pikafish.exe"),
                    help="UCI 引擎路径(默认自动查找目录内 pikafish*.exe)")
    ap.add_argument("--movetime", type=int, default=1000, help="引擎思考时间(ms)")
    ap.add_argument("--depth", type=int, default=0,
                    help="引擎搜索深度(0=按思考时间搜索, 默认)")
    ap.add_argument("--threads", type=int, default=4, help="引擎线程数")
    ap.add_argument("--hash", type=int, default=256, help="引擎置换表大小(MB)")
    ap.add_argument("--side", choices=["auto", "red", "black"], default="auto",
                    help="我方执子颜色(auto=按屏幕下方棋子自动识别, 默认)")
    ap.add_argument("--thr", type=float, default=0.55, help="棋子识别阈值")
    ap.add_argument("--debug", action="store_true", help="保存识别标注图")
    args = ap.parse_args()

    enable_dpi_awareness()
    root = tk.Tk()
    _set_app_icon(root)
    root.withdraw()
    app = Assistant(args, root)
    try:
        app.run()
    finally:
        if app.engine is not None:
            app.engine.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
