# -*- coding: utf-8 -*-
"""Windows 上的整机冒烟测试（手动运行，不属于 unittest 自动发现的范围）。

    python tests/win_smoke.py [输出目录]

做三件事，结果写进 输出目录/smoke.log：
  1. 跑全部单元测试；
  2. 托盘图标：创建 → 模拟一次左键 → 改提示文字 → 移除；
  3. 把每个窗口（四种提醒弹窗、练习窗口的各个阶段、设置面板）真的开出来再关掉，
     检查弹窗不进任务栏、不抢焦点，并把每个窗口自己的画面存成 PNG（只截本程序的窗口）。

学习记录用临时目录，绝不读写真实的 data/；题库用真实题库（只读）。
"""
import ctypes
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import time
import traceback
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "自测输出"))
os.makedirs(OUT, exist_ok=True)
LOG = open(os.path.join(OUT, "smoke.log"), "w", encoding="utf-8")
FAILS = []


def say(*a):
    line = " ".join(str(x) for x in a)
    LOG.write(line + "\n")
    LOG.flush()
    try:
        print(line)
    except Exception:
        pass


def check(name, ok, detail=""):
    say(("  ok   " if ok else "  FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILS.append(name)


# ── 1. 单元测试 ───────────────────────────────────────────────────────────
def run_unit_tests():
    say("== 单元测试")
    buf = io.StringIO()
    suite = unittest.defaultTestLoader.discover(os.path.join(ROOT, "tests"))
    res = unittest.TextTestRunner(stream=buf, verbosity=1).run(suite)
    say(buf.getvalue().strip()[-3000:])
    check("单元测试全部通过", res.wasSuccessful(),
          f"ran={res.testsRun} fail={len(res.failures)} err={len(res.errors)} skip={len(res.skipped)}")


# ── 截图：只截本程序自己的窗口（PrintWindow），不碰屏幕上别的内容 ─────────────
def write_png(path, w, h, bgra):
    rgb = bytearray(w * h * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += rgb[y * w * 3:(y + 1) * w * 3]

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


def grab(win, name):
    from ctypes import wintypes as w
    from ui.practice import hwnd_of
    try:
        win.update()
        u = ctypes.WinDLL("user32")
        g = ctypes.WinDLL("gdi32")
        hwnd = w.HWND(hwnd_of(win))
        r = w.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(r))
        W, H = r.right - r.left, r.bottom - r.top
        u.GetDC.restype, u.GetDC.argtypes = w.HDC, [w.HWND]
        u.ReleaseDC.argtypes = [w.HWND, w.HDC]
        u.PrintWindow.restype, u.PrintWindow.argtypes = w.BOOL, [w.HWND, w.HDC, w.UINT]
        g.CreateCompatibleDC.restype, g.CreateCompatibleDC.argtypes = w.HDC, [w.HDC]
        g.CreateCompatibleBitmap.restype = w.HBITMAP
        g.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]
        g.SelectObject.restype, g.SelectObject.argtypes = w.HGDIOBJ, [w.HDC, w.HGDIOBJ]
        g.DeleteObject.argtypes = [w.HGDIOBJ]
        g.DeleteDC.argtypes = [w.HDC]
        g.GetDIBits.restype = ctypes.c_int
        g.GetDIBits.argtypes = [w.HDC, w.HBITMAP, w.UINT, w.UINT, ctypes.c_void_p,
                                ctypes.c_void_p, w.UINT]

        class BIH(ctypes.Structure):
            _fields_ = [("biSize", w.DWORD), ("biWidth", w.LONG), ("biHeight", w.LONG),
                        ("biPlanes", w.WORD), ("biBitCount", w.WORD), ("biCompression", w.DWORD),
                        ("biSizeImage", w.DWORD), ("biXPelsPerMeter", w.LONG),
                        ("biYPelsPerMeter", w.LONG), ("biClrUsed", w.DWORD),
                        ("biClrImportant", w.DWORD)]

        screen = u.GetDC(None)
        mem = g.CreateCompatibleDC(screen)
        bmp = g.CreateCompatibleBitmap(screen, W, H)
        old = g.SelectObject(mem, bmp)
        ok = u.PrintWindow(hwnd, mem, 2)             # PW_RENDERFULLCONTENT
        g.SelectObject(mem, old)
        bih = BIH()
        bih.biSize, bih.biWidth, bih.biHeight = ctypes.sizeof(BIH), W, -H   # 负数 = 自上而下
        bih.biPlanes, bih.biBitCount = 1, 32
        buf = ctypes.create_string_buffer(W * H * 4)
        got = g.GetDIBits(mem, bmp, 0, H, buf, ctypes.byref(bih), 0)
        g.DeleteObject(bmp)
        g.DeleteDC(mem)
        u.ReleaseDC(None, screen)
        if not ok or got != H:
            say(f"  (截图 {name} 失败: PrintWindow={ok} lines={got})")
            return
        write_png(os.path.join(OUT, name + ".png"), W, H, bytearray(buf.raw))
        say(f"  截图 {name}.png  {W}x{H}")
    except Exception:
        say(f"  (截图 {name} 出错)\n" + traceback.format_exc())


# ── 2. 托盘 ───────────────────────────────────────────────────────────────
def run_tray():
    say("== 托盘图标")
    from ui import tray as T
    got = []
    t = T.Tray(got.append, lambda: [("practice", "现在学一题"), None, ("quit", "退出")],
               tip="每日一题 · 自测", icon=os.path.join(ROOT, "ui", "tray.ico"))
    ok = t.start()
    check("托盘图标创建成功", ok, t.error or "")
    if not t.hwnd:
        return
    say("  NOTIFYICONDATAW 大小:", ctypes.sizeof(t.NOTIFYICONDATAW), " 自带图标:", t._own_icon)
    check("加载了自带的图标文件", t._own_icon)
    t.u.PostMessageW(t.hwnd, T.WM_TRAY, 0, T.WM_LBUTTONUP)      # 模拟左键单击
    time.sleep(0.5)
    check("左键单击发出默认命令", got == ["practice"], str(got))
    t.set_tip("每日一题 · 今天已学 1 题")
    time.sleep(0.5)
    t.stop()
    check("托盘线程正常结束", not t._thread.is_alive() and t.hwnd is None)


# ── 3. 窗口 ───────────────────────────────────────────────────────────────
def run_windows():
    say("== 窗口")
    import tkinter as tk
    import daily
    tmp = tempfile.mkdtemp(prefix="meiri_smoke_")
    daily.DATA_DIR = os.path.join(tmp, "data")            # 只用临时目录，不碰真实学习记录
    daily.HISTORY = os.path.join(daily.DATA_DIR, "history.json")
    assert not daily.HISTORY.startswith(os.path.join(ROOT, "data"))
    from ui import state, theme
    from ui.nudge import Nudge
    from ui.practice import Practice, hwnd_of, no_more_notice
    from ui.settings_panel import SettingsPanel

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    root.withdraw()
    say(f"  Python {sys.version.split()[0]}  Tk {root.tk.call('info', 'patchlevel')}  "
        f"屏幕 {root.winfo_screenwidth()}x{root.winfo_screenheight()}  "
        f"缩放 {theme.init_scale(root):.2f}  题库 {len(state.bank())} 题")

    u = ctypes.windll.user32
    u.GetForegroundWindow.restype = ctypes.c_void_p
    S, steps = {}, []
    noop = lambda *a, **k: None       # noqa: E731

    def exstyle(win):
        from ui.practice import _exstyle_api, GWL_EXSTYLE
        _, get_l, _ = _exstyle_api()
        return get_l(hwnd_of(win), GWL_EXSTYLE)

    def step(delay, fn):
        steps.append((delay, fn))

    def run(i=0):
        if i >= len(steps):
            root.after(300, root.destroy)
            return
        delay, fn = steps[i]

        def go():
            try:
                fn()
            except Exception:
                FAILS.append(f"step {i}")
                say(f"  FAIL 第 {i} 步出错\n" + traceback.format_exc())
            run(i + 1)
        root.after(delay, go)

    # 提醒弹窗：不进任务栏、不抢焦点
    def nudge_first():
        S["fg"] = u.GetForegroundWindow()
        S["n"] = Nudge(root, noop, noop, noop)

    def nudge_checks():
        st = exstyle(S["n"].win)
        check("弹窗不在任务栏（TOOLWINDOW，非 APPWINDOW）", bool(st & 0x80) and not st & 0x40000, hex(st))
        check("弹窗带不抢焦点样式（NOACTIVATE）", bool(st & 0x08000000), hex(st))
        check("弹窗出现后前台窗口没变", u.GetForegroundWindow() == S["fg"],
              f"{S['fg']} -> {u.GetForegroundWindow()}")
        grab(S["n"].win, "01_提醒_首次")

    step(300, nudge_first)
    step(1200, nudge_checks)
    step(100, lambda: S["n"].swap())
    step(500, lambda: grab(S["n"].win, "02_提醒_换题后"))
    step(100, lambda: S["n"].withdraw_quiet())

    # 练习窗口：普通 → 揭晓 → 完成 → 庆祝页「再来一道」→ 连着学 → 小结
    step(200, lambda: S.update(p=Practice(root, on_close=noop)))
    step(900, lambda: grab(S["p"].win, "03_练习_先自己说"))
    step(100, lambda: S["p"].reveal())
    step(1000, lambda: grab(S["p"].win, "04_练习_解析"))
    step(100, lambda: S["p"].finish(4))
    step(900, lambda: grab(S["p"].win, "05_完成_可再来一道"))
    step(100, lambda: S["p"]._continue())
    step(700, lambda: grab(S["p"].win, "06_沉浸_下一题"))
    step(100, lambda: S["p"].reveal())
    step(1000, lambda: grab(S["p"].win, "07_沉浸_解析与底栏"))
    step(100, lambda: S["p"].finish(1))
    step(350, lambda: grab(S["p"].win, "08_沉浸_题间过渡"))
    step(1200, lambda: check("连着学自动进入第三题",
                             len(S["p"].graded) == 2 and not S["p"].revealed))
    step(100, lambda: S["p"].close())
    step(600, lambda: grab(S["p"].win, "09_沉浸_小结"))
    step(100, lambda: S["p"]._end())

    def after_session():
        h = state.load()
        check("学累了退出后记为今天收工", state.stopped_today(h))
        check("今天记了 2 题", state.count_today(h) == 2, str(state.today_ids(h)))
        ev = [e for e in h["study"]["events"] if e["type"] == "done"]
        check("行为日志带用时和入口", all("secs" in e and "mode" in e for e in ev), str(ev))
        h["nudge"]["last_prompt"] = ""
        state.save(h)

    step(500, after_session)
    step(100, lambda: S.update(n=Nudge(root, noop, noop, noop, kind="next", on_stop=noop)))
    step(900, lambda: grab(S["n"].win, "10_提醒_再来一道"))
    step(100, lambda: S["n"].withdraw_quiet())
    step(100, lambda: S.update(n=Nudge(root, noop, noop, noop, kind="resume", on_stop=noop,
                                       item=state.bank()[3])))
    step(900, lambda: grab(S["n"].win, "11_提醒_题还开着"))
    step(100, lambda: S["n"].withdraw_quiet())
    step(100, lambda: S.update(n=no_more_notice(root, "blocked")))
    step(900, lambda: grab(S["n"].win, "12_告知_贪多嚼不烂"))
    step(100, lambda: S["n"].withdraw_quiet())

    # 设置面板
    step(100, lambda: S.update(s=SettingsPanel(root)))
    step(900, lambda: grab(S["s"].win, "13_设置"))
    step(100, lambda: S["s"].segs["mode"].select("multi"))
    step(100, lambda: S["s"].segs["new_per_day"].select(5))
    step(400, lambda: grab(S["s"].win, "14_设置_改动后"))
    step(100, lambda: S["s"].save())
    step(500, lambda: check("设置保存生效", (daily.settings()["mode"], daily.settings()["new_per_day"])
                            == ("multi", 5), json.dumps(daily.settings(), ensure_ascii=False)))
    run()
    root.mainloop()
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    say(f"每日一题 · 冒烟测试  {time.strftime('%Y-%m-%d %H:%M:%S')}  {sys.platform}")
    for part in (run_unit_tests, run_tray, run_windows):
        try:
            part()
        except Exception:
            FAILS.append(part.__name__)
            say(f"  FAIL {part.__name__} 出错\n" + traceback.format_exc())
    say("")
    say("SMOKE DONE:", "全部通过" if not FAILS else f"{len(FAILS)} 项失败 → {FAILS}")
    LOG.close()
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
