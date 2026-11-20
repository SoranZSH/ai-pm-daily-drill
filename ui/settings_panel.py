# -*- coding: utf-8 -*-
"""设置面板：学习节奏（每天一题 / 多题提醒、每日上限）、提醒时机、题库余量。

从托盘图标的「设置…」打开。写法沿用练习窗口：无边框圆角窗口、顶栏可拖动、
分区标题 + 卡片、底栏按钮；所有尺寸经 px()、颜色取自 theme。
"""

import tkinter as tk
import tkinter.font  # noqa: F401

from . import state
from . import theme
from .practice import round_window, show_in_taskbar
from .theme import (CARD, CARD_HI, CORAL, GOLD, MINT, SKY, TEXT, TEXT_DIM, TEXT_MUTE,
                    VIOLET, VIOLET_HI, GlowButton, drag_bind, f, fade, mix, px)

LW = 720
RADIUS = 18
PAD = 34

# (设置键, 标题, 说明, [(按钮文字, 值), ...])
ROWS_PACE = [
    ("mode", "学习模式", "学过之后，还要不要继续提醒下一题",
     [("每天一题", "single"), ("多题提醒", "multi")]),
    ("new_per_day", "每天新题上限", "复习题不占名额",
     [("1", 1), ("2", 2), ("3", 3), ("5", 5), ("8", 8)]),
    ("max_per_day", "每天最多练", "新题和复习题合计",
     [("3", 3), ("5", 5), ("8", 8), ("12", 12), ("不限", 0)]),
]
ROWS_NUDGE = [
    ("interval_min", "提醒间隔", "点了稍后或学完一题后，隔多久再敲门",
     [("30 分钟", 30), ("1 小时", 60), ("1.5 小时", 90), ("2 小时", 120)]),
    ("warmup_min", "每天第一次提醒", "先让你用一会儿电脑，回到座位时再敲门",
     [("5 分钟后", 5), ("10 分钟后", 10), ("20 分钟后", 20), ("30 分钟后", 30)]),
    ("popup_secs", "弹窗停留", "没人理会就自动收起，过一阵再试",
     [("45 秒", 45), ("75 秒", 75), ("2 分钟", 120)]),
    ("day_start_hour", "新的一天从", "零点后接着学的，算前一天还是新的一天",
     [("零点", 0), ("凌晨 4 点", 4)]),
]


class Segment(tk.Frame):
    """分段选择：一排按钮里选一个（选中的实心，其余描边）。"""

    def __init__(self, master, options, value, accent=VIOLET, bg=CARD_HI, on_change=None):
        super().__init__(master, bg=bg)
        self.value = value
        self.on_change = on_change
        self.btns = []
        probe = tk.font.Font(family=f(9)[0], size=f(9)[1])
        for label, val in options:
            w = max(46, round(probe.measure(label) / theme.S) + 26)   # GlowButton 的宽度是逻辑像素
            b = GlowButton(self, label, lambda v=val: self.select(v), w=w, h=32,
                           accent=accent, bg=bg, filled=(val == value), font=f(9))
            b.pack(side="left", padx=(0, px(7)))
            self.btns.append((val, b))
        if value not in [v for _, v in options]:      # 手改过文件、不在选项里的值：都不高亮，保存时保留原值
            self.custom = True
        else:
            self.custom = False

    def select(self, value):
        self.value = value
        self.custom = False
        for val, b in self.btns:
            b.set_filled(val == value)
        if self.on_change:
            self.on_change(value)


class SettingsPanel:
    def __init__(self, master, on_close=None, on_saved=None):
        self.on_close, self.on_saved = on_close, on_saved
        self.cfg = state.settings()
        self.segs = {}
        self.closed = False

        w = self.win = tk.Toplevel(master)
        theme.init_scale(w)
        self.W, self.pad = px(LW), px(PAD)
        w.overrideredirect(True)
        w.configure(bg=CARD)
        w.attributes("-topmost", True)
        w.attributes("-alpha", 0.0)
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        room = sh - px(60)
        # 高度按内容算：先照完整版排一遍，屏幕太矮放不下就省掉每行的说明文字再排
        self.compact = False
        self.H = self._build()
        if self.H > room:
            for child in w.winfo_children():
                child.destroy()
            self.segs = {}
            self.compact = True
            self.H = min(self._build(), room)
        w.geometry(f"{self.W}x{self.H}+{(sw - self.W) // 2}+{max(px(16), (sh - self.H) // 2 - px(20))}")
        show_in_taskbar(w, "每日一题 · 设置")
        round_window(w, self.W, self.H, px(RADIUS))

        w.bind("<Escape>", lambda e: self.close())
        w.focus_force()
        fade(w, 0.0, 1.0, 180, done=lambda: w.attributes("-topmost", False))

    # ── 结构 ─────────────────────────────────────────────────────────────
    def _build(self):
        barh = px(46)
        bar = tk.Frame(self.win, bg=CARD_HI, height=barh)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        drag_bind(self.win, bar)
        strip = tk.Canvas(bar, width=px(4), height=barh, bg=CARD_HI,
                          highlightthickness=0, bd=0)
        strip.pack(side="left")
        for i in range(barh):
            strip.create_line(0, i, px(4), i, fill=mix(VIOLET, VIOLET_HI, i / barh))
        lbl = tk.Label(bar, text="  每日一题 · 设置", bg=CARD_HI, fg=TEXT, font=f(11, "bold"))
        lbl.pack(side="left", padx=(px(8), 0))
        drag_bind(self.win, lbl)
        x = tk.Label(bar, text="✕", bg=CARD_HI, fg=TEXT_DIM, font=f(12),
                     cursor="hand2", padx=px(9))
        x.pack(side="right", padx=(0, px(10)))
        x.bind("<Button-1>", lambda e: self.close())
        x.bind("<Enter>", lambda e: x.config(fg=CORAL))
        x.bind("<Leave>", lambda e: x.config(fg=TEXT_DIM))
        tk.Label(bar, text="Esc 关闭", bg=CARD_HI, fg=TEXT_MUTE,
                 font=f(8)).pack(side="right", padx=(px(10), px(6)))

        foot = tk.Frame(self.win, bg=CARD_HI, height=px(62))
        foot.pack(fill="x", side="bottom")
        foot.pack_propagate(False)
        row = tk.Frame(foot, bg=CARD_HI)
        row.pack(expand=True)
        GlowButton(row, "保存", self.save, w=132, h=40, accent=MINT, bg=CARD_HI,
                   font=f(11, "bold")).pack(side="left")
        GlowButton(row, "取消", self.close, w=112, h=40, accent=TEXT_DIM, bg=CARD_HI,
                   filled=False, font=f(9)).pack(side="left", padx=px(8))
        self.note = tk.Label(row, text="   保存后立即生效", bg=CARD_HI, fg=TEXT_MUTE, font=f(8))
        self.note.pack(side="left")

        body = tk.Frame(self.win, bg=CARD)
        body.pack(fill="both", expand=True, padx=self.pad)

        self._section(body, "学习节奏", "PACE", MINT)
        card = self._card(body)
        for i, r in enumerate(ROWS_PACE):
            self._row(card, r, VIOLET, first=(i == 0))

        self._section(body, "提醒", "REMINDERS", SKY)
        card = self._card(body)
        for i, r in enumerate(ROWS_NUDGE):
            self._row(card, r, VIOLET, first=(i == 0))

        self._section(body, "题库余量", "SUPPLY", GOLD)
        card = self._card(body, pady=14)
        self.supply = tk.Label(card, text=self._supply_text(), bg=CARD_HI, fg=TEXT,
                               font=f(10), justify="left", anchor="w",
                               wraplength=self.W - self.pad * 2 - px(40))
        self.supply.pack(fill="x")

        self.win.update_idletasks()
        return barh + px(62) + body.winfo_reqheight() + px(16)

    def _section(self, parent, title, en, color):
        fr = tk.Frame(parent, bg=CARD)
        fr.pack(fill="x", pady=(px(16), px(7)), anchor="w")
        c = tk.Canvas(fr, width=px(3), height=px(15), bg=CARD, highlightthickness=0, bd=0)
        c.create_rectangle(0, 0, px(3), px(15), fill=color, outline="")
        c.pack(side="left", padx=(0, px(9)))
        tk.Label(fr, text=title, bg=CARD, fg=TEXT, font=f(11, "bold")).pack(side="left")
        tk.Label(fr, text="  " + en, bg=CARD, fg=TEXT_MUTE,
                 font=f(8, "normal", en=True)).pack(side="left")

    def _card(self, parent, pady=8):
        box = tk.Frame(parent, bg=CARD_HI)
        box.pack(fill="x", pady=(0, px(6)))
        inner = tk.Frame(box, bg=CARD_HI)
        inner.pack(fill="x", padx=px(18), pady=px(pady))
        return inner

    def _row(self, card, spec, accent, first=False):
        key, title, hint, options = spec
        if not first:
            tk.Frame(card, bg=mix(CARD_HI, TEXT, .08), height=1).pack(fill="x")
        row = tk.Frame(card, bg=CARD_HI)
        row.pack(fill="x", pady=px(6))
        left = tk.Frame(row, bg=CARD_HI)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=title, bg=CARD_HI, fg=TEXT, font=f(10), anchor="w").pack(fill="x")
        if not self.compact:
            tk.Label(left, text=hint, bg=CARD_HI, fg=TEXT_MUTE, font=f(8), anchor="w",
                     justify="left", wraplength=px(290)).pack(fill="x")
        seg = Segment(row, options, self.cfg[key], accent=accent,
                      on_change=lambda v: self._changed())
        seg.pack(side="right")
        self.segs[key] = seg

    # ── 数据 ─────────────────────────────────────────────────────────────
    def values(self):
        return {k: seg.value for k, seg in self.segs.items()}

    def _supply_text(self):
        try:
            h = state.load()
            sup = state.supply(h, state.bank())
        except (SystemExit, Exception):
            return "读不到题库"
        per = self.segs["new_per_day"].value if "new_per_day" in self.segs else self.cfg["new_per_day"]
        if "mode" in self.segs and self.segs["mode"].value == "single":
            per = 1
        line = f"共 {sup['total']} 道，还没学的 {sup['unseen']} 道，今天到期复习 {sup['due']} 道。"
        if sup["unseen"]:
            line += (f"\n现在能学的新题 {sup['open']} 道，其余要等前置的基础题记住之后解锁。"
                     f"按每天 {per} 道新题，全部学完至少还要 {-(-sup['unseen'] // per)} 天。")
        else:
            line += "\n新题都学过了，等题库更新。"
        return line

    def _changed(self):
        self.supply.config(text=self._supply_text())
        self.note.config(text="   有改动，记得保存", fg=GOLD)

    # ── 出口 ─────────────────────────────────────────────────────────────
    def save(self):
        state.daily.save_settings(self.values())
        if self.on_saved:
            self.on_saved()
        self.close()

    def bring_front(self):
        from .practice import bring_front
        bring_front(self.win)

    def close(self):
        if self.closed:
            return
        self.closed = True
        fade(self.win, 1.0, 0.0, 160, done=self._destroy)

    def _destroy(self):
        try:
            self.win.destroy()
        except Exception:
            pass
        if self.on_close:
            self.on_close()
