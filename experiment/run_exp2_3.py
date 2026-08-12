#!/usr/bin/env python3
"""实验2/3: GStreamer 滤镜变体 — 256M @ 640×480 主线, --gst-extra 滤镜链
实验2 (分辨率与有效像素解耦, 检验"显示分辨率 vs 细节量"):
  B  640×480 采集 → 输入前缩到 320×240   (细节↓, 显示分辨率不变)
  C  320×240 采集 → 放大到 640×480        (细节少, 显示分辨率放大)
  D  640×480 裁剪中心 320×240 区域        (FOV 收窄)
实验3 (H2 细节驱动检验, 消细节看格式遵循是否恢复):
  B1/B2/B3 高斯模糊 σ=3/7/15              (纹理消除, 分辨率不变)
  C  下采样 160×120 再上采样回 640×480    (去纹理)
  D  强噪声: 板端无 gst noise 元素, 跳过(如实报告局限)
依赖: 板端 rk3588-vlm 为 v0.2 (含 --gst-extra, 由用户编译推板); 本脚本每次
自动推送新版 board_exp_run.sh 到板端 /tmp。每组独立 exec, 逐组拉回日志。
用法: python3 run_exp2_3.py [--dry]
注意: 实验2 C 组按"320×240 采集 → 放大 640×480"实现 (--width 320 --height 240);
补丁 README 原表"宽高参数仍传 640 480"是另一种解读, 推板后先短跑验证采集是否成功。
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from board import get_client, run, sftp_get, sftp_put

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
RUNSH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'board_exp_run.sh')
EXEC_TIMEOUT = 280

Q = "Is there a black industrial fan in the center of the image? Please answer only yes or no."
SECS = 180  # ~32 轮 @ 5.6s/轮
M256 = 'SmolVLM-256M-Instruct-Q8_0.gguf'

# (tag, w, h, gst_extra)
GROUPS = [
    # 实验2: 分辨率与有效像素解耦
    ('exp2_B_scale320', 640, 480, 'videoscale ! video/x-raw,width=320,height=240'),
    ('exp2_C_upscale640', 320, 240, 'videoscale ! video/x-raw,width=640,height=480'),
    ('exp2_D_crop320', 640, 480, 'videocrop left=160 right=160 top=120 bottom=120'),
    # 实验3: 模糊/去纹理 (H2)
    ('exp3_B1_blur3', 640, 480, 'gaussianblur sigma=3'),
    ('exp3_B2_blur7', 640, 480, 'gaussianblur sigma=7'),
    ('exp3_B3_blur15', 640, 480, 'gaussianblur sigma=15'),
    ('exp3_C_tex160', 640, 480, 'videoscale ! video/x-raw,width=160,height=120 ! videoscale ! video/x-raw,width=640,height=480'),
]

def main():
    dry = '--dry' in sys.argv
    c = get_client()
    run(c, 'pkill -f rk3588-vlm; pkill -f llama-server', timeout=30)
    sftp_put(c, RUNSH, '/tmp/board_exp_run.sh')
    run(c, 'chmod +x /tmp/board_exp_run.sh', timeout=30)
    results = []
    for i, (tag, w, h, gst) in enumerate(GROUPS, 1):
        log = f"/tmp/{tag}.log"
        cmd = (f'bash /tmp/board_exp_run.sh {M256} mmproj-{M256} '
               f'{w} {h} {SECS} "{Q}" {log} 1 "{gst}"')
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
        # 拉回帧采样 (验证滤镜实际生效: 模糊组帧应明显更糊)
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
