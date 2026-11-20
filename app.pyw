# -*- coding: utf-8 -*-
"""
后台提醒守护进程。

开机自启 → 先让你用一会儿电脑（默认 10 分钟），再挑你「离开一会儿又回来」的时候弹出提醒。
点【现在练习】→ 打开练习窗口；练完（点 完成/没记住）才算学过，没练完就关掉按「稍后」处理。
点【稍后再说】→ 再累计一个提醒间隔（默认 1 小时）的活跃使用时间后重新提醒；
弹窗没人理自动收起 → 多半是没看见，过一小会儿（默认 25 分钟）再试。
点【随机换题】→ 换一道（每天一次），之后按钮变成【算了，今天休息】。

一天多题（在设置里打开「多题提醒」）：当天学过之后仍按间隔提醒下一题，
直到每日上限、你点了「今天到此为止」，或者今天没有可学的题。
托盘图标：左键 = 现在学一题；右键菜单 = 沉浸学习 / 暂停提醒 / 设置 / 退出。

练习窗口开着没做完、被晾了 20 分钟 → 再提醒一次；跨天时自动收起。
学习日从凌晨 4 点开始（可在设置里改）：零点后接着学的仍算前一天。

勿扰：有全屏程序（在线笔试、全屏视频、演示）或麦克风/摄像头正在使用（视频面试、会议）时
      不弹出；已经弹出的提醒会悄悄收起。恢复正常 2 分钟后再提醒。检测逻辑见 ui/quiet.py。

调试：  python app.pyw --test           立刻弹一次
        python app.pyw --reset          清除今天的跳过/换题/收工标记和计时（不动学习记录）
        python app.pyw --quiet-check    10 秒后检测一次勿扰状态（期间切到要测试的全屏程序）
        python app.pyw --force          今天点过托盘「退出」后，手动重新启动
"""

import ctypes
import datetime as dt
import faulthandler
import os
import queue
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
AWAY_SECS = 120      # 秒，这么久没动键鼠算「离开了一会儿」
RETURN_WINDOW = 45   # 秒，回到电脑后的这段时间算「刚回来」，是敲门的好时机
PATIENCE = 30 * 60   # 秒，到了该提醒的时候一直等不到「刚回来」，最多再等这么久活跃时间
RESUME_NEED = 20 * 60  # 秒，练习窗口开着没做完、被晾了这么久活跃时间就再提醒
QUIET_GRACE = 120      # 秒，勿扰状态解除后再等这么久才弹出，避免刚结束就打扰
PAUSE_SECS = 2 * 3600  # 秒，托盘菜单「暂停提醒」的时长
PUMP_MS = 250          # 毫秒，多久取一次托盘发来的命令
HANG_LIMIT = 300       # 秒，主循环这么久没跳动就判定卡死，自动重启
WATCH_EVERY = 30       # 秒，看门狗检查间隔
ALIVE_EVERY = 3 * 3600  # 秒，每隔这么久在日志里记一行 alive，方便事后确认程序一直在跑
# 提醒间隔、首次等待、弹窗停留等可调的数值在设置面板里（data/settings.json，默认值见 daily.py）


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
    def __init__(self, root, test=False, tray=False):
        from ui import state
        self.state = state
        self.root = root
        self.day = state.today()
        self.popup = None
        self.popup_kind = "first"
        self.practice = None
        self.panel = None
        self.since_save = 0
        self.busy = None         # 当前的勿扰原因（None 表示可以打扰）
        self.free_since = None   # 勿扰解除的时间（单调时钟秒）
        self.was_away = True     # 上一次看时用户不在电脑前（启动时按「刚坐下」算）
        self.returned_at = None  # 最近一次「回到电脑」的时间
        self.ready = False       # 已经等到合适的时机，只差勿扰放行
        self.overdue = 0         # 该提醒了却没等到好时机，已经多等的活跃秒数
        self.away_practice = 0   # 练习窗口被晾在一边的活跃秒数
        self.no_more = None      # 今天已确认没有下一题（原因）；有值就不再反复计算
        self.pause_until = 0.0
        self.cmds = queue.Queue()    # 托盘线程 → 主线程
        self.tray = None
        self.menu_cache = []

        cfg = state.settings()
        rt = state.runtime_load()
        self.pause_until = float(rt.get("pause_until") or 0)
        if rt.get("day") == self.day and isinstance(rt.get("need"), (int, float)):
            self.active, self.need = rt.get("active", 0), rt["need"]
        else:
            # 第一次运行新版 / 新的一天：今天提醒过就接着按间隔算，否则从头来
            h = state.load()
            prompted = h["nudge"].get("last_prompt", "").endswith(self.day)
            self.active = h["nudge"].get("snooze_active", 0) if prompted and not rt else 0
            self.need = (cfg["interval_min"] if prompted else cfg["warmup_min"]) * 60
        if test:
            self.active, self.need = 0, 0
            self.root.after(400, self.show)
        log(f"daemon start (active={int(self.active)}s, need={int(self.need)}s, "
            f"mode={cfg['mode']}, pid={os.getpid()})")
        self.beat = time.monotonic()
        self.last_alive = self.beat
        if not test:
            threading.Thread(target=self._watchdog, daemon=True).start()
        if tray:
            self._start_tray()
        self._pump()
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

    # ── 托盘 ─────────────────────────────────────────────────────────────
    def _start_tray(self):
        try:
            from ui.tray import Tray
            self._status(self.state.load())
            self.tray = Tray(self.cmds.put, lambda: list(self.menu_cache), tip=self.tip,
                             icon=os.path.join(ROOT, "ui", "tray.ico"))
            if self.tray.start():
                log("tray icon ready")
            else:
                log(f"tray icon unavailable: {self.tray.error}")
        except Exception:
            log("tray failed\n" + traceback.format_exc())
            self.tray = None

    def _status(self, h):
        """托盘提示文字和右键菜单的内容。菜单由托盘线程读取，这里整份替换，不就地修改。"""
        try:
            n = self.state.count_today(h)
            streak = self.state.streak(h)
        except Exception:
            n, streak = 0, 0
        paused = self._paused()
        self.tip = f"每日一题 · 今天已学 {n} 题" + ("（提醒已暂停）" if paused else "")
        self.menu_cache = [
            ("practice", "现在学一题"),
            ("session", "沉浸学习（连着学）"),
            None,
            ("pause", "恢复提醒" if paused else "暂停提醒 2 小时"),
            ("settings", "设置…"),
            None,
            ("info", f"今天已学 {n} 题 · 连续 {streak} 天", {"grayed": True}),
            ("quit", "退出（明天再启动）"),
        ]
        if self.tray:
            self.tray.set_tip(self.tip)

    def _pump(self):
        """取出托盘发来的命令，在主线程里执行。"""
        try:
            while True:
                self._command(self.cmds.get_nowait())
        except queue.Empty:
            pass
        except Exception:
            log("tray command error\n" + traceback.format_exc())
        self.root.after(PUMP_MS, self._pump)

    def _command(self, name):
        if name == "practice":
            self.open_practice(source="tray")
        elif name == "session":
            self.open_practice(session=True, source="tray")
        elif name == "pause":
            self.pause_until = 0.0 if self._paused() else time.time() + PAUSE_SECS
            self.state.runtime_update(pause_until=self.pause_until)
            log("reminders paused for 2h" if self.pause_until else "reminders resumed")
            self._status(self.state.load())
        elif name == "settings":
            self.open_settings()
        elif name == "quit":
            self.quit()

    def _paused(self):
        return time.time() < self.pause_until

    def open_settings(self):
        if self.panel:
            self.panel.bring_front()
            return
        try:
            from ui.settings_panel import SettingsPanel
            self.panel = SettingsPanel(self.root, on_close=self._panel_closed,
                                       on_saved=self._settings_saved)
        except Exception:
            log("settings failed\n" + traceback.format_exc())
            self.panel = None

    def _panel_closed(self):
        self.panel = None

    def _settings_saved(self):
        cfg = self.state.settings()
        self.no_more = None                   # 上限可能变了，重新判断今天还有没有题
        log(f"settings saved (mode={cfg['mode']}, new={cfg['new_per_day']}, "
            f"max={cfg['max_per_day']}, interval={cfg['interval_min']}min)")

    def quit(self):
        """托盘「退出」：今天不再启动（守护定时任务拉起时会直接退出），明天照常。"""
        log("quit from tray (until tomorrow)")
        self._save_rt(quit_day=self.day)
        if self.tray:
            self.tray.stop()
        self.root.after(50, self.root.destroy)

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

    def _save_rt(self, **extra):
        self.state.runtime_update(day=self.day, active=self.active, need=self.need, **extra)

    def _wait(self, minutes):
        """重新计时：再累计这么多分钟活跃时间才提醒。"""
        self.active, self.need = 0, minutes * 60
        self.ready, self.overdue, self.since_save = False, 0, 0
        self._save_rt()

    def _tick(self):
        st = self.state
        cfg = st.settings()
        now = time.monotonic()

        # 是不是「离开一会儿刚回来」——打断成本最低的时刻
        idle = idle_seconds()
        using = idle < IDLE_LIMIT
        if idle >= AWAY_SECS:
            self.was_away = True
        elif self.was_away:
            self.was_away, self.returned_at = False, now
        returning = self.returned_at is not None and now - self.returned_at <= RETURN_WINDOW

        # 跨天（学习日，默认凌晨 4 点）
        if st.today() != self.day:
            self.day = st.today()
            self.no_more = None
            self._wait(cfg["warmup_min"])
            log("new day")
            if self.practice and not self.practice.graded and not self.practice.is_foreground():
                log("stale practice window closed at day change")
                self.practice._end()

        h = st.load()
        self._status(h)

        # 提醒已经弹出，但用户进入了全屏/开始通话：悄悄收起，之后再弹
        if self.popup:
            if self.popup_kind != "notice":
                reason = self.quiet()
                if reason:
                    try:
                        self.popup.withdraw_quiet()
                    except Exception:
                        pass
                    self.popup = None
                    log(f"nudge withdrawn: {reason}")
            return

        # 练习窗口开着：看它是不是被晾在一边了
        if self.practice:
            if self.practice.is_foreground():
                self.away_practice = 0
            elif using:
                self.away_practice += TICK
            if self.away_practice >= RESUME_NEED and self.quiet() is None:
                self.show("resume")
            return

        if self._paused():
            return
        if st.skipped_today(h) or st.stopped_today(h):
            return
        done = st.done_today(h)
        if done and (cfg["mode"] != "multi" or self.no_more):
            return

        if using:
            self.active += TICK
            self.since_save += TICK
            if self.since_save >= 60:
                self.since_save = 0
                self._save_rt()
        if self.active < self.need:
            return

        if done:                      # 多题提醒：先确认今天还有可学的题
            try:
                it, why = st.current_question(h, st.bank(), peek=True)
            except SystemExit:
                return
            if it is None:
                self.no_more = why
                log(f"no more questions today: {why}")
                return

        if not self.ready:
            if returning or self.overdue >= PATIENCE:
                self.ready = True
            else:
                if using:
                    self.overdue += TICK
                return
        if self.quiet() is None:
            self.show("next" if done else "first")

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
    def show(self, kind="first"):
        if self.popup or (self.practice and kind != "resume"):
            return
        try:
            from ui.nudge import Nudge
            if kind == "resume":
                self.popup = Nudge(self.root, self.on_resume, self.on_resume_later, self.on_skip,
                                   kind="resume", on_stop=self.on_put_away, item=self.practice.item)
            else:
                self.popup = Nudge(self.root, self.on_practice, self.on_snooze, self.on_skip,
                                   kind=kind, on_stop=self.on_stop)
            self.popup_kind = self.popup.kind      # 没题可练时弹窗会自己变成 notice
            self.ready, self.overdue = False, 0
            log("nudge shown" + ("" if kind == "first" else f" [{self.popup_kind}]"))
        except Exception:
            log("nudge failed\n" + traceback.format_exc())
            self.popup = None

    def on_snooze(self, reason="later"):
        kind, self.popup = self.popup_kind, None
        if kind == "notice":
            return
        cfg = self.state.settings()
        h = self.state.load()
        self.state.snooze(h)
        if reason == "timeout":       # 没人理：多半没看见，过一小会儿再试
            self._wait(cfg["retry_min"])
            log(f"nudge timed out → retry after {cfg['retry_min']} min active")
        else:                         # 点了「稍后」或 ✕：按完整间隔等
            self._wait(cfg["interval_min"])
            log(f"snoozed ({reason}) → {cfg['interval_min']} min active time")

    def on_skip(self, after_swap=False, qid=None):
        self.popup = None
        h = self.state.load()
        self.state.skip_today(h, after_swap=after_swap, qid=qid)
        log("rest today" + (" (after swap)" if after_swap else ""))

    def on_stop(self):
        """「今天到此为止」：今天学过了，不再提醒下一题。"""
        self.popup = None
        h = self.state.load()
        self.state.stop_today(h, why="enough")
        log("stop for today")

    def on_practice(self):
        self.popup = None
        self.open_practice()

    def open_practice(self, session=False, source="nudge"):
        if self.practice:                      # 已经开着：拉到眼前
            self.practice.bring_front()
            self.away_practice = 0
            return
        if self.popup:
            try:
                self.popup.withdraw_quiet()
            except Exception:
                pass
            self.popup = None
        try:
            st = self.state
            it, why = st.current_question(st.load(), st.bank(), peek=True)
            if it is None:                     # 今天没有可练的了：告知一句，不硬塞旧题
                from ui.practice import no_more_notice
                self.no_more = why
                self.popup = no_more_notice(self.root, why, on_close=self._notice_closed)
                self.popup_kind = "notice"
                log(f"nothing to practise: {why}")
                return
            from ui.practice import Practice
            self.practice = Practice(self.root, on_close=self.on_practice_closed, session=session)
            self.away_practice = 0
            log("practice opened" + (" [session]" if session else "")
                + ("" if source == "nudge" else f" via {source}"))
        except (Exception, SystemExit):
            log("practice failed\n" + traceback.format_exc())
            self.practice = None

    def _notice_closed(self):
        self.popup = None

    def on_practice_closed(self):
        p, self.practice = self.practice, None
        if self.popup and self.popup_kind == "resume":
            try:
                self.popup.withdraw_quiet()
            except Exception:
                pass
            self.popup = None
        cfg = self.state.settings()
        n = len(getattr(p, "graded", []) or [])
        if n:
            self.no_more = None
            self._wait(cfg["interval_min"])    # 多题提醒：隔一个间隔再敲门
            log(f"practice finished ({n} done"
                + (", stopped for today" if getattr(p, "stopped", False) else "") + ")")
            return
        # 打开了但没练完就关掉：不算学习，按「稍后再说」处理
        h = self.state.load()
        self.state.snooze(h)
        self._wait(cfg["interval_min"])
        log("practice closed unfinished → snooze")

    # ── 练习窗口被晾在一边时的提醒 ────────────────────────────────────────
    def on_resume(self):
        self.popup = None
        self.away_practice = 0
        if self.practice:
            self.practice.bring_front()
            log("resumed practice from reminder")

    def on_resume_later(self, reason="later"):
        self.popup = None
        self.away_practice = 0          # 过 20 分钟再问
        log(f"resume reminder dismissed ({reason})")

    def on_put_away(self):
        self.popup = None
        if self.practice:
            log("practice window put away from reminder")
            self.practice._end()


def main():
    args = sys.argv[1:]
    if "--reset" in args:
        sys.path.insert(0, ROOT)
        from ui import state
        h = state.load()
        h["nudge"]["last_prompt"] = ""
        h["nudge"]["swapped"] = ""
        state.save(h)
        state.runtime_save({})
        print("已清除今天的提醒/换题/收工状态和计时（学习记录不受影响）")
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
    from ui import state
    if "--force" in args:
        state.runtime_update(quit_day="")
    elif not takeover and state.runtime_load().get("quit_day") == state.today():
        return          # 今天在托盘里点过「退出」：守护定时任务拉起时不再启动，明天照常
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
    Daemon(root, tray=True)
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
    Nudge(root, on_practice, lambda *a, **k: quit_soon(), lambda *a, **k: quit_soon())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("fatal\n" + traceback.format_exc())
