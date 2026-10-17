#!/usr/bin/env python3
"""Generate docs/03-数据与索引.md from the actual parquet/graphml outputs.

Usage:
  python scripts/generate-data-doc.py
  python scripts/generate-data-doc.py --check
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import networkx as nx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "project" / "output"
DOC = ROOT / "docs" / "03-数据与索引.md"


def _load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def build_doc() -> str:
    e = pd.read_parquet(OUT / "entities.parquet")
    r = pd.read_parquet(OUT / "relationships.parquet")
    c = pd.read_parquet(OUT / "communities.parquet")
    cr = pd.read_parquet(OUT / "community_reports.parquet")
    t = pd.read_parquet(OUT / "text_units.parquet")
    d = pd.read_parquet(OUT / "documents.parquet")
    stats = _load_json(OUT / "stats.json", {})
    version = _load_json(OUT / "data_version.json", {})

    isolates = int((e["degree"].fillna(0) == 0).sum()) if "degree" in e.columns else 0
    related = len(e) - isolates
    ufffd_chars = int(t["text"].fillna("").str.count("\ufffd").sum()) if "text" in t.columns else 0
    ufffd_units = int(t["text"].fillna("").str.contains("\ufffd").sum()) if "text" in t.columns else 0

    graphml = OUT / "graph.graphml"
    if graphml.exists():
        g = nx.read_graphml(graphml)
        nodes, edges = g.number_of_nodes(), g.number_of_edges()
    else:
        nodes = edges = 0

    types = e["type"].value_counts().to_dict() if "type" in e.columns else {}
    type_rows = "\n".join(f"| {k} | {v:,} |" for k, v in types.items())
    report_summary = int(cr["summary"].notna().sum()) if "summary" in cr.columns else 0
    report_full = int(cr["full_content"].notna().sum()) if "full_content" in cr.columns else 0

    lines = [
        "# 03 · 数据与索引",
        "",
        "> 本页由 `scripts/generate-data-doc.py` 从 `project/output/*.parquet` 与 `graph.graphml` 自动生成。",
        "> 请勿手改数字；重建索引后重新运行脚本。",
        "",
        "## 1. 成品索引内容",
        "",
        "| 项目 | 数值 |",
        "|---|---:|",
        f"| 实体 | {len(e):,} |",
        f"| 有关联实体 | {related:,} |",
        f"| 孤立实体 | {isolates:,} |",
        f"| 关系 | {len(r):,} |",
        f"| 社区 | {len(c):,} |",
        f"| 社区报告 | {len(cr):,}（summary {report_summary:,} / full_content {report_full:,}） |",
        f"| 文本块 | {len(t):,} |",
        f"| 文档 | {len(d):,} |",
        f"| GraphML 节点 / 边 | {nodes:,} / {edges:,} |",
        f"| U+FFFD 字符 / 文本块 | {ufffd_chars:,} / {ufffd_units:,} |",
        "",
        "## 2. 实体类型分布（实测）",
        "",
        "| 类型 | 数量 |",
        "|---|---:|",
        type_rows,
        "",
        "## 3. 数据版本",
        "",
    ]
    if version:
        for key in ("generated_at", "build_date", "text_unit_hash", "entities", "relationships", "communities", "text_units"):
            if key in version:
                lines.append(f"- `{key}`: `{version[key]}`")
    else:
        lines.append("- `data_version.json` 尚未生成；运行 `scripts/repair-text-units.py` 或重建索引后生成。")
    lines += [
        "",
        "## 4. 数据质量说明",
        "",
        f"- 孤立实体：{isolates:,} / {len(e):,}（{isolates / max(len(e), 1):.1%}）。",
        f"- U+FFFD：{ufffd_chars:,} 个字符，分布在 {ufffd_units:,} 个文本块。",
        "- 实体别名未在 parquet 中物理合并；MCP 通过 `mcp/entity_aliases.json` 做查询期合并。",
        "- 类型字段可能存在少量抽取噪音；统计以 parquet 实际值为准。",
        "",
        "## 5. 构建统计",
        "",
    ]
    if stats:
        rt = stats.get("total_runtime")
        if isinstance(rt, (int, float)):
            lines.append(f"- `total_runtime`: {rt:.1f}s")
        wf = stats.get("workflows") or {}
        for name in ("extract_graph", "create_community_reports", "generate_text_embeddings"):
            if name in wf and isinstance(wf[name], dict):
                lines.append(f"- `{name}`: {wf[name].get('overall', 0):.1f}s")
    else:
        lines.append("- `stats.json` 不可用。")
    lines += [
        "",
        "## 6. 维护命令",
        "",
        "```powershell",
        "python scripts/generate-data-doc.py",
        "python scripts/repair-text-units.py --rebuild-vectors",
        "python scripts/verify-env.py --no-services",
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if the document differs from generated content")
    args = ap.parse_args()
    generated = build_doc()
    if args.check:
        current = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
        if current.strip() != generated.strip():
            print("docs/03-数据与索引.md is stale; run scripts/generate-data-doc.py")
            return 1
        print("docs/03-数据与索引.md is up to date")
        return 0
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text(generated, encoding="utf-8")
    print(f"wrote {DOC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())