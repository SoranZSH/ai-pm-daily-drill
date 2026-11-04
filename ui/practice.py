# -*- coding: utf-8 -*-
"""每日一题练习窗口。所有尺寸以逻辑像素书写，px() 负责按屏幕 DPI 换算。"""

import ctypes
import datetime as dt
import math
import random
import tkinter as tk

from . import state
from . import theme
from .theme import (CARD, CARD_HI, CHIP, CORAL, GOLD, MINT, SKY, TEXT,
                    TEXT_DIM, TEXT_MUTE, VIOLET, VIOLET_HI, CAT_COLOR,
                    GlowButton, chip, drag_bind, f, fade, mix, px, rr)

LW = 940               # 逻辑尺寸
LH_GATE = 360          # 揭晓前（只有题干 + 「先自己说」卡片）
LH_FULL = 700          # 揭晓后
LH = LH_FULL           # 对外兼容
RADIUS = 18
PAD = 34


GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
SW_HIDE, SW_SHOW, SW_MINIMIZE, SW_RESTORE = 0, 5, 6, 9


def hwnd_of(win):
    win.update_idletasks()
    return ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()


def round_window(win, w, h, r):
    """用 Windows 区域裁剪出真正的圆角（连子控件一起裁）。参数为物理像素。"""
    try:
        rgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, r * 2, r * 2)
        ctypes.windll.user32.SetWindowRgn(hwnd_of(win), rgn, True)
    except Exception:
        pass


def show_in_taskbar(win, title):
    """无边框窗口默认带 TOOLWINDOW 样式，不进任务栏也不进 Alt+Tab，
    一旦切到别的窗口就再也找不回来。这里改成 APPWINDOW。"""
    try:
        win.title(title)
        u = ctypes.windll.user32
        h = hwnd_of(win)
        try:
            get_l, set_l = u.GetWindowLongPtrW, u.SetWindowLongPtrW
        except AttributeError:            # 32 位 Python 没有 Ptr 版本
            get_l, set_l = u.GetWindowLongW, u.SetWindowLongW
        get_l.restype = ctypes.c_ssize_t
        get_l.argtypes = [ctypes.c_void_p, ctypes.c_int]
        set_l.restype = ctypes.c_ssize_t
        set_l.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        style = get_l(h, GWL_EXSTYLE)
        style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
        u.ShowWindow(h, SW_HIDE)          # 样式变更需要重新显示才生效
        set_l(h, GWL_EXSTYLE, style)
        u.ShowWindow(h, SW_SHOW)
    except Exception:
        pass


def minimize(win):
    try:
        ctypes.windll.user32.ShowWindow(hwnd_of(win), SW_MINIMIZE)
    except Exception:
        pass


def autotext(parent, content, font, fg, bg=CARD, spacing=7):
    """自动撑高的只读文本块（可选中复制）。"""
    t = tk.Text(parent, wrap="word", font=font, fg=fg, bg=bg, bd=0,
                highlightthickness=0, spacing2=px(spacing), spacing3=px(spacing),
                padx=0, pady=0, cursor="arrow", height=1,
                selectbackground=mix(bg, VIOLET, .45), selectforeground="#FFFFFF")
    t.insert("1.0", content)
    t.configure(state="disabled")
    t.pack(fill="x", expand=False)

    def fit(_=None):
        t.configure(state="normal")
        try:
            n = t.count("1.0", "end", "displaylines")[0]
        except Exception:
            n = 8
        t.configure(height=max(1, n), state="disabled")

    t.after_idle(fit)
    t.bind("<Configure>", lambda e: t.after_idle(fit))
    return t


class Practice:
    def __init__(self, master=None, on_close=None):
        self.owns_root = master is None
        self.on_close = on_close
        self.hist = state.load()
        self.item = state.today_question(self.hist, state.bank())
        self.revealed = False
        self.timer_left = 0
        self.timer_job = None

        self.win = tk.Tk() if self.owns_root else tk.Toplevel(master)
        w = self.win
        theme.init_scale(w)
        self.W, self.pad = px(LW), px(PAD)
        self.H_gate, self.H_full = px(LH_GATE), px(LH_FULL)
        self.H = self.H_gate
        self.wrapw = self.W - self.pad * 2

        w.overrideredirect(True)
        w.configure(bg=CARD)
        w.attributes("-topmost", True)
        w.attributes("-alpha", 0.0)
        self.sw, self.sh = w.winfo_screenwidth(), w.winfo_screenheight()
        self.x = (self.sw - self.W) // 2
        self.y = self._center_y(self.H)
        w.geometry(f"{self.W}x{self.H}+{self.x}+{self.y + px(14)}")
        show_in_taskbar(w, "每日一题 · 面试英语")
        round_window(w, self.W, self.H, px(RADIUS))

        self._build()
        w.bind("<Escape>", lambda e: self.close())
        w.bind("<Return>", lambda e: self.reveal())
        w.bind("<space>", lambda e: self.reveal())
        w.focus_force()
        self._enter()
        # 注意：打开窗口不算学习，练完点【完成】/【没记住】才记一天

    # ── 入场动画 ─────────────────────────────────────────────────────────
    def _center_y(self, h):
        return max(px(16), (self.sh - h) // 2 - px(20))

    def _enter(self, step=0):
        n = 14
        if step <= n:
            t = 1 - (1 - step / n) ** 3
            self.win.geometry(
                f"{self.W}x{self.H}+{self.x}+{int(self.y + px(14) * (1 - t))}")
            self.win.attributes("-alpha", t)
            self.win.after(14, lambda: self._enter(step + 1))
        else:
            self.win.attributes("-alpha", 1.0)
            self.win.attributes("-topmost", False)

    def _grow(self, step=0):
        """揭晓答案时把窗口从 gate 高度长到完整高度。"""
        n = 10
        a, b = self.H_gate, self.H_full
        t = 1 - (1 - min(step, n) / n) ** 3
        h = int(a + (b - a) * t)
        y = self._center_y(h)
        self.win.geometry(f"{self.W}x{h}+{self.x}+{y}")
        if step >= n:
            self.H, self.y = b, y
            round_window(self.win, self.W, b, px(RADIUS))
            return
        self.win.after(14, lambda: self._grow(step + 1))

    # ── 结构 ─────────────────────────────────────────────────────────────
    def _build(self):
        it = self.item
        self.accent = accent = CAT_COLOR.get(it["category"], VIOLET)
        barh = px(46)

        # 顶栏
        bar = tk.Frame(self.win, bg=CARD_HI, height=barh)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        drag_bind(self.win, bar)

        strip = tk.Canvas(bar, width=px(4), height=barh, bg=CARD_HI,
                          highlightthickness=0, bd=0)
        strip.pack(side="left")
        for i in range(barh):
            strip.create_line(0, i, px(4), i, fill=mix(accent, VIOLET_HI, i / barh))

        lbl = tk.Label(bar, text="  每日一题", bg=CARD_HI, fg=TEXT, font=f(11, "bold"))
        lbl.pack(side="left", padx=(px(8), 0))
        drag_bind(self.win, lbl)
        d = tk.Label(bar, text=dt.date.today().strftime("  %Y年%m月%d日"),
                     bg=CARD_HI, fg=TEXT_MUTE, font=f(9))
        d.pack(side="left")
        drag_bind(self.win, d)

        def titlebtn(txt, cmd, hover, pad):
            b = tk.Label(bar, text=txt, bg=CARD_HI, fg=TEXT_DIM, font=f(12),
                         cursor="hand2", padx=px(9))
            b.pack(side="right", padx=pad)
            b.bind("<Button-1>", lambda e: cmd())
            b.bind("<Enter>", lambda e: b.config(fg=hover))
            b.bind("<Leave>", lambda e: b.config(fg=TEXT_DIM))
            return b

        titlebtn("✕", self.close, CORAL, (0, px(10)))
        titlebtn("—", lambda: minimize(self.win), TEXT, (0, 0))
        tk.Label(bar, text="Esc 关闭", bg=CARD_HI, fg=TEXT_MUTE,
                 font=f(8)).pack(side="right", padx=(px(10), px(6)))

        total, cur, best = state.stats(self.hist)
        seen = state.seen_count(self.hist)
        tk.Label(bar, text=f"📅 累计 {total} 天   🔥 连续 {cur} 天   🏆 最长 {best} 天"
                           f"   ·   已练 {seen}/{state.total()}",
                 bg=CARD_HI, fg=TEXT_DIM, font=f(9)).pack(side="right")

        # 题干
        head = tk.Frame(self.win, bg=CARD)
        head.pack(fill="x", padx=self.pad, pady=(px(20), 0))

        row = tk.Frame(head, bg=CARD)
        row.pack(fill="x", anchor="w")
        chips = [(it["id"], accent)]
        if it.get("level") in ("F", "X"):           # 题库 v2：基础 / 拓展
            chips.append(("基础", MINT) if it["level"] == "F" else ("拓展", CORAL))
        chips += [(it["category"], TEXT_DIM), (it["difficulty"], GOLD)]
        for txt, col in chips:
            chip(row, txt, col).pack(side="left", padx=(0, px(7)))
        if it.get("tags"):
            tk.Label(row, text="  " + "  ".join("#" + t for t in it["tags"]),
                     bg=CARD, fg=TEXT_MUTE, font=f(9)).pack(side="left")

        tk.Label(head, text=it["q_cn"], bg=CARD, fg=TEXT, font=f(16, "bold"),
                 wraplength=self.wrapw, justify="left",
                 anchor="w").pack(fill="x", pady=(px(14), px(6)))
        tk.Label(head, text=it["q_en"], bg=CARD, fg=accent,
                 font=f(11, "normal", en=True), wraplength=self.wrapw,
                 justify="left", anchor="w").pack(fill="x")
        if it.get("level") == "X":                   # 拓展题：提示它建立在哪些基础题上
            try:
                pre = state.prereq_titles(it, state.bank())
            except SystemExit:
                pre = []
            if pre:
                txt = "前置：" + "；".join(
                    f"{pid} {q[:20]}{'…' if len(q) > 20 else ''}" for pid, q in pre)
                tk.Label(head, text=txt, bg=CARD, fg=TEXT_MUTE, font=f(9),
                         wraplength=self.wrapw, justify="left",
                         anchor="w").pack(fill="x", pady=(px(6), 0))

        # 揭晓前：先自己说一遍
        self.gate = tk.Frame(self.win, bg=CARD)
        self.gate.pack(fill="x", padx=self.pad, pady=(px(22), 0))
        g = tk.Frame(self.gate, bg=CARD_HI)
        g.pack(fill="x", ipady=px(16))

        tk.Label(g, text="🎙  先别看答案 —— 用英文自己说一遍",
                 bg=CARD_HI, fg=TEXT, font=f(12, "bold")).pack(pady=(px(4), px(4)))
        tk.Label(g, text="目标 60–90 秒。说不出来的地方，正是等下要重点背的地方。",
                 bg=CARD_HI, fg=TEXT_MUTE, font=f(9)).pack()

        btns = tk.Frame(g, bg=CARD_HI)
        btns.pack(pady=(px(14), px(2)))
        self.rr_ = px(46)
        self.ring = tk.Canvas(btns, width=self.rr_, height=self.rr_, bg=CARD_HI,
                              highlightthickness=0, bd=0)
        self.ring.pack(side="left", padx=(0, px(12)))
        self._draw_ring(1.0, "90")
        self.timer_btn = GlowButton(btns, "开始计时", self.toggle_timer, w=104, h=42,
                                    accent=SKY, bg=CARD_HI, filled=False,
                                    font=f(10, "bold"))
        self.timer_btn.pack(side="left", padx=(0, px(10)))
        GlowButton(btns, "揭晓参考答案  →", self.reveal, w=180, h=42, accent=accent,
                   bg=CARD_HI, font=f(11, "bold"), pulse=True).pack(side="left")

        # 滚动主体
        self.wrap = tk.Frame(self.win, bg=CARD)
        self.sb = tk.Canvas(self.wrap, width=px(4), bg=CARD,
                            highlightthickness=0, bd=0)
        self.sb.pack(side="right", fill="y", padx=(px(6), 0))
        self.canvas = tk.Canvas(self.wrap, bg=CARD, highlightthickness=0, bd=0,
                                yscrollcommand=self._scrollbar)
        self.body = tk.Frame(self.canvas, bg=CARD)
        self.cwin = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(
            self.cwin, width=e.width))
        self.win.bind_all("<MouseWheel>", self._wheel)

        self.foot = tk.Frame(self.win, bg=CARD_HI, height=px(62))

    def _wheel(self, e):
        if self.revealed:
            self.canvas.yview_scroll(int(-e.delta / 120), "units")

    def _scrollbar(self, first, last):
        """右侧细滚动条：内容超出一屏时才出现。"""
        a, b = float(first), float(last)
        c = self.sb
        c.delete("all")
        if b - a >= 0.999:
            return
        h = c.winfo_height()
        w = px(4)
        c.create_rectangle(0, 0, w, h, fill=mix(CARD, TEXT, .06), outline="")
        y1, y2 = h * a, h * b
        c.create_rectangle(0, y1, w, max(y2, y1 + px(24)),
                           fill=mix(CARD, self.accent, .55), outline="")

    # ── 计时环 ───────────────────────────────────────────────────────────
    def _draw_ring(self, frac, label):
        c, s = self.ring, self.rr_
        c.delete("all")
        m, wd = px(4), px(3)
        c.create_oval(m, m, s - m, s - m, outline=CHIP, width=wd)
        if frac > 0:
            c.create_arc(m, m, s - m, s - m, start=90, extent=-359.9 * frac,
                         style="arc", outline=SKY if frac > .25 else CORAL, width=wd)
        c.create_text(s / 2, s / 2, text=label, fill=TEXT_DIM, font=f(9, "bold"))

    def toggle_timer(self):
        if self.timer_job:
            self.win.after_cancel(self.timer_job)
            self.timer_job = None
            self._draw_ring(1.0, "90")
            self.timer_btn.set_text("开始计时")
        else:
            self.timer_left = 90
            self.timer_btn.set_text("重新计时")
            self._tick()

    def _tick(self):
        self._draw_ring(self.timer_left / 90, str(self.timer_left))
        if self.timer_left <= 0:
            self.timer_job = None
            self._draw_ring(0, "到")
            return
        self.timer_left -= 1
        self.timer_job = self.win.after(1000, self._tick)

    # ── 揭晓 ─────────────────────────────────────────────────────────────
    def reveal(self):
        if self.revealed:
            return
        self.revealed = True
        if self.timer_job:
            self.win.after_cancel(self.timer_job)
            self.timer_job = None
        self.gate.destroy()
        self._grow()
        self.wrap.pack(fill="both", expand=True, padx=self.pad, pady=(px(18), 0))
        self.foot.pack(fill="x", side="bottom")
        self.foot.pack_propagate(False)
        self._fill_body()
        self._fill_foot()

    # ── 解析页（规范 v2.1：第一层对答案，第二层弄懂它；旧题自动退回整段显示） ──
    def _section(self, title, en, color, parent=None):
        fr = tk.Frame(parent or self.body, bg=CARD)
        fr.pack(fill="x", pady=(px(16), px(7)), anchor="w")
        c = tk.Canvas(fr, width=px(3), height=px(15), bg=CARD,
                      highlightthickness=0, bd=0)
        c.create_rectangle(0, 0, px(3), px(15), fill=color, outline="")
        c.pack(side="left", padx=(0, px(9)))
        tk.Label(fr, text=title, bg=CARD, fg=TEXT, font=f(11, "bold")).pack(side="left")
        if en:
            tk.Label(fr, text="  " + en, bg=CARD, fg=TEXT_MUTE,
                     font=f(8, "normal", en=True)).pack(side="left")
        return fr

    def _card(self, parent, pady=14):
        box = tk.Frame(parent, bg=CARD_HI)
        box.pack(fill="x", pady=(0, px(6)))
        inner = tk.Frame(box, bg=CARD_HI)
        inner.pack(fill="x", padx=px(18), pady=px(pady))
        return inner

    def _label(self, parent, text, fg=TEXT, font=None, bg=CARD_HI, pady=0, wrap=None):
        lb = tk.Label(parent, text=text, bg=bg, fg=fg, font=font or f(10),
                      wraplength=wrap or (self.wrapw - px(50)), justify="left", anchor="w")
        lb.pack(fill="x", pady=pady)
        return lb

    def _para(self, parent, text, fg=TEXT, font=None, bg=CARD_HI, pady=0):
        """中文长段落：按字换行，避免夹着英文单词时在空格处断行留下大片空白。"""
        hold = tk.Frame(parent, bg=bg, height=px(24))
        hold.pack_propagate(False)
        t = tk.Text(hold, wrap="char", font=font or f(10), fg=fg, bg=bg, bd=0,
                    highlightthickness=0, padx=0, pady=0, cursor="arrow", height=1,
                    spacing2=px(4), selectbackground=mix(bg, VIOLET, .45),
                    selectforeground="#FFFFFF")
        t.insert("1.0", text)
        t.configure(state="disabled")
        hold.pack(fill="x", pady=pady)
        t.pack(fill="both", expand=True)
        self._pixel_fit(t, hold)
        return t

    @staticmethod
    def _s(v):
        return v.strip() if isinstance(v, str) else ""

    def _fill_body(self):
        it = self.item
        has_l1 = bool(it.get("gist") or it.get("points") or it.get("a_pairs"))
        # 第一层 · 对答案
        if has_l1:
            self._layer1(it)
        else:
            # 旧格式题目：保持原来的顺序（概念解析 → 参考答案）
            self._concept(it, self.body)
            self._section("参考答案 · 背这一段", "MODEL ANSWER", self.accent)
            self._answer(it, self.body)
        # 第二层 · 弄懂它
        deep = it.get("level") == "X" or it.get("difficulty") == "较难" or not has_l1
        self._layer2(it, has_l1, open_=deep)
        tk.Frame(self.body, bg=CARD, height=px(22)).pack()

    # ── 第一层 ───────────────────────────────────────────────────────────
    def _layer1(self, it):
        g = it.get("gist") or {}
        if self._s(g.get("cn")) or self._s(g.get("en")):
            self._section("一句话答案", "THE SHORT ANSWER", self.accent)
            c = self._card(self.body)
            if self._s(g.get("cn")):
                self._label(c, self._s(g["cn"]), font=f(13, "bold"))
            if self._s(g.get("en")):
                self._label(c, self._s(g["en"]), fg=self.accent,
                            font=f(10, "normal", en=True), pady=(px(4), 0))

        pts = [p for p in (it.get("points") or []) if isinstance(p, dict) and self._s(p.get("cn"))]
        self.point_vars = []
        if pts:
            self._section("要点自查 · 我说到了吗？", "SELF-CHECK", MINT)
            c = self._card(self.body, pady=8)
            for i, p in enumerate(pts):
                if i:
                    tk.Frame(c, bg=mix(CARD_HI, TEXT, .08), height=1).pack(fill="x")
                self._point_row(c, p)
            self.point_info = tk.Label(c, text="点击勾选你刚才说到的要点", bg=CARD_HI,
                                       fg=TEXT_MUTE, font=f(9), anchor="w")
            self.point_info.pack(fill="x", pady=(px(6), px(2)))

        self._section("参考答案 · 背这一段", "MODEL ANSWER", self.accent)
        self._answer(it, self.body)

    def _point_row(self, parent, p):
        var = {"on": False}
        row = tk.Frame(parent, bg=CARD_HI, cursor="hand2")
        row.pack(fill="x", pady=px(6))
        box = tk.Label(row, text="☐", bg=CARD_HI, fg=TEXT_DIM, font=f(13), cursor="hand2")
        box.pack(side="left", anchor="n", padx=(0, px(10)))
        txt = tk.Frame(row, bg=CARD_HI, cursor="hand2")
        txt.pack(side="left", fill="x", expand=True)
        a = tk.Label(txt, text=self._s(p.get("cn")), bg=CARD_HI, fg=TEXT, font=f(10),
                     wraplength=self.wrapw - px(90), justify="left", anchor="w", cursor="hand2")
        a.pack(fill="x")
        widgets = [row, box, txt, a]
        if self._s(p.get("en")):
            b = tk.Label(txt, text=self._s(p["en"]), bg=CARD_HI, fg=TEXT_MUTE,
                         font=f(9, "normal", en=True), wraplength=self.wrapw - px(90),
                         justify="left", anchor="w", cursor="hand2")
            b.pack(fill="x")
            widgets.append(b)

        def toggle(_=None):
            var["on"] = not var["on"]
            box.config(text="☑" if var["on"] else "☐", fg=MINT if var["on"] else TEXT_DIM)
            a.config(fg=MINT if var["on"] else TEXT)
            self._update_check()

        for w in widgets:
            w.bind("<Button-1>", toggle)
        self.point_vars.append(var)

    def _update_check(self):
        n, total = sum(v["on"] for v in self.point_vars), len(self.point_vars)
        if not total:
            return
        good = n * 3 >= total * 2          # 说到三分之二以上
        if n == 0:
            info, sug, col = "点击勾选你刚才说到的要点", "", TEXT_MUTE
        elif n == total:
            info, sug, col = f"答到 {n}/{total} 个要点 · 完整", "建议：完成，明天见", MINT
        elif good:
            info, sug, col = f"答到 {n}/{total} 个要点 · 没勾的再看一眼", "建议：完成，明天见", MINT
        else:
            info, sug, col = f"答到 {n}/{total} 个要点", "建议：这题还没记住", CORAL
        self.point_info.config(text=info, fg=col)
        if getattr(self, "sug", None) is not None:
            self.sug.config(text=("   " + sug) if sug else self.sug_default, fg=col if sug else TEXT_MUTE)

    # ── 参考答案：逐句对照 + 关键表达划线 ───────────────────────────────────
    def _answer(self, it, parent):
        pairs = [p for p in (it.get("a_pairs") or [])
                 if isinstance(p, dict) and self._s(p.get("en"))]
        box = tk.Frame(parent, bg=CARD_HI)
        box.pack(fill="x")
        inner = tk.Frame(box, bg=CARD_HI)
        inner.pack(fill="x", padx=px(18), pady=(px(10), px(14)))

        bar = tk.Frame(inner, bg=CARD_HI)
        bar.pack(fill="x", pady=(0, px(6)))
        has_kp = bool(it.get("key_phrases"))
        tk.Label(bar, text="划线的是关键表达，鼠标停在上面看中文" if has_kp else "",
                 bg=CARD_HI, fg=TEXT_MUTE, font=f(8)).pack(side="left")
        cn_btn = tk.Label(bar, text="显示逐句中文" if pairs else "显示中文对照",
                          bg=CHIP, fg=TEXT_DIM, font=f(9), padx=px(10), pady=px(2),
                          cursor="hand2")
        cn_btn.pack(side="right")

        bg = CARD_HI
        holder = tk.Frame(inner, bg=bg, height=px(300))
        holder.pack_propagate(False)
        t = tk.Text(holder, wrap="word", font=f(12, "normal", en=True), fg=TEXT, bg=bg, bd=0,
                    highlightthickness=0, spacing1=px(2), spacing2=px(6), spacing3=px(6),
                    padx=0, pady=0, cursor="arrow", height=1,
                    selectbackground=mix(bg, VIOLET, .45), selectforeground="#FFFFFF")
        t.tag_configure("cn", font=f(10), foreground=TEXT_DIM, spacing3=px(12), elide=True, wrap="char")
        t.tag_configure("kp", underline=True, foreground=MINT)
        if pairs:
            for p in pairs:
                t.insert("end", self._s(p["en"]) + "\n")
                cn = self._s(p.get("cn"))
                if cn:
                    t.insert("end", cn + "\n", "cn")
        else:
            t.insert("end", self._s(it.get("a_en")) + "\n")
            if self._s(it.get("a_cn")):
                t.insert("end", self._s(it["a_cn"]) + "\n", "cn")
        t.delete("end-2c", "end-1c")            # 去掉末尾多余换行

        for i, kp in enumerate(it.get("key_phrases") or []):
            en, cn = self._s(kp.get("en")), self._s(kp.get("cn"))
            if not en:
                continue
            tag = f"kp{i}"
            start = "1.0"
            while True:
                pos = t.search(en, start, stopindex="end")
                if not pos:
                    break
                end = f"{pos}+{len(en)}c"
                if "cn" not in t.tag_names(pos):
                    t.tag_add("kp", pos, end)
                    t.tag_add(tag, pos, end)
                start = end
            tip = cn + ("　·　" + self._s(kp.get("usage")) if self._s(kp.get("usage")) else "")
            t.tag_bind(tag, "<Enter>", lambda e, s=tip: self._float_tip(s, e.x_root, e.y_root))
            t.tag_bind(tag, "<Leave>", lambda e: self._hide_tip())
        t.configure(state="disabled")
        holder.pack(fill="x")
        t.pack(fill="both", expand=True)
        fit = self._pixel_fit(t, holder)

        shown = {"on": False}

        def toggle(_=None):
            shown["on"] = not shown["on"]
            t.tag_configure("cn", elide=not shown["on"])
            if pairs:
                cn_btn.config(text="收起中文" if shown["on"] else "显示逐句中文")
            else:
                cn_btn.config(text="收起中文" if shown["on"] else "显示中文对照")
            t.after_idle(fit)

        cn_btn.bind("<Button-1>", toggle)

    def _float_tip(self, text, x, y):
        self._hide_tip()
        if not text:
            return
        tw = tk.Toplevel(self.win)
        tw.overrideredirect(True)
        tw.attributes("-topmost", True)
        tk.Label(tw, text=text, bg=CHIP, fg=TEXT, font=f(9), padx=px(10), pady=px(5),
                 wraplength=px(360), justify="left").pack()
        tw.geometry(f"+{x + px(8)}+{y + px(16)}")
        self._tipwin = tw

    def _hide_tip(self):
        if getattr(self, "_tipwin", None):
            try:
                self._tipwin.destroy()
            except Exception:
                pass
            self._tipwin = None

    # ── 第二层 ───────────────────────────────────────────────────────────
    def _layer2(self, it, has_l1, open_):
        parts = []
        if it.get("basics"):
            parts.append("基础概念")
        if has_l1 and it.get("concept"):
            parts.append("概念解析")
        if it.get("pitfalls"):
            parts.append("常见误区")
        if it.get("walkthrough"):
            parts.append("难点拆解")
        if it.get("method"):
            parts.append("思维方法")
        if it.get("key_phrases"):
            parts.append("表达积累")
        if it.get("approach") or it.get("tips"):
            parts.append("答题结构")
        if not parts:
            return

        head = tk.Frame(self.body, bg=CARD, cursor="hand2")
        head.pack(fill="x", pady=(px(24), 0))
        arrow = tk.Label(head, text="▾" if open_ else "▸", bg=CARD, fg=TEXT,
                         font=f(12, "bold"), cursor="hand2")
        arrow.pack(side="left")
        t1 = tk.Label(head, text=" 第二层 · 弄懂它", bg=CARD, fg=TEXT, font=f(12, "bold"),
                      cursor="hand2")
        t1.pack(side="left")
        t2 = tk.Label(head, text="   " + " · ".join(parts), bg=CARD, fg=TEXT_MUTE,
                      font=f(9), cursor="hand2")
        t2.pack(side="left")
        tk.Frame(self.body, bg=mix(CARD, TEXT, .10), height=1).pack(fill="x", pady=(px(8), 0))

        holder = tk.Frame(self.body, bg=CARD)
        content = tk.Frame(holder, bg=CARD)
        holder.pack(fill="x")
        state_ = {"open": open_, "built": False}

        def build():
            self._layer2_content(it, content, has_l1)
            state_["built"] = True

        def toggle(_=None):
            state_["open"] = not state_["open"]
            arrow.config(text="▾" if state_["open"] else "▸")
            if state_["open"]:
                if not state_["built"]:
                    build()
                content.pack(fill="x")
            else:
                content.pack_forget()

        for w in (head, arrow, t1, t2):
            w.bind("<Button-1>", toggle)
        if open_:
            build()
            content.pack(fill="x")

    def _concept(self, it, parent):
        con = it.get("concept")
        if not isinstance(con, dict) or not (self._s(con.get("cn")) or self._s(con.get("en"))):
            return
        self._section("概念解析 · 先搞懂再背", "WHAT THIS IS", SKY, parent)
        c = self._card(parent)
        if self._s(con.get("cn")):
            self._para(c, self._s(con["cn"]))
        if self._s(con.get("en")):
            tk.Frame(c, bg=mix(CARD_HI, TEXT, .10), height=1).pack(fill="x", pady=px(10))
            self._label(c, self._s(con["en"]), fg=SKY, font=f(9, "normal", en=True))

    def _layer2_content(self, it, b, has_l1):
        wrap = self.wrapw - px(50)

        basics = [x for x in (it.get("basics") or []) if isinstance(x, dict) and self._s(x.get("term"))]
        if basics:
            self._section("先补基础概念", "BASICS", SKY, b)
            c = self._card(b)
            for i, x in enumerate(basics):
                if i:
                    tk.Frame(c, bg=mix(CARD_HI, TEXT, .08), height=1).pack(fill="x", pady=px(8))
                row = tk.Frame(c, bg=CARD_HI)
                row.pack(fill="x")
                tk.Label(row, text=self._s(x["term"]), bg=CARD_HI, fg=TEXT,
                         font=f(10, "bold")).pack(side="left")
                if self._s(x.get("term_en")):
                    tk.Label(row, text="  " + self._s(x["term_en"]), bg=CARD_HI, fg=TEXT_MUTE,
                             font=f(9, "normal", en=True)).pack(side="left")
                if self._s(x.get("explain")):
                    self._para(c, self._s(x["explain"]), fg=TEXT_DIM, pady=(px(3), 0))
                if self._s(x.get("analogy")):
                    self._label(c, "类比：" + self._s(x["analogy"]), fg=SKY, font=f(9),
                                pady=(px(3), 0))

        if has_l1:
            self._concept(it, b)

        pits = [x for x in (it.get("pitfalls") or []) if isinstance(x, dict) and self._s(x.get("wrong"))]
        if pits:
            self._section("常见误区", "PITFALLS", CORAL, b)
            for x in pits:
                c = self._card(b)
                for key, name, col in (("wrong", "常见误区", CORAL), ("why", "为什么错", GOLD),
                                       ("right", "正确判断", MINT)):
                    if not self._s(x.get(key)):
                        continue
                    row = tk.Frame(c, bg=CARD_HI)
                    row.pack(fill="x", pady=px(3))
                    chip(row, name, col, bg=CARD_HI, size=8).pack(side="left", anchor="n",
                                                                  padx=(0, px(10)))
                    tk.Label(row, text=self._s(x[key]), bg=CARD_HI, fg=TEXT, font=f(10),
                             wraplength=wrap - px(90), justify="left",
                             anchor="w").pack(side="left", fill="x")

        steps = [self._s(s) for s in (it.get("walkthrough") or []) if self._s(s)]
        if steps:
            self._section("难点拆解", "STEP BY STEP", VIOLET_HI, b)
            c = self._card(b)
            nums = "①②③④⑤⑥⑦⑧"
            for i, s in enumerate(steps):
                row = tk.Frame(c, bg=CARD_HI)
                row.pack(fill="x", pady=px(4))
                tk.Label(row, text=nums[i] if i < len(nums) else f"{i + 1}.", bg=CARD_HI,
                         fg=VIOLET_HI, font=f(11, "bold")).pack(side="left", anchor="n",
                                                               padx=(0, px(8)))
                head, sep, rest = s.partition("：")
                hold = tk.Frame(row, bg=CARD_HI, height=px(24))
                hold.pack_propagate(False)
                txt = tk.Text(hold, wrap="word", font=f(10), fg=TEXT_DIM, bg=CARD_HI, bd=0,
                              highlightthickness=0, padx=0, pady=0, height=1, cursor="arrow",
                              spacing2=px(4))
                txt.tag_configure("h", font=f(10, "bold"), foreground=TEXT)
                if sep and len(head) <= 8:
                    txt.insert("end", head + "：", "h")
                    txt.insert("end", rest)
                else:
                    txt.insert("end", s)
                txt.configure(state="disabled")
                hold.pack(side="left", fill="x", expand=True)
                txt.pack(fill="both", expand=True)
                self._pixel_fit(txt, hold)

        m = it.get("method")
        if isinstance(m, dict) and self._s(m.get("name")):
            self._section("思维方法", "THINKING PATTERN", GOLD, b)
            c = self._card(b)
            row = tk.Frame(c, bg=CARD_HI)
            row.pack(fill="x")
            chip(row, self._s(m["name"]), GOLD, bg=CARD_HI).pack(side="left")
            st = [self._s(x) for x in (m.get("steps") or []) if self._s(x)]
            if st:
                tk.Label(row, text="   " + "  →  ".join(st), bg=CARD_HI, fg=TEXT,
                         font=f(10), wraplength=wrap - px(140), justify="left",
                         anchor="w").pack(side="left", fill="x")
            if self._s(m.get("transfer")):
                self._label(c, "还能用在：" + self._s(m["transfer"]), fg=TEXT_DIM,
                            pady=(px(8), 0))

        kps = [x for x in (it.get("key_phrases") or []) if isinstance(x, dict) and self._s(x.get("en"))]
        if kps:
            self._section("表达积累", "KEY PHRASES", MINT, b)
            type_col = {"词汇": SKY, "搭配": MINT, "句型": GOLD}
            for kp in kps:
                c = self._card(b, pady=9)
                row = tk.Frame(c, bg=CARD_HI)
                row.pack(fill="x")
                tk.Label(row, text=self._s(kp["en"]), bg=CARD_HI, fg=MINT,
                         font=f(10, "bold", en=True)).pack(side="left")
                ty = self._s(kp.get("type"))
                if ty:
                    chip(row, ty, type_col.get(ty, TEXT_DIM), bg=CARD_HI, size=8,
                         pad=7).pack(side="left", padx=(px(8), 0))
                if self._s(kp.get("cn")):
                    tk.Label(row, text="  " + self._s(kp["cn"]), bg=CARD_HI, fg=TEXT,
                             font=f(9)).pack(side="left")
                if self._s(kp.get("usage")):
                    self._label(c, self._s(kp["usage"]), fg=TEXT_DIM, font=f(9),
                                pady=(px(3), 0))

        if self._s(it.get("approach")):
            self._section("答题结构", "HOW TO STRUCTURE IT", CORAL, b)
            c = self._card(b)
            self._para(c, self._s(it["approach"]), fg=TEXT_DIM)

        if self._s(it.get("tips")):
            self._section("答题提示", "WHAT THEY'RE LOOKING FOR", GOLD, b)
            t = tk.Frame(b, bg=CARD)
            t.pack(fill="x")
            c = tk.Canvas(t, width=px(3), height=1, bg=CARD, highlightthickness=0, bd=0)
            c.pack(side="left", fill="y", padx=(0, px(11)))
            c.bind("<Configure>", lambda e, c=c: (
                c.delete("all"),
                c.create_rectangle(0, 0, px(3), e.height, fill=GOLD, outline="")))
            tk.Label(t, text=self._s(it["tips"]), bg=CARD, fg=TEXT_DIM, font=f(9),
                     wraplength=self.wrapw - px(20), justify="left",
                     anchor="w").pack(side="left", fill="x")

    @staticmethod
    def _pixel_fit(t, holder):
        """按实际像素高度撑开文本框（行距、中英混排、隐藏行都会让「按行数」算错）。"""
        def fit(_=None):
            try:
                h = t.count("1.0", "end", "update", "ypixels")
                h = h[0] if isinstance(h, tuple) else h
            except Exception:
                h = None
            if h:
                new = int(h) + px(4)
                if abs(holder.winfo_height() - new) > 1:
                    holder.configure(height=new)
        t.after_idle(fit)
        t.bind("<Configure>", lambda e: t.after_idle(fit))
        return fit

    def _fill_foot(self):
        row = tk.Frame(self.foot, bg=CARD_HI)
        row.pack(expand=True)
        GlowButton(row, "完成，明天见", lambda: self.finish(4), w=132, h=40,
                   accent=MINT, bg=CARD_HI, font=f(11, "bold")).pack(side="left")
        GlowButton(row, "这题还没记住", lambda: self.finish(1), w=112, h=40,
                   accent=TEXT_DIM, bg=CARD_HI, filled=False,
                   font=f(9)).pack(side="left", padx=px(8))
        self.sug_default = "   没记住的明天再出现，记住的隔几天再来"
        self.sug = tk.Label(row, text=self.sug_default, bg=CARD_HI, fg=TEXT_MUTE,
                            font=f(9 if self.point_vars_any() else 8))
        self.sug.pack(side="left")

    def point_vars_any(self):
        return bool(getattr(self, "point_vars", None))

    def _tip(self, widget, text):
        def on(_):
            self._tipwin = tw = tk.Toplevel(self.win)
            tw.overrideredirect(True)
            tw.attributes("-topmost", True)
            tk.Label(tw, text=text, bg=CHIP, fg=TEXT, font=f(9),
                     padx=px(8), pady=px(4)).pack()
            tw.geometry(f"+{widget.winfo_rootx() - px(10)}+{widget.winfo_rooty() - px(34)}")

        def off(_):
            if getattr(self, "_tipwin", None):
                self._tipwin.destroy()
                self._tipwin = None

        widget.bind("<Enter>", on, add="+")
        widget.bind("<Leave>", off, add="+")

    # ── 完成 → 庆祝 → 关闭 ───────────────────────────────────────────────
    def finish(self, g):
        st = state.grade(self.hist, self.item["id"], g)
        self._celebrate(f"下次复习 {st['due']}")

    def _celebrate(self, msg):
        ov = tk.Frame(self.win, bg=CARD)
        ov.place(x=0, y=0, relwidth=1, relheight=1)
        c = tk.Canvas(ov, bg=CARD, highlightthickness=0, bd=0)
        c.pack(fill="both", expand=True)
        cx, cy = self.W / 2, self.H / 2 - px(30)

        total, cur, best = state.stats(self.hist)
        record = cur >= best and cur > 1
        c.create_text(cx, cy - px(46), text="🏆" if record else "🔥",
                      font=("Segoe UI Emoji", 36))
        c.create_text(cx, cy + px(20), text=f"连续 {cur} 天", fill=TEXT, font=f(19, "bold"))
        c.create_text(cx, cy + px(54),
                      text=f"累计学习 {total} 天  ·  最长连续 {best} 天"
                           + ("  ·  新纪录！" if record else ""),
                      fill=GOLD if record else TEXT_DIM, font=f(10))
        c.create_text(cx, cy + px(80), text=msg, fill=TEXT_DIM, font=f(10))
        c.create_text(cx, cy + px(112), text="明天见 👋", fill=TEXT_MUTE, font=f(9))

        parts = []
        for _ in range(46):
            a = random.uniform(0, 6.283)
            sp = random.uniform(2.4, 7.5) * theme.S
            parts.append([cx, cy - px(46), -abs(math.sin(a)) * sp - 2 * theme.S,
                          math.cos(a) * sp,
                          random.choice([VIOLET, MINT, GOLD, CORAL, SKY]),
                          random.uniform(2.5, 5) * theme.S])

        def step(n=0):
            c.delete("p")
            alive = False
            for p in parts:
                p[0] += p[3]
                p[1] += p[2]
                p[2] += 0.34 * theme.S
                if p[1] < self.H:
                    alive = True
                    c.create_oval(p[0] - p[5], p[1] - p[5], p[0] + p[5], p[1] + p[5],
                                  fill=p[4], outline="", tags="p")
            if alive and n < 90:
                c.after(16, lambda: step(n + 1))

        step()
        self.win.after(1900, self.close)

    def close(self):
        self._hide_tip()
        try:
            self.win.unbind_all("<MouseWheel>")
        except Exception:
            pass
        fade(self.win, 1.0, 0.0, 160, done=self._destroy)

    def _destroy(self):
        try:
            self.win.destroy()
        except Exception:
            pass
        if self.on_close:
            self.on_close()


def open_practice(master=None, on_close=None):
    p = Practice(master, on_close)
    if p.owns_root:
        p.win.mainloop()
    return p
