# -*- coding: utf-8 -*-
"""生成 README 用的界面截图（开发用脚本，非运行时依赖）。

打开 GUI 窗口，真实解压一份示例数据，运行中途截取主窗口保存为
docs/screenshot.png。需要开发依赖 pillow。
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from fixtures import make_fixtures  # noqa: E402

DEMO = os.path.join(ROOT, 'docs', 'screenshot-demo')
SHOT = os.path.join(ROOT, 'docs', 'screenshot.png')


def main():
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    import tkinter as tk
    from recursive_extract_gui import App

    make_fixtures(DEMO)

    root = tk.Tk()
    root.geometry('800x680+80+60')
    app = App(root)
    app.path_var.set(DEMO)
    root.after(600, app.start)

    def window_bbox():
        """用 DWM 取完整窗口边界（含标题栏），失败则退回客户区。"""
        try:
            import ctypes
            from ctypes import wintypes
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
            rect = wintypes.RECT()
            rc = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))  # EXTENDED_FRAME_BOUNDS
            if rc == 0:
                return (rect.left, rect.top, rect.right, rect.bottom)
        except Exception:
            pass
        x, y = root.winfo_rootx(), root.winfo_rooty()
        return (x, y, x + root.winfo_width(), y + root.winfo_height())

    def shoot():
        root.update_idletasks()
        root.update()
        from PIL import ImageGrab
        ImageGrab.grab(bbox=window_bbox()).save(SHOT)
        root.destroy()

    root.after(5200, shoot)
    root.mainloop()

    shutil.rmtree(DEMO, ignore_errors=True)
    print('screenshot -> %s (%d bytes)' % (SHOT, os.path.getsize(SHOT)))


if __name__ == '__main__':
    main()
