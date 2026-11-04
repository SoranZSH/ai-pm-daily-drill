# -*- coding: utf-8 -*-
"""右下角提醒弹窗。"""

import datetime as dt
import random
import tkinter as tk

from . import state
from . import theme
from .practice import round_window, show_in_taskbar
from .theme import (CARD, CARD_HI, CHIP, CORAL, GOLD, MINT, SKY, TEXT, TEXT_DIM,
                    TEXT_MUTE, VIOLET, VIOLET_HI, CAT_COLOR, GlowButton, chip,
                    drag_bind, f, fade, mix, px)

LW, LH = 400, 254      # 逻辑尺寸
MARGIN_R, MARGIN_B = 20, 58
LIFE = 75              # 秒；无人理会则自动收起，算作「忽略」

GREET = {
    "morning":   ("☕", ["早上脑子最清楚", "趁开工前热个身", "今天从一道题开始"]),
    "noon":      ("🍜", ["午休来一道", "十分钟，练一道", "换换脑子"]),
    "afternoon": ("🌤", ["下午茶时间", "空隙里练一道", "五分钟就够"]),
    "evening":   ("🌙", ["今天还没练", "睡前最后一件事", "别断了连胜"]),
}


def slot():
    h = dt.datetime.now().hour
    return ("morning" if h < 11 else "noon" if h < 14
            else "afternoon" if h < 18 else "evening")


class Nudge:
    def __init__(self, master, on_practice, on_snooze, on_skip):
        self.on_practice, self.on_snooze, self.on_skip = on_practice, on_snooze, on_skip
        self.closed = False
        self.left = LIFE
        self.paused = False

        hist = state.load()
        self.item = state.today_question(hist, state.bank())
        self.total_days, self.streak, self.best = state.stats(hist)
        self.swapped = state.swapped_today(hist)    # 今天换过题 → 按钮直接是「算了，今天休息」

        w = self.win = tk.Toplevel(master)
        theme.init_scale(w)
        self.W, self.H = px(LW), px(LH)

        w.overrideredirect(True)
        w.configure(bg=CARD)
        w.attributes("-topmost", True)
        w.attributes("-alpha", 0.0)
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        self.x = sw - self.W - px(MARGIN_R)
        self.y = sh - self.H - px(MARGIN_B)
        self.slide = px(40)
        w.geometry(f"{self.W}x{self.H}+{self.x + self.slide}+{self.y}")
        show_in_taskbar(w, "今天要练习英语面试技巧吗？")
        round_window(w, self.W, self.H, px(16))

        self._build()
        w.bind("<Enter>", lambda e: setattr(self, "paused", True))
        w.bind("<Leave>", lambda e: setattr(self, "paused", False))
        self._slide_in()
        self._countdown()

    # ── 动画 ─────────────────────────────────────────────────────────────
    def _slide_in(self, step=0):
        n = 16
        if self.closed:
            return
        if step <= n:
            t = 1 - (1 - step / n) ** 3
            self.win.geometry(
                f"{self.W}x{self.H}+{int(self.x + self.slide * (1 - t))}+{self.y}")
            self.win.attributes("-alpha", t)
            self.win.after(14, lambda: self._slide_in(step + 1))
        else:
            self.win.attributes("-alpha", 1.0)

    def _countdown(self):
        if self.closed:
            return
        if not self.paused:
            self.left -= 0.1
        frac = max(0.0, self.left / LIFE)
        h = px(3)
        self.bar.delete("all")
        self.bar.create_rectangle(0, 0, self.W, h, fill=CHIP, outline="")
        if frac > 0:
            self.bar.create_rectangle(0, 0, self.W * frac, h,
                                      fill=mix(self.accent, CORAL, 1 - frac), outline="")
        if self.left <= 0:
            return self.snooze()
        self.win.after(100, self._countdown)

    # ── 结构 ─────────────────────────────────────────────────────────────
    def _build(self):
        it = self.item
        self.accent = accent = CAT_COLOR.get(it["category"], VIOLET)
        # 所有内容放进 content，换题时整块销毁重建
        w = self.content = tk.Frame(self.win, bg=CARD)
        w.pack(fill="both", expand=True)

        top = tk.Canvas(w, width=self.W, height=px(4), bg=CARD,
                        highlightthickness=0, bd=0)
        top.pack(fill="x")
        for i in range(0, self.W, 2):
            top.create_line(i, 0, i + 2, 0, fill=mix(accent, VIOLET_HI, i / self.W),
                            width=px(4))
        drag_bind(self.win, top)

        body = tk.Frame(w, bg=CARD)
        body.pack(fill="both", expand=True, padx=px(18), pady=(px(13), 0))
        drag_bind(self.win, body)

        emoji, lines = GREET[slot()]
        head = tk.Frame(body, bg=CARD)
        head.pack(fill="x")
        tk.Label(head, text=emoji, bg=CARD, fg=TEXT,
                 font=("Segoe UI Emoji", 17)).pack(side="left", padx=(0, px(9)))
        col = tk.Frame(head, bg=CARD)
        col.pack(side="left", fill="x", expand=True)
        tk.Label(col, text="今天要练习英语面试技巧吗？", bg=CARD, fg=TEXT,
                 font=f(11, "bold"), anchor="w").pack(fill="x")
        tk.Label(col, text=random.choice(lines), bg=CARD, fg=TEXT_MUTE,
                 font=f(9), anchor="w").pack(fill="x")

        x = tk.Label(head, text="✕", bg=CARD, fg=TEXT_MUTE, font=f(9), cursor="hand2")
        x.pack(side="right", anchor="n")
        x.bind("<Button-1>", lambda e: self.snooze())
        x.bind("<Enter>", lambda e: x.config(fg=CORAL))
        x.bind("<Leave>", lambda e: x.config(fg=TEXT_MUTE))

        # 战绩
        stat = tk.Frame(body, bg=CARD)
        stat.pack(fill="x", pady=(px(11), 0))
        bits = [("📅", f"累计 {self.total_days} 天", TEXT_DIM),
                ("🔥", f"连续 {self.streak} 天", GOLD if self.streak else TEXT_MUTE),
                ("🏆", f"最长 {self.best} 天", TEXT_DIM)]
        for ic, txt, c in bits:
            tk.Label(stat, text=f"{ic} {txt}", bg=CARD, fg=c,
                     font=f(8)).pack(side="left", padx=(0, px(12)))

        # 今日题目预览（钩子）
        card = tk.Frame(body, bg=CARD_HI)
        card.pack(fill="x", pady=(px(10), 0))
        inner = tk.Frame(card, bg=CARD_HI)
        inner.pack(fill="x", padx=px(13), pady=px(11))
        r = tk.Frame(inner, bg=CARD_HI)
        r.pack(fill="x")
        tk.Label(r, text="换了一道，这道呢？" if self.swapped else "今天抽到的是",
                 bg=CARD_HI, fg=TEXT_MUTE,
                 font=f(8)).pack(side="left")
        chip(r, it["category"], accent, bg=CARD_HI, size=8, pad=7).pack(side="right")
        q = it["q_cn"]
        tk.Label(inner, text=q if len(q) <= 34 else q[:33] + "…", bg=CARD_HI, fg=TEXT,
                 font=f(10, "bold"), anchor="w", justify="left",
                 wraplength=self.W - px(66)).pack(fill="x", pady=(px(6), 0))

        # 按钮：现在练习 | 随机换题 → 算了，今天休息 | 稍后再说
        btns = tk.Frame(body, bg=CARD)
        btns.pack(fill="x", pady=(px(13), 0))
        GlowButton(btns, "现在练习  →", self.practice, w=132, h=40, accent=accent,
                   bg=CARD, font=f(11, "bold"), pulse=True).pack(side="left")
        if self.swapped:
            GlowButton(btns, "算了，今天休息", self.rest, w=118, h=40, accent=CORAL,
                       bg=CARD, filled=False, font=f(9)).pack(side="left", padx=px(7))
        else:
            GlowButton(btns, "🎲 随机换题", self.swap, w=118, h=40, accent=SKY,
                       bg=CARD, filled=False, font=f(9)).pack(side="left", padx=px(7))
        GlowButton(btns, "稍后再说", self.snooze, w=84, h=40, accent=TEXT_DIM,
                   bg=CARD, filled=False, font=f(9)).pack(side="left")

        tk.Label(body, text="忽略的话，等你再用 1.5 小时电脑我会回来敲门",
                 bg=CARD, fg=TEXT_MUTE, font=f(8)).pack(pady=(px(7), 0))

        self.bar = tk.Canvas(w, width=self.W, height=px(3), bg=CARD,
                             highlightthickness=0, bd=0)
        self.bar.pack(side="bottom", fill="x")

    # ── 出口 ─────────────────────────────────────────────────────────────
    def _dismiss(self, cb):
        if self.closed:
            return
        self.closed = True
        fade(self.win, 0.98, 0.0, 150, done=lambda: (self.win.destroy(), cb()))

    def practice(self):
        self._dismiss(self.on_practice)

    def snooze(self):
        self._dismiss(self.on_snooze)

    def withdraw_quiet(self):
        """勿扰：立即收起，不触发任何回调（不算稍后、不算休息），之后由守护进程重新弹出。"""
        if self.closed:
            return
        self.closed = True
        try:
            self.win.destroy()
        except Exception:
            pass

    def swap(self):
        """题目不吸引人 → 换一道（每天一次）。换完按钮变成「算了，今天休息」。"""
        if self.closed or self.swapped:
            return
        try:
            h = state.load()
            self.item = state.swap_today(h, state.bank(), self.item["id"])
        except Exception:
            return
        self.swapped = True
        self.left = LIFE                    # 换题后重新给足 75 秒
        self.content.destroy()
        self._build()

    def rest(self):
        """换了题还是不想学 → 今天休息（记为「换题后休息」）。"""
        qid = self.item["id"]
        self._dismiss(lambda: self.on_skip(after_swap=True, qid=qid))
