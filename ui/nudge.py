# -*- coding: utf-8 -*-
"""右下角提醒弹窗。

同一个弹窗有四种用法（kind）：
  first   今天第一次敲门：现在练习 | 随机换题 → 算了，今天休息 | 稍后再说
  next    今天已经学过，再来一道（多题提醒）：现在练习 | 今天到此为止 | 稍后再说
  resume  练习窗口开着没做完，被晾了一阵：回去做完 | 先收起来 | 稍后再说
  notice  只告知一句话（比如「贪多嚼不烂，夯实基础下次继续」）：好的

弹窗不进任务栏、不抢键盘焦点；没人理会到时自动收起。
"""

import datetime as dt
import random
import tkinter as tk

from . import state
from . import theme
from .practice import no_activate, round_window, work_area
from .theme import (CARD, CARD_HI, CHIP, CORAL, GOLD, MINT, SKY, TEXT, TEXT_DIM,
                    TEXT_MUTE, VIOLET, VIOLET_HI, CAT_COLOR, GlowButton, chip,
                    drag_bind, f, fade, mix, px)

LW, LH = 400, 254      # 逻辑尺寸
LH_NOTICE = 150        # 只有一句话时的高度
MARGIN_R, MARGIN_B = 20, 12   # 距可用区域（不含任务栏）右、下边缘
LIFE = 75              # 秒；默认停留时间，实际以设置里的 popup_secs 为准

GREET = {
    "morning":   ("☕", ["早上脑子最清楚", "趁开工前热个身", "今天从一道题开始"]),
    "noon":      ("🍜", ["午休来一道", "十分钟，练一道", "换换脑子"]),
    "afternoon": ("🌤", ["下午茶时间", "空隙里练一道", "五分钟就够"]),
    "evening":   ("🌙", ["今天还没练", "睡前最后一件事", "别断了连胜"]),
}


def slot():
    h = dt.datetime.now().hour
    return ("evening" if h < 4 else "morning" if h < 11 else "noon" if h < 14
            else "afternoon" if h < 18 else "evening")


def span_text(minutes):
    """90 → 「1.5 小时」，30 → 「30 分钟」。"""
    if minutes < 60:
        return f"{minutes} 分钟"
    h = minutes / 60
    return f"{int(h) if h == int(h) else round(h, 1)} 小时"


class Nudge:
    def __init__(self, master, on_practice, on_snooze, on_skip, kind="first",
                 on_stop=None, item=None, text=None):
        self.on_practice, self.on_snooze, self.on_skip = on_practice, on_snooze, on_skip
        self.on_stop = on_stop
        self.kind = kind
        self.text = text or ("", "")
        self.closed = False
        self.paused = False

        cfg = state.settings()
        self.life = self.left = cfg["popup_secs"]
        self.interval = cfg["interval_min"]

        hist = state.load()
        self.item = item
        if self.item is None and kind in ("first", "next"):
            self.item, why = state.current_question(hist, state.bank())
            if self.item is None:                     # 今天没有可练的了：改成告知
                self.kind = "notice"
                self.text = (state.NO_MORE.get(why, state.NO_MORE["empty"]), "今天先到这里")
        self.review = bool(self.item) and state.is_review(hist, self.item)
        self.total_days, self.streak, self.best = state.stats(hist)
        self.count = state.count_today(hist)
        self.swapped = state.swapped_today(hist)    # 今天换过题 → 按钮直接是「算了，今天休息」

        w = self.win = tk.Toplevel(master)
        theme.init_scale(w)
        self.W, self.H = px(LW), px(LH_NOTICE if self.kind == "notice" else LH)

        w.overrideredirect(True)
        w.configure(bg=CARD)
        w.attributes("-topmost", True)
        w.attributes("-alpha", 0.0)
        _, _, right, bottom = work_area(w)
        self.x = right - self.W - px(MARGIN_R)
        self.y = bottom - self.H - px(MARGIN_B)
        self.slide = px(40)
        w.geometry(f"{self.W}x{self.H}+{self.x + self.slide}+{self.y}")
        no_activate(w)

        self._build()
        self._fit()
        w.bind("<Enter>", lambda e: setattr(self, "paused", True))
        w.bind("<Leave>", lambda e: setattr(self, "paused", False))
        self._slide_in()
        self._countdown()

    def _fit(self):
        """高度按内容来：题目折成两行、或者字体比预想的高时，窗口向上长高，底部说明不被裁掉。"""
        self.win.update_idletasks()
        need = self.content.winfo_reqheight()
        if need > self.H:
            self.y -= need - self.H
            self.H = need
            self.win.geometry(f"{self.W}x{self.H}+{self.x}+{self.y}")
        round_window(self.win, self.W, self.H, px(16))

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
        frac = max(0.0, self.left / self.life)
        h = px(3)
        self.bar.delete("all")
        self.bar.create_rectangle(0, 0, self.W, h, fill=CHIP, outline="")
        if frac > 0:
            self.bar.create_rectangle(0, 0, self.W * frac, h,
                                      fill=mix(self.accent, CORAL, 1 - frac), outline="")
        if self.left <= 0:
            return self.snooze("timeout")
        self.win.after(100, self._countdown)

    # ── 文案 ─────────────────────────────────────────────────────────────
    def _words(self):
        """(图标, 标题, 副标题, 预览卡上的小字, 底部说明)"""
        emoji, lines = GREET[slot()]
        back = f"忽略的话，等你再用 {span_text(self.interval)}电脑我会回来敲门"
        if self.kind == "next":
            return ("📚", "再来一道？", "趁热打铁，十分钟一道",
                    "到期复习" if self.review else "接下来这道", back)
        if self.kind == "resume":
            return ("📌", "刚才那道题还开着",
                    "做完这道再收工" if self.count else "做完它，今天才算学过",
                    "还开着的这道", "题开着没做完的话，过一阵我会再提醒")
        if self.kind == "notice":
            return ("🌱", self.text[0], self.text[1], "", "")
        return (emoji, "今天要练习英语面试技巧吗？", random.choice(lines),
                "换了一道，这道呢？" if self.swapped else
                ("到期复习" if self.review else "今天抽到的是"), back)

    # ── 结构 ─────────────────────────────────────────────────────────────
    def _build(self):
        it = self.item
        self.accent = accent = CAT_COLOR.get(it["category"], VIOLET) if it else MINT
        emoji, title, sub, hook, foot = self._words()
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

        head = tk.Frame(body, bg=CARD)
        head.pack(fill="x")
        tk.Label(head, text=emoji, bg=CARD, fg=TEXT,
                 font=("Segoe UI Emoji", 17)).pack(side="left", padx=(0, px(9)))
        col = tk.Frame(head, bg=CARD)
        col.pack(side="left", fill="x", expand=True)
        tk.Label(col, text=title, bg=CARD, fg=TEXT,
                 font=f(11, "bold"), anchor="w").pack(fill="x")
        tk.Label(col, text=sub, bg=CARD, fg=TEXT_MUTE,
                 font=f(9), anchor="w").pack(fill="x")

        x = tk.Label(head, text="✕", bg=CARD, fg=TEXT_MUTE, font=f(9), cursor="hand2")
        x.pack(side="right", anchor="n")
        x.bind("<Button-1>", lambda e: self.snooze("close"))
        x.bind("<Enter>", lambda e: x.config(fg=CORAL))
        x.bind("<Leave>", lambda e: x.config(fg=TEXT_MUTE))

        if self.kind != "notice":
            # 战绩
            stat = tk.Frame(body, bg=CARD)
            stat.pack(fill="x", pady=(px(11), 0))
            if self.kind == "first":
                bits = [("📅", f"累计 {self.total_days} 天", TEXT_DIM),
                        ("🔥", f"连续 {self.streak} 天", GOLD if self.streak else TEXT_MUTE),
                        ("🏆", f"最长 {self.best} 天", TEXT_DIM)]
            else:
                bits = [("✅", f"今天已学 {self.count} 题", MINT if self.count else TEXT_MUTE),
                        ("🔥", f"连续 {self.streak} 天", GOLD if self.streak else TEXT_MUTE)]
            for ic, txt, c in bits:
                tk.Label(stat, text=f"{ic} {txt}", bg=CARD, fg=c,
                         font=f(8)).pack(side="left", padx=(0, px(12)))

            # 题目预览（钩子）
            card = tk.Frame(body, bg=CARD_HI)
            card.pack(fill="x", pady=(px(10), 0))
            inner = tk.Frame(card, bg=CARD_HI)
            inner.pack(fill="x", padx=px(13), pady=px(11))
            r = tk.Frame(inner, bg=CARD_HI)
            r.pack(fill="x")
            tk.Label(r, text=hook, bg=CARD_HI, fg=TEXT_MUTE, font=f(8)).pack(side="left")
            chip(r, it["category"], accent, bg=CARD_HI, size=8, pad=7).pack(side="right")
            q = it["q_cn"]
            tk.Label(inner, text=q if len(q) <= 34 else q[:33] + "…", bg=CARD_HI, fg=TEXT,
                     font=f(10, "bold"), anchor="w", justify="left",
                     wraplength=self.W - px(66)).pack(fill="x", pady=(px(6), 0))

        # 按钮
        btns = tk.Frame(body, bg=CARD)
        btns.pack(fill="x", pady=(px(13), 0))

        def main(label, cmd, pulse=True):
            GlowButton(btns, label, cmd, w=132, h=40, accent=accent,
                       bg=CARD, font=f(11, "bold"), pulse=pulse).pack(side="left")

        def second(label, cmd, color):
            GlowButton(btns, label, cmd, w=118, h=40, accent=color,
                       bg=CARD, filled=False, font=f(9)).pack(side="left", padx=px(7))

        def later():
            GlowButton(btns, "稍后再说", lambda: self.snooze("later"), w=84, h=40,
                       accent=TEXT_DIM, bg=CARD, filled=False, font=f(9)).pack(side="left")

        if self.kind == "notice":
            main("好的", lambda: self.snooze("ok"), pulse=False)
        elif self.kind == "next":
            main("现在练习  →", self.practice)
            second("今天到此为止", self.stop, CORAL)
            later()
        elif self.kind == "resume":
            main("回去做完  →", self.practice)
            second("先收起来", self.stop, CORAL)
            later()
        else:
            main("现在练习  →", self.practice)
            if self.swapped:
                second("算了，今天休息", self.rest, CORAL)
            else:
                second("🎲 随机换题", self.swap, SKY)
            later()

        if foot:
            tk.Label(body, text=foot, bg=CARD, fg=TEXT_MUTE, font=f(8)).pack(pady=(px(7), 0))

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

    def snooze(self, reason="later"):
        """reason: later 点了稍后 / close 点了 ✕ / timeout 没人理自动收起 / ok 告知已读。"""
        self._dismiss(lambda: self.on_snooze(reason))

    def stop(self):
        """今天到此为止（next）/ 把开着的练习窗口收起来（resume）。"""
        self._dismiss(self.on_stop or (lambda: self.on_snooze("later")))

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
        self.review = False
        self.left = self.life               # 换题后重新给足时间
        self.x, self.y = self.win.winfo_x(), self.win.winfo_y()   # 可能被拖动过
        self.content.destroy()
        self._build()
        self._fit()

    def rest(self):
        """换了题还是不想学 → 今天休息（记为「换题后休息」）。"""
        qid = self.item["id"]
        self._dismiss(lambda: self.on_skip(after_swap=True, qid=qid))
