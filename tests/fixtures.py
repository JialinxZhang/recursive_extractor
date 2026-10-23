# -*- coding: utf-8 -*-
"""构造自测用的压缩包：嵌套 zip、GBK 文件名、tar.gz 套 zip、单文件 gz、
路径穿越（Zip Slip）、7z 套 zip（本机装有 7-Zip 时）。

被 selftest.py 和 scripts/make_screenshot.py 共用。
"""
import gzip
import io
import os
import shutil
import subprocess
import tarfile
import zipfile

SEVEN_ZIP = r'C:\Program Files\7-Zip\7z.exe'

INNER_TEXT = '最里层文件'
GBK_DIR = '中文目录'
GBK_FILE = '报告文件.txt'
NOTE_NAME = '笔记.txt'


def make_fixtures(test_dir):
    """在 test_dir 下生成测试压缩包，返回断言用的期望路径字典。"""
    shutil.rmtree(test_dir, ignore_errors=True)
    os.makedirs(test_dir)

    # 嵌套: outer.zip > mid.zip > inner.txt
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('inner.txt', INNER_TEXT)
    with zipfile.ZipFile(os.path.join(test_dir, 'outer.zip'), 'w') as z:
        z.writestr('mid.zip', buf.getvalue())
        z.writestr('readme.txt', '普通文件')

    # GBK 中文文件名的 zip：先用等长 ASCII 占位名写入，再字节替换成 GBK
    gbk_name = GBK_DIR + '/' + GBK_FILE
    gbk_bytes = gbk_name.encode('gbk')
    holder = 'PLACEHOLDER-' + 'x' * (len(gbk_bytes) - len('PLACEHOLDER-'))
    gbk_path = os.path.join(test_dir, 'gbk-names.zip')
    with zipfile.ZipFile(gbk_path, 'w') as z:
        z.writestr(zipfile.ZipInfo(holder.replace('/', '_')), 'GBK 文件名测试')
    raw = open(gbk_path, 'rb').read()
    open(gbk_path, 'wb').write(raw.replace(holder.replace('/', '_').encode(), gbk_bytes))

    # tar.gz 里套 zip
    inner_zip = os.path.join(test_dir, '_tmp_inner.zip')
    with zipfile.ZipFile(inner_zip, 'w') as z:
        z.writestr('from-tar.txt', 'tar.gz 里的 zip')
    with tarfile.open(os.path.join(test_dir, 'bundle.tar.gz'), 'w:gz') as tf:
        tf.add(inner_zip, arcname='inner.zip')
        tf.addfile(tarfile.TarInfo('说明.txt'), io.BytesIO('打包说明'.encode()))
    os.remove(inner_zip)

    # 单文件 gz
    with gzip.open(os.path.join(test_dir, NOTE_NAME + '.gz'), 'wt',
                   encoding='utf-8') as f:
        f.write('gz 单文件内容')

    # 恶意路径穿越条目（Zip Slip）：../evil.txt 不应被解出
    with zipfile.ZipFile(os.path.join(test_dir, 'evil.zip'), 'w') as z:
        z.writestr('正常.txt', 'ok')
        z.writestr('../evil.txt', '不应被解出的内容')

    expect = {
        'nested': os.path.join(test_dir, 'outer', 'mid', 'inner.txt'),
        'readme': os.path.join(test_dir, 'outer', 'readme.txt'),
        'gbk': os.path.join(test_dir, 'gbk-names', GBK_DIR, GBK_FILE),
        'from_tar': os.path.join(test_dir, 'bundle', 'inner', 'from-tar.txt'),
        'tar_note': os.path.join(test_dir, 'bundle', '说明.txt'),
        'gz_note': os.path.join(test_dir, NOTE_NAME),
        'evil_ok': os.path.join(test_dir, 'evil', '正常.txt'),
        'evil_escape': os.path.join(test_dir, 'evil.txt'),  # 不应存在
        'deep7z': None,
    }

    # 7z 套 zip（可选，取决于本机是否装有 7-Zip）
    if os.path.isfile(SEVEN_ZIP):
        stage = os.path.join(test_dir, '_stage')
        os.makedirs(os.path.join(stage, 'sub'))
        with zipfile.ZipFile(os.path.join(stage, 'sub', 'deep.zip'), 'w') as z:
            z.writestr('deep.txt', '7z 里的 zip')
        subprocess.run([SEVEN_ZIP, 'a',
                        os.path.abspath(os.path.join(test_dir, 'pack.7z')), 'sub'],
                       check=True, stdout=subprocess.DEVNULL, cwd=stage)
        shutil.rmtree(stage)
        expect['deep7z'] = os.path.join(test_dir, 'pack', 'sub', 'deep', 'deep.txt')

    return expect
