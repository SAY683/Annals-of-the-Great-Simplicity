# -*- coding: utf-8 -*-
"""
reapply-graphrag-patches.py - Re-apply GraphRAG site-packages patches after an upgrade.

WHY: the patches live inside G:\\Python\\Lib\\site-packages\\graphrag\\ and pip
overwrites them on every upgrade. Run this once after `pip install --upgrade graphrag`.

IDEMPOTENT + ROBUST: each patch is gated by a marker (function/import/string).
  - marker already present  -> "already applied (skip)"
  - marker absent           -> apply the patch steps; if an anchor is missing
                               (graphrag version changed), it reports clearly.

Patches covered (docs/04 sections 5 & 10):
  A. community_reports_extractor.py   - JSON three-layer tolerance (fences / repair / json_repair)
  B. drift_search/primer.py           - drop response_format, parse JSON manually
  C. drift_search/search.py           - drop response_format_json_object from local sub-step
  D. context_builder/rate_relevancy.py- drop response_format_json_object (defensive)

Usage:  python reapply-graphrag-patches.py [--site-packages PATH]
"""
import argparse
import io
import os
import re
import sys

GRAPH = "graphrag"
DEFAULT_SP = r"G:\Python\Lib\site-packages"

def _auto_site_packages():
    """Detect site-packages from the running interpreter (works on any machine)."""
    try:
        import graphrag
        return os.path.dirname(os.path.dirname(os.path.abspath(graphrag.__file__)))
    except Exception:
        return None

HELPER = '''

def _extract_json(text: str) -> str:
    """Best-effort repair of a model JSON response.

    Handles markdown code fences, stray text around the JSON object,
    and trailing commas before closing brackets. Returns a string that
    can be fed to pydantic, or the original text if no JSON object is found.
    """
    if not text:
        return text
    text = text.strip()
    # 1) strip markdown code fences (```json ... ```)
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\\n".join(lines).strip()
    # 2) keep only the outermost JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    # 3) remove trailing commas before } or ] (a very common model slip)
    text = re.sub(r",\\s*([}\\]]])", r"\\1", text)
    return text
'''

PATCHES = []

# ---- A: community_reports_extractor.py ----
def _patch_a(sp):
    f = os.path.join(sp, GRAPH, "index", "operations", "summarize_communities", "community_reports_extractor.py")
    steps = [
        ("import logging\n", "import logging\nimport re\n"),
        ("logger = logging.getLogger(__name__)", "logger = logging.getLogger(__name__)" + HELPER),
        ('''            output = (
                CommunityReportResponse.model_validate_json(response.content)
                if response.content
                else None
            )''',
         '''            content = _extract_json(response.content) if response.content else None
            output = None
            if content:
                try:
                    output = CommunityReportResponse.model_validate_json(content)
                except Exception:
                    try:
                        import json_repair
                        repaired = json_repair.loads(content)
                        if isinstance(repaired, dict):
                            output = CommunityReportResponse.model_validate(repaired)
                    except Exception:
                        output = None'''),
    ]
    return f, "def _extract_json(", steps
PATCHES.append(("A community_reports_extractor", _patch_a))

# ---- B: drift primer.py ----
def _patch_b(sp):
    f = os.path.join(sp, GRAPH, "query", "structured_search", "drift_search", "primer.py")
    steps = [
        ("from graphrag.query.structured_search.base import SearchResult",
         "from graphrag.query.llm.text_utils import try_parse_json_object\nfrom graphrag.query.structured_search.base import SearchResult"),
        ('''        model_response: LLMCompletionResponse[
            PrimerResponse
        ] = await self.chat_model.completion_async(
            messages=prompt, response_format=PrimerResponse
        )  # type: ignore

        parsed_response = model_response.formatted_response.model_dump()  # type: ignore''',
         '''        model_response: LLMCompletionResponse[
            PrimerResponse
        ] = await self.chat_model.completion_async(
            messages=prompt
        )  # type: ignore

        _, parsed_json = try_parse_json_object(model_response.content, verbose=False)
        parsed_response = PrimerResponse.model_validate(parsed_json).model_dump()'''),
    ]
    return f, "try_parse_json_object(model_response.content", steps
PATCHES.append(("B drift primer", _patch_b))

# ---- C: drift search.py ----
def _patch_c(sp):
    f = os.path.join(sp, GRAPH, "query", "structured_search", "drift_search", "search.py")
    steps = [(
        '''            "max_completion_tokens": self.context_builder.config.local_search_llm_max_gen_completion_tokens,
            "response_format_json_object": True,
        }''',
        '''            "max_completion_tokens": self.context_builder.config.local_search_llm_max_gen_completion_tokens,
        }''')]
    return f, None, steps  # marker=None => "patched" means the bad string is GONE
PATCHES.append(("C drift search", _patch_c))

# ---- D: rate_relevancy.py ----
def _patch_d(sp):
    f = os.path.join(sp, GRAPH, "query", "context_builder", "rate_relevancy.py")
    steps = [(
        '''            model_response = await model.completion_async(
                messages=messages_builder.build(),
                response_format_json_object=True,
                **model_params,
            )''',
        '''            model_response = await model.completion_async(
                messages=messages_builder.build(),
                **model_params,
            )''')]
    return f, None, steps
PATCHES.append(("D rate_relevancy", _patch_d))


def apply_file(path, marker, steps):
    if not os.path.exists(path):
        return "MISSING FILE"
    with io.open(path, "r", encoding="utf-8") as f:
        src = f.read()
    if marker is not None:
        if marker in src:
            return "already applied (skip)"
    else:
        # marker=None: "patched" means the offending string is absent
        bad = "response_format_json_object"
        if bad not in src:
            return "already applied (skip)"
    orig = src
    applied = 0
    for old, new in steps:
        if old in src:
            if new in src:
                continue
            src = src.replace(old, new, 1)
            applied += 1
    if src == orig:
        return "NOT APPLIED (anchors missing - version changed?)"
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(src)
    return f"applied {applied} step(s)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-packages", default=None)
    args = ap.parse_args()
    sp = args.site_packages or _auto_site_packages() or DEFAULT_SP
    if not os.path.isdir(os.path.join(sp, GRAPH)):
        print(f"[ERROR] {GRAPH} not found under {sp}")
        sys.exit(1)
    print(f"GraphRAG site-packages: {sp}")
    ok = True
    for name, fn in PATCHES:
        path, marker, steps = fn(sp)
        rel = os.path.relpath(path, os.path.join(sp, GRAPH))
        status = apply_file(path, marker, steps)
        print(f"  [{name:<28}] {status:<45} {rel}")
        if status.startswith(("MISSING", "NOT APPLIED")):
            ok = False
    print("DONE" + ("" if ok else "  (manual check required)"))


if __name__ == "__main__":
    main()
