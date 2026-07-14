"""数值与单位轻量校验（纯物理/数学计算，非业务规则）

本模块仅提供：
- 从字符串解析数值与单位
- 物理单位换算（dBm↔W、SI 前缀 G↔M↔k 等）
- 数值范围/容差区间比较

不包含任何参数映射、关键词命中、参数同义判定等业务规则——
参数提取/对齐/同义判定/偏离结论均由 LLM 完成。
"""
import math
import re
from typing import Optional, Tuple, Union

# SI 前缀倍率（纯物理换算）
_SI_PREFIXES = {
    "T": 1e12,
    "G": 1e9,
    "M": 1e6,
    "k": 1e3,
    "K": 1e3,
    "m": 1e-3,
    "u": 1e-6,
    "μ": 1e-6,
    "µ": 1e-6,
    "n": 1e-9,
    "p": 1e-12,
    "f": 1e-15,
}

# 数值匹配（含科学计数法与范围符号前缀，如 "≥100"、"100~200" 取首个数值）
_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")

# 比较符号前缀（解析单位时应剥离）
_PREFIX_SYMBOLS = set("≥≤><≈~≥≤")


def parse_numeric(value: Union[str, int, float, None]) -> Optional[Tuple[float, str]]:
    """从字符串/数值中提取数值与单位。

    例：
        '100 dBm'  -> (100.0, 'dBm')
        '≥50 kg'   -> (50.0, 'kg')
        '1.5GHz'   -> (1.5, 'GHz')
        100        -> (100.0, '')
        None       -> None
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (float(value), "")
    s = str(value).strip()
    if not s:
        return None
    m = _NUM_RE.search(s)
    if not m:
        return None
    try:
        num = float(m.group(0))
    except ValueError:
        return None
    unit = (s[: m.start()] + " " + s[m.end():]).strip()
    unit = " ".join(unit.split())
    # 剥离前缀比较符号（≥ ≤ > < ≈ ~）
    unit = unit.lstrip("".join(_PREFIX_SYMBOLS)).strip()
    return (num, unit)


def _split_si_prefix(unit: str) -> Tuple[float, str]:
    """拆解 SI 前缀，返回 (倍率, 基单位)。

    'GHz' -> (1e9, 'Hz')；'dBm' -> (1.0, 'dBm')；'' -> (1.0, '')
    """
    unit = (unit or "").strip()
    if not unit:
        return (1.0, "")
    prefix = unit[0]
    if prefix in _SI_PREFIXES and len(unit) > 1:
        return (_SI_PREFIXES[prefix], unit[1:])
    return (1.0, unit)


def convert_unit(value: float, from_unit: str, to_unit: str) -> Optional[float]:
    """单位换算：dBm↔W、SI 前缀（G↔M↔k 等）。

    仅做物理换算，无法换算返回 None。
    """
    fu = (from_unit or "").strip()
    tu = (to_unit or "").strip()
    if fu == tu:
        return float(value)

    # dBm <-> W：P(W) = 10^(P(dBm)/10) / 1000
    if fu.lower() == "dbm" and tu.lower() == "w":
        return 10 ** (value / 10.0) / 1000.0
    if fu.lower() == "w" and tu.lower() == "dbm":
        if value <= 0:
            return None
        return 10.0 * math.log10(value * 1000.0)

    # 同基单位的 SI 前缀换算：GHz -> MHz 等
    ff, fbase = _split_si_prefix(fu)
    tf, tbase = _split_si_prefix(tu)
    if fbase and tbase and fbase.lower() == tbase.lower():
        return value * ff / tf

    return None


def is_within_tolerance(tender_val: float, spec_val: float, tolerance_pct) -> bool:
    """容差判断：spec 落在 tender*(1±tolerance_pct/100) 内为通过。

    tolerance_pct 为 None 时按精确相等处理（含浮点容差）。
    """
    if tolerance_pct is None:
        return math.isclose(float(tender_val), float(spec_val), rel_tol=1e-9, abs_tol=1e-9)
    try:
        base = float(tender_val)
        spec = float(spec_val)
    except (TypeError, ValueError):
        return False
    tol = abs(float(tolerance_pct)) / 100.0
    if base == 0:
        return abs(spec) <= tol
    lo = base * (1 - tol)
    hi = base * (1 + tol)
    return lo <= spec <= hi


def compare_numeric(
    tender_val: Union[str, int, float, None],
    spec_val: Union[str, int, float, None],
    tolerance_pct: Optional[float] = None,
) -> str:
    """数值比较，返回 match / deviation / need_confirm。

    - 自动尝试单位换算；单位不可换算返回 need_confirm（交由 LLM 判定）
    - 任一侧无法解析为数值返回 need_confirm
    """
    tn = parse_numeric(tender_val)
    sn = parse_numeric(spec_val)
    if tn is None or sn is None:
        return "need_confirm"

    tv, tu = tn
    sv, su = sn

    # 单位不同时尝试换算到招标侧单位
    if tu != su:
        converted = convert_unit(sv, su, tu)
        if converted is None:
            return "need_confirm"
        sv = converted

    if is_within_tolerance(tv, sv, tolerance_pct):
        return "match"
    return "deviation"
