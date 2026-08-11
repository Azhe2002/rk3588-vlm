#!/usr/bin/env python3
"""解析 rk3588-vlm 实验日志, 输出每组统计表 (严格遵循/语义/输出类型/耗时)
用法: python3 analyze.py [log...]  (默认解析 data/exp_*.log + data/exp1_*.log)
"""
import re, sys, os, json, glob

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

ROUND_RE   = re.compile(r'─── \[(\d+)\] ─')
RAW_RE     = re.compile(r'原始输出: "(.*)"')
RESULT_RE  = re.compile(r'结果: (YES|NO|无法识别)\s*\((-?\d)\)')
LAT_RE     = re.compile(r'耗时: ([\d.]+)s')
END_RE     = re.compile(r'共运行 [\d.]+s, 推理 (\d+) 次')

def classify(raw):
    """输出类型: 'word' (yes/no 单词) / 'sentence' (完整句子) / 'other'"""
    t = raw.strip().rstrip('.').lower()
    if t in ('yes', 'no'):
        return 'word'
    if len(raw.split()) >= 3:
        return 'sentence'
    return 'other'

def semantic(raw):
    """语义判定: 'yes' / 'no' / 'unknown'"""
    t = raw.strip().rstrip('.').lower()
    if t == 'yes': return 'yes'
    if t == 'no': return 'no'
    # 否定式句子
    if re.search(r'no (black )?industrial fan|no fan|not (a|visible|present)|there is no|there isn|does not|cannot see|can.t see', t):
        return 'no'
    # 肯定式: yes 词 / there is / 描述性断言 (提到目标物体即视为肯定)
    if re.search(r'\byes\b|there is|there are|with a black industrial fan|a black industrial fan|the black industrial fan|contains?', t):
        return 'yes'
    return 'unknown'

def parse_log(path):
    rounds = []
    cur = None
    for line in open(path, encoding='utf-8', errors='replace'):
        m = ROUND_RE.search(line)
        if m:
            cur = {'round': int(m.group(1))}
            rounds.append(cur)
            continue
        if cur is None: continue
        m = RAW_RE.search(line)
        if m:
            cur['raw'] = m.group(1)
            cur['type'] = classify(m.group(1))
            cur['sem'] = semantic(m.group(1))
            continue
        m = RESULT_RE.search(line)
        if m:
            cur['strict'] = 1 if m.group(1) == 'YES' else 0
            continue
        m = LAT_RE.search(line)
        if m:
            cur['lat'] = float(m.group(1))
    return rounds

def stats(path):
    rounds = [r for r in parse_log(path) if 'raw' in r]
    n = len(rounds)
    if n == 0: return None
    strict = [r.get('strict') for r in rounds if 'strict' in r]
    words = [r for r in rounds if r['type'] == 'word']
    sents = [r for r in rounds if r['type'] == 'sentence']
    sem_yes = sum(1 for r in rounds if r['sem'] == 'yes')
    sem_no  = sum(1 for r in rounds if r['sem'] == 'no')
    sem_un  = sum(1 for r in rounds if r['sem'] == 'unknown')
    lats = [r['lat'] for r in rounds if 'lat' in r]
    return {
        'rounds': n,
        'strict_yes_rate': f"{sum(strict)}/{len(strict)}" if strict else 'n/a',
        'word_rate': f"{len(words)}/{n}",
        'sentence_rate': f"{len(sents)}/{n}",
        'sem_yes/no/un': f"{sem_yes}/{sem_no}/{sem_un}",
        'lat_mean': f"{sum(lats)/len(lats):.1f}s" if lats else 'n/a',
    }

def main():
    files = sys.argv[1:]
    if not files:
        files = sorted(glob.glob(os.path.join(DATA, 'exp*.log')))
    print(f"{'文件':<24} {'轮次':>4} {'严格YES':>9} {'单词':>7} {'句子':>6} {'语义Y/N/U':>11} {'耗时':>7}")
    print('-' * 76)
    for f in files:
        s = stats(f)
        if not s:
            print(f"{os.path.basename(f):<24} 无数据"); continue
        print(f"{os.path.basename(f):<24} {s['rounds']:>4} {s['strict_yes_rate']:>9} "
              f"{s['word_rate']:>7} {s['sentence_rate']:>6} {s['sem_yes/no/un']:>11} {s['lat_mean']:>7}")

if __name__ == '__main__':
    main()
