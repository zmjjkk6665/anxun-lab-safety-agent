"""临时工具：在真实 PTY 中运行需要交互式确认的命令，遇到确认提示自动回答 y。

用法：
    python scripts/_pty_run.py <命令> [参数...]

输出实时打印并写入 outputs/_pty.log，便于排查。仅供本机接入 AGH 时使用。
"""

import sys
import time
import os

from winpty import PtyProcess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, 'outputs', '_pty.log')

cmd = sys.argv[1:]
if not cmd:
    print('用法: python scripts/_pty_run.py <命令> [参数...]')
    raise SystemExit(2)

proc = PtyProcess.spawn(cmd)
buf = []
answered = 0
deadline = time.time() + 240

try:
    while proc.isalive() and time.time() < deadline:
        try:
            data = proc.read()
        except EOFError:
            break
        if data:
            buf.append(data)
            sys.stdout.write(data)
            sys.stdout.flush()
            if 'Continue?' in data and answered < 5:
                time.sleep(0.4)
                proc.write('y\r\n')
                answered += 1
        else:
            time.sleep(0.3)
    try:
        while True:
            d = proc.read()
            if not d:
                break
            buf.append(d)
            sys.stdout.write(d)
    except EOFError:
        pass
finally:
    with open(LOG, 'w', encoding='utf-8') as f:
        f.write(''.join(buf))
    print('\n=== 自动确认次数: %d ===' % answered)
