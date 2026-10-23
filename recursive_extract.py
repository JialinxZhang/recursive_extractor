#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""recursive_extract.py — Windows 下递归解压工具（核心模块 + 命令行界面）

给定一个压缩包或一个目录，把其中所有压缩包解压出来；解压产物里如果
还有压缩包（嵌套压缩包），会继续解压，直到没有新的压缩包为止。

支持的格式：
  zip / tar / tar.gz / tgz / tar.bz2 / tbz2 / tar.xz / txz / gz / bz2 / xz
    —— 使用 Python 标准库，无需额外安装
  7z / rar
    —— 自动调用本机 7-Zip（或 PATH 中的 7z、WinRAR、tar）

命令行用法：
  python recursive_extract.py 压缩包或目录 [更多路径...]
  python recursive_extract.py D:\\下载 --delete      解压成功后删除压缩包
  python recursive_extract.py D:\\下载 --depth 3      限制嵌套解压深度
  python recursive_extract.py D:\\下载 --list         只列出将解压的文件

图形界面：python recursive_extract_gui.py
"""

import argparse
import bz2
import gzip
import lzma
import os
import posixpath
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from collections import deque

__version__ = '1.0.0'

# 复合扩展名需在单扩展名之前匹配
COMPOUND_EXTS = ('.tar.gz', '.tar.bz2', '.tar.xz', '.tgz', '.tbz2', '.tbz', '.txz')
ZIP_EXTS = {'.zip'}
TAR_EXTS = {'.tar'}
SINGLE_MODULES = {'.gz': gzip, '.bz2': bz2, '.xz': lzma}
EXTERNAL_EXTS = {'.7z', '.rar'}

EXTERNAL_CANDIDATES = (
    r'C:\Program Files\7-Zip\7z.exe',
    r'C:\Program Files (x86)\7-Zip\7z.exe',
    r'C:\Program Files\WinRAR\WinRAR.exe',
    r'C:\Program Files (x86)\WinRAR\WinRAR.exe',
)


# ---------- 扩展名识别 ----------

def split_archive_ext(name):
    """返回 (扩展名(小写含点)或 None, 去掉扩展名后的主名)。"""
    low = name.lower()
    for c in COMPOUND_EXTS:
        if low.endswith(c):
            return c, low[:-len(c)]
    base, ext = os.path.splitext(low)
    if ext and len(ext) > 1:
        return ext, base
    return None, low


def archive_kind(path):
    """返回 (类型, 输出主名)；不是压缩包则 (None, None)。"""
    ext, base = split_archive_ext(os.path.basename(path))
    if ext is None:
        return None, None
    if ext in ZIP_EXTS:
        return 'zip', base
    if ext in TAR_EXTS or ext in COMPOUND_EXTS:
        return 'tar', base
    if ext in SINGLE_MODULES:
        return ext[1:], base
    if ext in EXTERNAL_EXTS:
        return ext[1:], base
    return None, None


def is_archive(path):
    return archive_kind(path)[0] is not None


# ---------- 通用工具 ----------

def win_long(path):
    """普通路径超过 260 字符时加 \\\\?\\ 前缀，避免深层嵌套解压时打不开文件。"""
    path = os.path.abspath(path)
    if os.name == 'nt' and len(path) > 240 and not path.startswith('\\\\?\\'):
        return '\\\\?\\' + path
    return path


def is_inside(base, target):
    """检查 target 解析后是否仍位于 base 目录内（防 Zip Slip 路径穿越）。"""
    base = os.path.realpath(base)
    target = os.path.realpath(target)
    return target == base or target.startswith(base + os.sep)


def unique_dir(base):
    cand, i = base, 1
    while os.path.exists(cand):
        i += 1
        cand = '%s_%d' % (base, i)
    os.makedirs(win_long(cand))
    return cand


def unique_file(path):
    cand, i = path, 1
    stem, ext = os.path.splitext(path)
    while os.path.exists(cand):
        i += 1
        cand = '%s_%d%s' % (stem, i, ext)
    return cand


def find_archives(root):
    """列出 root 目录下所有压缩包。"""
    found = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(dirpath, f)
            if is_archive(p):
                found.append(p)
    return found


def find_external():
    """找可用于 7z/rar 的外部程序，返回 (路径, 类型) 或 (None, None)。"""
    exe = shutil.which('7z') or shutil.which('7za')
    if exe:
        return exe, '7z'
    for p in EXTERNAL_CANDIDATES:
        if os.path.isfile(p):
            tool = 'winrar' if 'winrar' in os.path.basename(p).lower() else '7z'
            return p, tool
    exe = shutil.which('tar')
    if exe:
        return exe, 'tar'
    return None, None


# ---------- 各格式解压 ----------

def fix_zip_name(info):
    """修复中文文件名乱码：无 UTF-8 标志时，尝试按 GBK 等编码重新解码。"""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        raw = info.filename.encode('cp437')
    except UnicodeEncodeError:
        return info.filename
    for enc in ('gbk', 'big5', 'shift_jis', 'utf-8'):
        try:
            fixed = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        return fixed
    return info.filename


def extract_zip(arc, out_dir, warn):
    count = 0
    with zipfile.ZipFile(win_long(arc)) as zf:
        for info in zf.infolist():
            name = fix_zip_name(info).replace('\\', '/')
            name = posixpath.normpath(name)
            if not name or name in ('.', '/') or name.startswith('../'):
                warn('不安全条目 %r（来自 %s）' % (info.filename, os.path.basename(arc)))
                continue
            dest = os.path.join(out_dir, *name.split('/'))
            if not is_inside(out_dir, dest):
                warn('不安全条目 %r（来自 %s）' % (info.filename, os.path.basename(arc)))
                continue
            if info.is_dir() or name.endswith('/'):
                os.makedirs(win_long(dest), exist_ok=True)
                continue
            try:
                os.makedirs(win_long(os.path.dirname(dest) or out_dir), exist_ok=True)
                with zf.open(info) as src, open(win_long(dest), 'wb') as dst:
                    shutil.copyfileobj(src, dst)
            except RuntimeError as e:
                warn('%s（可能需要密码）：%s' % (name, e))
                continue
            try:
                ts = time.mktime(info.date_time + (0, 0, -1))
                os.utime(win_long(dest), (ts, ts))
            except (OSError, ValueError, OverflowError):
                pass
            count += 1
    return count


def extract_tar(arc, out_dir, warn):
    count = 0
    with tarfile.open(win_long(arc), 'r:*') as tf:
        for member in tf:
            try:
                # filter='data' 会拒绝绝对路径、路径穿越和越界链接（Python 3.12+）
                tf.extract(member, win_long(out_dir), filter='data')
            except tarfile.FilterError as e:
                warn('不安全条目 %r：%s' % (member.name, e))
                continue
            except TypeError:
                # 旧版 Python 没有 filter 参数，手动校验路径
                dest = os.path.join(out_dir, member.name)
                if not is_inside(out_dir, dest):
                    warn('不安全条目 %r' % member.name)
                    continue
                tf.extract(member, win_long(out_dir))
            if member.isreg():
                count += 1
    return count


def extract_single(arc, kind):
    """解压 gz/bz2/xz 单文件压缩，产物放在压缩包旁边，返回产物路径。"""
    _ext, base = split_archive_ext(os.path.basename(arc))
    out_path = unique_file(os.path.join(os.path.dirname(arc), base))
    module = SINGLE_MODULES['.' + kind]
    with module.open(win_long(arc), 'rb') as src, open(win_long(out_path), 'wb') as dst:
        shutil.copyfileobj(src, dst)
    return out_path


def extract_external(arc, out_dir, exe, tool):
    if tool == '7z':
        cmd = [exe, 'x', '-y', '-p', '-o' + out_dir, '--', arc]
    elif tool == 'winrar':
        cmd = [exe, 'x', '-y', '-ibck', arc, out_dir.rstrip('\\') + '\\']
    else:  # Windows 自带的 bsdtar，也能读 7z/rar
        cmd = [exe, '-xf', arc, '-C', out_dir]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding='utf-8', errors='replace')
    if proc.returncode != 0:
        tail = (proc.stdout or '').strip().splitlines()[-3:]
        raise RuntimeError('外部程序失败(%d): %s' % (proc.returncode, '; '.join(tail)))
    return sum(len(files) for _, _, files in os.walk(out_dir))


# ---------- 解压引擎（CLI 与图形界面共用） ----------

class Extractor:
    """递归解压引擎。

    log/warn 为文本输出回调（GUI 里传入线程安全队列即可）；
    request_stop() 可在两个压缩包之间安全中断。
    """

    def __init__(self, delete=False, max_depth=10, log=None, warn=None):
        self.delete = delete
        self.max_depth = max_depth
        self.log = log or (lambda msg: print(msg))
        self.warn = warn or (lambda msg: print('    [跳过] ' + msg))
        self.stop = False
        self.external = find_external()

    def request_stop(self):
        self.stop = True

    def handle_archive(self, arc, kind, base, depth):
        """解压一个压缩包。返回 (成功?, 本次产生的新压缩包列表)。"""
        sub = '  ' * (depth + 1) + '-> '
        if kind in ('gz', 'bz2', 'xz'):
            try:
                produced = extract_single(arc, kind)
            except Exception as e:
                self.log(sub + '[失败] %s' % e)
                return False, []
            self.log(sub + os.path.basename(produced) + ' [OK]')
            if self.delete:
                os.remove(arc)
            return True, ([produced] if is_archive(produced) else [])

        out_dir = unique_dir(os.path.join(os.path.dirname(arc), base))
        label = os.path.basename(out_dir) + os.sep
        try:
            if kind == 'zip':
                extract_zip(arc, out_dir, self.warn)
            elif kind == 'tar':
                extract_tar(arc, out_dir, self.warn)
            else:  # 7z / rar
                exe, tool = self.external
                if not exe:
                    raise RuntimeError('本机未找到 7-Zip / WinRAR，无法解压 .%s 文件' % kind)
                extract_external(arc, out_dir, exe, tool)
        except Exception as e:  # 单个失败不影响其他压缩包
            self.log(sub + label + ' [失败] %s' % e)
            if os.path.isdir(out_dir) and not os.listdir(out_dir):
                os.rmdir(out_dir)  # 清理刚建的空目录
            return False, []
        self.log(sub + label + ' [OK]')
        if self.delete:
            os.remove(arc)
        return True, find_archives(out_dir)

    def process(self, paths):
        """处理一批路径，返回 (成功数, 失败数)。"""
        queue = deque()
        bad_paths = []
        for p in paths:
            p = os.path.abspath(p)
            if os.path.isdir(p):
                queue.extend((a, 0) for a in find_archives(p))
            elif os.path.isfile(p):
                if is_archive(p):
                    queue.append((p, 0))
                else:
                    bad_paths.append('%s 不是受支持的压缩包' % p)
            else:
                bad_paths.append('%s 不存在' % p)
        for msg in bad_paths:
            self.log('[错误] ' + msg)
        if not queue:
            self.log('没有找到可解压的压缩包。')
            return 0, len(bad_paths)

        seen = set()
        ok = fail = 0
        idx = 0
        while queue:
            if self.stop:
                self.log('    [已停止] 用户取消，共处理 %d 个。' % idx)
                break
            arc, depth = queue.popleft()
            key = os.path.realpath(arc).lower()
            if key in seen:
                continue
            seen.add(key)
            idx += 1
            kind, base = archive_kind(arc)
            self.log('[%d]%s %s' % (idx, '  ' * depth, arc))
            if depth >= self.max_depth:
                self.warn('已达到最大嵌套深度 %d（可用 --depth 调整）' % self.max_depth)
                continue
            success, children = self.handle_archive(arc, kind, base, depth)
            if success:
                ok += 1
                queue.extend((c, depth + 1) for c in children)
            else:
                fail += 1

        line = '完成：成功 %d 个，失败 %d 个。' % (ok, fail)
        if self.delete:
            line += '（已删除解压成功的压缩包）'
        self.log(line)
        return ok, fail


# ---------- 命令行界面 ----------

def main(argv=None):
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        prog='recursive_extract.py',
        description='递归解压工具：解压目录/压缩包中的所有压缩包，并继续解压嵌套的压缩包。',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='示例:\n'
               '  python recursive_extract.py D:\\下载\n'
               '  python recursive_extract.py a.zip b.tar.gz\n'
               '  python recursive_extract.py D:\\下载 --delete --depth 5')
    ap.add_argument('paths', nargs='+', help='要处理的压缩包或目录（可多个）')
    ap.add_argument('-d', '--delete', action='store_true', help='解压成功后删除对应的压缩包')
    ap.add_argument('--depth', type=int, default=10, metavar='N',
                    help='最大嵌套深度，默认 10（防止自解压死循环撑爆磁盘）')
    ap.add_argument('-l', '--list', dest='list_only', action='store_true',
                    help='只列出找到的压缩包，不解压')
    args = ap.parse_args(argv)
    if args.depth < 0:
        ap.error('--depth 不能为负数')

    if args.list_only:
        found = []
        for p in args.paths:
            p = os.path.abspath(p)
            if os.path.isdir(p):
                found.extend(find_archives(p))
            elif os.path.isfile(p) and is_archive(p):
                found.append(p)
        for a in found:
            print(a)
        print('共找到 %d 个压缩包。' % len(found))
        return 0

    ex = Extractor(delete=args.delete, max_depth=args.depth)
    ok, fail = ex.process(args.paths)
    return 1 if fail else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\n已取消。')
        sys.exit(130)
