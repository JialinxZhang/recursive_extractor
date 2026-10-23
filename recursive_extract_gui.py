#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""recursive_extract_gui.py — 递归解压工具 图形界面

用法：
  python recursive_extract_gui.py                     打开窗口
  python recursive_extract_gui.py D:\\某个目录          打开窗口并填好路径
  python recursive_extract_gui.py D:\\某个目录 --go     填好路径并自动开始，完成后退出（批处理用）
"""

import os
import queue
import sys
import threading
import time
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from recursive_extract import Extractor, __version__

AUTO_FLAGS = ('--go', '-g')
APP_TITLE = '递归解压工具'


def resource_path(name):
    """兼容 PyInstaller 打包后的资源路径。"""
    base = getattr(sys, '_MEIPASS', None)
    if base:
        p = os.path.join(base, name)
        if os.path.exists(p):
            return p
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


class App:
    def __init__(self, root, auto_close=False):
        self.root = root
        self.auto_close = auto_close
        self.msgs = queue.Queue()   # 工作线程 -> 界面线程 的消息队列
        self.worker = None
        self.extractor = None

        root.title('%s v%s' % (APP_TITLE, __version__))
        root.minsize(640, 430)
        try:
            root.iconbitmap(resource_path('icon.ico'))
        except Exception:
            pass
        root.option_add('*Font', ('Microsoft YaHei UI', 10))

        self._build()
        root.after(100, self._poll)
        root.protocol('WM_DELETE_WINDOW', self._on_close)

    # ----- 界面布局 -----

    def _build(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill='both', expand=True)

        # 路径行
        row1 = ttk.Frame(top)
        row1.pack(fill='x')
        ttk.Label(row1, text='路径:').pack(side='left')
        self.path_var = tk.StringVar()
        self.entry = ttk.Entry(row1, textvariable=self.path_var)
        self.entry.pack(side='left', fill='x', expand=True, padx=6)
        self.btn_file = ttk.Button(row1, text='选文件…', command=self.browse_file)
        self.btn_file.pack(side='left')
        self.btn_dir = ttk.Button(row1, text='选文件夹…', command=self.browse_dir)
        self.btn_dir.pack(side='left', padx=(6, 0))

        # 选项行
        row2 = ttk.Frame(top)
        row2.pack(fill='x', pady=(10, 0))
        self.del_var = tk.BooleanVar(value=False)
        self.chk_delete = ttk.Checkbutton(row2, text='解压成功后删除压缩包',
                                          variable=self.del_var)
        self.chk_delete.pack(side='left')
        ttk.Label(row2, text='　最大嵌套深度:').pack(side='left')
        self.depth_var = tk.IntVar(value=10)
        self.spin_depth = ttk.Spinbox(row2, from_=1, to=99, width=4,
                                      textvariable=self.depth_var)
        self.spin_depth.pack(side='left', padx=4)
        ttk.Label(row2, text='层').pack(side='left')
        self.btn_open = ttk.Button(row2, text='打开所在文件夹', command=self.open_folder)
        self.btn_open.pack(side='right')

        # 按钮行
        row3 = ttk.Frame(top)
        row3.pack(fill='x', pady=(10, 0))
        self.btn_start = ttk.Button(row3, text='▶ 开始解压', command=self.start)
        self.btn_start.pack(side='left')
        self.btn_stop = ttk.Button(row3, text='■ 停止', command=self.stop, state='disabled')
        self.btn_stop.pack(side='left', padx=6)

        # 日志区
        self.logbox = scrolledtext.ScrolledText(
            top, height=16, state='disabled', font=('Consolas', 9),
            background='#fafafa', relief='solid', borderwidth=1)
        self.logbox.pack(fill='both', expand=True, pady=(10, 0))
        self.logbox.tag_config('err', foreground='#c62828')
        self.logbox.tag_config('warn', foreground='#ef6c00')
        self.logbox.tag_config('ok', foreground='#2e7d32')
        self.logbox.tag_config('dim', foreground='#757575')

        # 状态栏
        self.status_var = tk.StringVar(value='就绪')
        ttk.Label(self.root, textvariable=self.status_var, relief='sunken',
                  anchor='w', padding=(6, 3)).pack(fill='x', side='bottom')

        self._append('提示: 选择压缩包或文件夹后点「开始解压」，嵌套的压缩包会自动继续解压。', 'dim')

    # ----- 日志 -----

    def _append(self, line, tag=None):
        self.logbox.configure(state='normal')
        self.logbox.insert('end', line + '\n', tag or ())
        self.logbox.see('end')
        self.logbox.configure(state='disabled')

    @staticmethod
    def _tag_for(line):
        if '[失败]' in line or '[错误]' in line:
            return 'err'
        if '[跳过]' in line or '[已停止]' in line:
            return 'warn'
        if '[OK]' in line or line.startswith('完成'):
            return 'ok'
        if line.lstrip().startswith('->'):
            return 'dim'
        return None

    def _poll(self):
        """界面线程轮询工作线程发来的日志。"""
        try:
            while True:
                msg = self.msgs.get_nowait()
                if isinstance(msg, tuple):
                    if msg[0] == '__done__':
                        self._finish(msg[1], msg[2])
                    elif msg[0] == '__error__':
                        self._finish_error(msg[1])
                else:
                    self._append(msg, self._tag_for(msg))
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    # ----- 动作 -----

    def browse_file(self):
        p = filedialog.askopenfilename(parent=self.root, title='选择压缩包',
                                       filetypes=[('压缩包', '*.zip *.7z *.rar *.tar *.gz *.tgz *.bz2 *.xz *.txz'), ('所有文件', '*.*')])
        if p:
            self.path_var.set(p)

    def browse_dir(self):
        p = filedialog.askdirectory(parent=self.root, title='选择文件夹')
        if p:
            self.path_var.set(p)

    def open_folder(self):
        p = self.path_var.get().strip().strip('"')
        if not p or not os.path.exists(p):
            messagebox.showinfo(APP_TITLE, '请先选择一个有效的路径。', parent=self.root)
            return
        if os.path.isfile(p):
            p = os.path.dirname(p)
        os.startfile(p)

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        path = self.path_var.get().strip().strip('"')
        if not path:
            messagebox.showwarning(APP_TITLE, '请先选择要解压的压缩包或文件夹。', parent=self.root)
            return
        if not os.path.exists(path):
            messagebox.showwarning(APP_TITLE, '路径不存在：%s' % path, parent=self.root)
            return
        try:
            depth = max(1, int(self.depth_var.get()))
        except (ValueError, tk.TclError):
            depth = 10

        self._append('=' * 52 + ' ' + time.strftime('%Y-%m-%d %H:%M:%S'), 'dim')
        self.status_var.set('正在解压…')
        self._set_running(True)

        self.extractor = Extractor(delete=self.del_var.get(), max_depth=depth,
                                   log=self.msgs.put)
        self.worker = threading.Thread(target=self._work, args=(path,), daemon=True)
        self.worker.start()

    def _work(self, path):
        try:
            ok, fail = self.extractor.process([path])
            self.msgs.put(('__done__', ok, fail))
        except Exception:
            self.msgs.put(('__error__', traceback.format_exc()))

    def stop(self):
        if self.extractor:
            self.extractor.request_stop()
        self.status_var.set('正在停止，等待当前压缩包完成…')

    # ----- 状态切换 -----

    def _set_running(self, busy):
        st = 'disabled' if busy else 'normal'
        for w in (self.btn_start, self.btn_file, self.btn_dir, self.chk_delete,
                  self.spin_depth, self.btn_open, self.entry):
            w.configure(state=st)
        self.btn_stop.configure(state='normal' if busy else 'disabled')

    def _finish(self, ok, fail):
        self._set_running(False)
        text = '完成：成功 %d 个，失败 %d 个　%s' % (ok, fail, time.strftime('%H:%M:%S'))
        self.status_var.set(text)
        if fail:
            self._append('注意: 有 %d 个压缩包解压失败，详见上方日志。' % fail, 'warn')
        elif self.auto_close:
            self.root.after(1500, self.root.destroy)

    def _finish_error(self, tb_text):
        self._set_running(False)
        self.status_var.set('发生错误')
        self._append(tb_text, 'err')
        messagebox.showerror(APP_TITLE, '程序发生错误，详情见日志窗口。', parent=self.root)

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askokcancel('退出', '正在解压，确定要停止并退出吗？',
                                          parent=self.root):
                return
            self.extractor.request_stop()
        self.root.destroy()


def main():
    if sys.platform == 'win32':
        try:  # 高分屏下界面清晰不模糊
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    argv = sys.argv[1:]
    auto = any(a in AUTO_FLAGS for a in argv)
    paths = [a for a in argv if a not in AUTO_FLAGS]

    root = tk.Tk()
    app = App(root, auto_close=auto)
    if paths:
        app.path_var.set(os.path.abspath(paths[0]))
        if auto:
            root.after(300, app.start)
    root.mainloop()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        try:  # 打包成 exe 后没有控制台，错误写日志文件
            log_file = os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                                    '递归解压工具-错误.log')
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(err)
        except OSError:
            pass
        try:
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror(APP_TITLE, '程序出错，详情已写入:\n%s' % log_file)
        except Exception:
            pass
        sys.exit(1)
