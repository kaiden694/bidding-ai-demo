"""文本预处理工具（P3-15 T15.3）

参考 lib-v0.2 pgvector_store.py._semantic_expert_requirement_text：
- 招标/合同/技术规格文档中常见 "1 | 参数" / "2、 参数" / "3. 参数" / "(1) 参数" 等行号前缀
- 这些前缀污染语义向量化与关键词检索，应在切块入库前剥离

设计原则（v1.2 §13 AI 优先）：
- 仅做确定性的正则剥离，不做语义判断（剥离规则固定可重建）
- 剥离失败时返回原文（保守降级）
"""
import re

# 行号前缀正则模式（按优先级匹配）：
# 1. "1 | " 或 "1 | 2、 "（lib-v0.2 原版模式）
# 2. "1、 " 或 "1, " （中文顿号/英文逗号）
# 3. "1. " 或 "1）" （英文句号/中文右括号）
# 4. "(1) " 或 "（1）" （中英文括号编号）
# 5. "① " 等 Unicode 圈数字（匹配前缀数字符）
_LINE_NUMBER_PREFIX_PATTERN = re.compile(
    r"^\s*(?:"
    r"\d+\s*[\|｜]\s*(?:\d+\s*[、,]\s*)?"  # 1 | / 1 | 2、
    r"|\d+\s*[、,，]\s*"                   # 1、 / 1, / 1，
    r"|\d+\s*[.．]\s*"                     # 1. / 1．
    r"|\d+\s*[)）]\s*"                      # 1) / 1）
    r"|[（(]\s*\d+\s*[)）]\s*"             # (1) / （1）
    r"|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]\s*"      # Unicode 圈数字
    r")"
)


def strip_line_number_prefix(text: str) -> str:
    """剥离行号前缀（如 "1 | " / "2、 " / "3. " / "(1) " / "① "）

    用法：
        >>> strip_line_number_prefix("1 | 额定功率：≥ 100W")
        '额定功率：≥ 100W'
        >>> strip_line_number_prefix("2、 工作温度：-10~50℃")
        '工作温度：-10~50℃'
        >>> strip_line_number_prefix("正常文本无前缀")
        '正常文本无前缀'

    返回剥离前缀后的文本；若未匹配前缀则原样返回。
    """
    text_value = str(text or "").strip()
    if not text_value:
        return text_value
    stripped = _LINE_NUMBER_PREFIX_PATTERN.sub("", text_value, count=1).strip()
    return stripped or text_value


def semantic_requirement_text(value: str) -> str:
    """语义化需求文本：剥离行号前缀（lib-v0.2 兼容别名）

    用于：
    - 向量化前的文本清洗（ProductChunk / DocumentChunk 写入）
    - 检索 query 文本清洗
    - 保留原文用于显示，仅在向量化/检索时使用清洗后的版本
    """
    text_value = str(value or "").strip()
    semantic = strip_line_number_prefix(text_value)
    return semantic or text_value
