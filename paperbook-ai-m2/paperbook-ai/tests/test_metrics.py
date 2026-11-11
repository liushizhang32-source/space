from eval import metrics


def test_normalize_strips_whitespace_only():
    assert metrics.normalize(" 小兔子\n跳 起 来。") == "小兔子跳起来。"
    assert metrics.normalize("") == ""
    assert metrics.normalize(None) == ""


def test_levenshtein_basic():
    assert metrics.levenshtein("", "") == 0
    assert metrics.levenshtein("abc", "abc") == 0
    assert metrics.levenshtein("", "abc") == 3
    assert metrics.levenshtein("abc", "") == 3
    assert metrics.levenshtein("kitten", "sitting") == 3
    assert metrics.levenshtein("小兔子", "小兔") == 1


def test_cer_and_accuracy():
    assert metrics.cer("小兔子", "小兔子") == 0.0
    assert metrics.cer("小兔子", "小兔") == 0.5
    assert metrics.cer("", "小兔") == 1.0
    assert metrics.cer("任意", "") is None
    assert metrics.char_accuracy("小兔子", "小兔子") == 1.0
    assert metrics.char_accuracy("小兔子", "小兔") == 0.5
    # 预测比真值长很多时，准确率截到 0，不出现负数
    assert metrics.char_accuracy("这是一个非常非常长的错误文本", "短") == 0.0


def test_cer_whitespace_insensitive():
    assert metrics.cer("小 兔 子", "小兔子") == 0.0
