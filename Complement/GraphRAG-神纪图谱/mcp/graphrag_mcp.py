# -*- coding: utf-8 -*-
"""GraphRAG MCP Server - 通用知识图谱问答接口

暴露工具:
- graphrag_query: 对已索引的文档库执行 GraphRAG 查询 (local/global/drift/basic)
- graphrag_list_projects: 列出可用的索引项目
- graphrag_get_context: 获取某个实体的图谱上下文 (邻居/关系/社区)

任何 OpenAI 兼容问答系统(Codex/Claude/Cursor等支持MCP的)都可以通过标准MCP协议调用。
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer

# ---------- 配置 ----------
# 默认项目根目录 (可通过环境变量 GRAPHRAG_PROJECT 覆盖)
# Portable layout: <archive>/project (resolved relative to this script by _resolve_project).
DEFAULT_PROJECT = r"..\\project"

server = MCPServer(
    name="graphrag",
    title="GraphRAG Knowledge Graph Query",
    description="Query an indexed GraphRAG knowledge graph. Supports local/global/drift/basic search over the documents.",
    version="1.0.0",
)


def _resolve_project(project: str | None) -> str:
    """Resolve project root; validate it has an output dir.

    Robust resolution order:
      1. explicit `project` argument
      2. $GRAPHRAG_PROJECT env var
      3. DEFAULT_PROJECT
      4. script-relative candidates (portable layout)
    Falls back gracefully so a mangled env value never breaks the server.
    """
    script_dir = Path(__file__).resolve().parent
    candidates: list[Path] = []
    if project:
        candidates.append(Path(project))
    if os.environ.get("GRAPHRAG_PROJECT"):
        candidates.append(Path(os.environ["GRAPHRAG_PROJECT"]))
    candidates.append(Path(DEFAULT_PROJECT))
    # portable layouts: <root>/project  or  <root>/GraphRAG-*/project  (script inside <root>/mcp)
    candidates.append(script_dir.parent / "project")
    candidates.append(script_dir.parent / "GraphRAG-\u795e\u7eaa\u56fe\u8c31" / "project")
    candidates.append(script_dir / "project")

    seen: list[str] = []
    for c in candidates:
        if not c or not str(c).strip():
            continue
        rp = c.resolve()
        seen.append(str(rp))
        if (rp / "output").exists():
            return str(rp)

    raise ValueError(
        "No GraphRAG project found. Pass project=... or set GRAPHRAG_PROJECT. "
        "Checked: " + "; ".join(seen)
    )


# ---------- 解经模式 (decode mode) ----------
# 把"密语/经文式"语料翻译成平白的概念语言，避免"念经式"复读。
# 通用设计：不绑定任何特定语料，任何隐喻/宗教/玄学文本都适用。
_DECODE_WRAPPER = (
    "（解经模式）请以解经者(exegete)身份回答下面的问题。对检索到的文本："
    "1) 用平白的概念语言翻译每一处密语/隐喻的寓意，不要复读原文字句；"
    "2) 区分哪些是字面叙事、哪些是象征义，并给出判断标准；"
    "3) 最后给出可直接操作的结论：这些内容对一个现代读者意味着什么，如何改变他的日常判断。"
    "请引用原文出处。问题：{question}"
)


def _apply_decode(question: str, decode: bool) -> str:
    """Wrap question with exegesis instruction when decode=True."""
    if not decode:
        return question
    return _DECODE_WRAPPER.format(question=question)


def _query_graph(project: str, question: str, method: str = "local", community_level: int = 2, decode: bool = False) -> dict:
    """Run graphrag query and return structured JSON."""
    import subprocess

    env = dict(os.environ)
    try:
        import certifi
        env["SSL_CERT_FILE"] = certifi.where()
        env["REQUESTS_CA_BUNDLE"] = certifi.where()
    except Exception:
        pass
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    # Locate graphrag CLI (prefer known location, then fall back)
    cli = r"G:\Python\Scripts\graphrag.exe"
    if not Path(cli).exists():
        cli = str(Path(sys.executable).parent / "Scripts" / "graphrag.exe")
    if not Path(cli).exists():
        cli = "graphrag"

    cmd = [cli, "query", "--root", project, "--method", method, _apply_decode(question, decode)]
    if method == "global":
        cmd += ["--community-level", str(community_level)]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=1800)
        answer = (res.stdout or res.stderr or "").strip()
        return {
            "ok": res.returncode == 0,
            "method": method,
            "question": question,
            "answer": answer,
            "returncode": res.returncode,
            "error": None if res.returncode == 0 else (res.stderr or res.stdout or "")[:1000],
        }
    except Exception as e:
        return {"ok": False, "method": method, "question": question, "answer": "", "error": str(e)}


@server.tool()
async def graphrag_query(question: str, method: str = "local", community_level: int = 2, decode: bool = False, project: str | None = None) -> str:
    """Query the indexed GraphRAG knowledge graph.

    Args:
        question: The question to ask (any language, e.g. "什么是爱", "what is enlightenment").
        method: Search strategy - 'local' (specific entities/relationships), 'global' (whole-corpus themes),
                'drift' (multi-hop complex), 'basic' (vector baseline). Default 'local'.
        community_level: For global search, Leiden hierarchy level (higher = smaller communities). Default 2.
        decode: If True, wrap the question with an exegesis instruction: translate encoded/metaphorical
                language into plain conceptual terms, separate literal vs symbolic, and give actionable
                conclusions (avoids 'chanting-style' answers). Works with any corpus. Default False.
        project: Optional project root. Defaults to GRAPHRAG_PROJECT env or the configured default.

    Returns:
        JSON string with {ok, method, question, answer, error}.
    """
    root = _resolve_project(project)
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _query_graph, root, question, method, community_level, decode)
    return json.dumps(result, ensure_ascii=False)


@server.tool()
async def graphrag_list_projects(project: str | None = None) -> str:
    """List indexed GraphRAG projects and their basic stats.

    Args:
        project: Optional; if provided, return stats for that single project.

    Returns:
        JSON string with project path, entity/relationship/community counts.
    """
    import pandas as pd

    root = _resolve_project(project)
    out = Path(root) / "output"
    stats = {"project": root, "exists": out.exists()}
    if out.exists():
        try:
            e = pd.read_parquet(out / "entities.parquet")
            r = pd.read_parquet(out / "relationships.parquet")
            c = pd.read_parquet(out / "communities.parquet")
            stats.update({
                "entities": int(len(e)),
                "relationships": int(len(r)),
                "communities": int(len(c)),
                "entity_types": e["type"].value_counts().to_dict() if "type" in e.columns else {},
            })
        except Exception as ex:
            stats["error"] = str(ex)
    return json.dumps(stats, ensure_ascii=False)


@server.tool()
async def graphrag_get_context(entity: str, project: str | None = None) -> str:
    """Get the graph context (neighbors, relationships, community) for a specific entity.

    Args:
        entity: The entity name to look up, e.g. "爱", "美姬", "弥赛亚".
        project: Optional project root.

    Returns:
        JSON string with entity info, neighbors and relationship descriptions.
    """
    import pandas as pd

    root = _resolve_project(project)
    out = Path(root) / "output"
    e = pd.read_parquet(out / "entities.parquet")
    r = pd.read_parquet(out / "relationships.parquet")

    # match by title (case-insensitive, exact then contains)
    titles = e["title"].astype(str)
    exact = titles.str.lower() == entity.lower()
    if exact.any():
        match = e[exact]
    else:
        match = e[titles.str.contains(entity, case=False, na=False)]
    if match.empty:
        return json.dumps({"ok": False, "entity": entity, "error": "entity not found"}, ensure_ascii=False)

    row = match.iloc[0]
    ename = row["title"]
    rels = r[(r["source"] == ename) | (r["target"] == ename)]
    neighbors = []
    for _, rel in rels.iterrows():
        other = rel["target"] if rel["source"] == ename else rel["source"]
        neighbors.append({
            "entity": other,
            "relationship": str(rel.get("description", "")),
            "weight": float(rel.get("weight", 0)) if "weight" in rel else None,
        })
    neighbors.sort(key=lambda x: x["weight"] or 0, reverse=True)
    return json.dumps({
        "ok": True,
        "entity": ename,
        "type": row.get("type", ""),
        "description": str(row.get("description", ""))[:500],
        "degree": int(row.get("degree", 0)) if "degree" in row else None,
        "top_neighbors": neighbors[:20],
        "total_neighbors": len(neighbors),
    }, ensure_ascii=False)


def main():
    # mcp 2.0: run() with transport='stdio' is a synchronous blocking call
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
