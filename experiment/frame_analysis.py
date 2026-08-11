#!/usr/bin/env python3
"""帧特征分析: 从 data/*.tgz 提取帧, 计算亮度/模糊(Laplacian方差)/帧差/JPEG体积
按时间 bin 与轮次遵循率粗略对齐, 输出特征 vs 遵循率的关系
用法: python3 frame_analysis.py [tgz...]   (默认 data/exp1_*.tgz + exp5_A_*.tgz)
"""
import os, sys, io, tarfile, glob, re
import numpy as np
from PIL import Image, ImageFilter

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

def features_jpeg(data):
    """单帧特征: 亮度均值/方差, 灰度拉普拉斯方差(模糊度), JPEG 字节数"""
    img = Image.open(io.BytesIO(data)).convert('L')
    a = np.asarray(img, dtype=np.float32)
    la = np.asarray(img.filter(ImageFilter.FIND_EDGES), dtype=np.float32)
    lap_var = la.var()
    return {
        'mean': float(a.mean()),
        'std': float(a.std()),
        'lap_var': float(lap_var),
        'bytes': len(data),
    }

def load_group(path, want_arrays=False):
    """返回 (features列表, rounds合规序列); want_arrays=True 时附灰度帧数组"""
    # 轮次序列来自同名 .log
    log = os.path.join(DATA, os.path.basename(path).replace('.tgz', '.log'))
    rounds = []
    if os.path.exists(log):
        for line in open(log, encoding='utf-8', errors='replace'):
            m = re.search(r'结果: (YES|NO|无法识别)', line)
            if m: rounds.append(1 if m.group(1) == 'YES' else 0)
    feats = []
    arrays = [] if want_arrays else None
    with tarfile.open(path) as tf:
        names = sorted(n for n in tf.getnames() if n.endswith('.jpg'))
        for n in names:
            f = tf.extractfile(n)
            if not f: continue
            data = f.read()
            feats.append(features_jpeg(data))
            if want_arrays:
                arrays.append(np.asarray(Image.open(io.BytesIO(data)).convert('L'), dtype=np.float32))
    return feats, rounds, arrays

def main():
    files = sys.argv[1:] or sorted(glob.glob(os.path.join(DATA, 'exp1_*.tgz'))) + \
            sorted(glob.glob(os.path.join(DATA, 'exp5_A_*.tgz')))
    print(f"{'组':<22} {'帧数':>5} {'亮度':>7} {'亮std':>7} {'模糊LapVar':>10} {'JPEG字节':>8} {'轮次YES':>9} {'帧/轮':>5} {'帧间差':>7}")
    print('-' * 98)
    for path in files:
        feats, rounds, arrays = load_group(path, want_arrays=True)
        if not feats:
            print(f"{os.path.basename(path):<22} 无帧"); continue
        # 帧间平均绝对差 (场景稳定性)
        if len(arrays) > 1:
            diffs = [np.abs(arrays[i] - arrays[i-1]).mean()
                     for i in range(1, min(len(arrays), 60))]
            ifd = f"{np.mean(diffs):.2f}"
        else:
            ifd = 'n/a'
        # 时间 bin 对齐: 帧按每轮 ~3 帧粗略分桶
        frames_per_round = max(1, round(len(feats) / max(1, len(rounds))))
        n_bins = min(len(rounds), len(feats) // frames_per_round)
        if n_bins == 0:
            print(f"{os.path.basename(path):<22} 帧/轮次 数量异常"); continue
        means = np.array([f['mean'] for f in feats[:n_bins*frames_per_round]])
        lvs   = np.array([f['lap_var'] for f in feats[:n_bins*frames_per_round]])
        means = means.reshape(n_bins, frames_per_round).mean(axis=1)
        lvs   = lvs.reshape(n_bins, frames_per_round).mean(axis=1)
        r = np.array(rounds[:n_bins])
        if r.std() > 0 and lvs.std() > 0 and means.std() > 0:
            c_lap = np.corrcoef(r, lvs)[0,1]
            c_br  = np.corrcoef(r, means)[0,1]
            corr = f"lap:{c_lap:+.2f} br:{c_br:+.2f}"
        else:
            corr = 'n/a'
        print(f"{os.path.basename(path):<22} {len(feats):>5} "
              f"{np.mean([f['mean'] for f in feats]):>7.1f} "
              f"{np.mean([f['std'] for f in feats]):>7.1f} "
              f"{np.median([f['lap_var'] for f in feats]):>10.0f} "
              f"{int(np.mean([f['bytes'] for f in feats])):>8} "
              f"{sum(r)}/{len(r):<4} {frames_per_round:>5} {ifd:>7}  corr[{corr}]")

if __name__ == '__main__':
    main()
