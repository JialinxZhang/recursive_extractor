# -*- coding: utf-8 -*-
"""自测脚本：无需第三方依赖，python tests/selftest.py 直接运行。

构造嵌套/GBK/Zip-Slip 等测试压缩包，用 Extractor 引擎解压并断言结果，
同时冒烟测试命令行界面。
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from fixtures import INNER_TEXT, make_fixtures          # noqa: E402
from recursive_extract import Extractor, is_archive     # noqa: E402

checks = 0


def check(cond, what):
    global checks
    if not cond:
        print('FAIL: %s' % what)
        sys.exit(1)
    checks += 1


def main():
    tmp = tempfile.mkdtemp(prefix='rec_extract_test_')
    expect = make_fixtures(tmp)

    logs = []
    ex = Extractor(log=logs.append,
                   warn=lambda m: logs.append('    [跳过] ' + m))
    ok, fail = ex.process([tmp])
    check(fail == 0, '不应有失败项 (fail=%d)' % fail)
    check(ok >= 6, '至少解压 6 个（7z 存在时更多），实际 %d' % ok)

    check(os.path.isfile(expect['nested']), '嵌套 zip 解出 inner.txt')
    with open(expect['nested'], encoding='utf-8') as f:
        check(f.read() == INNER_TEXT, 'inner.txt 内容正确')
    check(os.path.isfile(expect['readme']), 'zip 普通文件解出')
    check(os.path.isfile(expect['gbk']), 'GBK 中文文件名正确还原')
    check(os.path.isfile(expect['from_tar']), 'tar.gz 里的 zip 继续解压')
    check(os.path.isfile(expect['tar_note']), 'tar.gz 中文条目解出')
    check(os.path.isfile(expect['gz_note']), 'gz 单文件解压')
    with open(expect['gz_note'], encoding='utf-8') as f:
        check(f.read() == 'gz 单文件内容', 'gz 内容正确')
    check(os.path.isfile(expect['evil_ok']), 'Zip-Slip 压缩包的正常条目已解出')
    check(not os.path.exists(expect['evil_escape']), 'Zip-Slip ../evil.txt 未越界')
    if expect['deep7z']:
        check(os.path.isfile(expect['deep7z']), '7z 套 zip 继续解压')
    check(any('不安全条目' in line for line in logs), 'Zip-Slip 条目有警告日志')

    # --delete 模式：全部压缩包（含嵌套产物）解压成功后被删除
    tmp2 = tempfile.mkdtemp(prefix='rec_extract_del_')
    make_fixtures(tmp2)
    ok2, fail2 = Extractor(delete=True).process([tmp2])
    check(fail2 == 0 and ok2 == ok, '--delete 模式成功数一致')
    remain = [os.path.join(r, f) for r, _d, fs in os.walk(tmp2) for f in fs
              if is_archive(os.path.join(r, f))]
    check(not remain, '--delete 后无残留压缩包: %s' % remain)

    # 命令行冒烟测试
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'recursive_extract.py'),
                        '--help'], capture_output=True)
    check(r.returncode == 0, '--help 正常退出')

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmp2, ignore_errors=True)
    print('selftest OK: %d 项断言全部通过' % checks)


if __name__ == '__main__':
    main()
