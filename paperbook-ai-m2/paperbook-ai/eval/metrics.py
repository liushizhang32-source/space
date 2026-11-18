"""OCR 评测指标：字符错误率（CER）。

CER = 编辑距离(预测, 真值) / 真值字数；1 - CER 即"字准确率"。
中文按字符算，标点算 1 个字，空白在归一化时去掉。
"""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """去掉所有空白，保留中英文与标点。"""
    return _WHITESPACE.sub("", text or "")


def levenshtein(a: str, b: str) -> int:
    """编辑距离（插入/删除/替换各算 1），滚动数组省内存。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,  # 删除
                    current[j - 1] + 1,  # 插入
                    previous[j - 1] + (char_a != char_b),  # 替换
                )
            )
        previous = current
    return previous[-1]


def cer(prediction: str, ground_truth: str) -> float | None:
    """真值为空时返回 None（无法计算）。"""
    truth = normalize(ground_truth)
    if not truth:
        return None
    return levenshtein(normalize(prediction), truth) / len(truth)


def char_accuracy(prediction: str, ground_truth: str) -> float | None:
    """1 - CER，下限截到 0（预测远长于真值时会出现负值）。"""
    value = cer(prediction, ground_truth)
    return None if value is None else max(0.0, 1.0 - value)
