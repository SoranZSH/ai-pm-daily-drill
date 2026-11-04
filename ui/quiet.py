# -*- coding: utf-8 -*-
"""勿扰检测：判断现在是不是不该弹出学习提醒。

返回 None 表示可以打扰；返回一段中文原因表示应当推迟。三道检查，任一命中即推迟：

1. Windows 通知状态（SHQueryUserNotificationState）——系统自己判断「全屏程序 / 全屏游戏或视频 /
   演示模式 / 专注时段」时就不弹通知，这里沿用同一个判断。
2. 前台窗口是否铺满整个显示器——补上第 1 条漏掉的情况，比如浏览器按 F11 进入的在线笔试页面。
3. 麦克风或摄像头正在被使用——视频面试、会议、语音通话通常不是全屏，但一定开着麦克风。

非 Windows 环境或任何检查出错时，该项视为「没有命中」，不影响提醒的正常工作。
"""

import ctypes
import os
import sys

# SHQueryUserNotificationState 的返回值
_QUNS = {
    1: "锁屏或屏幕保护",          # QUNS_NOT_PRESENT
    2: "有全屏程序正在运行",       # QUNS_BUSY
    3: "正在全屏播放视频或游戏",   # QUNS_RUNNING_D3D_FULL_SCREEN
    4: "处于演示模式",            # QUNS_PRESENTATION_MODE
    6: "处于系统勿扰时段",         # QUNS_QUIET_TIME
    7: "有全屏应用正在运行",       # QUNS_APP
}

# 这些窗口铺满屏幕也不算全屏程序（桌面、任务栏）
_SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}

_CAPS = {"microphone": "麦克风", "webcam": "摄像头"}
_CAP_ROOT = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"


def _is_windows():
    return os.name == "nt" and hasattr(ctypes, "windll")


def notification_state():
    """第 1 道：Windows 通知状态。"""
    if not _is_windows():
        return None
    try:
        state = ctypes.c_int(0)
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return None
        return _QUNS.get(state.value)
    except Exception:
        return None


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong)]


def foreground_fullscreen(own_pid=None):
    """第 2 道：前台窗口是否铺满它所在的整个显示器（含任务栏区域）。"""
    if not _is_windows():
        return None
    try:
        u = ctypes.windll.user32
        u.GetForegroundWindow.restype = ctypes.c_void_p
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return None
        hwnd = ctypes.c_void_p(hwnd)
        buf = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, buf, 256)
        if buf.value in _SHELL_CLASSES:
            return None
        pid = ctypes.c_ulong(0)
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == (own_pid or os.getpid()):
            return None                          # 自己的窗口
        r = _RECT()
        if not u.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        u.MonitorFromWindow.restype = ctypes.c_void_p
        mon = u.MonitorFromWindow(hwnd, 2)       # MONITOR_DEFAULTTONEAREST
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        if not u.GetMonitorInfoW(ctypes.c_void_p(mon), ctypes.byref(mi)):
            return None
        m = mi.rcMonitor
        if r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom:
            # 不用 GetWindowTextW：它会给目标窗口发消息，目标程序无响应时会一直卡住，
            # 连带整个提醒程序停摆（2026-10-15 疑似发生过）。InternalGetWindowText 直接读缓存，不会卡。
            title = ctypes.create_unicode_buffer(256)
            u.InternalGetWindowText(hwnd, title, 256)
            name = title.value.strip()[:30] or buf.value
            return f"前台窗口全屏（{name}）"
        return None
    except Exception:
        return None


def capture_in_use():
    """第 3 道：麦克风 / 摄像头是否正被某个程序使用（Windows 10 1903 起支持）。

    依据注册表 ConsentStore：某程序的 LastUsedTimeStart > 0 且 LastUsedTimeStop == 0，
    表示它此刻正在使用该设备。
    """
    if not _is_windows():
        return None
    try:
        import winreg
    except ImportError:
        return None

    def in_use(key):
        try:
            start, _ = winreg.QueryValueEx(key, "LastUsedTimeStart")
            stop, _ = winreg.QueryValueEx(key, "LastUsedTimeStop")
            return bool(start) and stop == 0
        except OSError:
            return False

    def subkeys(key):
        i = 0
        while True:
            try:
                yield winreg.EnumKey(key, i)
            except OSError:
                return
            i += 1

    for cap, label in _CAPS.items():
        try:
            root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{_CAP_ROOT}\\{cap}")
        except OSError:
            continue
        with root:
            for name in list(subkeys(root)):
                try:
                    with winreg.OpenKey(root, name) as k:
                        if name == "NonPackaged":           # 普通桌面程序，按 exe 路径分子键
                            for app in list(subkeys(k)):
                                with winreg.OpenKey(k, app) as ak:
                                    if in_use(ak):
                                        exe = app.replace("#", "\\").rsplit("\\", 1)[-1]
                                        return f"{label}正在使用（{exe}）"
                        elif in_use(k):                     # 应用商店应用
                            return f"{label}正在使用（{name.split('_')[0]}）"
                except OSError:
                    continue
    return None


def busy_reason(check_capture=True):
    """依次做三道检查，返回第一个命中的原因；都没命中返回 None。"""
    for check in (notification_state, foreground_fullscreen):
        reason = check()
        if reason:
            return reason
    if check_capture:
        return capture_in_use()
    return None


if __name__ == "__main__":               # 手动自检：python ui/quiet.py
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("通知状态：", notification_state() or "可以打扰")
    print("前台全屏：", foreground_fullscreen() or "否")
    print("麦克风/摄像头：", capture_in_use() or "未在使用")
