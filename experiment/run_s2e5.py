#!/usr/bin/env python3
"""S2-E5 受限解码驱动: 上传帧+plan → external 模式起 server → 板端跑探测 → 拉回 → 清理
设计: text→image 顺序 (C 客户端现状, 部署兼容) × {正/负场景} × {320/640} × {constrained/unconstrained}
每帧两约束配对, 20 帧/格 → 160 请求。t=0.0, cache_prompt=false, max_tokens=16, 256M Q8_0。
用法: python3 run_s2e5.py [tag]
"""
import hashlib, json, os, random, sys, tarfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from board import get_client, run, sftp_put, sftp_get

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
TAG = sys.argv[1] if len(sys.argv) > 1 else 's2e5'
DIR = os.path.join(DATA, TAG)
FRAMES = os.path.join(DIR, 'frames')
MODEL = 'SmolVLM-256M-Instruct-Q8_0.gguf'
MMPROJ = 'mmproj-SmolVLM-256M-Instruct-Q8_0.gguf'
SEED = 20260817

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()

def build_plan():
    """每格 20 帧 × 2 约束 (同帧配对) → 160 行, 全局乱序"""
    cells = []
    for scene in ('pos', 'neg'):
        for res in ('640', '320'):
            cells.append(f"{scene}{res}")
    plan = []
    for cell in cells:
        fdir = os.path.join(FRAMES, cell)
        for f in sorted(os.listdir(fdir)):
            p = os.path.join(fdir, f)
            plan.append({"frame_id": f"{cell}/{f}",
                         "constraint": "unconstrained", "sha256": sha256_file(p)})
            plan.append({"frame_id": f"{cell}/{f}",
                         "constraint": "constrained", "sha256": sha256_file(p)})
    random.Random(SEED).shuffle(plan)
    with open(os.path.join(DIR, 'plan.json'), 'w') as f:
        json.dump(plan, f, indent=1)
    print(f"plan: {len(plan)} 请求 ({len(plan)//2} 帧配对)")

def pack_frames():
    """帧打包 tgz (结构: frames/<cell>/f_XX.jpg)"""
    tgz = os.path.join(DIR, 'frames.tgz')
    with tarfile.open(tgz, 'w:gz') as t:
        for cell in sorted(os.listdir(FRAMES)):
            for f in sorted(os.listdir(os.path.join(FRAMES, cell))):
                t.add(os.path.join(FRAMES, cell, f), arcname=f"frames/{cell}/{f}")
    return tgz

def main():
    os.makedirs(DIR, exist_ok=True)
    build_plan()
    frames_tgz = pack_frames()
    c = get_client()
    # 1. 清理残留 + 建目录
    run(c, 'pkill -x llama-server 2>/dev/null; sleep 1; rm -rf /tmp/s2e5; mkdir -p /tmp/s2e5', timeout=30)
    # 2. 上传
    sftp_put(c, os.path.join(HERE, 's2e5_probe.py'), '/tmp/s2e5/probe.py')
    sftp_put(c, frames_tgz, '/tmp/s2e5/frames.tgz')
    run(c, 'cd /tmp/s2e5 && tar xzf frames.tgz && ls frames | tr "\\n" " "', timeout=60)
    sftp_put(c, os.path.join(DIR, 'plan.json'), '/tmp/s2e5/plan.json')
    print('[1/4] 帧 + plan + probe 已上传')
    # 3. 记录版本 + 起 server
    code, ver, _ = run(c, 'export LD_LIBRARY_PATH=/userdata/llama/bin; /userdata/llama/bin/llama-server --version 2>&1 | head -3', timeout=30)
    with open(os.path.join(DIR, 'server_version.txt'), 'w') as f:
        f.write(ver)
    code, out, err = run(c,
        f'export LD_LIBRARY_PATH=/userdata/llama/bin; '
        f'nohup /userdata/llama/bin/llama-server -m /userdata/llama/models/{MODEL} '
        f'--mmproj /userdata/llama/models/{MMPROJ} --port 8088 -t 8 '
        f'> /tmp/s2e5/server.log 2>&1 & echo started_pid=$!', timeout=30)
    print(f'[2/4] server 启动: {out.strip()}')
    ok = False
    for i in range(40):
        code, out, _ = run(c, 'curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8088/health', timeout=15)
        if out.strip() == '200':
            ok = True
            print(f'[2/4] server 就绪 ({i*2}s)')
            break
        time.sleep(2)
    if not ok:
        code, out, _ = run(c, 'tail -20 /tmp/s2e5/server.log', timeout=15)
        print('server 启动超时! server.log:\n' + out)
        c.close(); sys.exit(1)
    # 4. 跑探测 (160 请求 × ~6.2s ≈ 17 分钟)
    print('[3/4] 运行探测 (160 请求, 预计 ~17 分钟)...')
    t0 = time.time()
    code, out, err = run(c, 'cd /tmp/s2e5 && python3 probe.py 2>&1', timeout=1800)
    print(f'[3/4] 探测完成 ({(time.time()-t0)/60:.1f} min), 最后 20 行:')
    print(out[-1200:])
    if err:
        print('STDERR:', err[:300])
    # 5. 拉回
    run(c, 'cd /tmp && tar czf s2e5_results.tgz s2e5 2>/dev/null; ls -la s2e5_results.tgz', timeout=60)
    sftp_get(c, '/tmp/s2e5_results.tgz', os.path.join(DIR, 's2e5_results.tgz'))
    # 单独拉 rounds 便于直接分析
    sftp_get(c, '/tmp/s2e5/rounds.jsonl', os.path.join(DIR, 'rounds.jsonl'))
    sftp_get(c, '/tmp/s2e5/server.log', os.path.join(DIR, 'server.log'))
    print('[4/4] 结果已拉回 data/s2e5/')
    run(c, 'pkill -x llama-server 2>/dev/null; true', timeout=30)
    c.close()
    print('DONE')

if __name__ == '__main__':
    main()
