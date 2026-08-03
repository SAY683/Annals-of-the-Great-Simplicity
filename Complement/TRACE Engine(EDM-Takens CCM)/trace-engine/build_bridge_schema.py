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
    if isinstance(value, int):
        return 'integer'
    if isinstance(value, float):
        return 'number'
    # 仅当值本身无法判断类型时，才用范围推断数值类型
    if min_val is not None and max_val is not None:
        if min_val == int(min_val) and max_val == int(max_val):
            return 'integer'
        return 'number'
    return 'string'


def load_presets_yaml(skill_dir: Path) -> dict:
    """加载 presets.yaml，优先使用 skill 目录下的 presets.py 解析器。"""
    presets_py = skill_dir / 'presets.py'
    if presets_py.exists():
        import sys
        skill_dir_str = str(skill_dir)
        if skill_dir_str not in sys.path:
            sys.path.insert(0, skill_dir_str)
        try:
            from presets import load_yaml_presets
            return load_yaml_presets()
        except Exception as e:
            # P2-F 修复 (ROUND27 12维度核对): 原 except: pass 完全静默吞错,
            # presets.yaml 解析失败时 schema 退化为空 dict, Web 端无法感知根因.
            print(f"[build_bridge_schema] presets.load_yaml_presets() 失败: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
    try:
        import yaml
        yaml_path = skill_dir / 'presets.yaml'
        return yaml.safe_load(yaml_path.read_text(encoding='utf-8'))
    except Exception as e:
        # P2-F 修复: 同上, 记录失败原因而非静默返回空 dict
        print(f"[build_bridge_schema] yaml.safe_load() 失败: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return {}


def _param_meta(key: str, value, comment_line: str = '') -> dict:
    """根据参数名和注释推断 schema 元数据。"""
    min_val, max_val = parse_range(comment_line)
    param_type = infer_type(value, min_val, max_val)

    defaults = {
        'threshold': {'min': 0, 'max': 10, 'description': '因果边显著性阈值（LLaMA V4 过拟合模型建议 0.01-0.03）'},
        'concept_min_freq': {'min': 1, 'max': 1000, 'description': '概念最小出现频次'},
        'max_edges_for_dowhy': {'min': 1, 'max': 100, 'description': '传入 DoWhy 的最大边数'},
        'filter_mode': {'description': '边过滤模式 (topn / percentile / adaptive)'},
        'filter_percentile': {'min': 50, 'max': 99, 'description': 'percentile 模式的百分位'},
        'random_state': {'min': 0, 'max': 999999, 'description': '随机种子'},
        'classical_mode': {'description': '古汉语模式（Shenji 古文保留之/乎/者/也等虚词）'},
    }
    meta = defaults.get(key, {})
    if param_type in ('integer', 'number'):
        if 'min' not in meta and min_val is not None:
            meta['min'] = min_val
        if 'max' not in meta and max_val is not None:
            meta['max'] = max_val
    return meta


def build_schema(skill_dir: Path, preset: str = None) -> dict:
    presets_path = skill_dir / 'presets.yaml'
    presets = load_presets_yaml(skill_dir)

    # 如果指定了 preset，用预设值覆盖基础 section
    base_trace = dict(presets.get('trace2dowhy', {}))
    base_super = dict(presets.get('super', {}))
    base_auditor = dict(presets.get('auditor', {}))
    if preset and preset in presets.get('presets', {}):
        selected = presets['presets'][preset]
        if 'trace2dowhy' in selected:
            base_trace.update(selected['trace2dowhy'])
        if 'super' in selected:
            base_super.update(selected['super'])
        if 'auditor' in selected:
            base_auditor.update(selected['auditor'])

    schema = {}

    # 1. 从 presets.yaml trace2dowhy 段提取参数
    comment_map = {}
    if presets_path.exists():
        for line in presets_path.read_text(encoding='utf-8').splitlines():
            stripped = line.strip()
            if ':' in stripped and not stripped.startswith('#'):
                key = stripped.split(':', 1)[0].strip()
                comment_map[key] = line

    for key, value in base_trace.items():
        meta = _param_meta(key, value, comment_map.get(key, ''))
        param_type = infer_type(value, meta.get('min'), meta.get('max'))
        schema[key] = {
            'type': param_type,
            'default': value,
            'description': meta.get('description', f'presets.yaml trace2dowhy.{key}'),
        }
        if 'min' in meta:
            schema[key]['min'] = meta['min']
        if 'max' in meta:
            schema[key]['max'] = meta['max']

    # 2. Web/桥接层特有参数（部分在 presets.yaml super 段中定义）
    web_specific = {
        'window_size': {'type': 'integer', 'min': 2, 'max': 256, 'default': base_super.get('window_size', 64), 'description': 'TRACE 滑动窗口大小'},
        'max_segments': {'type': 'integer', 'min': 1, 'max': 16, 'default': base_super.get('max_segments', 4), 'description': 'LLaMA TRACE 最大分段数'},
        'max_concepts': {'type': 'integer', 'min': 1, 'max': 128, 'default': 12, 'description': '最大概念数'},
        'min_valid_tokens': {'type': 'integer', 'min': 1, 'max': 10000, 'default': base_super.get('min_valid_tokens', 10), 'description': '最小有效 token 数'},
        'min_concepts': {'type': 'integer', 'min': 2, 'max': 128, 'default': 3, 'description': '最小概念数'},
    }
    for key, meta in web_specific.items():
        schema[key] = meta

    return schema


def build_presets_only(skill_dir: Path) -> dict:
    """仅输出 presets 段（debt-16 audit 修复：供 trace-engine-web loadPresets() 调用）。

    读取 presets.yaml 的 presets 段，将每个预设的 trace2dowhy+super+auditor
    扁平化为单一字典，与 bridge_schema.json 的 presets 段格式一致。
    """
    presets = load_presets_yaml(skill_dir)
    preset_section = presets.get('presets', {})
    base_trace = presets.get('trace2dowhy', {})
    base_super = presets.get('super', {})

    result = {}
    for name, preset_config in preset_section.items():
        merged = {}
        # 基础值
        merged.update(base_trace)
        merged.update(base_super)
        # 预设覆盖
        if 'trace2dowhy' in preset_config:
            merged.update(preset_config['trace2dowhy'])
        if 'super' in preset_config:
            merged.update(preset_config['super'])
        # Web 特有参数默认值
        merged.setdefault('max_concepts', 12)
        merged.setdefault('concept_min_freq', 2)
        merged.setdefault('min_valid_tokens', 10)
        merged.setdefault('max_edges_for_dowhy', 8)
        merged.setdefault('filter_mode', 'topn')
        merged.setdefault('filter_percentile', 85)
        merged.setdefault('random_state', 42)
        merged.setdefault('classical_mode', False)
        merged.setdefault('max_segments', 4)
        result[name] = merged
    return result


def main():
    args = sys.argv[1:]
    default_skill_dir = Path(__file__).resolve().parent / 'examples' / 'counterfactual_hybrid'
    # 支持两种调用方式：
    #   python build_bridge_schema.py [skill_dir] [--preset <name>]
    #   python build_bridge_schema.py [--preset <name>]
    if args and not args[0].startswith('--'):
        skill_dir = Path(args[0])
        args = args[1:]
    else:
        skill_dir = default_skill_dir
    preset = None
    if '--preset' in args:
        idx = args.index('--preset')
        if idx + 1 < len(args):
            preset = args[idx + 1]

    # debt-16 audit 修复：支持 --presets-only 参数，仅输出 presets 段
    if '--presets-only' in args:
        presets = build_presets_only(Path(skill_dir))
        print(json.dumps(presets, ensure_ascii=False, indent=2))
        return

    schema = build_schema(Path(skill_dir), preset=preset)
    print(json.dumps(schema, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
