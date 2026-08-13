#!/usr/bin/env python3
"""S2-E2-RES 驱动: image→text 固定下的分辨率梯度重扫
6 分辨率 (160x120/320x240/480x360/640x480/800x600/1280x960) × 20 帧 (相机逐分辨率采集)
× 256M, image→text, t=0.0, cache off = 120 请求
用法: python3 run_s2e2res.py
"""
import os, sys, time, json, hashlib, tarfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from board import get_client, run, sftp_put, sftp_get

HERE = os.path.dirname(os.path.abspath(__file__))
TAG = sys.argv[1] if len(sys.argv) > 1 else 's2e2res'
MODEL = sys.argv[2] if len(sys.argv) > 2 else 'SmolVLM-256M-Instruct-Q8_0.gguf'
MMPROJ = sys.argv[3] if len(sys.argv) > 3 else 'mmproj-SmolVLM-256M-Instruct-Q8_0.gguf'
DATA = os.path.join(HERE, 'data', TAG)
os.makedirs(DATA, exist_ok=True)
BDIR = f"/tmp/{TAG}"
RESOLUTIONS = [(160, 120), (320, 240), (480, 360), (640, 480), (800, 600), (1280, 960)]
NFRAMES = 20

def filter_resolutions():
    """argv[4] 可选, 如 '160x120' 只跑该档"""
    global RESOLUTIONS
    if len(sys.argv) > 4:
        want = sys.argv[4]
        RESOLUTIONS = [(w, h) for w, h in RESOLUTIONS if f'{w}x{h}' == want]
        if not RESOLUTIONS:
            print(f'未知分辨率过滤: {want}'); sys.exit(1)

def capture_frames(c):
    run(c, f'rm -rf {BDIR}; mkdir -p {BDIR}/frames', timeout=30)
    for w, h in RESOLUTIONS:
        tag = f'{w}x{h}'
        run(c, f'mkdir -p {BDIR}/frames/{tag}', timeout=15)
        for i in range(NFRAMES):
            cmd = (f'gst-launch-1.0 -q v4l2src device=/dev/video22 num-buffers=1 '
                   f'! video/x-raw,format=NV12,width={w},height={h} '
                   f'! jpegenc ! filesink location={BDIR}/frames/{tag}/f_{i:02d}.jpg 2>/dev/null; '
                   f'stat -c %s {BDIR}/frames/{tag}/f_{i:02d}.jpg')
            code, out, err = run(c, cmd, timeout=30)
            try:
                size = int(out.strip().split('\n')[-1])
            except (ValueError, IndexError):
                size = 0
            if size <= 0:
                print(f'  [capture] {tag}/f_{i:02d} FAILED: {out.strip()[-100:]}')
                return False
            time.sleep(0.4)
        print(f'  [capture] {tag} × {NFRAMES} ok')
    return True

def main():
    filter_resolutions()
    c = get_client()
    run(c, 'pkill -x llama-server 2>/dev/null; true', timeout=30)
    print('[1/4] 采集 6 分辨率 × 20 帧...')
    if not capture_frames(c):
        c.close(); sys.exit(1)
    run(c, f'cd /tmp && tar czf {TAG}_frames.tgz {TAG}/frames', timeout=120)
    sftp_get(c, f'/tmp/{TAG}_frames.tgz', os.path.join(DATA, 'frames.tgz'))
    with tarfile.open(os.path.join(DATA, 'frames.tgz')) as tf:
        tf.extractall(DATA, filter='data')
    print('[2/4] 帧已拉回, 生成计划 (全部 image→text)...')
    plan = []
    for w, h in RESOLUTIONS:
        tag = f'{w}x{h}'
        d = os.path.join(DATA, TAG, 'frames', tag)
        for fid in sorted(os.listdir(d)):
            p = os.path.join(d, fid)
            sha = hashlib.sha256(open(p, 'rb').read()).hexdigest()
            plan.append({'frame_id': f'{tag}/{fid}', 'order': 'image-text', 'sha256': sha})
    with open(os.path.join(DATA, 'plan.json'), 'w') as f:
        json.dump(plan, f)
    print(f'  {len(plan)} 请求计划')
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
            print(f'[3/4] server 就绪 ({i*2}s)'); break
        time.sleep(2)
    else:
        print('[3/4] server 超时!'); run(c, f'tail -20 {BDIR}/server.log', timeout=15); c.close(); sys.exit(1)
    print(f'[4/4] 运行 {len(plan)} 请求 (约 12 分钟)...')
    code, out, err = run(c, f'cd {BDIR} && python3 probe.py {BDIR} 2>&1', timeout=900)
    print(out[-600:])
    if err: print('STDERR:', err[:300])
    sftp_get(c, f'{BDIR}/rounds.jsonl', os.path.join(DATA, 'rounds.jsonl'))
    sftp_get(c, f'{BDIR}/server.log', os.path.join(DATA, 'server.log'))
    run(c, 'pkill -x llama-server 2>/dev/null; true', timeout=30)
    c.close()
    print(f'DONE → data/{TAG}/rounds.jsonl')

if __name__ == '__main__':
    main()
