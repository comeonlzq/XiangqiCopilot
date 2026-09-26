#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""棋谱工具: UCI 坐标转换、中文纵线记谱、局面走子检测"""

import xiangqi_recognizer as rec

CN_NUM = "一二三四五六七八九十"
FILES = "abcdefghi"
NAME = {
    "K": "帅", "A": "仕", "B": "相", "N": "马", "R": "车", "C": "炮", "P": "兵",
    "k": "将", "a": "士", "b": "象", "n": "马", "r": "车", "c": "炮", "p": "卒",
}
# 标准开局棋盘(用于判断首次同步是否为开局 -> 引擎可用 startpos+moves 走历史)
OPEN_GRID = [[None] * rec.COLS for _ in range(rec.ROWS)]
for _r, _c, _ch in rec.OPENING:
    OPEN_GRID[_r][_c] = _ch


def square_name(r, c):
    """网格(行,列) -> UCI 坐标, 如 (7,7)->'h2' (a0=左上黑方角)"""
    return f"{FILES[c]}{9 - r}"


def parse_square(s):
    """UCI 坐标 -> (行, 列)"""
    return 9 - int(s[1]), FILES.index(s[0])


def flip_square(sq):
    """坐标旋转180°: (r,c) <-> (9-r, 8-c), 引擎方向(黑上红下)与屏幕方向(我执黑)互换"""
    return (rec.ROWS - 1 - sq[0], rec.COLS - 1 - sq[1])


def flip_fen(fen):
    """FEN 棋盘串旋转180°(行序倒置 + 每行内列序倒置): 黑上红下 <-> 红上黑下"""
    rows = []
    for row in fen.split("/")[::-1]:
        cells = []
        for ch in row:  # 先展开空位数字再逐格倒序(直接倒字符串会错位)
            cells.extend([None] * int(ch) if ch.isdigit() else [ch])
        cells.reverse()
        s, emp = "", 0
        for cell in cells:
            if cell is None:
                emp += 1
            else:
                if emp:
                    s += str(emp)
                    emp = 0
                s += cell
        if emp:
            s += str(emp)
        rows.append(s)
    return "/".join(rows)


def cn_notation(ch, frm, to, grid):
    """中文纵线记谱, 如 炮二平五 / 马8进7; grid 为走子前局面(用于前后消歧)"""
    r1, c1 = frm
    r2, c2 = to
    red = ch.isupper()
    name = NAME[ch]

    def fnum(c):  # 纵线号: 红方从右往左 一~九, 黑方从左往右 1~9(黑方视角)
        return CN_NUM[8 - c] if red else str(c + 1)

    def step(n):
        return CN_NUM[n - 1] if red else str(n)

    # 同列同种棋子 >= 2 时用 前/中/后 消歧(红方向上为前, 黑方向下为前)
    prefix = ""
    same_col = [frm] + [(r, c) for r in range(rec.ROWS)
                        for c in (c1,) if grid[r][c] == ch and (r, c) != frm]
    if len(same_col) > 1:
        same_col.sort(key=lambda t: t[0], reverse=not red)
        labels = ["前", "中", "后"] if len(same_col) == 3 else \
            (["前", "后"] if len(same_col) == 2 else
             ["前"] + [CN_NUM[i] for i in range(1, len(same_col) - 1)] + ["后"])
        prefix = labels[same_col.index(frm)]

    head = f"{prefix}{name}" if prefix else f"{name}{fnum(c1)}"  # 消歧时省略出发纵线
    if r1 == r2:
        return f"{head}平{fnum(c2)}"
    forward = r2 < r1 if red else r2 > r1
    verb = "进" if forward else "退"
    if ch.upper() in "NBA":  # 斜行棋子(马相仕)进退报落点纵线
        return f"{head}{verb}{fnum(c2)}"
    return f"{head}{verb}{step(abs(r2 - r1))}"


def detect_move(prev, cur):
    """对比两个局面, 返回 (frm, to, 走子, 被吃子|None); 无法唯一确定时返回 (None,)*4"""
    changed = [(r, c) for r in range(rec.ROWS) for c in range(rec.COLS)
               if prev[r][c] != cur[r][c]]
    removed = [(r, c, prev[r][c]) for r, c in changed if prev[r][c]]
    added = [(r, c, cur[r][c]) for r, c in changed if cur[r][c]]
    for r2, c2, ch in added:
        srcs = [t for t in removed if t[2] == ch and (t[0], t[1]) != (r2, c2)]
        others = [t for t in removed if t not in srcs]
        # 其余变化必须恰好是 (r2,c2) 处被吃的子
        if len(srcs) == 1 and len(others) <= 1 and \
                all((r, c) == (r2, c2) for r, c, _ in others):
            r1, c1, _ = srcs[0]
            return (r1, c1), (r2, c2), ch, (others[0][2] if others else None)
    return None, None, None, None


def apply_move(grid, frm, to):
    """返回应用一步走子后的新局面(不修改原局面)"""
    g2 = [row[:] for row in grid]
    g2[to[0]][to[1]] = g2[frm[0]][frm[1]]
    g2[frm[0]][frm[1]] = None
    return g2
