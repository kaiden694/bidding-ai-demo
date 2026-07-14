"""LLM 响应解析工具：统一 JSON 容错 + 英文→中文翻译映射

参考 lib-v0.2 ai_comparator.py 的 _parse_ai_response + _ensure_chinese_response：
- 多重 JSON 容错：去 <think> 思考标签、修复换行、中文冒号（：→:）、单引号（'→"）、补全括号、去尾逗号
- 英文→中文翻译映射表（可演进，TODO 存 ExpertMemory）
- 强制中文 system prompt 片段

设计原则：所有解析逻辑集中在此模块，各 service 调用统一接口
"""
import json
import re
from typing import Optional, Any


# 英文→中文翻译映射表（常见 LLM 输出）
# TODO: 后续迁移到 ExpertMemory 作为可演进知识资产
_EN_ZH_MAP = {
    "match": "一致",
    "deviation": "偏离",
    "missing": "缺失",
    "extra": "多余",
    "need_confirm": "待确认",
    "compliant": "合规",
    "non_compliant": "不合规",
    "high": "高",
    "medium": "中",
    "low": "低",
    "satisfied": "满足",
    "partially_satisfied": "部分满足",
    "not_satisfied": "不满足",
    "pass": "通过",
    "fail": "不通过",
    "yes": "是",
    "no": "否",
    "true": "是",
    "false": "否",
}

# 中文 system prompt 片段（强制中文输出）
FORCE_CHINESE_PROMPT = (
    "\n\n重要：你必须使用简体中文输出所有内容，包括判定结果、理由、证据引用。"
    "禁止使用英文输出判定结果（如 match/deviation 等），必须使用中文。"
)


def parse_llm_json(raw: str) -> Optional[dict | list]:
    """解析 LLM 返回的 JSON，多重容错

    步骤：
    1. 去除 <think> 思考标签
    2. 去除 markdown 代码块围栏（```json ... ```）
    3. 修复中文冒号（：→:）
    4. 修复单引号（'→"）
    5. 提取 JSON 主体（首个 { 到最后 }）
    6. 去尾逗号
    7. 尝试 json.loads

    返回 None 表示解析失败
    """
    if not raw:
        return None

    text = raw.strip()
    if not text:
        return None

    # 1. 去除 <think> 思考标签（DeepSeek/通义等推理模型输出）
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)

    # 2. 去除 markdown 代码块围栏
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()

    # 3. 修复中文冒号（仅在 JSON 上下文中）
    text = text.replace("：", ":")

    # 4. 修复单引号为双引号（仅在 JSON key/value 上下文中）
    # 注意：这里要小心，不能把 JSON 值中的单引号也替换掉
    # 简单方案：把 key 的单引号替换为双引号
    text = re.sub(r"'(\w+)'\s*:", r'"\1":', text)

    # 5. 提取 JSON 主体
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        # 尝试数组
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return None
    json_str = text[start: end + 1]

    # 6. 去尾逗号（trailing comma）
    json_str = re.sub(r",\s*}", "}", json_str)
    json_str = re.sub(r",\s*]", "]", json_str)

    # 7. 尝试解析
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        # 二次尝试：修复换行符
        try:
            json_str = json_str.replace("\n", "\\n")
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

        # 三次尝试：补全缺失的右括号
        try:
            open_braces = json_str.count("{") - json_str.count("}")
            open_brackets = json_str.count("[") - json_str.count("]")
            if open_braces > 0 or open_brackets > 0:
                patched = json_str + ("}" * open_braces) + ("]" * open_brackets)
                return json.loads(patched)
        except json.JSONDecodeError:
            pass

        return None


def parse_llm_json_field(raw: str, field: str, default: Any = None) -> Any:
    """解析 LLM JSON 并提取指定字段

    用法：results = parse_llm_json_field(raw, "results", default=[])
    """
    data = parse_llm_json(raw)
    if data is None:
        return default
    if isinstance(data, dict):
        return data.get(field, default)
    return default


def ensure_chinese(text: str) -> str:
    """英文→中文翻译映射

    将 LLM 偶发英文输出翻译为中文。
    翻译映射表后续迁移到 ExpertMemory 作为可演进知识资产。
    """
    if not text:
        return text
    result = text
    for en, zh in _EN_ZH_MAP.items():
        # 全词匹配，避免误替换
        result = re.sub(rf"\b{re.escape(en)}\b", zh, result, flags=re.IGNORECASE)
    return result


def get_force_chinese_system_prompt() -> str:
    """获取强制中文 system prompt 片段

    用法：在 system prompt 末尾追加此片段
    system_prompt = "你是参数比对专家..." + get_force_chinese_system_prompt()
    """
    return FORCE_CHINESE_PROMPT
