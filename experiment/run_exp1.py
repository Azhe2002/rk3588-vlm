#!/usr/bin/env python3
"""实验1: 分辨率梯度 — 4 分辨率 (160x120/480x360/800x600/1280x960) × 2 模型
每组独立 exec (280s 超时), 超时/失败则清理后继续下一组, 逐组拉回日志+帧采样
用法: python3 run_exp1.py [--dry]
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from board import get_client, run, sftp_get

Q = "Is there a black industrial fan in the center of the image? Please answer only yes or no."
SECS = 180  # 每组运行秒数 (~27 轮 @ 6.5s/轮)
EXEC_TIMEOUT = 280
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

GROUPS = [
    ('SmolVLM-256M-Instruct-Q8_0.gguf', 'mmproj-SmolVLM-256M-Instruct-Q8_0.gguf', 160, 120),
    ('SmolVLM-256M-Instruct-Q8_0.gguf', 'mmproj-SmolVLM-256M-Instruct-Q8_0.gguf', 480, 360),
    ('SmolVLM-256M-Instruct-Q8_0.gguf', 'mmproj-SmolVLM-256M-Instruct-Q8_0.gguf', 800, 600),
    ('SmolVLM-256M-Instruct-Q8_0.gguf', 'mmproj-SmolVLM-256M-Instruct-Q8_0.gguf', 1280, 960),
    ('SmolVLM-500M-Instruct-Q8_0.gguf', 'mmproj-SmolVLM-500M-Instruct-Q8_0.gguf', 160, 120),
    ('SmolVLM-500M-Instruct-Q8_0.gguf', 'mmproj-SmolVLM-500M-Instruct-Q8_0.gguf', 480, 360),
    ('SmolVLM-500M-Instruct-Q8_0.gguf', 'mmproj-SmolVLM-500M-Instruct-Q8_0.gguf', 800, 600),
    ('SmolVLM-500M-Instruct-Q8_0.gguf', 'mmproj-SmolVLM-500M-Instruct-Q8_0.gguf', 1280, 960),
]

def tag_of(model, w, h):
    short = model.split('-')[1].rstrip('M')  # 256M -> 256
    return f"exp1_{short}_{w}x{h}"

def main():
    dry = '--dry' in sys.argv
    c = get_client()
    results = []
    for i, (model, mmproj, w, h) in enumerate(GROUPS, 1):
        tag = tag_of(model, w, h)
        log = f"/tmp/{tag}.log"
        cmd = f'bash /tmp/board_exp_run.sh {model} {mmproj} {w} {h} {SECS} "{Q}" {log} 1'
        print(f"[{i}/8] {tag} ...", flush=True)
        t0 = time.time()
        try:
            code, out, err = run(c, cmd, timeout=EXEC_TIMEOUT)
            dt = time.time() - t0
            print(f"  exit={code} ({dt:.0f}s) {out.strip()[-140:]}", flush=True)
            results.append((tag, 'ok', code, dt))
        except Exception as e:
            dt = time.time() - t0
            print(f"  EXEC FAILED after {dt:.0f}s: {e}", flush=True)
            results.append((tag, 'exec_fail', -1, dt))
            run(c, 'pkill -f rk3588-vlm; pkill -f llama-server', timeout=30)
        # 拉回日志
        try:
            sftp_get(c, log, os.path.join(DATA, f"{tag}.log"))
            print(f"  pulled {tag}.log", flush=True)
        except Exception as e:
            print(f"  LOG PULL FAILED: {e}", flush=True)
        # 拉回帧采样 (tar)
        try:
            code, out, err = run(c, f'cd /tmp && tar czf {tag}.tgz frames_{tag} 2>/dev/null; ls -la {tag}.tgz', timeout=60)
            sftp_get(c, f'/tmp/{tag}.tgz', os.path.join(DATA, f'{tag}.tgz'))
            print(f"  pulled {tag}.tgz {out.strip()[-80:]}", flush=True)
        except Exception as e:
            print(f"  FRAMES PULL FAILED: {e}", flush=True)
        # 清理板端残留
        run(c, 'pkill -f rk3588-vlm; pkill -f llama-server', timeout=30)
    c.close()
    print("\n=== 汇总 ===")
    for r in results:
        print(r)

if __name__ == '__main__':
    main()
