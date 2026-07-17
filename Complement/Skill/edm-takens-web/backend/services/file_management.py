"""
Services — file management and variable selection (debt-19).

Extracted from api.py. Contains all file I/O helpers, CSV preparation,
variable selection, and pipeline-data mapping logic.
"""
import os
import re
import tempfile
import uuid
import shutil
from typing import List, Optional, Tuple

import pandas as pd
from fastapi import HTTPException

from core.locks import DATA_DIR, RESULTS_DIR, ARCHIVE_DIR, _PROJECT_ROOT
from _usability import is_usable_for_edm
from pipeline import PipelineConfig
from analysis_profiles import recommend_profile
from data_quality import evaluate_dataframe

# 保留别名以兼容现有调用点
_is_usable_for_edm = is_usable_for_edm


def _list_uploaded_csvs() -> List[str]:
    files = []
    if os.path.isdir(DATA_DIR):
        files = sorted([f for f in os.listdir(DATA_DIR) if f.lower().endswith(".csv")])
    return files


_ID_LIKE = {
    # English
    "game", "id", "index", "time", "date", "timestamp", "seq",
    "hour", "minute", "second", "month", "weekday", "day",
    # Chinese (common ID / time / sequence columns)
    "时序", "时间", "序号", "编号", "索引", "日期", "时刻",
}


def _is_id_like(col: str) -> bool:
    """Return True if a column name looks like an ID/time/sequence column."""
    low = col.lower()
    return low in _ID_LIKE or any(id_name in low for id_name in _ID_LIKE)


def _recommend_target(numeric_cols, df=None):
    """Recommend a meaningful target column, avoiding obvious IDs and binary columns.

    Prefers continuous numeric columns over low-cardinality indicators so wide
    tables of 0/1 features do not silently become the default target.
    """
    if not numeric_cols:
        return None
    for col in numeric_cols:
        if col.lower() == "result":
            return col

    def _is_reasonable_target(col):
        if _is_id_like(col):
            return False
        if df is not None and col in df.columns:
            if _is_usable_for_edm(df[col]):
                return True
        return False

    for col in numeric_cols:
        if _is_reasonable_target(col):
            return col
    return numeric_cols[0] if numeric_cols else None


def _read_csv_robust(csv_path: str) -> pd.DataFrame:
    """Read a CSV file, falling back to alternate encodings/separators."""
    for encoding in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
        for sep in (",", ";", "\t"):
            try:
                return pd.read_csv(csv_path, encoding=encoding, sep=sep)
            except Exception:
                continue
    raise HTTPException(status_code=400, detail="无法解析 CSV 文件：编码/分隔符不兼容")


def _prepare_dataset(filename: str) -> Tuple[str, pd.DataFrame, List[str]]:
    """Load a CSV from DATA_DIR and return (path, df, numeric_cols)."""
    csv_path = os.path.abspath(os.path.join(DATA_DIR, os.path.basename(filename)))
    if not csv_path.startswith(os.path.abspath(DATA_DIR) + os.sep) and csv_path != os.path.abspath(DATA_DIR):
        raise HTTPException(status_code=400, detail=f"Invalid filename: path traversal rejected")
    if not os.path.exists(csv_path):
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    df = _read_csv_robust(csv_path)
    numeric_cols = list(df.select_dtypes(include=["number"]).columns)
    if len(numeric_cols) < 2:
        raise HTTPException(
            status_code=400,
            detail="Need at least 2 numeric columns for EDM analysis",
        )
    return csv_path, df, numeric_cols


def _select_variables(
    df: pd.DataFrame,
    numeric_cols: List[str],
    target_col: Optional[str],
    variables: Optional[str],
) -> Tuple[str, List[str]]:
    recommended = _recommend_target(numeric_cols, df=df)
    if target_col is None or target_col not in numeric_cols:
        print(f"[API] target_col '{target_col}' invalid; falling back to '{recommended}'")
        target_col = recommended

    # Strictly usable candidates (enough variation / minority samples).
    usable_candidates = []
    # Fallback numeric candidates excluding obvious IDs.
    numeric_candidates = []
    for c in numeric_cols:
        if _is_id_like(c):
            continue
        numeric_candidates.append(c)
        if _is_usable_for_edm(df[c]):
            usable_candidates.append(c)

    selected_vars = None
    if variables:
        selected_vars = [v.strip() for v in variables.split(",") if v.strip() in numeric_cols]
        # Reject user-selected variables that are numerically unusable, but keep
        # the target so the mapping layer can still produce a valid pipeline CSV.
        selected_vars = [v for v in selected_vars if v == target_col or _is_usable_for_edm(df[v])]

    if not selected_vars:
        selected_vars = usable_candidates[:6]

    # Fallback: if filtering left us with too few columns, relax the usability
    # filter and just exclude ID-like columns.
    if len(selected_vars) < 2 and numeric_candidates:
        selected_vars = numeric_candidates[:6]

    if target_col not in selected_vars:
        selected_vars = [target_col] + [v for v in selected_vars if v != target_col]

    return target_col, selected_vars


def _check_target_quality(
    df: pd.DataFrame, target_col: str, selected_vars: List[str]
) -> Tuple[Optional[str], dict]:
    """Return a strong warning if the target column is not EDM-ready."""
    report = evaluate_dataframe(df, target_col, selected_vars)
    target_report = report.get(target_col, {})
    if target_report.get("usable_for_edm", True):
        return None, report
    warnings = target_report.get("warnings", [])
    warning_text = (
        f"Target column '{target_col}' is flagged as not usable for EDM. "
        "The analysis will still run, but interpret results with caution. "
        f"Issues: {'; '.join(warnings[:3])}"
    )
    return warning_text, report


def _prepare_pipeline_data(
    csv_path: str, target_col: str, selected_vars: List[str]
) -> Tuple[str, str, List[str], str, dict]:
    """Create a pipeline-compatible CSV with the game-log schema.

    The copied pipeline still contains hardcoded references to the game-log
    schema (target='result', plus kills/damage/deaths for CCM).  Rather than
    rewriting the entire algorithm, we transparently map the user's columns
    for computation and keep the original names for display.

    Returns:
        (temp_csv_path, pipeline_target, pipeline_vars, original_target,
         display_map)
    """
    original_target = target_col
    df = _read_csv_robust(csv_path)
    column_map: dict[str, str] = {}  # original -> pipeline alias

    schema_aliases = ["kills", "damage", "deaths"]

    def _stash_conflict(frame: pd.DataFrame, alias: str) -> pd.DataFrame:
        if alias in frame.columns:
            backup = f"_original_{alias}_"
            if backup in frame.columns:
                raise ValueError(
                    f"无法将列重映射到 '{alias}'：CSV 中已同时存在 '{alias}' "
                    f"和备份列 '{backup}'。请重命名其中一列后重新上传。")
            frame = frame.rename(columns={alias: backup})
        return frame

    # Map target -> result
    if target_col != "result":
        df = _stash_conflict(df, "result")
        df = df.rename(columns={target_col: "result"})
        column_map[target_col] = "result"

    # Map up to 3 non-target variables to kills/damage/deaths so the
    # cross-validation stage has its expected CCM candidates.
    other_vars = [v for v in selected_vars if v != target_col]
    for alias, orig in zip(schema_aliases, other_vars):
        if orig == alias:
            continue
        if orig not in df.columns:
            continue
        df = _stash_conflict(df, alias)
        df = df.rename(columns={orig: alias})
        column_map[orig] = alias

    display_map = {alias: orig for orig, alias in column_map.items()}

    if target_col == "result" and not column_map:
        return csv_path, target_col, selected_vars, original_target, display_map

    fd, temp_path = tempfile.mkstemp(suffix=".csv", prefix="edmtakens_")
    os.close(fd)
    df.to_csv(temp_path, index=False)

    pipeline_vars = [column_map.get(v, v) for v in selected_vars]
    # Ensure target stays first
    if pipeline_vars[0] != "result":
        pipeline_vars = ["result"] + [v for v in pipeline_vars if v != "result"]
    return temp_path, "result", pipeline_vars, original_target, display_map


def _make_config(csv_path, target_col, selected_vars, q, max_e, auto_fix):
    print(f"[API] target_col={target_col}, selected_vars={selected_vars}, q={q}, max_e={max_e}, auto_fix={auto_fix}")
    return PipelineConfig(
        data_path=csv_path,
        target_col=target_col,
        columns=selected_vars,
        q=q,
        max_E=max_e,
        auto_fix=auto_fix,
    )


def _resolve_analysis_params(
    df: pd.DataFrame,
    target_col: str,
    selected_vars: List[str],
    intensity: str,
    q: Optional[int],
    max_e: Optional[int],
):
    """Resolve q/max_e based on the requested intensity level.

    - ``auto``  : derive level from data characteristics.
    - ``light`` / ``medium`` / ``heavy`` : force that level.
    - User-provided q/max_e always take precedence over the recommendation.
    """
    intensity = (intensity or "medium").lower().strip()
    if intensity == "auto":
        profile = recommend_profile(df, target_col, selected_vars, user_q=q, user_max_e=max_e)
    elif intensity in ("light", "medium", "heavy"):
        profile = recommend_profile(
            df, target_col, selected_vars, level=intensity, user_q=q, user_max_e=max_e
        )
    else:
        profile = recommend_profile(
            df, target_col, selected_vars, level="medium", user_q=q, user_max_e=max_e
        )
    params = profile["params"]
    return params["q"], params["max_e"], profile


def _collect_images(task_id: Optional[str] = None) -> List[str]:
    """Collect image names from a task directory or the root results folder."""
    root = os.path.join(RESULTS_DIR, task_id) if task_id else RESULTS_DIR
    images = []
    if os.path.isdir(root):
        for fname in os.listdir(root):
            if fname.lower().endswith((".png", ".jpg", ".jpeg")):
                images.append(fname)
    images.sort(reverse=True)
    return images


def _safe_task_path(task_id: str, base_dir: str) -> Optional[str]:
    """Resolve a task_id under base_dir and prevent path traversal."""
    target = os.path.abspath(os.path.join(base_dir, task_id))
    root = os.path.abspath(base_dir)
    if not target.startswith(root + os.sep) and target != root:
        return None
    return target


def _zip_task(task_id: str) -> str:
    """Create or return the zip archive path for a task's results.

    The zip is written to ``archive/{task_id}.zip``.  If the task directory
    does not exist but the zip already does, the existing zip path is returned.
    """
    task_dir = _safe_task_path(task_id, RESULTS_DIR)
    zip_path = _safe_task_path(task_id + ".zip", ARCHIVE_DIR) or os.path.join(
        ARCHIVE_DIR, task_id + ".zip"
    )
    if task_dir and os.path.isdir(task_dir):
        base = os.path.join(ARCHIVE_DIR, task_id)
        zip_path = shutil.make_archive(base, "zip", task_dir)
    return zip_path


def _sanitize_project_name(name: Optional[str]) -> Optional[str]:
    """Sanitize a user-provided project name for use as a directory name.

    Keeps letters, digits, Chinese characters, underscores, hyphens and dots;
    strips leading dots/hyphens and limits length.
    """
    if not name:
        return None
    name = name.strip().replace(" ", "_")
    name = re.sub(r"[^\w\u4e00-\u9fff\-_.]", "", name)
    name = re.sub(r"^[._\-]+", "", name)
    name = name[:80]
    if not name:
        return None
    return name


def _move_results_to_task(
    start_time: float,
    preexisting_files: Optional[set] = None,
    project_name: Optional[str] = None,
) -> Tuple[str, List[str]]:
    """
    Move files generated during this analysis into a per-task subdirectory.

    The original pipeline writes fixed filenames like
    `results/enhanced_cross_validation.png`.  For the web system we need each
    request's outputs isolated so concurrent analyses and the browser cache do
    not collide.

    If ``project_name`` is provided, it is used as the directory base name;
    otherwise a random timestamp-based id is used.  Duplicate names are
    resolved by appending an incrementing suffix.

    NEW-3: ``preexisting_files`` 是分析开始前对 results/ 目录做的文件名
    快照，用于过滤掉其它历史/并发任务残留的产物，避免误迁移。调用方应在
    持有 ``_MOVE_LOCK`` 的前提下调用本函数，使"快照→迁移"成为原子临界区。
    """
    base = _sanitize_project_name(project_name) or f"{int(start_time)}_{uuid.uuid4().hex[:8]}"
    task_id = base
    task_dir = os.path.join(RESULTS_DIR, task_id)
    counter = 1
    while os.path.exists(task_dir):
        task_id = f"{base}_{counter}"
        task_dir = os.path.join(RESULTS_DIR, task_id)
        counter += 1
    os.makedirs(task_dir, exist_ok=True)

    # NEW-3: 快照过滤 — 只迁移本任务运行期间新增的文件，避免误移其它
    # 并发/历史任务的产物。preexisting_files 为分析开始前 results/ 中
    # 已存在的文件名集合。
    existing = preexisting_files or set()
    moved_images = []
    for fname in os.listdir(RESULTS_DIR):
        if fname in existing:
            continue
        fpath = os.path.join(RESULTS_DIR, fname)
        if not os.path.isfile(fpath):
            continue
        # 双重保险：mtime 过滤，确保文件确实在本任务运行期间被写入
        if os.path.getmtime(fpath) >= start_time - 1.0:
            dest = os.path.join(task_dir, fname)
            shutil.move(fpath, dest)
            if fname.lower().endswith((".png", ".jpg", ".jpeg")):
                moved_images.append(fname)

    return task_id, moved_images


def _total_size_mb(paths):
    """Return total size of files/directories in megabytes."""
    total = 0
    for path in paths:
        if os.path.isfile(path):
            total += os.path.getsize(path)
        elif os.path.isdir(path):
            for root, _, files in os.walk(path):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
    return total / (1024 * 1024)


# 上传文件大小上限：50MB（与典型 CSV 数据规模相称，避免内存/磁盘滥用）
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
# 用于判定二进制内容的头部探测字节数
_SNIFF_BYTES = 1024
