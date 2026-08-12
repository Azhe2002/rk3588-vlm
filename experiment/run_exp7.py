#!/usr/bin/env python3
"""实验7: 温度扫描 (H6) — 256M @ 640×480, temp ∈ {0.0, 0.1, 0.5, 1.0}
依赖: 板端 rk3588-vlm 为 v0.2 (含 --temp, 由用户编译推板); 本脚本每次运行
自动推送新版 board_exp_run.sh (支持 --temp/--gst-extra 传递) 到板端 /tmp。
每组独立 exec (280s 超时), 逐组拉回日志; 不做帧采样 (温度不改变输入帧)。
用法: python3 run_exp7.py [--dry] [--500]   # --500 追加 500M 温度组
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from board import get_client, run, sftp_get, sftp_put

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
RUNSH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'board_exp_run.sh')
EXEC_TIMEOUT = 280

Q = "Is there a black industrial fan in the center of the image? Please answer only yes or no."
SECS = 180  # ~32 轮 @ 5.6s/轮

TEMPS = [0.0, 0.1, 0.5, 1.0]

def main():
    dry = '--dry' in sys.argv
    models = ['SmolVLM-256M-Instruct-Q8_0.gguf']
    if '--500' in sys.argv:
        models.append('SmolVLM-500M-Instruct-Q8_0.gguf')
    c = get_client()
    run(c, 'pkill -f rk3588-vlm; pkill -f llama-server', timeout=30)
    sftp_put(c, RUNSH, '/tmp/board_exp_run.sh')
    run(c, 'chmod +x /tmp/board_exp_run.sh', timeout=30)
    results = []
    for model in models:
        short = model.split('-')[1].rstrip('M')  # 256M -> 256
        for temp in TEMPS:
            tag = f"exp7_{short}_640_t{str(temp).replace('.', 'p')}"
            log = f"/tmp/{tag}.log"
            cmd = (f'bash /tmp/board_exp_run.sh {model} '
                   f'mmproj-{model} 640 480 {SECS} "{Q}" {log} 0 {temp}')
            print(f"[{tag}] ...", flush=True)
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
            run(c, 'pkill -f rk3588-vlm; pkill -f llama-server', timeout=30)
    c.close()
    print("\n=== 汇总 ===")
    for r in results:
        print(r)

if __name__ == '__main__':
    main()
