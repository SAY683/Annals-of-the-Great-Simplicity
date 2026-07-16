"""
Counterfactual Sentai — 预设加载器
====================================
从 presets.yaml 加载参数预设，支持场景快捷方式。

YAML 解析策略 (debt-06):
    优先使用 PyYAML（``yaml.safe_load``，完整 YAML 规范支持），
    PyYAML 不可用时回退到内置手写解析器 ``_simple_yaml_parse``
    （仅支持 presets.yaml 所需的嵌套子集，零硬依赖兜底）。
    手写解析器保留不删除，确保在最小化环境也能运行。

用法:
    from presets import load_presets
    p = load_presets("standard")
    # p.trace2dowhy → dict of TRACE→DoWhy params
    # p.dowhy → dict of DoWhy params
    # p.counterfactual → dict of CF params
"""

from pathlib import Path
from typing import Optional


class _DotDict(dict):
    """支持点号访问的字典"""
    def __getattr__(self, key):
        if key in self:
            v = self[key]
            return _DotDict(v) if isinstance(v, dict) else v
        raise AttributeError(key)


def _is_pyyaml_available() -> bool:
    """探测 PyYAML 是否可用（debt-06: 显式探测，便于优先路径决策）。"""
    try:
        import yaml  # noqa: F401
        return True
    except ImportError:
        return False


def load_yaml_presets() -> dict:
    """加载 presets.yaml 原始字典。

    解析顺序 (debt-06):
      1. 优先: ``yaml.safe_load``（PyYAML 已安装时，完整 YAML 规范）
      2. 回退: ``_simple_yaml_parse``（手写解析器，仅支持本文件所需子集）

    两种路径返回同构 dict，调用方无需感知差异。
    """
    yaml_path = Path(__file__).resolve().parent / "presets.yaml"

    # 优先路径: PyYAML（完整 YAML 规范，支持注释/引用/多行字符串等）
    if _is_pyyaml_available():
        import yaml
        with open(yaml_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    # 回退路径: 手写解析器（PyYAML 未安装时的零依赖兜底）
    return _simple_yaml_parse(yaml_path)


def _simple_yaml_parse(path: Path) -> dict:
    """简易 YAML 解析器 — 仅支持本文件所需的嵌套格式。

    作为 PyYAML 不可用时的回退（debt-06），保留不删除。
    支持特性: 嵌套字典、字符串/数值/布尔/null 字面量、行内注释。
    不支持: 多行字符串、锚点/引用、流式语法等高级 YAML 特性。
    """
    import re
    result = {}
    stack = [(result, -1)]  # (dict, indent)

    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.strip().startswith('#'):
            continue

        indent = len(line) - len(line.lstrip())
        key_match = re.match(r'^(\w[\w_]*)\s*:\s*(.*)', line.strip())
        if not key_match:
            continue

        key, val = key_match.groups()

        # debt-06: 统一剥离行内注释（# ... 到行尾）。
        # presets.yaml 不含引号内 # 字符，简单 split 即可；
        # 此前仅数值分支剥离，导致字符串/布尔/嵌套字典误含注释文本。
        val = val.split('#')[0].strip()

        # 弹出更深层级的栈
        while stack and stack[-1][1] >= indent:
            stack.pop()

        current_dict = stack[-1][0]

        if val == '':
            # 嵌套字典
            current_dict[key] = {}
            stack.append((current_dict[key], indent))
        elif val.startswith('"') or val.startswith("'"):
            # 字符串值
            current_dict[key] = val.strip('"\'')
        elif val == 'null':
            current_dict[key] = None
        elif val in ('true', 'false'):
            current_dict[key] = val == 'true'
        else:
            # 数值
            try:
                if '.' in val:
                    current_dict[key] = float(val)
                else:
                    current_dict[key] = int(val)
            except ValueError:
                current_dict[key] = val

    return result


def load_presets(preset: str = "standard") -> _DotDict:
    """
    加载参数预设。

    Parameters
    ----------
    preset : str
        预设名: "demo", "standard", "deep", "archival", "llama"
        也可以直接使用顶层键名: "trace2dowhy", "dowhy", "counterfactual", "auditor"

    Returns
    -------
    _DotDict — 支持点号访问的参数对象
    """
    raw = load_yaml_presets()

    if preset in raw.get('presets', {}):
        # 预设场景: 用基础值覆盖预设值
        merged = {}
        for section in ['trace2dowhy', 'dowhy', 'counterfactual', 'auditor', 'visualization', 'super']:
            if section in raw:
                merged[section] = dict(raw[section])
                if section in raw['presets'][preset]:
                    merged[section].update(raw['presets'][preset][section])
        return _DotDict(merged)
    elif preset in raw:
        # 直接返回单个 section
        return _DotDict(raw[preset])
    else:
        return _DotDict(raw.get('presets', {}).get('standard', raw))
