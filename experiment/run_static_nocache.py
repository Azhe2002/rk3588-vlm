#!/usr/bin/env python3
"""静态图无缓存对照 (实验7/2/3 会话内): 固定帧 × N 轮, cache_prompt=false
目的: 排除 §4.7 静态图 10/10 合规的 prompt-cache 混淆——同帧同 prompt 反复请求
命中 KV cache (0.1s) 返回缓存结果; cache_prompt=false 强制每轮全量计算 (~5.9s)。
- 帧源: 会话内最近采样帧 (默认 exp2_C_upscale640.tgz 的 f_0000, 640×480 实时帧快照)
- 系统提示词/问题/温度/max_tokens 与 rk3588-vlm 完全一致
- 对照: 同会话实时基线 = exp7 t0p1 的 67% (256M@640)
用法: python3 run_static_nocache.py [N轮] [帧文件]
"""
import base64, json, os, sys, tarfile, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from board import get_client, run

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
HOST, PORT = '192.168.1.8', 8088
ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
MODEL = 'SmolVLM-256M-Instruct-Q8_0.gguf'
MMPROJ = 'mmproj-' + MODEL

SYS = ("You are an expert in recognition, processing, and analysis. "
       "Please carefully analyze the image and answer the question accurately. "
       "Please respond with only 'yes' or 'no'. "
       "Detection target: industrial items. Scene: factory warehouse, dim lighting.")
Q = "Is there a black industrial fan in the center of the image? Please answer only yes or no."

def frame_bytes():
    if len(sys.argv) > 2:
        with open(sys.argv[2], 'rb') as f:
            return f.read()
    tgz = os.path.join(DATA, 'exp2_C_upscale640.tgz')
    with tarfile.open(tgz) as t:
        m = [n for n in t.getnames() if n.endswith('.jpg')][0]
        return t.extractfile(m).read()

def infer(b64, cache_prompt):
    payload = {
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": Q},
            ]},
        ],
        "temperature": 0.1, "max_tokens": 16,
        "cache_prompt": cache_prompt,
    }
    req = urllib.request.Request(f"http://{HOST}:{PORT}/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    return time.time() - t0, data['choices'][0]['message']['content']

def main():
    fb = frame_bytes()
    b64 = base64.b64encode(fb).decode()
    log = os.path.join(DATA, 'exp_static_nocache.log')
    c = get_client()
    run(c, 'pkill -f rk3588-vlm; pkill -f llama-server', timeout=30)
    run(c, f'LD_LIBRARY_PATH=/userdata/llama/bin /userdata/llama/bin/llama-server '
           f'-m /userdata/llama/models/{MODEL} --mmproj /userdata/llama/models/{MMPROJ} '
           f'--host 0.0.0.0 --port {PORT} -t 8 >/tmp/server.log 2>&1 &', timeout=30)
    for _ in range(20):
        code, out, err = run(c, f'curl -s -o /dev/null -w %{{http_code}} http://127.0.0.1:{PORT}/v1/models', timeout=15)
        if out.strip() == '200':
            break
        time.sleep(3)
    c.close()
    print(f"静态帧 {len(fb)}B @ 640×480, {ROUNDS} 轮, cache_prompt=false, temp=0.1")
    with open(log, 'w') as f:
        f.write(f"# static image no-cache test, {ROUNDS} rounds, frame {len(fb)}B\n")
        for i in range(ROUNDS):
            dt, out = infer(b64, False)
            line = f"[{i+1:03d}] {dt:.1f}s | {out!r}"
            print(line)
            f.write(line + '\n')
            f.flush()
    print(f"日志: {log}")
    c = get_client()
    run(c, 'pkill -f llama-server', timeout=30)
    c.close()

if __name__ == '__main__':
    main()
