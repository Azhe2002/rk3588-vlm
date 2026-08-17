#!/usr/bin/env python3
"""S2-E5 受限解码分析: text→image × {正/负} × {320/640} × {constrained/unconstrained}
8 格 × 20 帧, 同帧两约束配对。输出: 8 格表 (format_word/语义/semOK) + Fisher 关键对比。
用法: python3 s2e5_analyze.py [tag]
"""
import json, os, sys
from collections import defaultdict
from math import comb
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metrics import classify_format, classify_semantic

TAG = sys.argv[1] if len(sys.argv) > 1 else 's2e5'
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', TAG)
GT = {'pos': 'yes', 'neg': 'no'}  # 场景 → 真值

def fisher_exact_2s(table):
    """2×2 Fisher exact 双尾 p (无 scipy 依赖, math.comb 精确计算)"""
    (a, b), (c, d) = table
    r1, r2, c1 = a + b, c + d, a + c
    n = r1 + r2
    p_obs = comb(r1, a) * comb(r2, c1 - a) / comb(n, c1)
    p = 0.0
    lo, hi = max(0, c1 - r2), min(r1, c1)
    for x in range(lo, hi + 1):
        px = comb(r1, x) * comb(r2, c1 - x) / comb(n, c1)
        if px <= p_obs + 1e-15:
            p += px
    return min(1.0, p)

def mcnemar_2s(n_ab, n_ba):
    """exact two-sided McNemar: 不一致对 d=n_ab+n_ba, 小方向 k=min(n_ab,n_ba)"""
    d = n_ab + n_ba
    if d == 0:
        return None
    p = 0.5 ** d * sum(comb(d, x) for x in range(min(n_ab, n_ba) + 1))
    return min(1.0, 2 * p)

def main():
    rows = [json.loads(l) for l in open(os.path.join(DATA, 'rounds.jsonl'), encoding='utf-8')]
    fails = [r for r in rows if r['http_status'] != 200]
    cached = [r for r in rows if r.get('usage', {}).get('prompt_tokens_details', {}).get('cached_tokens', 0) > 0]
    print(f"总请求: {len(rows)}, 失败: {len(fails)}, 缓存命中>0: {len(cached)}")
    if fails:
        for f in fails[:5]:
            print('  FAIL:', f['frame_id'], f['constraint'], f.get('error'))
    if cached:
        print('  ⚠ 缓存未按预期关闭:', [r['frame_id'] for r in cached[:5]])

    by_cell = defaultdict(list)
    for r in rows:
        cell, _, _ = r['frame_id'].partition('/')
        by_cell[(cell, r['constraint'])].append(r)

    def cell_stats(rs):
        n = len(rs)
        fw = sum(1 for r in rs if r['raw_output'] and classify_format(r['raw_output']) in ('exact', 'word'))
        sy = sum(1 for r in rs if r['raw_output'] and classify_semantic(r['raw_output']) == 'yes')
        sn = sum(1 for r in rs if r['raw_output'] and classify_semantic(r['raw_output']) == 'no')
        su = n - sy - sn
        return n, fw, sy, sn, su

    print(f"\n{'场景':<5} {'分辨率':<4} {'约束':<14} {'轮':>3} {'format_word':>11} {'语义Y/N/U':>10} {'semOK':>7} {'样例(去重)'}")
    print('-' * 100)
    for scene in ('pos', 'neg'):
        for res in ('320', '640'):
            for cons in ('unconstrained', 'constrained'):
                rs = by_cell[(f'{scene}{res}', cons)]
                n, fw, sy, sn, su = cell_stats(rs)
                sc = sy if GT[scene] == 'yes' else sn
                outs = sorted(set(r['raw_output'] for r in rs if r['raw_output']))
                sample = '; '.join(repr(o)[:40] for o in outs[:4])
                print(f"{scene:<5} {res:<4} {cons:<14} {n:>3} {fw:>4}/{n:<6} "
                      f"{sy}/{sn}/{su:<8} {sc:>5}/{n:<6} {sample}")

    # 关键对比: 同帧配对 McNemar (constraint 前后), 跨格 Fisher
    print("\n--- 关键对比 (同帧配对 McNemar / 跨格 Fisher) ---")
    def bin_format(rs):
        return [1 if r['raw_output'] and classify_format(r['raw_output']) in ('exact', 'word') else 0 for r in rs]
    def bin_sem(rs):
        return [1 if r['raw_output'] and classify_semantic(r['raw_output']) == 'yes' else 0 for r in rs]

    for scene in ('pos', 'neg'):
        for res in ('320', '640'):
            cell = f'{scene}{res}'
            un, cn = by_cell[(cell, 'unconstrained')], by_cell[(cell, 'constrained')]
            un.sort(key=lambda r: r['frame_id']); cn.sort(key=lambda r: r['frame_id'])
            f_un, f_cn = bin_format(un), bin_format(cn)
            s_un, s_cn = bin_sem(un), bin_sem(cn)
            n_ab = sum(1 for a, b in zip(f_un, f_cn) if a and not b)
            n_ba = sum(1 for a, b in zip(f_un, f_cn) if not a and b)
            pf = mcnemar_2s(n_ab, n_ba)
            n_ab = sum(1 for a, b in zip(s_un, s_cn) if a and not b)
            n_ba = sum(1 for a, b in zip(s_un, s_cn) if not a and b)
            ps = mcnemar_2s(n_ab, n_ba)
            print(f"  {cell}: format un={sum(f_un)}/20 → con={sum(f_cn)}/20 "
                  f"(McNemar p={pf if pf is not None else 'ns'}), "
                  f"语义yes un={sum(s_un)}/20 → con={sum(s_cn)}/20 (p={ps if ps is not None else 'ns'})")

    # 部署关键指标: grammar 下 FPR (neg→Yes) / TPR (pos→Yes)
    print("\n--- 部署指标 (grammar constrained, text→image) ---")
    for res in ('320', '640'):
        neg = by_cell[(f'neg{res}', 'constrained')]
        pos = by_cell[(f'pos{res}', 'constrained')]
        fpr = sum(1 for r in neg if classify_semantic(r['raw_output']) == 'yes')
        tpr = sum(1 for r in pos if classify_semantic(r['raw_output']) == 'yes')
        print(f"  {res}: FPR(neg→Yes)={fpr}/20, TPR(pos→Yes)={tpr}/20")
    n320 = by_cell[('neg320', 'constrained')]
    n640 = by_cell[('neg640', 'constrained')]
    a = sum(1 for r in n640 if classify_semantic(r['raw_output']) == 'yes'); b = len(n640) - a
    c = sum(1 for r in n320 if classify_semantic(r['raw_output']) == 'yes'); d = len(n320) - c
    print(f"  FPR 640 vs 320 Fisher p={fisher_exact_2s([[a, b], [c, d]]):.4f}")

    # 与 S2-E1 (unconstrained 640 text→image) 复现核对
    print("\n--- 与 S2-E1 对照 (unconstrained, 640) ---")
    e1_path = os.path.join(DATA, '..', 's2e1', 'rounds.jsonl')
    e1p_path = os.path.join(DATA, '..', 's2e1pos', 'rounds.jsonl')
    for name, p, scene, gt in (('neg640', e1_path, 'neg', 'no'), ('pos640', e1p_path, 'pos', 'yes')):
        try:
            e1 = [json.loads(l) for l in open(p, encoding='utf-8')]
            e1 = [r for r in e1 if r['order'] == 'text-image']
            n, fw, sy, sn, su = cell_stats(e1)
            sc = sy if gt == 'yes' else sn
            cur = by_cell[(name, 'unconstrained')]
            n2, fw2, sy2, sn2, su2 = cell_stats(cur)
            sc2 = sy2 if gt == 'yes' else sn2
            print(f"  {name}: S2-E1 {fw}/{n} format, {sc}/{n} semOK (n={n}) | "
                  f"S2-E5 本次 {fw2}/{n2} format, {sc2}/{n2} semOK (n={n2})")
        except FileNotFoundError:
            pass

if __name__ == '__main__':
    main()
