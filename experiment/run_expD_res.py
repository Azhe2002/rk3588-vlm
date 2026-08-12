#!/usr/bin/env python3
"""实验 D 组措辞 @ 多分辨率: "Does the image contain..." 恢复是否普适
- 措辞: "Does the image contain a black industrial fan?" (实验5 D 组, 曾恢复 82%)
- 分辨率: 320×240 / 480×360 / 800×600 (对比实验1 突变区间 480→640)
- 模型: 256M (D 组原模型); --500 追加 500M
依赖: v0.2 板端二进制 (--temp 无涉, 用默认 0.1); board_exp_run.sh 已推送。
每组独立 exec (~3.2min), 逐组拉回日志。不做帧采样 (措辞/分辨率已覆盖)。
用法: python3 run_expD_res.py [--500]
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from board import get_client, run, sftp_get, sftp_put

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
RUNSH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'board_exp_run.sh')
EXEC_TIMEOUT = 280

Q_D = "Does the image contain a black industrial fan? Please answer only yes or no."
SECS = 180  # ~32 轮 @ 5.6s/轮

RES = [(320, 240), (480, 360), (800, 600)]

def main():
    models = ['SmolVLM-256M-Instruct-Q8_0.gguf']
    if '--500' in sys.argv:
        models.append('SmolVLM-500M-Instruct-Q8_0.gguf')
    c = get_client()
    run(c, 'pkill -f rk3588-vlm; pkill -f llama-server', timeout=30)
    sftp_put(c, RUNSH, '/tmp/board_exp_run.sh')
    run(c, 'chmod +x /tmp/board_exp_run.sh', timeout=30)
    results = []
    for model in models:
        short = model.split('-')[1].rstrip('M')
        for w, h in RES:
            tag = f"expD_{short}_{w}x{h}"
            log = f"/tmp/{tag}.log"
            cmd = (f'bash /tmp/board_exp_run.sh {model} mmproj-{model} '
                   f'{w} {h} {SECS} "{Q_D}" {log} 0')
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
