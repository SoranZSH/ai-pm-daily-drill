# -*- coding: utf-8 -*-
"""任务栏右下角的托盘图标（常驻入口）。纯 ctypes 实现，不依赖第三方库。

左键单击 → 发出默认命令（现在学一题）；右键 → 弹出菜单。
托盘自己跑在一个后台线程里（它需要自己的窗口消息循环），绝不直接碰 Tk：
用户点了什么，只通过 on_command(命令名) 通知出去——调用方应当把它放进线程安全的队列，
由主线程取出来处理。

非 Windows 环境、或创建失败时 start() 返回 False，提醒程序照常工作，只是没有托盘图标。
"""

import ctypes
import os
import threading

WM_DESTROY, WM_CLOSE, WM_NULL, WM_COMMAND = 0x0002, 0x0010, 0x0000, 0x0111
WM_LBUTTONUP, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0202, 0x0205, 0x007B
WM_APP = 0x8000
WM_TRAY = WM_APP + 1          # 托盘图标上的鼠标事件
WM_REFRESH = WM_APP + 2       # 提示文字变了，刷新一下

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
MF_STRING, MF_GRAYED, MF_CHECKED, MF_SEPARATOR = 0x0, 0x1, 0x8, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x0002, 0x0100, 0x0080
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x0010
SM_CXSMICON, SM_CYSMICON = 49, 50
IDI_APPLICATION = 32512


def available():
    return os.name == "nt" and hasattr(ctypes, "WinDLL")


class Tray:
    def __init__(self, on_command, menu, tip="每日一题", icon=None, default="practice"):
        """on_command(name)  用户选了某个命令（在托盘线程里调用，必须线程安全）
        menu()            返回菜单项列表（在托盘线程里调用，只应读取现成的数据）：
                          [(命令名, 文字, {"grayed": bool, "checked": bool}) 或 None 表示分隔线]
        """
        self.on_command = on_command
        self.menu = menu
        self.tip = tip
        self.icon = icon
        self.default = default
        self.hwnd = None
        self.ok = False               # 图标是否已成功加进托盘
        self.error = None
        self._ready = threading.Event()
        self._thread = None

    # ── 对外 ─────────────────────────────────────────────────────────────
    def start(self, wait=5.0):
        if not available():
            self.error = "not windows"
            return False
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()
        self._ready.wait(wait)
        return self.ok

    def stop(self):
        if self.hwnd:
            try:
                self.u.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(2.0)

    def set_tip(self, text):
        """更新鼠标悬停时的提示文字（任何线程都可以调用）。"""
        text = text[:120]
        if text == self.tip:
            return
        self.tip = text
        if self.hwnd:
            try:
                self.u.PostMessageW(self.hwnd, WM_REFRESH, 0, 0)
            except Exception:
                pass

    # ── 托盘线程 ─────────────────────────────────────────────────────────
    def _bind(self):
        from ctypes import wintypes as w
        self.w = w
        u = self.u = ctypes.WinDLL("user32", use_last_error=True)
        k = self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        sh = self.sh = ctypes.WinDLL("shell32", use_last_error=True)

        LRESULT = ctypes.c_ssize_t
        self.WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", w.UINT), ("lpfnWndProc", self.WNDPROC),
                        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                        ("hInstance", w.HINSTANCE), ("hIcon", w.HANDLE), ("hCursor", w.HANDLE),
                        ("hbrBackground", w.HANDLE), ("lpszMenuName", w.LPCWSTR),
                        ("lpszClassName", w.LPCWSTR)]

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", w.DWORD), ("Data2", w.WORD), ("Data3", w.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [("cbSize", w.DWORD), ("hWnd", w.HWND), ("uID", w.UINT),
                        ("uFlags", w.UINT), ("uCallbackMessage", w.UINT), ("hIcon", w.HANDLE),
                        ("szTip", w.WCHAR * 128), ("dwState", w.DWORD),
                        ("dwStateMask", w.DWORD), ("szInfo", w.WCHAR * 256),
                        ("uVersion", w.UINT), ("szInfoTitle", w.WCHAR * 64),
                        ("dwInfoFlags", w.DWORD), ("guidItem", GUID), ("hBalloonIcon", w.HANDLE)]

        self.WNDCLASSW, self.NOTIFYICONDATAW = WNDCLASSW, NOTIFYICONDATAW

        def sig(fn, res, *args):
            fn.restype, fn.argtypes = res, list(args)

        sig(k.GetModuleHandleW, w.HMODULE, w.LPCWSTR)
        sig(u.DefWindowProcW, LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
        sig(u.RegisterClassW, w.ATOM, ctypes.POINTER(WNDCLASSW))
        sig(u.UnregisterClassW, w.BOOL, w.LPCWSTR, w.HINSTANCE)
        sig(u.CreateWindowExW, w.HWND, w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID)
        sig(u.DestroyWindow, w.BOOL, w.HWND)
        sig(u.GetMessageW, ctypes.c_int, ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT)
        sig(u.TranslateMessage, w.BOOL, ctypes.POINTER(w.MSG))
        sig(u.DispatchMessageW, LRESULT, ctypes.POINTER(w.MSG))
        sig(u.PostMessageW, w.BOOL, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
        sig(u.PostQuitMessage, None, ctypes.c_int)
        sig(u.RegisterWindowMessageW, w.UINT, w.LPCWSTR)
        sig(u.LoadImageW, w.HANDLE, w.HINSTANCE, w.LPCWSTR, w.UINT,
            ctypes.c_int, ctypes.c_int, w.UINT)
        sig(u.LoadIconW, w.HANDLE, w.HINSTANCE, ctypes.c_void_p)
        sig(u.DestroyIcon, w.BOOL, w.HANDLE)
        sig(u.GetSystemMetrics, ctypes.c_int, ctypes.c_int)
        sig(u.CreatePopupMenu, w.HMENU)
        sig(u.AppendMenuW, w.BOOL, w.HMENU, w.UINT, ctypes.c_size_t, w.LPCWSTR)
        sig(u.SetMenuDefaultItem, w.BOOL, w.HMENU, w.UINT, w.UINT)
        sig(u.TrackPopupMenu, ctypes.c_int, w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, w.HWND, w.LPVOID)
        sig(u.DestroyMenu, w.BOOL, w.HMENU)
        sig(u.GetCursorPos, w.BOOL, ctypes.POINTER(w.POINT))
        sig(u.SetForegroundWindow, w.BOOL, w.HWND)
        sig(sh.Shell_NotifyIconW, w.BOOL, w.DWORD, ctypes.POINTER(NOTIFYICONDATAW))

    def _nid(self, flags):
        nid = self.NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = flags
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self.hicon
        nid.szTip = self.tip[:127]
        return nid

    def _add(self):
        self.ok = bool(self.sh.Shell_NotifyIconW(
            NIM_ADD, ctypes.byref(self._nid(NIF_MESSAGE | NIF_ICON | NIF_TIP))))
        if not self.ok:
            self.error = f"Shell_NotifyIcon failed ({ctypes.get_last_error()})"
        return self.ok

    def _load_icon(self):
        u = self.u
        self._own_icon = False
        if self.icon and os.path.exists(self.icon):
            cx = u.GetSystemMetrics(SM_CXSMICON) or 16
            cy = u.GetSystemMetrics(SM_CYSMICON) or 16
            h = u.LoadImageW(None, self.icon, IMAGE_ICON, cx, cy, LR_LOADFROMFILE)
            if h:
                self._own_icon = True
                return h
        return u.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))

    def _show_menu(self):
        u = self.u
        try:
            entries = list(self.menu())
        except Exception:
            entries = []
        if not entries:
            return
        hmenu = u.CreatePopupMenu()
        names = {}
        for n, e in enumerate(entries, start=1):
            if e is None:
                u.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
                continue
            name, label, opt = (tuple(e) + ({},))[:3]
            flags = MF_STRING | (MF_GRAYED if opt.get("grayed") else 0) \
                | (MF_CHECKED if opt.get("checked") else 0)
            u.AppendMenuW(hmenu, flags, n, label)
            names[n] = name
            if name == self.default:
                u.SetMenuDefaultItem(hmenu, n, 0)
        pt = self.w.POINT()
        u.GetCursorPos(ctypes.byref(pt))
        u.SetForegroundWindow(self.hwnd)      # 不这样做，点菜单外面菜单不会自己消失
        cmd = u.TrackPopupMenu(hmenu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                               pt.x, pt.y, 0, self.hwnd, None)
        u.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        u.DestroyMenu(hmenu)
        if cmd in names:
            self._emit(names[cmd])

    def _emit(self, name):
        try:
            self.on_command(name)
        except Exception:
            pass

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                ev = lparam & 0xFFFF
                if ev == WM_LBUTTONUP:
                    self._emit(self.default)
                elif ev in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._show_menu()
                return 0
            if msg == WM_REFRESH:
                if self.ok:
                    self.sh.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid(NIF_TIP)))
                return 0
            if msg == self.wm_taskbar_created:        # 资源管理器重启后图标会丢，重新加回去
                self._add()
                return 0
            if msg == WM_CLOSE:
                self.u.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                if self.ok:
                    self.sh.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid(0)))
                    self.ok = False
                self.u.PostQuitMessage(0)
                return 0
        except Exception:
            pass
        return self.u.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self):
        cls = None
        try:
            self._bind()
            u, k = self.u, self.k
            hinst = k.GetModuleHandleW(None)
            self._proc = self.WNDPROC(self._wndproc)       # 必须留住引用，否则回调会被回收
            cls = f"MeiriYitiTray{os.getpid()}"
            wc = self.WNDCLASSW()
            wc.lpfnWndProc = self._proc
            wc.hInstance = hinst
            wc.lpszClassName = cls
            if not u.RegisterClassW(ctypes.byref(wc)):
                raise OSError(f"RegisterClass failed ({ctypes.get_last_error()})")
            self.wm_taskbar_created = u.RegisterWindowMessageW("TaskbarCreated")
            self.hwnd = u.CreateWindowExW(0, cls, "每日一题", 0, 0, 0, 0, 0, None, None, hinst, None)
            if not self.hwnd:
                raise OSError(f"CreateWindow failed ({ctypes.get_last_error()})")
            self.hicon = self._load_icon()
            self._add()
        except Exception as e:                          # 托盘起不来不影响提醒
            self.error = self.error or repr(e)
            self._ready.set()
            return
        self._ready.set()
        msg = self.w.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))
        try:
            if self._own_icon:
                u.DestroyIcon(self.hicon)
            u.UnregisterClassW(cls, hinst)
        except Exception:
            pass
        self.hwnd = None
