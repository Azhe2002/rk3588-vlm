#!/usr/bin/env python3
"""实验5: 问题措辞变体 — @640x480, 256M (A 同期基线 + B/C/D/E/F 变体) + 补充 G (500M@320 延长)
每组独立 exec (280s 超时), 逐组拉回日志; 仅 A 组帧采样 (用于时间效应分析)
用法: python3 run_exp5.py [--dry]
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from board import get_client, run, sftp_get

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
EXEC_TIMEOUT = 280

SUFFIX = "Please answer only yes or no."
A = f"Is there a black industrial fan in the center of the image? {SUFFIX}"

GROUPS = [
    # (tag, model, mmproj, w, h, secs, question, sample)
    ('exp5_A_256_640_ctrl', 'SmolVLM-256M-Instruct-Q8_0.gguf', 'mmproj-SmolVLM-256M-Instruct-Q8_0.gguf',
     640, 480, 180, A, 1),
    ('exp5_B_256_640', 'SmolVLM-256M-Instruct-Q8_0.gguf', 'mmproj-SmolVLM-256M-Instruct-Q8_0.gguf',
     640, 480, 180, f"Is there a black industrial fan in the image? {SUFFIX}", 0),
    ('exp5_C_256_640', 'SmolVLM-256M-Instruct-Q8_0.gguf', 'mmproj-SmolVLM-256M-Instruct-Q8_0.gguf',
     640, 480, 180, f"Is there an industrial fan? {SUFFIX}", 0),
    ('exp5_D_256_640', 'SmolVLM-256M-Instruct-Q8_0.gguf', 'mmproj-SmolVLM-256M-Instruct-Q8_0.gguf',
     640, 480, 180, f"Does the image contain a black industrial fan? {SUFFIX}", 0),
    ('exp5_E_256_640', 'SmolVLM-256M-Instruct-Q8_0.gguf', 'mmproj-SmolVLM-256M-Instruct-Q8_0.gguf',
     640, 480, 180, f"{SUFFIX} Is there a black industrial fan in the center of the image?", 0),
    ('exp5_F_256_640', 'SmolVLM-256M-Instruct-Q8_0.gguf', 'mmproj-SmolVLM-256M-Instruct-Q8_0.gguf',
     640, 480, 180, f"Is there a black industrial fan in the center of the image? Example: Yes. {SUFFIX}", 0),
    ('exp5_G_500_320', 'SmolVLM-500M-Instruct-Q8_0.gguf', 'mmproj-SmolVLM-500M-Instruct-Q8_0.gguf',
     320, 240, 240, A, 0),
]

def main():
    dry = '--dry' in sys.argv
    c = get_client()
    results = []
    for i, (tag, model, mmproj, w, h, secs, q, sample) in enumerate(GROUPS, 1):
        log = f"/tmp/{tag}.log"
        cmd = f'bash /tmp/board_exp_run.sh {model} {mmproj} {w} {h} {secs} "{q}" {log} {sample}'
        print(f"[{i}/{len(GROUPS)}] {tag} ...", flush=True)
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
        try:
            sftp_get(c, log, os.path.join(DATA, f"{tag}.log"))
            print(f"  pulled {tag}.log", flush=True)
        except Exception as e:
            print(f"  LOG PULL FAILED: {e}", flush=True)
        if sample:
            try:
                code, out, err = run(c, f'cd /tmp && tar czf {tag}.tgz frames_{tag} 2>/dev/null; ls -la {tag}.tgz', timeout=60)
                sftp_get(c, f'/tmp/{tag}.tgz', os.path.join(DATA, f'{tag}.tgz'))
                print(f"  pulled {tag}.tgz {out.strip()[-80:]}", flush=True)
            except Exception as e:
                print(f"  FRAMES PULL FAILED: {e}", flush=True)
        run(c, 'pkill -f rk3588-vlm; pkill -f llama-server', timeout=30)
    c.close()
    print("\n=== 汇总 ===")
    for r in results:
        print(r)

if __name__ == '__main__':
    main()
