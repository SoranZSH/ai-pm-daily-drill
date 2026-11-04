# -*- coding: utf-8 -*-
"""直接打开今天的练习窗口（不经过提醒）。"""

import ctypes
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

from ui.practice import open_practice  # noqa: E402

if __name__ == "__main__":
    open_practice()
