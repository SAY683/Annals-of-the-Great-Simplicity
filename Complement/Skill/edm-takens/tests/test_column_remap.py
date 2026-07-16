"""
Pipeline 列重映射冲突测试。

验证 _prepare_pipeline_data 在用户数据已包含 kills/damage/deaths/result 等
与 pipeline 内置 schema 别名冲突的列时，能正确将原始列备份到
_original_<alias>_ 而非被静默覆盖或丢失。

被测函数位于 edm-takens-web/backend/api.py，依赖 web 后端运行时
（fastapi 等）。若这些依赖不可用，测试自动跳过——本测试主要在 web
开发环境中通过 pytest 运行。
"""
import os
import sys
import tempfile

import pandas as pd
import pytest

# 让测试既能被 pytest 发现，也能被 edm-takens 的 run_tests.py 调用。
_SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WEB_BACKEND = os.path.abspath(
    os.path.join(_SKILL_ROOT, "..", "edm-takens-web", "backend")
)


def _import_prepare_pipeline_data():
    """延迟导入 _prepare_pipeline_data。

    缺失 web 后端依赖（fastapi）时通过 pytest.skip 跳过，
    而非抛出 ImportError 让整个测试模块失败。
    """
    pytest.importorskip("fastapi", reason="需要 web 后端依赖才能导入 api._prepare_pipeline_data")
    if _WEB_BACKEND not in sys.path:
        sys.path.insert(0, _WEB_BACKEND)
    from api import _prepare_pipeline_data
    return _prepare_pipeline_data


def test_result_alias_conflict_is_backed_up():
    """用户已有 result 列时，应备份到 _original_result_ 再映射目标。"""
    _prepare_pipeline_data = _import_prepare_pipeline_data()
    with tempfile.TemporaryDirectory() as tmpdir:
        # 用户数据：victory 是目标，但 CSV 中已有一列 result（与 schema 别名冲突）
        df = pd.DataFrame({
            "victory": [1.0, 0.0, 1.0, 1.0],
            "result": [99.0, 88.0, 77.0, 66.0],  # 冲突！
            "assists": [5.0, 3.0, 7.0, 2.0],
            "gold": [100.0, 80.0, 120.0, 90.0],
        })
        csv_path = os.path.join(tmpdir, "conflict_result.csv")
        df.to_csv(csv_path, index=False)

        temp_csv, pipeline_target, pipeline_vars, original_target, display_map = (
            _prepare_pipeline_data(csv_path, "victory", ["victory", "assists", "gold"])
        )
        try:
            out = pd.read_csv(temp_csv)
            # 原始 result 列应被备份
            assert "_original_result_" in out.columns, (
                "用户已有的 result 列未被备份到 _original_result_"
            )
            assert list(out["_original_result_"]) == [99.0, 88.0, 77.0, 66.0], (
                "_original_result_ 的值与原始用户数据不一致"
            )
            # pipeline 目标映射到 result，且包含 victory 的数据
            assert pipeline_target == "result"
            assert original_target == "victory"
            assert list(out["result"]) == [1.0, 0.0, 1.0, 1.0], (
                "result 列应包含 victory 的原始数据"
            )
        finally:
            if os.path.exists(temp_csv):
                os.remove(temp_csv)


def test_kills_alias_conflict_is_backed_up():
    """用户已有 kills 列（但未选为变量）时，映射其他变量到 kills 前应先备份。"""
    _prepare_pipeline_data = _import_prepare_pipeline_data()
    with tempfile.TemporaryDirectory() as tmpdir:
        # 用户数据：assists 要被映射到 kills 别名，但 CSV 中已有一列 kills
        df = pd.DataFrame({
            "victory": [1.0, 0.0, 1.0, 1.0],
            "assists": [5.0, 3.0, 7.0, 2.0],
            "kills": [10.0, 20.0, 30.0, 40.0],  # 冲突！
            "gold": [100.0, 80.0, 120.0, 90.0],
        })
        csv_path = os.path.join(tmpdir, "conflict_kills.csv")
        df.to_csv(csv_path, index=False)

        temp_csv, pipeline_target, pipeline_vars, original_target, display_map = (
            _prepare_pipeline_data(csv_path, "victory", ["victory", "assists", "gold"])
        )
        try:
            out = pd.read_csv(temp_csv)
            # 原始 kills 列应被备份到 _original_kills_
            assert "_original_kills_" in out.columns, (
                "用户已有的 kills 列未被备份到 _original_kills_"
            )
            assert list(out["_original_kills_"]) == [10.0, 20.0, 30.0, 40.0], (
                "_original_kills_ 的值与原始用户数据不一致"
            )
            # assists 被重映射到 kills 别名
            assert "kills" in pipeline_vars
            assert list(out["kills"]) == [5.0, 3.0, 7.0, 2.0], (
                "kills 列应包含 assists 的原始数据"
            )
            # display_map 方向为 {pipeline别名: 原始列名}，
            # 应能把 "kills" 别名映射回原始列名 "assists"
            assert display_map.get("kills") == "assists", (
                f"display_map 应将 kills 别名映射回 assists，实际: {display_map}"
            )
        finally:
            if os.path.exists(temp_csv):
                os.remove(temp_csv)


def test_damage_alias_conflict_is_backed_up():
    """用户已有 damage 列时，映射 gold→damage 前应先备份原始 damage 列。"""
    _prepare_pipeline_data = _import_prepare_pipeline_data()
    with tempfile.TemporaryDirectory() as tmpdir:
        # 用户数据：gold 要被映射到 damage 别名，但 CSV 中已有一列 damage
        df = pd.DataFrame({
            "victory": [1.0, 0.0, 1.0, 1.0],
            "assists": [5.0, 3.0, 7.0, 2.0],
            "gold": [100.0, 80.0, 120.0, 90.0],
            "damage": [500.0, 400.0, 600.0, 350.0],  # 冲突！
        })
        csv_path = os.path.join(tmpdir, "conflict_damage.csv")
        df.to_csv(csv_path, index=False)

        temp_csv, pipeline_target, pipeline_vars, original_target, display_map = (
            _prepare_pipeline_data(csv_path, "victory", ["victory", "assists", "gold"])
        )
        try:
            out = pd.read_csv(temp_csv)
            # 原始 damage 列应被备份到 _original_damage_
            assert "_original_damage_" in out.columns, (
                "用户已有的 damage 列未被备份到 _original_damage_"
            )
            assert list(out["_original_damage_"]) == [500.0, 400.0, 600.0, 350.0], (
                "_original_damage_ 的值与原始用户数据不一致"
            )
            # gold 被重映射到 damage 别名
            assert "damage" in pipeline_vars
            assert list(out["damage"]) == [100.0, 80.0, 120.0, 90.0], (
                "damage 列应包含 gold 的原始数据"
            )
            assert display_map.get("damage") == "gold", (
                f"display_map 应将 damage 别名映射回 gold，实际: {display_map}"
            )
        finally:
            if os.path.exists(temp_csv):
                os.remove(temp_csv)


def test_deaths_alias_conflict_is_backed_up():
    """用户已有 deaths 列时，映射第三个变量→deaths 前应先备份原始 deaths 列。"""
    _prepare_pipeline_data = _import_prepare_pipeline_data()
    with tempfile.TemporaryDirectory() as tmpdir:
        # 用户数据：wards 要被映射到 deaths 别名，但 CSV 中已有一列 deaths
        df = pd.DataFrame({
            "victory": [1.0, 0.0, 1.0, 1.0],
            "assists": [5.0, 3.0, 7.0, 2.0],
            "gold": [100.0, 80.0, 120.0, 90.0],
            "wards": [3.0, 2.0, 5.0, 1.0],
            "deaths": [2.0, 4.0, 1.0, 3.0],  # 冲突！
        })
        csv_path = os.path.join(tmpdir, "conflict_deaths.csv")
        df.to_csv(csv_path, index=False)

        temp_csv, pipeline_target, pipeline_vars, original_target, display_map = (
            _prepare_pipeline_data(
                csv_path, "victory", ["victory", "assists", "gold", "wards"]
            )
        )
        try:
            out = pd.read_csv(temp_csv)
            # 原始 deaths 列应被备份到 _original_deaths_
            assert "_original_deaths_" in out.columns, (
                "用户已有的 deaths 列未被备份到 _original_deaths_"
            )
            assert list(out["_original_deaths_"]) == [2.0, 4.0, 1.0, 3.0], (
                "_original_deaths_ 的值与原始用户数据不一致"
            )
            # wards 被重映射到 deaths 别名
            assert "deaths" in pipeline_vars
            assert list(out["deaths"]) == [3.0, 2.0, 5.0, 1.0], (
                "deaths 列应包含 wards 的原始数据"
            )
            assert display_map.get("deaths") == "wards", (
                f"display_map 应将 deaths 别名映射回 wards，实际: {display_map}"
            )
        finally:
            if os.path.exists(temp_csv):
                os.remove(temp_csv)


def test_no_conflict_passes_through_cleanly():
    """无列名冲突时，重映射应正常进行且不产生 _original_ 备份列。"""
    _prepare_pipeline_data = _import_prepare_pipeline_data()
    with tempfile.TemporaryDirectory() as tmpdir:
        df = pd.DataFrame({
            "victory": [1.0, 0.0, 1.0, 1.0],
            "assists": [5.0, 3.0, 7.0, 2.0],
            "gold": [100.0, 80.0, 120.0, 90.0],
            "wards": [3.0, 2.0, 5.0, 1.0],
        })
        csv_path = os.path.join(tmpdir, "clean.csv")
        df.to_csv(csv_path, index=False)

        temp_csv, pipeline_target, pipeline_vars, original_target, display_map = (
            _prepare_pipeline_data(csv_path, "victory",
                                   ["victory", "assists", "gold", "wards"])
        )
        try:
            out = pd.read_csv(temp_csv)
            # 无冲突时不应出现任何备份列
            backup_cols = [c for c in out.columns if c.startswith("_original_")]
            assert backup_cols == [], f"无冲突却产生了备份列: {backup_cols}"
            # 目标映射到 result
            assert pipeline_target == "result"
            # 前三个非目标变量映射到 kills/damage/deaths
            assert "kills" in pipeline_vars
            assert "damage" in pipeline_vars
            assert "deaths" in pipeline_vars
        finally:
            if os.path.exists(temp_csv):
                os.remove(temp_csv)


def test_double_conflict_raises_clear_error():
    """CSV 同时已有别名列和同名备份列时，应抛出明确的错误而非静默丢失。"""
    _prepare_pipeline_data = _import_prepare_pipeline_data()
    with tempfile.TemporaryDirectory() as tmpdir:
        df = pd.DataFrame({
            "victory": [1.0, 0.0, 1.0, 1.0],
            "result": [99.0, 88.0, 77.0, 66.0],      # 冲突
            "_original_result_": [0.0, 0.0, 0.0, 0.0],  # 备份列也已存在
            "assists": [5.0, 3.0, 7.0, 2.0],
        })
        csv_path = os.path.join(tmpdir, "double_conflict.csv")
        df.to_csv(csv_path, index=False)

        with pytest.raises(ValueError, match="result"):
            _prepare_pipeline_data(csv_path, "victory", ["victory", "assists"])
