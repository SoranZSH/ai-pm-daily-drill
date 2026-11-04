# -*- coding: utf-8 -*-
"""视觉主题：配色、字体、圆角卡片、发光按钮、动画。"""

import math
import tkinter as tk
import tkinter.font  # noqa: F401  (theme.chip 需要 tk.font)

# ── 配色 ──────────────────────────────────────────────────────────────────
MAGIC     = "#FF00FE"   # 透明键色（窗口圆角外的区域）

INK       = "#14161F"   # 最深
CARD      = "#1C1F2D"   # 卡片
CARD_HI   = "#242940"   # 卡片高亮层
CHIP      = "#2B3049"
STROKE    = "#333A55"

TEXT      = "#F4F5F9"
TEXT_DIM  = "#A2A8BE"
TEXT_MUTE = "#6C7391"

VIOLET    = "#7C5CFF"
VIOLET_HI = "#9C85FF"
CORAL     = "#FF7A66"
MINT      = "#37D9A0"
GOLD      = "#FFC46B"
SKY       = "#5CC8FF"

ROSE      = "#FF6B9D"
LIME      = "#A8E05F"
AQUA      = "#4DD8D8"
INDIGO    = "#6C8CFF"
AMBER     = "#F5A65B"

CAT_COLOR = {
    "行为面试": CORAL, "数据分析": SKY, "AI产品经理": VIOLET,
    "数据产品经理": MINT, "数字化转型与解决方案": GOLD, "数字营销": CORAL,
    "市场营销与商业分析": GOLD, "咨询与案例面试": SKY, "简历深挖": VIOLET_HI,
    # 行业专业题库
    "行业 · 金融": MINT, "行业 · 具身智能": VIOLET, "行业 · 汽车": SKY,
    "行业 · 消费电子": AQUA, "行业 · 科技出海": INDIGO, "行业 · 互联网": ROSE,
    "行业 · 能源": LIME, "行业 · 高端制造": AMBER, "行业 · 快消品": GOLD,
    "数据科学与治理": AQUA,
    # 题库 v2：AI 知识题库
    "大模型原理": VIOLET, "提示与上下文工程": GOLD, "检索增强与知识库": SKY,
    "智能体与工具": MINT, "评测与质量": AMBER, "推理部署与成本": INDIGO,
    "训练、微调与数据": ROSE, "多模态与语音": AQUA, "安全与治理": CORAL,
    "AI 产品与商业化": LIME,
}

CN = "Microsoft YaHei UI"
EN = "Segoe UI"


def f(size, weight="normal", en=False):
    return ((EN if en else CN), size, weight)


# ── DPI 缩放 ──────────────────────────────────────────────────────────────
# 字号是「点」，Tk 会按屏幕 DPI 自动放大；但所有尺寸/间距是「像素」，要自己缩。
S = 1.0


def init_scale(root):
    """在创建任何窗口之前调用一次。"""
    global S
    try:
        S = max(1.0, root.winfo_fpixels("1i") / 96.0)
    except Exception:
        S = 1.0
    return S


def px(n):
    return int(round(n * S))


# ── 颜色工具 ──────────────────────────────────────────────────────────────
def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(c1, c2, t):
    """在两色之间插值，t=0 取 c1，t=1 取 c2。"""
    a, b = _rgb(c1), _rgb(c2)
    return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


# ── 圆角矩形 ──────────────────────────────────────────────────────────────
def rr_points(x1, y1, x2, y2, r, steps=9):
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    pts = []
    for cx, cy, a0, a1 in ((x2 - r, y1 + r, -90, 0), (x2 - r, y2 - r, 0, 90),
                           (x1 + r, y2 - r, 90, 180), (x1 + r, y1 + r, 180, 270)):
        for i in range(steps + 1):
            a = math.radians(a0 + (a1 - a0) * i / steps)
            pts += [cx + r * math.cos(a), cy + r * math.sin(a)]
    return pts


def rr(canvas, x1, y1, x2, y2, r, **kw):
    return canvas.create_polygon(rr_points(x1, y1, x2, y2, r), **kw)


def glow(canvas, x1, y1, x2, y2, r, color, base, layers=5, spread=9):
    """在卡片下方画一圈由外向内渐亮的辉光，模拟阴影/发光。"""
    ids = []
    for i in range(layers, 0, -1):
        p = i / layers
        ids.append(rr(canvas, x1 - spread * p, y1 - spread * p,
                      x2 + spread * p, y2 + spread * p, r + spread * p,
                      fill=mix(base, color, 0.10 * (1 - p) + 0.04), outline=""))
    return ids


# ── 发光按钮 ──────────────────────────────────────────────────────────────
class GlowButton(tk.Canvas):
    """圆角按钮：悬停变亮、按下微缩、可呼吸发光。"""

    def __init__(self, master, text, command, w=150, h=44, accent=VIOLET,
                 bg=CARD, filled=True, font=None, radius=None, pulse=False):
        w, h = px(w), px(h)
        super().__init__(master, width=w, height=h, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.cmd, self.w, self.h = command, w, h
        self.accent, self.bg, self.filled = accent, bg, filled
        self.r = px(radius) if radius is not None else h / 2
        self.g = px(3)
        self.font = font or f(11, "bold")
        self.txt = text
        self._hover = False
        self._t = 0.0
        self._pulse = pulse
        self._draw()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        if pulse:
            self._breathe()

    def _draw(self, squeeze=0, boost=0.0):
        self.delete("all")
        s = squeeze * S
        g = self.g
        x1, y1, x2, y2 = 1 + s, 1 + s, self.w - 1 - s, self.h - 1 - s
        if self.filled:
            halo = 0.30 + boost
            for i in (3, 2, 1):
                k = i / 3
                self.create_polygon(rr_points(x1 - g * k, y1 - g * k, x2 + g * k,
                                              y2 + g * k, self.r + g * k),
                                    fill=mix(self.bg, self.accent, halo * (1 - k) * 0.5),
                                    outline="")
            fill = mix(self.accent, "#FFFFFF", 0.18 if self._hover else 0.0)
            rr(self, x1, y1, x2, y2, self.r, fill=fill, outline="")
            fg = "#FFFFFF"
        else:
            rr(self, x1, y1, x2, y2, self.r,
               fill=mix(self.bg, self.accent, 0.16 if self._hover else 0.0),
               outline=mix(STROKE, self.accent, 0.6 if self._hover else 0.0), width=1)
            fg = TEXT if self._hover else TEXT_DIM
        self.create_text(self.w / 2, self.h / 2 + s / 2, text=self.txt,
                         fill=fg, font=self.font)

    def _breathe(self):
        if not self.winfo_exists():
            return
        self._t += 0.06
        if not self._hover:
            self._draw(boost=0.22 * (math.sin(self._t) * 0.5 + 0.5))
        self.after(45, self._breathe)

    def _on_enter(self, _):
        self._hover = True
        self._draw()

    def _on_leave(self, _):
        self._hover = False
        self._draw()

    def _on_press(self, _):
        self._draw(squeeze=1.5)

    def _on_release(self, e):
        self._draw()
        if 0 <= e.x <= self.w and 0 <= e.y <= self.h:
            self.cmd()

    def set_text(self, t):
        self.txt = t
        self._draw()


# ── 小组件 ────────────────────────────────────────────────────────────────
def chip(parent, text, color, bg=CARD, pad=9, size=9):
    """胶囊标签。"""
    fnt = f(size, "bold")
    probe = tk.font.Font(family=fnt[0], size=fnt[1], weight=fnt[2])
    w, h = probe.measure(text) + px(pad) * 2, px(22)
    c = tk.Canvas(parent, width=w, height=h, bg=bg, highlightthickness=0, bd=0)
    rr(c, 0, 0, w, h, h / 2, fill=mix(bg, color, 0.22), outline="")
    c.create_text(w / 2, h / 2 + 1, text=text, fill=color, font=fnt)
    return c


def drag_bind(win, widget):
    """让无边框窗口可以拖动。"""
    st = {}

    def down(e):
        st["x"], st["y"] = e.x_root - win.winfo_x(), e.y_root - win.winfo_y()

    def move(e):
        if "x" in st:
            win.geometry(f"+{e.x_root - st['x']}+{e.y_root - st['y']}")

    widget.bind("<Button-1>", down, add="+")
    widget.bind("<B1-Motion>", move, add="+")


def fade(win, start, end, ms=220, step=None, done=None):
    """透明度动画。"""
    steps = max(1, ms // 16)
    step = step if step is not None else 0
    v = start + (end - start) * (step / steps)
    try:
        win.attributes("-alpha", max(0.0, min(1.0, v)))
    except tk.TclError:
        return
    if step < steps:
        win.after(16, lambda: fade(win, start, end, ms, step + 1, done))
    elif done:
        done()
