#!/usr/bin/env python3
"""S2-E0 能力探测驱动: 上传材料 → external 模式起 server → 板端跑探测 → 拉回结果 → 清理
用法: python3 run_s2e0.py
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from board import get_client, run, sftp_put, sftp_get

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data', 's2e0')
MODEL = 'SmolVLM-256M-Instruct-Q8_0.gguf'
MMPROJ = 'mmproj-SmolVLM-256M-Instruct-Q8_0.gguf'

def main():
    c = get_client()
    # 1. 清理残留 (pkill -x 精确进程名, 避免 -f 匹配到本 shell 自身)
    run(c, 'pkill -x llama-server 2>/dev/null; sleep 1; rm -rf /tmp/s2e0; mkdir -p /tmp/s2e0; ls -d /tmp/s2e0', timeout=30)
    # 2. 上传探测脚本 + 测试图
    sftp_put(c, os.path.join(HERE, 's2e0_probe.py'), '/tmp/s2e0/probe.py')
    sftp_put(c, os.path.join(DATA, 'img_pos.jpg'), '/tmp/s2e0/img_pos.jpg')
    sftp_put(c, os.path.join(DATA, 'img_neg_gray.jpg'), '/tmp/s2e0/img_neg.jpg')
    print('[1/4] 材料已上传')
    # 3. 记录 server 版本 + 起 server (external 模式: 只此一个 owner)
    code, ver, _ = run(c, 'export LD_LIBRARY_PATH=/userdata/llama/bin; /userdata/llama/bin/llama-server --version 2>&1 | head -3', timeout=30)
    print('[2/4] server 版本:\n' + ver.strip())
    with open(os.path.join(DATA, 'server_version.txt'), 'w') as f:
        f.write(ver)
    code, out, err = run(c,
        f'export LD_LIBRARY_PATH=/userdata/llama/bin; '
        f'nohup /userdata/llama/bin/llama-server -m /userdata/llama/models/{MODEL} '
        f'--mmproj /userdata/llama/models/{MMPROJ} --port 8088 -t 8 '
        f'> /tmp/s2e0/server.log 2>&1 & echo started_pid=$!', timeout=30)
    print(f'[2/4] server 启动: {out.strip()}')
    # 等待 /health
    ok = False
    for i in range(40):
        code, out, _ = run(c, 'curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8088/health', timeout=15)
        if out.strip() == '200':
            ok = True
            print(f'[2/4] server 就绪 ({i*2}s)')
            break
        time.sleep(2)
    if not ok:
        print('[2/4] server 启动超时! server.log:')
        code, out, _ = run(c, 'tail -20 /tmp/s2e0/server.log', timeout=15)
        print(out)
        c.close()
        sys.exit(1)
    # 4. 跑探测 (24 请求, 约 2-4 分钟)
    print('[3/4] 运行探测 (24 请求)...')
    code, out, err = run(c, 'cd /tmp/s2e0 && python3 probe.py 2>&1', timeout=420)
    print(out[-800:])
    if err:
        print('STDERR:', err[:300])
    # 5. 拉回结果
    run(c, 'cd /tmp && tar czf s2e0_results.tgz s2e0 2>/dev/null; ls -la s2e0_results.tgz', timeout=60)
    sftp_get(c, '/tmp/s2e0_results.tgz', os.path.join(DATA, 's2e0_results.tgz'))
    print('[4/4] 结果已拉回 data/s2e0/s2e0_results.tgz')
    # 清理 server
    run(c, 'pkill -x llama-server 2>/dev/null; true', timeout=30)
    c.close()
    print('DONE')

if __name__ == '__main__':
    main()
