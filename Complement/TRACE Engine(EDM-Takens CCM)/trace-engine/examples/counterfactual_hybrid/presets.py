"""
Counterfactual Sentai — 预设加载器
====================================
从 presets.yaml 加载参数预设，支持场景快捷方式。

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


def load_yaml_presets() -> dict:
    """加载 presets.yaml 原始字典"""
    import json
    yaml_path = Path(__file__).resolve().parent / "presets.yaml"

    # 简单的 YAML 解析（避免添加 PyYAML 依赖）
    # presets.yaml 的结构足够简单，可以用逐行解析
    try:
        import yaml
        with open(yaml_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except ImportError:
        # Fallback: 从 YAML 提取键值对（简单解析器）
        return _simple_yaml_parse(yaml_path)


def _simple_yaml_parse(path: Path) -> dict:
    """简易 YAML 解析器 — 仅支持本文件所需的嵌套格式"""
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

        # 弹出更深层级的栈
        while stack and stack[-1][1] >= indent:
            stack.pop()

        current_dict = stack[-1][0]

        if val.strip() == '':
            # 嵌套字典
            current_dict[key] = {}
            stack.append((current_dict[key], indent))
        elif val.strip().startswith('"') or val.strip().startswith("'"):
            # 字符串值
            current_dict[key] = val.strip().strip('"\'')
        elif val.strip() == 'null':
            current_dict[key] = None
        elif val.strip() in ('true', 'false'):
            current_dict[key] = val.strip() == 'true'
        else:
            # 数值
            try:
                if '.' in val:
                    current_dict[key] = float(val.split('#')[0].strip())
                else:
                    current_dict[key] = int(val.split('#')[0].strip())
            except ValueError:
                current_dict[key] = val.split('#')[0].strip()

    return result


def load_presets(preset: str = "standard") -> _DotDict:
    """
    加载参数预设。

    Parameters
    ----------
    preset : str
        预设名: "demo", "standard", "deep", "archival"
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
