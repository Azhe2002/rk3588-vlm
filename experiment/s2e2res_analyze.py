#!/usr/bin/env python3
"""S2-E2-RES 分析: image→text 固定下分辨率梯度 — format_word/语义/帧特征逐分辨率
用法: python3 s2e2res_analyze.py [gt] [tag]  (默认 gt=yes, tag=s2e2res)
"""
import json, os, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metrics import classify_format, classify_semantic

GT = sys.argv[1] if len(sys.argv) > 1 else 'yes'
TAG = sys.argv[2] if len(sys.argv) > 2 else 's2e2res'
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', TAG)

def frame_features(path):
    """帧特征: 亮度均值, 灰度Laplacian方差(清晰度), JPEG字节"""
    img = Image.open(path).convert('L')
    a = np.asarray(img, dtype=np.float32)
    edge = np.asarray(img.filter(__import__('PIL.ImageFilter', fromlist=['ImageFilter']).FIND_EDGES), dtype=np.float32)
    return float(a.mean()), float(edge.var()), os.path.getsize(path)

def main():
    rows = [json.loads(l) for l in open(os.path.join(DATA, 'rounds.jsonl'), encoding='utf-8')]
    fails = sum(1 for r in rows if r['http_status'] != 200)
    print(f"总请求: {len(rows)}, 失败: {fails}")
    from collections import defaultdict
    by_res = defaultdict(list)
    for r in rows:
        by_res[r['frame_id'].split('/')[0]].append(r)
    print(f"\n{'分辨率':<10} {'轮':>3} {'format_word':>11} {'语义Y/N/U':>11} {f'semOK(gt={GT})':>12} {'耗时':>6} {'亮度':>7} {'清晰度':>9} {'JPEG字节':>8}")
    print('-' * 95)
    for res in sorted(by_res, key=lambda x: int(x.split('x')[0])):
        rs = by_res[res]
        n = len(rs)
        fw = sum(1 for r in rs if r['raw_output'] and classify_format(r['raw_output']) in ('exact', 'word'))
        sy = sum(1 for r in rs if r['raw_output'] and classify_semantic(r['raw_output']) == 'yes')
        sn = sum(1 for r in rs if r['raw_output'] and classify_semantic(r['raw_output']) == 'no')
        su = n - sy - sn
        sc = sy if GT == 'yes' else sn
        lats = [r['latency_s'] for r in rs if r['latency_s']]
        # 帧特征
        d = os.path.join(DATA, TAG, 'frames', res)
        brights, sharps, sizes = [], [], []
        for fid in sorted(os.listdir(d))[:10]:
            b, s, sz = frame_features(os.path.join(d, fid))
            brights.append(b); sharps.append(s); sizes.append(sz)
        print(f"{res:<10} {n:>3} {fw:>4}/{n:<6} {sy}/{sn}/{su:<8} {sc:>5}/{n:<6} "
              f"{np.mean(lats):>5.1f}s {np.mean(brights):>7.1f} {np.mean(sharps):>9.0f} {int(np.mean(sizes)):>8}")
    # 输出样例
    print("\n各分辨率输出样例:")
    for res in sorted(by_res, key=lambda x: int(x.split('x')[0])):
        rs = by_res[res]
        outs = set(r['raw_output'] for r in rs if r['raw_output'])
        print(f"  {res:<10} {sorted(outs)}")

if __name__ == '__main__':
    main()
