#!/usr/bin/env python3
"""S2-E1 分析: 图文顺序消融 — format_word 逐顺序 + 逐帧转移表 + McNemar
用法: python3 s2e1_analyze.py [tag] [gt]   (默认 tag=s2e1, gt=no)
"""
import json, os, sys
from math import comb
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metrics import classify_format, classify_semantic

TAG = sys.argv[1] if len(sys.argv) > 1 else 's2e1'
GT = sys.argv[2] if len(sys.argv) > 2 else 'no'
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', TAG)

def mcnemar_exact(b, c):
    """McNemar exact: 双尾二项检验 (n=b+c 次成功中 <= min(b,c) 的概率×2)"""
    n = b + c
    if n == 0:
        return 1.0
    m = min(b, c)
    p = sum(comb(n, k) for k in range(m + 1)) / 2**n
    return min(1.0, 2 * p)

def main():
    rows = [json.loads(l) for l in open(os.path.join(DATA, 'rounds.jsonl'), encoding='utf-8')]
    print(f"总请求: {len(rows)}, 失败: {sum(1 for r in rows if r['http_status'] != 200)}")
    # 逐帧配对
    by_frame = {}
    for r in rows:
        by_frame.setdefault(r['frame_id'], {})[r['order']] = r
    print(f"帧数: {len(by_frame)}")
    # 逐顺序统计 (真值由命令行 gt 给定)
    gt = GT
    print(f"\n{'顺序':<14} {'format_word':>12} {'语义Y/N/U':>11} {f'sem_correct(gt={gt})':>18} {'例':>36}")
    for order in ('text-image', 'image-text'):
        rs = [r for r in rows if r['order'] == order and r['raw_output']]
        fw = sum(1 for r in rs if classify_format(r['raw_output']) in ('exact', 'word'))
        sy = sum(1 for r in rs if classify_semantic(r['raw_output']) == 'yes')
        sn = sum(1 for r in rs if classify_semantic(r['raw_output']) == 'no')
        su = len(rs) - sy - sn
        sc = sn if gt == 'no' else sy
        sample = next((r['raw_output'] for r in rs if classify_format(r['raw_output']) == 'noncompliant'), '')
        print(f"{order:<14} {fw:>4}/{len(rs):<7} {sy}/{sn}/{su:<8} {sc:>5}/{len(rs):<11} {sample[:34]!r}")
    # 逐帧转移表 (text-image × image-text)
    print(f"\n{'帧':<10} {'text-image':>28} {'image-text':>28}")
    tt = {'ww': 0, 'ws': 0, 'sw': 0, 'ss': 0}
    for fid in sorted(by_frame):
        a = by_frame[fid].get('text-image', {})
        b = by_frame[fid].get('image-text', {})
        ra = a.get('raw_output') or 'FAIL'
        rb = b.get('raw_output') or 'FAIL'
        wa = classify_format(ra) in ('exact', 'word')
        wb = classify_format(rb) in ('exact', 'word')
        if wa and wb: tt['ww'] += 1
        elif wa and not wb: tt['ws'] += 1
        elif not wa and wb: tt['sw'] += 1
        else: tt['ss'] += 1
        print(f"{fid:<10} {ra[:26]:>28} {rb[:26]:>28}")
    print(f"\n转移表 (text-image 行 × image-text 列):")
    print(f"          image-text 单词   句子")
    print(f"text-image 单词:    {tt['ww']:>4}  {tt['ws']:>4}")
    print(f"text-image 句子:    {tt['sw']:>4}  {tt['ss']:>4}")
    # McNemar (不一致对: ws vs sw)
    b_, c_ = tt['ws'], tt['sw']
    print(f"\n不一致对: text-image单词/image-text句子 = {b_}, 反向 = {c_}")
    print(f"McNemar exact p = {mcnemar_exact(b_, c_):.2e}  (n={b_ + c_})")
    # 帧 sha 去重检查
    shas = set(r['sha256'] for r in rows)
    print(f"\n唯一帧 SHA: {len(shas)} (应为 {len(by_frame)})")
    # 语义正确率 (gt 由命令行给定)
    print(f"\n[真值 gt={GT}]")
    for order in ('text-image', 'image-text'):
        rs = [r for r in rows if r['order'] == order and r['raw_output']]
        sc = sum(1 for r in rs if classify_semantic(r['raw_output']) == GT)
        print(f"  {order:<14} semantic_correct = {sc}/{len(rs)} ({100*sc/len(rs):.0f}%)")

if __name__ == '__main__':
    main()
