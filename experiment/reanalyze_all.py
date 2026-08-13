#!/usr/bin/env python3
"""全量重算历史日志 (修正指标口径, 2026-08-13)

- 直接解析原始输出行 (旧 "结果:" 判定行来自有缺陷的 strict_yes_rate, 不再使用)
- 指标: format_exact / format_word / semantic yes-no-unknown / semantic_correct (gt 由外部给定)
- 输出: data/results_corrected.csv + 汇总表

用法: python3 reanalyze_all.py
"""
import re, os, csv, glob, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metrics import classify_format, classify_semantic

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

RAW_RE = re.compile(r'原始输出: "(.*)"')
LAT_RE = re.compile(r'耗时: ([\d.]+)s')
# banner 行
MODEL_RE  = re.compile(r'模型:\s+(\S+)')
RES_RE    = re.compile(r'分辨率:\s+(\d+)x(\d+)')
QUES_RE   = re.compile(r'问题:\s+(.*)')
TEMP_RE   = re.compile(r'温度:\s+([\d.]+)')
GST_RE    = re.compile(r'GStreamer 附加:\s+(.*)')
TOTAL_RE  = re.compile(r'共运行 [\d.]+s, 推理 (\d+) 次')

def question_tag(q):
    """问题措辞 → A/B/C/D/E/F/other"""
    if not q:
        return '?'
    if q.strip().startswith('Please answer only'):
        return 'E'
    if 'Example' in q:
        return 'F'
    if q.startswith('Does the image contain'):
        return 'D'
    if 'in the center of the image' in q or 'in the center of the picture' in q:
        return 'A'
    if 'Is there an industrial fan?' in q:
        return 'C'
    if 'in the image?' in q:
        return 'B'
    return '?'

def parse_log(path):
    out = {'file': os.path.basename(path), 'raws': [], 'lats': [],
           'model': None, 'w': None, 'h': None, 'question': None,
           'temp': None, 'gst': None, 'total_rounds': None}
    for line in open(path, encoding='utf-8', errors='replace'):
        m = RAW_RE.search(line)
        if m:
            out['raws'].append(m.group(1))
            continue
        m = LAT_RE.search(line)
        if m:
            out['lats'].append(float(m.group(1)))
            continue
        m = MODEL_RE.search(line)
        if m: out['model'] = m.group(1)
        m = RES_RE.search(line)
        if m: out['w'], out['h'] = int(m.group(1)), int(m.group(2))
        m = QUES_RE.search(line)
        if m: out['question'] = m.group(1).strip()
        m = TEMP_RE.search(line)
        if m: out['temp'] = float(m.group(1))
        m = GST_RE.search(line)
        if m: out['gst'] = m.group(1).strip()
        m = TOTAL_RE.search(line)
        if m: out['total_rounds'] = int(m.group(1))
    return out

def analyze_log(path, ground_truth):
    d = parse_log(path)
    raws = d['raws']
    n = len(raws)
    if n == 0:
        return None
    fe = sum(1 for r in raws if classify_format(r) == 'exact')
    fw = sum(1 for r in raws if classify_format(r) in ('exact', 'word'))
    sy = sum(1 for r in raws if classify_semantic(r) == 'yes')
    sn = sum(1 for r in raws if classify_semantic(r) == 'no')
    su = n - sy - sn
    sc = (sy if ground_truth == 'yes' else sn)
    lats = d['lats']
    return {
        'file': d['file'],
        'model': os.path.basename(d['model'] or ''),
        'resolution': f"{d['w']}x{d['h']}" if d['w'] else '?',
        'q_tag': question_tag(d['question']),
        'temp': d['temp'],
        'gst': d['gst'] or '',
        'rounds': n,
        'format_exact': fe,
        'format_word': fw,
        'sem_yes': sy, 'sem_no': sn, 'sem_unknown': su,
        'ground_truth': ground_truth,
        'sem_correct': sc,
        'lat_mean': round(sum(lats) / len(lats), 1) if lats else None,
    }

def main():
    # 所有历史日志均为正样本场景 (黑色工业风扇在画面中)
    files = sorted(glob.glob(os.path.join(DATA, '*.log')))
    rows = []
    for f in files:
        # 排除板端运行记录类日志 (非实验日志)
        if os.path.basename(f) in ('exp5_run_BG.log',):
            continue
        r = analyze_log(f, ground_truth='yes')
        if r:
            rows.append(r)
    # CSV
    with open(os.path.join(DATA, 'results_corrected.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    # 汇总表
    print(f"{'文件':<32} {'模型':<22} {'分辨率':>9} {'Q':<2} {'temp':>5} "
          f"{'轮':>3} {'format_word':>11} {'exact':>5} {'语义Y/N/U':>11} {'gt':>4} {'semOK':>6} {'耗时':>5}")
    print('-' * 130)
    for r in rows:
        gt = 'yes' if r['ground_truth'] == 'yes' else r['ground_truth']
        temp_s = str(r['temp']) if r['temp'] is not None else '-'
        print(f"{r['file']:<32} {r['model']:<22} {r['resolution']:>9} {r['q_tag']:>2} "
              f"{temp_s:>5} {r['rounds']:>3} "
              f"{r['format_word']:>4}/{r['rounds']:<6} {r['format_exact']:>5} "
              f"{r['sem_yes']}/{r['sem_no']}/{r['sem_unknown']:<8} {gt:>4} "
              f"{r['sem_correct']:>4}/{r['rounds']:<2} {r['lat_mean'] or '-':>5}")
    print(f"\n共 {len(rows)} 组 → data/results_corrected.csv")

if __name__ == '__main__':
    main()
