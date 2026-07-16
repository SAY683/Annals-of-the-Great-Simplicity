"""
EDM-Takens Skill Environment Validator
=======================================
Validates that the Python environment has all required dependencies
for the EDM-Takens skill pipeline.

Run before any computation:
    python environment_check.py
    # or:
    from environment_check import validate_environment
    report = validate_environment()
    if not report['ready']: ...  # install missing packages

Checks:
  - Python version (>= 3.9)
  - Core packages: numpy, scipy, pandas, matplotlib
  - pyEDM (optional but recommended for EDM pipeline)
  - SovereignHAVOK importability
  - Project file structure integrity
"""

import sys
import os
import importlib.util
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class DependencyCheck:
    name: str
    required: bool       # True = hard requirement, False = optional
    installed: bool
    version: Optional[str] = None
    min_version: Optional[str] = None
    import_path: Optional[str] = None
    note: str = ""


@dataclass
class EnvReport:
    checks: List[DependencyCheck] = field(default_factory=list)
    file_checks: List[Dict] = field(default_factory=list)
    ready: bool = True              # backward-compatible alias
    required_ready: bool = True
    optional_ready: bool = True
    python_version: str = ""

    def summary(self) -> str:
        lines = [
            "=" * 60,
            f"  EDM-Takens Skill Environment Report",
            f"  Python: {self.python_version}",
            "=" * 60,
        ]
        for c in self.checks:
            status = "[OK]" if c.installed else ("[XX]" if c.required else "[--]")
            ver_str = f" (v{c.version})" if c.version else ""
            lines.append(f"  {status} {c.name}{ver_str}")
            if c.note:
                lines.append(f"      {c.note}")
            if not c.installed and c.required:
                lines.append(f"      => INSTALL: pip install {c.import_path or c.name}")
        for fc in self.file_checks:
            status = "[OK]" if fc['exists'] else "[XX]"
            lines.append(f"  {status} {fc['label']}: {fc['path']}")
        overall = ("READY" if self.required_ready
                   else "NOT READY — fix required [XX] items above")
        if self.required_ready and not self.optional_ready:
            overall += " (optional packages missing — core fallback active)"
        lines.append(f"\n  Overall: {overall}")
        lines.append("=" * 60)
        return "\n".join(lines)


def check_package(name: str, import_path: str = None,
                  min_version: str = None, required: bool = True) -> DependencyCheck:
    """Check if a Python package is importable and get its version."""
    if import_path is None:
        import_path = name

    try:
        mod = importlib.import_module(import_path)
        version = getattr(mod, '__version__', None)
        if version is None:
            try:
                from importlib.metadata import version as get_version
                version = get_version(name)
            except Exception:
                pass
        installed = True
        note = ""
        if min_version and version:
            # Simple version comparison
            v_parts = [int(x) for x in version.split('.')[:2]]
            m_parts = [int(x) for x in min_version.split('.')[:2]]
            if v_parts < m_parts:
                note = f"Version {version} < minimum {min_version}"
    except ImportError:
        installed = False
        version = None
        note = f"Not installed"

    return DependencyCheck(
        name=name, required=required, installed=installed,
        version=str(version) if version else None,
        min_version=min_version, import_path=import_path, note=note,
    )


def check_file(label: str, path: str, required: bool = True) -> Dict:
    """Check if a project file exists."""
    exists = os.path.exists(path)
    return {'label': label, 'path': path, 'exists': exists, 'required': required}


def validate_environment(skill_root: str = None) -> EnvReport:
    """
    Validate the environment for the EDM-Takens skill.

    Parameters
    ----------
    skill_root : str, optional
        Path to the skill root directory (contains src/, data/, tests/).
        Defaults to the parent of the directory containing this script.
    """
    if skill_root is None:
        # script is at <skill_root>/src/environment_check.py
        skill_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    report = EnvReport()
    report.python_version = sys.version.split()[0]

    # Python version check
    py_major, py_minor = sys.version_info[:2]
    if (py_major, py_minor) < (3, 9):
        report.checks.append(DependencyCheck(
            "Python", True, True, report.python_version, "3.9",
            note=f"Python {report.python_version} < 3.9. Upgrade recommended."))
    else:
        report.checks.append(DependencyCheck(
            "Python", True, True, report.python_version, "3.9",
            note="OK"))

    # Core packages (hard requirements)
    report.checks.append(check_package("numpy", min_version="1.22"))
    report.checks.append(check_package("scipy", min_version="1.8"))
    report.checks.append(check_package("pandas", min_version="1.4"))
    report.checks.append(check_package("matplotlib", min_version="3.5"))

    # Optional packages
    report.checks.append(check_package("pyEDM", required=False))

    # Check SovereignHAVOK importability
    src_dir = os.path.join(skill_root, 'src')
    try:
        sys.path.insert(0, src_dir)
        from sovereign_havok import SovereignHAVOK
        report.checks.append(DependencyCheck(
            "sovereign_havok", True, True,
            note=f"Importable"))
    except ImportError as e:
        report.checks.append(DependencyCheck(
            "sovereign_havok", True, False,
            note=f"Cannot import: {e}"))

    # Check file integrity within skill folder
    report.file_checks.append(check_file(
        "Sovereign HAVOK engine",
        os.path.join(src_dir, "sovereign_havok.py")))
    report.file_checks.append(check_file(
        "Path resolver",
        os.path.join(src_dir, "_paths.py")))
    report.file_checks.append(check_file(
        "Auditor firewall",
        os.path.join(src_dir, "edm_auditor.py")))
    report.file_checks.append(check_file(
        "Unified pipeline",
        os.path.join(src_dir, "pipeline.py")))
    report.file_checks.append(check_file(
        "Data routing engine",
        os.path.join(src_dir, "router.py")))
    report.file_checks.append(check_file(
        "Cross-validation",
        os.path.join(src_dir, "enhanced_cross_validate.py")))
    report.file_checks.append(check_file(
        "Verification suite",
        os.path.join(src_dir, "verify_algorithms.py")))
    report.file_checks.append(check_file(
        "EDM adaptive pipeline",
        os.path.join(src_dir, "edm_adaptive_pipeline.py")))
    report.file_checks.append(check_file(
        "Multiview + SVD monitor",
        os.path.join(src_dir, "multiview_svd_monitor.py")))
    report.file_checks.append(check_file(
        "Game interpretation",
        os.path.join(src_dir, "final_interpretation.py")))
    report.file_checks.append(check_file(
        "Sensitivity + config capture",
        os.path.join(src_dir, "sensitivity_config.py")))
    report.file_checks.append(check_file(
        "Surrogate data testing",
        os.path.join(src_dir, "surrogate_test.py")))
    report.file_checks.append(check_file(
        "Tau optimizer",
        os.path.join(src_dir, "edm_tau_optimization.py")))
    report.file_checks.append(check_file(
        "SovereignHAVOK class tests",
        os.path.join(skill_root, "tests", "test_sovereign_havok.py")))
    report.file_checks.append(check_file(
        "Game data",
        os.path.join(skill_root, "examples", "game_analysis", "data", "game_log.csv")))
    report.file_checks.append(check_file(
        "SKILL.md",
        os.path.join(skill_root, "SKILL.md")))
    report.file_checks.append(check_file(
        "DESIGN.md",
        os.path.join(skill_root, "DESIGN.md")))
    report.file_checks.append(check_file(
        "requirements.txt",
        os.path.join(skill_root, "requirements.txt")))
    report.file_checks.append(check_file(
        "requirements-lock.txt",
        os.path.join(skill_root, "requirements-lock.txt"),
        required=False))
    report.file_checks.append(check_file(
        "CHANGELOG (docs attachment)",
        os.path.join(skill_root, "docs", "CHANGELOG.md")))
    report.file_checks.append(check_file(
        "Thresholds documentation (docs attachment)",
        os.path.join(skill_root, "docs", "thresholds_and_heuristics.md")))

    # Determine readiness
    missing_required = any(
        c.required and not c.installed for c in report.checks)
    missing_optional = any(
        not c.required and not c.installed for c in report.checks)
    missing_files = any(
        not fc['exists'] and fc.get('required', True) for fc in report.file_checks)
    report.required_ready = not (missing_required or missing_files)
    report.optional_ready = not missing_optional
    report.ready = report.required_ready  # backward-compatible alias

    return report


# ============================================================
# Self-test
# ============================================================

if __name__ == '__main__':
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # script_dir = .../.skills/edm-takens/src
    # skill_root = .../.skills/edm-takens (one level up)
    skill_root = os.path.dirname(script_dir)
    report = validate_environment(skill_root)
    print(report.summary())
    sys.exit(0 if report.required_ready else 1)
