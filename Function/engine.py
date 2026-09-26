#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UCI 引擎封装: 皮卡鱼等标准 UCI 引擎的最小交互实现"""

import os
import re
import subprocess


class UciEngine:
    """皮卡鱼等标准 UCI 引擎的最小封装"""

    def __init__(self, path, threads=4, hash_mb=256):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"未找到引擎: {path}")
        self.p = subprocess.Popen(
            [path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="ignore", bufsize=1, cwd=os.path.dirname(os.path.abspath(path)))
        self._send("uci")
        self._wait("uciok")
        self._send(f"setoption name Threads value {threads}")
        self._send(f"setoption name Hash value {hash_mb}")
        self._send("isready")
        self._wait("readyok")

    def _send(self, cmd):
        self.p.stdin.write(cmd + "\n")
        self.p.stdin.flush()

    def _wait(self, token):
        for line in self.p.stdout:
            if token in line:
                return

    def position(self, cmd):
        self._send("position " + cmd)

    def go(self, movetime, depth=0):
        """阻塞思考(深度>0时按深度搜索, 否则按时间), 返回 (bestmove, cp分, 杀棋步数|None)"""
        if depth and int(depth) > 0:
            self._send(f"go depth {int(depth)}")
        else:
            self._send(f"go movetime {int(movetime)}")
        score = mate = None
        while True:
            line = self.p.stdout.readline()
            if not line:  # 引擎退出/异常
                return None, None, None
            if "score cp" in line:
                m = re.search(r"score cp (-?\d+)", line)
                if m:
                    score = int(m.group(1))
            elif "score mate" in line:
                m = re.search(r"score mate (-?\d+)", line)
                if m:
                    mate = int(m.group(1))
            elif line.startswith("bestmove"):
                parts = line.split()
                return (parts[1] if len(parts) > 1 else None), score, mate

    def ucinewgame(self):
        self._send("ucinewgame")
        self._send("isready")
        self._wait("readyok")

    def quit(self):
        try:
            self._send("quit")
            self.p.wait(timeout=2)
        except Exception:
            self.p.kill()
