#!/usr/bin/env python3
"""S2-E1 驱动: 冻结 20 帧 (板端相机 one-shot) → 拉回 → 40 请求 (2 顺序 × 20 帧) → 拉回 JSONL
用法: python3 run_s2e1.py
"""
import os, sys, time, json, hashlib, random, tarfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from board import get_client, run, sftp_put, sftp_get

HERE = os.path.dirname(os.path.abspath(__file__))
TAG = sys.argv[1] if len(sys.argv) > 1 else 's2e1'
DATA = os.path.join(HERE, 'data', TAG)
os.makedirs(DATA, exist_ok=True)
BDIR = f"/tmp/{TAG}"
MODEL = 'SmolVLM-256M-Instruct-Q8_0.gguf'
MMPROJ = 'mmproj-SmolVLM-256M-Instruct-Q8_0.gguf'
NFRAMES = 20
SEED = 20260813

def capture_frames(c):
    """板端 one-shot 采集 20 帧到 /tmp/s2e1/frames/"""
    run(c, f'rm -rf {BDIR}; mkdir -p {BDIR}/frames', timeout=30)
    for i in range(NFRAMES):
        cmd = (f'gst-launch-1.0 -q v4l2src device=/dev/video22 num-buffers=1 '
               f'! video/x-raw,format=NV12,width=640,height=480 '
               f'! jpegenc ! filesink location={BDIR}/frames/f_{i:02d}.jpg 2>/dev/null; '
               f'stat -c %s {BDIR}/frames/f_{i:02d}.jpg')
        code, out, err = run(c, cmd, timeout=30)
        try:
            size = int(out.strip().split('\n')[-1])
        except (ValueError, IndexError):
            size = 0
        if size <= 0:
            print(f'  [capture] f_{i:02d} FAILED: {out.strip()[-100:]}')
            return False
        time.sleep(0.5)
    code, out, err = run(c, 'ls /tmp/s2e1/frames/ | wc -l; du -sh /tmp/s2e1/frames', timeout=30)
    print(f'[1/5] 采集完成: {out.strip()}')
    return True

def main():
    c = get_client()
    run(c, 'pkill -x llama-server 2>/dev/null; true', timeout=30)
    # 1. 采集
    if not capture_frames(c):
        c.close(); sys.exit(1)
    # 2. 拉回帧
    run(c, f'cd /tmp && tar czf {TAG}_frames.tgz {TAG}/frames', timeout=60)
    sftp_get(c, f'/tmp/{TAG}_frames.tgz', os.path.join(DATA, 'frames.tgz'))
    with tarfile.open(os.path.join(DATA, 'frames.tgz')) as tf:
        tf.extractall(DATA, filter='data')
    print('[2/5] 帧已拉回')
    # 3. 生成计划: 每帧两顺序, 先后随机 (seed 固定)
    rng = random.Random(SEED)
    frames = sorted(os.listdir(os.path.join(DATA, TAG, 'frames')))
    plan = []
    for fid in frames:
        p = os.path.join(DATA, TAG, 'frames', fid)
        sha = hashlib.sha256(open(p, 'rb').read()).hexdigest()
        orders = ['text-image', 'image-text']
        rng.shuffle(orders)
        for o in orders:
            plan.append({'frame_id': fid, 'order': o, 'sha256': sha})
    with open(os.path.join(DATA, 'plan.json'), 'w') as f:
        json.dump(plan, f, indent=1)
    # 4. 上传探测脚本 + 计划, 起 server, 跑
    sftp_put(c, os.path.join(HERE, 's2e1_probe.py'), f'{BDIR}/probe.py')
    sftp_put(c, os.path.join(DATA, 'plan.json'), f'{BDIR}/plan.json')
    code, out, err = run(c,
        f'export LD_LIBRARY_PATH=/userdata/llama/bin; '
        f'nohup /userdata/llama/bin/llama-server -m /userdata/llama/models/{MODEL} '
        f'--mmproj /userdata/llama/models/{MMPROJ} --port 8088 -t 8 '
        f'> {BDIR}/server.log 2>&1 & echo pid=$!', timeout=30)
    for i in range(40):
        code, out, _ = run(c, 'curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8088/health', timeout=15)
        if out.strip() == '200':
            print(f'[3/5] server 就绪 ({i*2}s)'); break
        time.sleep(2)
    else:
        print('[3/5] server 超时!'); run(c, f'tail -20 {BDIR}/server.log', timeout=15); c.close(); sys.exit(1)
    print('[4/5] 运行 40 请求 (约 4 分钟)...')
    code, out, err = run(c, f'cd {BDIR} && python3 probe.py {BDIR} 2>&1', timeout=420)
    print(out[-1000:])
    if err: print('STDERR:', err[:300])
    # 5. 拉回结果
    sftp_get(c, f'{BDIR}/rounds.jsonl', os.path.join(DATA, 'rounds.jsonl'))
    sftp_get(c, f'{BDIR}/server.log', os.path.join(DATA, 'server.log'))
    run(c, 'pkill -x llama-server 2>/dev/null; true', timeout=30)
    c.close()
    print(f'[5/5] rounds.jsonl 已拉回 → data/{TAG}/')
    print('DONE')

if __name__ == '__main__':
    main()
