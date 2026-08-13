#!/usr/bin/env python3
"""修正后的输出指标分类器 (2026-08-13)

口径 (与 Codex-preview.md 审稿意见一致):
- format_exact : 原始输出严格等于 "yes" 或 "no" (忽略大小写, 无句点)
- format_word  : 去首尾空白及允许的末尾标点 [.!] 后, 整条输出为单个 yes/no
- semantic_label: 输出语义 yes / no / unknown (不依赖真值)
- semantic_correct: semantic_label 与外部真值一致 (由调用方结合 ground_truth 计算)
- yes_rate     : semantic_label=yes 的比例 (不是准确率)

旧 analyze.py 的 strict_yes_rate 只统计程序判定 YES 的轮次 (合规的 "No."
被计为 0), 不再作为格式指标使用 — analyze.py 标记为 legacy。

测试: python3 metrics.py --test
"""
import re

# 整行锚定: 可选空白 + yes/no (任意大小写) + 可选末尾标点 + 可选空白
_WORD_RE = re.compile(r"^\s*(yes|no)[.!]?\s*$", re.IGNORECASE)
_EXACT_RE = re.compile(r"^\s*(yes|no)\s*$", re.IGNORECASE)

# 否定句式 (先判, 避免 "no fan" 被肯定关键词误吞)
_NEG_RE = re.compile(
    r"\bno (black )?(industrial )?fan\b|"
    r"\bthere is no\b|\bthere isn'?t\b|\bthere are no\b|"
    r"\bno fan is\b|\bnot (a |an )?(black )?(industrial )?fan\b|"
    r"\bno visible\b|\bnot visible\b|\bdoes not\b|\bdoesn'?t\b|"
    r"\bcannot see\b|\bcan'?t see\b|\bfan is not\b|\bis not\b|"
    r"\bfan is absent\b|\babsent\b|"
    r"^\s*no\b",
    re.IGNORECASE,
)
# 条件句 (无明确判定, 判 unknown)
_COND_RE = re.compile(r"^\s*if\b|\bif there is\b|\bwhether\b", re.IGNORECASE)
# yes/no 单词同时出现 (冲突输出, 判 unknown)
_CONFLICT_RE = re.compile(r"\byes\b.*\bno\b|\bno\b.*\byes\b", re.IGNORECASE)
# 肯定句式
_POS_RE = re.compile(
    r"^\s*yes\b|\byes,?\b|\bthere is (a |an )?\b|\bthere are\b|"
    r"\ba black industrial fan\b|\bthe black industrial fan\b|"
    r"\ban industrial fan\b|\bcontains?\b|\bshows?\b|\bdepicts?\b",
    re.IGNORECASE,
)


def classify_format(raw):
    """返回 'exact' / 'word' / 'noncompliant'"""
    if raw is None:
        return "noncompliant"
    t = raw.strip()
    if _EXACT_RE.match(t):
        return "exact"
    if _WORD_RE.match(t):
        return "word"
    return "noncompliant"


def classify_semantic(raw):
    """返回 'yes' / 'no' / 'unknown'"""
    if raw is None:
        return "unknown"
    t = raw.strip()
    # 单词输出直接判定
    if _WORD_RE.match(t):
        m = _WORD_RE.match(t)
        return "yes" if m.group(1).lower() == "yes" else "no"
    # 条件句 → unknown
    if _COND_RE.search(t):
        return "unknown"
    # yes/no 冲突 → unknown
    if _CONFLICT_RE.search(t):
        return "unknown"
    # 否定优先
    if _NEG_RE.search(t):
        return "no"
    if _POS_RE.search(t):
        return "yes"
    return "unknown"


def format_word_rate(rounds):
    """rounds: [raw_output, ...] → format_word 比例"""
    n = len(rounds)
    if n == 0:
        return None
    w = sum(1 for r in rounds if classify_format(r) in ("exact", "word"))
    return f"{w}/{n}"


def yes_rate(rounds):
    """semantic_label=yes 的比例 (不能称准确率)"""
    n = len(rounds)
    if n == 0:
        return None
    y = sum(1 for r in rounds if classify_semantic(r) == "yes")
    return f"{y}/{n}"


# ---- 测试用例 (来自 Codex-preview.md 最低测试表 + 历史日志实测句型) ----
_TEST_CASES = [
    # (raw, format, semantic)
    ("Yes.", "word", "yes"),
    ("No.", "word", "no"),
    ("yes", "exact", "yes"),
    ("NO", "exact", "no"),
    ("There is a fan.", "noncompliant", "yes"),
    ("No fan is visible.", "noncompliant", "no"),
    ("Yes, there is a fan.", "noncompliant", "yes"),
    ("If there is a fan, answer yes.", "noncompliant", "unknown"),
    ("yes no", "noncompliant", "unknown"),
    ("", "noncompliant", "unknown"),
    ("   ", "noncompliant", "unknown"),
    # 历史实测句型
    ("There is a black industrial fan in the center of the image.",
     "noncompliant", "yes"),
    ("A factory warehouse scene with a black industrial fan in the center.",
     "noncompliant", "yes"),
    ("A factory warehouse with a dim lighting scene and a black industrial fan in the center",
     "noncompliant", "yes"),
    ("An indoor shot of a factory warehouse with a black industrial fan in the center.",
     "noncompliant", "yes"),
    # 16-token 截断句 ("showing a black" 后无 fan 词), 与历史 800 组计数一致 → unknown
    ("A view of the factory warehouse from the center of the room, showing a black",
     "noncompliant", "unknown"),
    ("A black industrial fan is in the center of the image.", "noncompliant", "yes"),
    ("A black industrial fan sits on a table in a factory warehouse.",
     "noncompliant", "yes"),
    ("A black industrial fan is in the foreground of the image.",
     "noncompliant", "yes"),
    ("There is no black industrial fan in the image.", "noncompliant", "no"),
    ("No black industrial fan is visible in the image.", "noncompliant", "no"),
    ("The image does not contain a black industrial fan.", "noncompliant", "no"),
]


def run_tests():
    fails = 0
    for raw, want_fmt, want_sem in _TEST_CASES:
        got_fmt = classify_format(raw)
        got_sem = classify_semantic(raw)
        if got_fmt != want_fmt or got_sem != want_sem:
            fails += 1
            print(f"FAIL {raw!r}: fmt {got_fmt} != {want_fmt}, sem {got_sem} != {want_sem}")
    print(f"{len(_TEST_CASES) - fails}/{len(_TEST_CASES)} PASS")
    return fails


if __name__ == "__main__":
    import sys
    sys.exit(1 if run_tests() else 0)
