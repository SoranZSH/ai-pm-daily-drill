# -*- coding: utf-8 -*-
"""
后台提醒守护进程。

开机自启 → 使用电脑约 90 秒后弹出「今天要练习英语面试技巧吗？」
忽略（关闭 / 稍后 / 自动收起）→ 再累计 1.5 小时「活跃使用时间」后重新提醒。
点【现在练习】→ 打开当日习题；练完（点 完成/没记住）当天不再提示，没练完就关掉按「稍后」处理。
点【随机换题】→ 换一道（每天一次），之后按钮变成【算了，今天休息】。

勿扰：有全屏程序（在线笔试、全屏视频、演示）或麦克风/摄像头正在使用（视频面试、会议）时
      不弹出；已经弹出的提醒会悄悄收起。恢复正常 2 分钟后再提醒。检测逻辑见 ui/quiet.py。

调试：  python app.pyw --test           立刻弹一次
        python app.pyw --reset          清除今天的跳过/换题标记（不动学习记录）
        python app.pyw --quiet-check    10 秒后检测一次勿扰状态（期间切到要测试的全屏程序）
"""

import ctypes
import datetime as dt
import faulthandler
import os
import subprocess
import sys
import threading
import time
import traceback
import tkinter as tk

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
LOG = os.path.join(ROOT, "data", "nudge.log")
CRASH_LOG = os.path.join(ROOT, "data", "crash.log")

TICK = 15            # 秒，主循环节奏
IDLE_LIMIT = 120     # 秒，超过这么久没动键鼠就不算在使用电脑
FIRST_DELAY = 90     # 秒，开机后累计活跃多久首次提醒
SNOOZE_NEED = 90 * 60  # 秒，被忽略后需再累计 1.5 小时
QUIET_GRACE = 120      # 秒，勿扰状态解除后再等这么久才弹出，避免刚结束就打扰
HANG_LIMIT = 300       # 秒，主循环这么久没跳动就判定卡死，自动重启
WATCH_EVERY = 30       # 秒，看门狗检查间隔
ALIVE_EVERY = 3 * 3600  # 秒，每隔这么久在日志里记一行 alive，方便事后确认程序一直在跑


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
    except Exception:
        pass


# ── Windows 交互 ──────────────────────────────────────────────────────────
class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def idle_from(now_ms, last_ms):
    """两个 32 位毫秒计数之差（处理约 49.7 天一次的回绕）。"""
    return ((now_ms - last_ms) & 0xFFFFFFFF) / 1000.0


def idle_seconds():
    """距离上次键盘/鼠标输入过了多少秒。

    GetLastInputInfo 给的是 32 位毫秒计数，要和同样是 32 位的 GetTickCount 比。
    旧版用 GetTickCount64 却没声明返回类型，被截成有符号 32 位，开机约 25 天后算错。
    """
    try:
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(lii)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
        k32 = ctypes.windll.kernel32
        k32.GetTickCount.restype = ctypes.c_uint32
        return idle_from(k32.GetTickCount(), lii.dwTime)
    except Exception:
        return 0.0


def single_instance(wait=0):
    """同一时间只允许一个守护进程。wait>0 时最多等这么多秒（用于卡死后自动重启的接班）。"""
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateMutexW.restype = ctypes.c_void_p
        h = k32.CreateMutexW(None, False, "InterviewEN.Nudge.Daemon")
        if k32.GetLastError() != 183:
            return True, h
        if wait > 0 and k32.WaitForSingleObject(ctypes.c_void_p(h), int(wait * 1000)) in (0, 0x80):
            return True, h          # 旧进程退出，拿到了锁
        return False, h
    except Exception:
        return True, None


def hung(now, last_check, last_beat, limit=HANG_LIMIT, every=WATCH_EVERY):
    """看门狗判定：主循环超过 limit 秒没跳动算卡死。
    返回 (是否卡死, 新的 last_beat)。看门狗自己两次检查间隔过长说明电脑刚从睡眠恢复，
    这时把心跳视为刚刚发生，避免一唤醒就误判。"""
    if now - last_check > every * 3:
        return False, now
    return now - last_beat > limit, last_beat


def dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# ── 守护 ──────────────────────────────────────────────────────────────────
class Daemon:
    def __init__(self, root, test=False):
        from ui import state
        self.state = state
        self.root = root
        self.day = state.today()
        self.popup = None
        self.practice = None
        self.since_save = 0
        self.busy = None         # 当前的勿扰原因（None 表示可以打扰）
        self.free_since = None   # 勿扰解除的时间（单调时钟秒）

        h = state.load()
        self.active = 0 if test else h["nudge"].get("snooze_active", 0)
        self.prompted = bool(h["nudge"].get("last_prompt", "").endswith(self.day)) \
            and not test
        if test:
            self.root.after(400, self.show)
        log(f"daemon start (prompted_today={self.prompted}, active={int(self.active)}s, pid={os.getpid()})")
        self.beat = time.monotonic()
        self.last_alive = self.beat
        if not test:
            threading.Thread(target=self._watchdog, daemon=True).start()
        self.tick()

    # ── 看门狗：主循环卡死时留下现场并自动重启 ────────────────────────────
    def _watchdog(self):
        last_check = time.monotonic()
        while True:
            time.sleep(WATCH_EVERY)
            now = time.monotonic()
            stuck, self.beat = hung(now, last_check, self.beat, HANG_LIMIT, WATCH_EVERY)
            last_check = now
            if not stuck:
                continue
            log(f"main loop stuck for {int(now - self.beat)}s, restarting (details in crash.log)")
            try:
                with open(CRASH_LOG, "a", encoding="utf-8") as fh:
                    fh.write(f"\n==== {dt.datetime.now():%Y-%m-%d %H:%M:%S} 主循环卡死，各线程现场：\n")
                    faulthandler.dump_traceback(file=fh, all_threads=True)
            except Exception:
                pass
            try:
                exe = sys.executable.replace("python.exe", "pythonw.exe")
                subprocess.Popen([exe, os.path.abspath(__file__), "--takeover"], cwd=ROOT,
                                 creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
            except Exception:
                log("restart failed\n" + traceback.format_exc())
            os._exit(3)

    # ── 主循环 ───────────────────────────────────────────────────────────
    def tick(self):
        self.beat = time.monotonic()
        if self.beat - self.last_alive >= ALIVE_EVERY:
            self.last_alive = self.beat
            log(f"alive (active={int(self.active)}s)")
        try:
            self._tick()
        except Exception:
            log("tick error\n" + traceback.format_exc())
        self.root.after(TICK * 1000, self.tick)

    def _tick(self):
        st = self.state
        h = st.load()

        # 跨天重置
        if st.today() != self.day:
            self.day = st.today()
            self.active = 0
            self.prompted = False
            h["nudge"]["snooze_active"] = 0
            st.save(h)
            log("new day")

        if st.done_today(h) or st.skipped_today(h):
            return

        # 提醒已经弹出，但用户进入了全屏/开始通话：悄悄收起，之后再弹
        if self.popup and not self.practice:
            reason = self.quiet()
            if reason:
                try:
                    self.popup.withdraw_quiet()
                except Exception:
                    pass
                self.popup = None
                log(f"nudge withdrawn: {reason}")
                return
        if self.popup or self.practice:
            return

        if idle_seconds() < IDLE_LIMIT:
            self.active += TICK
            self.since_save += TICK
            if self.since_save >= 60:
                self.since_save = 0
                h["nudge"]["snooze_active"] = self.active
                st.save(h)

        need = SNOOZE_NEED if self.prompted else FIRST_DELAY
        if self.active >= need and self.quiet() is None:
            self.show()

    def quiet(self):
        """返回当前的勿扰原因；没有则返回 None。勿扰解除后还要再等 QUIET_GRACE 秒。"""
        try:
            from ui import quiet
            reason = quiet.busy_reason()
        except Exception:
            log("quiet check error\n" + traceback.format_exc())
            reason = None
        now = time.monotonic()
        if reason:
            if reason != self.busy:
                log(f"do not disturb: {reason}")
            self.busy, self.free_since = reason, None
            return reason
        if self.busy is not None:                # 刚刚解除
            log(f"do not disturb ended ({self.busy})")
            self.busy, self.free_since = None, now
        if self.free_since is not None and now - self.free_since < QUIET_GRACE:
            return "勿扰刚解除，稍等片刻"
        self.free_since = None
        return None

    # ── 弹窗 ─────────────────────────────────────────────────────────────
    def show(self):
        if self.popup or self.practice:
            return
        try:
            from ui.nudge import Nudge
            self.popup = Nudge(self.root, self.on_practice, self.on_snooze, self.on_skip)
            log("nudge shown")
        except Exception:
            log("nudge failed\n" + traceback.format_exc())
            self.popup = None

    def on_snooze(self):
        self.popup = None
        self.prompted = True
        self.active = 0
        h = self.state.load()
        self.state.snooze(h)
        log("snoozed → 1.5h active time")

    def on_skip(self, after_swap=False, qid=None):
        self.popup = None
        h = self.state.load()
        self.state.skip_today(h, after_swap=after_swap, qid=qid)
        log("rest today" + (" (after swap)" if after_swap else ""))

    def on_practice(self):
        self.popup = None
        try:
            from ui.practice import Practice
            self.practice = Practice(self.root, on_close=self.on_practice_closed)
            log("practice opened")
        except Exception:
            log("practice failed\n" + traceback.format_exc())
            self.practice = None

    def on_practice_closed(self):
        self.practice = None
        h = self.state.load()
        if self.state.done_today(h):
            log("practice finished")
            return
        # 打开了但没练完就关掉：不算学习，按「稍后再说」处理，1.5 小时后再敲门
        self.prompted = True
        self.active = 0
        self.state.snooze(h)
        log("practice closed unfinished → snooze")


def main():
    args = sys.argv[1:]
    if "--reset" in args:
        sys.path.insert(0, ROOT)
        from ui import state
        h = state.load()
        t = state.today()
        h["nudge"]["last_prompt"] = ""
        h["nudge"]["swapped"] = ""
        h["nudge"]["snooze_active"] = 0
        state.save(h)
        print("已清除今天的提醒/换题状态（学习记录不受影响）")
        return

    if "--quiet-check" in args:
        from ui import quiet
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        print("10 秒后检测，请现在切换到要测试的程序（全屏笔试页面、视频会议等）…")
        time.sleep(10)
        print("通知状态：    ", quiet.notification_state() or "可以打扰")
        print("前台全屏：    ", quiet.foreground_fullscreen() or "否")
        print("麦克风/摄像头：", quiet.capture_in_use() or "未在使用")
        r = quiet.busy_reason()
        print("结论：", f"推迟提醒（{r}）" if r else "可以弹出提醒")
        return

    if "--test" in args:
        # 预览模式：不抢单实例锁、不跑守护循环，弹一次看效果，关掉即退出。
        dpi_aware()
        root = tk.Tk()
        root.withdraw()
        preview(root)
        root.mainloop()
        return

    takeover = "--takeover" in args
    ok, _mutex = single_instance(wait=60 if takeover else 0)
    if not ok:
        if takeover:
            log("takeover failed: old instance still holds the lock")
        return          # 已有实例在运行（定时任务每 30 分钟拉起一次，属于正常情况，不记日志）
    try:
        _crash_fh = open(CRASH_LOG, "a", encoding="utf-8")
        faulthandler.enable(file=_crash_fh, all_threads=True)   # Python 之外的崩溃也留下现场
    except Exception:
        pass

    dpi_aware()
    root = tk.Tk()
    root.withdraw()
    Daemon(root)
    root.mainloop()


def preview(root):
    """python app.pyw --test 走这里：立刻弹窗，走完整流程后退出。"""
    from ui.nudge import Nudge
    from ui.practice import Practice
    state = {"practice": None}

    def quit_soon():
        root.after(400, root.destroy)

    def on_practice():
        state["practice"] = Practice(root, on_close=quit_soon)

    log("preview mode")
    Nudge(root, on_practice, quit_soon, lambda *a, **k: quit_soon())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("fatal\n" + traceback.format_exc())
