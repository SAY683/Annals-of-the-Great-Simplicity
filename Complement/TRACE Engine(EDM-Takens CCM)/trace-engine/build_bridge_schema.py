"""
TRACE Engine Bridge Parameter Schema Builder
=============================================
读取 presets.yaml 并与 Web 端桥接参数合并，输出统一的 JSON Schema。
供 trace-engine-web/server.js 在启动时调用，避免参数双写。

用法:
    python build_bridge_schema.py [skill_dir]

输出:
    JSON 对象，键为参数名，值为 {type, min, max, default, description}
"""
import json
import os
import re
import sys
from pathlib import Path


def parse_range(comment: str):
    """从注释中提取 {min-max} 范围。"""
    m = re.search(r'\{([\d.]+)\s*-\s*([\d.]+)\}', comment)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


def infer_type(value, min_val, max_val):
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, int) or (min_val is not None and min_val == int(min_val) and max_val is not None and max_val == int(max_val)):
        return 'integer'
    return 'number' if isinstance(value, (int, float)) else 'string'


def load_presets_yaml(path: Path) -> dict:
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding='utf-8'))
    except Exception:
        # 无 PyYAML 时做极简 YAML 解析（仅支持 key: value 单层）
        data = {}
        current_section = None
        for line in path.read_text(encoding='utf-8').splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            if stripped.endswith(':') and not '=' in stripped:
                current_section = stripped[:-1]
                data[current_section] = {}
                continue
            if ':' in stripped and current_section is not None:
                key, val = stripped.split(':', 1)
                key = key.strip()
                val = val.split('#')[0].strip()
                if val.lower() in ('true', 'false'):
                    parsed = val.lower() == 'true'
                elif val.lower() in ('null', '~'):
                    parsed = None
                elif val.startswith('"') and val.endswith('"'):
                    parsed = val[1:-1]
                else:
                    try:
                        parsed = int(val)
                    except ValueError:
                        try:
                            parsed = float(val)
                        except ValueError:
                            parsed = val
                data[current_section][key] = parsed
        return data


def build_schema(skill_dir: Path) -> dict:
    presets_path = skill_dir / 'presets.yaml'
    presets = load_presets_yaml(presets_path) if presets_path.exists() else {}

    schema = {}

    # 1. 从 presets.yaml trace2dowhy 段提取参数
    for key, value in presets.get('trace2dowhy', {}).items():
        # 读取原始行以获取范围注释
        min_val, max_val = None, None
        if presets_path.exists():
            for line in presets_path.read_text(encoding='utf-8').splitlines():
                if line.strip().startswith(f'{key}:'):
                    min_val, max_val = parse_range(line)
                    break
        param_type = infer_type(value, min_val, max_val)
        schema[key] = {
            'type': param_type,
            'min': min_val if min_val is not None else (0 if param_type in ('integer', 'number') else None),
            'max': max_val if max_val is not None else (1000 if param_type in ('integer', 'number') else None),
            'default': value,
            'description': f'presets.yaml trace2dowhy.{key}',
        }

    # 2. Web/桥接层特有参数（不在 presets.yaml 中）
    web_specific = {
        'window_size': {'type': 'integer', 'min': 2, 'max': 128, 'default': 8, 'description': '滑动窗口大小'},
        'max_concepts': {'type': 'integer', 'min': 1, 'max': 128, 'default': 12, 'description': '最大概念数'},
        'min_valid_tokens': {'type': 'integer', 'min': 1, 'max': 10000, 'default': 10, 'description': '最小有效 token 数'},
        'min_concepts': {'type': 'integer', 'min': 2, 'max': 128, 'default': 3, 'description': '最小概念数'},
    }
    for key, meta in web_specific.items():
        schema[key] = meta

    return schema


def main():
    skill_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / 'examples' / 'counterfactual_hybrid'
    schema = build_schema(Path(skill_dir))
    print(json.dumps(schema, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
