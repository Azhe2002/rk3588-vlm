#!/usr/bin/env python3
"""σ sham 对照: 解耦 GStreamer 管线效应 — videoconvert 双转换零模糊 vs 基线 vs σ1 参考
会话内对照 (同日同场景, 当前场景无风扇, gt=no):
  sham_base        无滤镜 (基线)
  sham_videoconvert videoconvert ! videoconvert (零模糊双转换, 只测管线插入)
  sham_sigma1       videoconvert ! gaussianblur sigma=1 ! videoconvert (σ=1 参考)
疑问: σ=1 的格式恢复 (67%→100%, 2026-08-12) 是模糊本身还是 videoconvert 插入?
若 sham_videoconvert ≈ sham_base (格式率无差异), 则管线插入无效应, 恢复归因于模糊。
依赖: 板端 rk3588-vlm v0.2 (含 --gst-extra)。256M@640, t=0.1 (与 σ 扫描一致)。
用法: python3 run_sham.py [--dry]
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from board import get_client, run, sftp_get, sftp_put

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
RUNSH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'board_exp_run.sh')
EXEC_TIMEOUT = 280

Q = "Is there a black industrial fan in the center of the image? Please answer only yes or no."
SECS = 180  # ~25 轮 @ 1s 间隔 + ~6s 推理
M256 = 'SmolVLM-256M-Instruct-Q8_0.gguf'
TEMP = '0.1'

GROUPS = [
    ('sham_base',          640, 480, ''),
    ('sham_videoconvert',  640, 480, 'videoconvert ! videoconvert'),
    ('sham_sigma1',        640, 480, 'videoconvert ! gaussianblur sigma=1 ! videoconvert'),
]

def main():
    dry = '--dry' in sys.argv
    c = get_client()
    run(c, 'pkill -f rk3588-vlm; pkill -f llama-server', timeout=30)
    sftp_put(c, RUNSH, '/tmp/board_exp_run.sh')
    run(c, 'chmod +x /tmp/board_exp_run.sh', timeout=30)
    for i, (tag, w, h, gst) in enumerate(GROUPS, 1):
        log = f"/tmp/{tag}.log"
        cmd = (f'bash /tmp/board_exp_run.sh {M256} mmproj-{M256} '
               f'{w} {h} {SECS} "{Q}" {log} 1 "{TEMP}" "{gst}"')
        print(f"[{i}/{len(GROUPS)}] {tag} ...", flush=True)
        if dry:
            print(f"  (dry) {cmd}", flush=True)
            continue
        t0 = time.time()
        try:
            code, out, err = run(c, cmd, timeout=EXEC_TIMEOUT)
            dt = time.time() - t0
            print(f"  exit={code} ({dt:.0f}s) {out.strip()[-140:]}", flush=True)
        except Exception as e:
            print(f"  FAILED: {e}", flush=True)
            continue
        sftp_get(c, log, os.path.join(DATA, f'{tag}.log'))
        # 帧采样 (若有)
        code, out, _ = run(c, f'ls /tmp/frames_{tag} 2>/dev/null | wc -l', timeout=30)
        nf = out.strip()
        if nf and nf != '0':
            run(c, f'cd /tmp && tar czf {tag}.tgz frames_{tag}', timeout=60)
            sftp_get(c, f'/tmp/{tag}.tgz', os.path.join(DATA, f'{tag}.tgz'))
        print(f"  拉回 data/{tag}.log, 帧数: {nf}", flush=True)
    run(c, 'pkill -f llama-server', timeout=30)
    c.close()
    print('DONE')

if __name__ == '__main__':
    main()
