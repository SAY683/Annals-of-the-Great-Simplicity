#!/usr/bin/env python3
"""
EDM-Takens Unified Pipeline — top-level CLI wrapper.

Mirrors the CLI in `src/pipeline.py` so the Skill can be invoked from the
project root without manually adding `src/` to PYTHONPATH.
"""
import sys
import os
import tempfile

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_ROOT, 'src'))

# debt-22: 环境变量从 pipeline.py 移至此入口点，确保在 numpy/matplotlib
# 导入前生效。
os.environ['MPLBACKEND'] = 'Agg'
os.environ['MPLCONFIGDIR'] = os.path.join(tempfile.gettempdir(), 'edm_takens_mpl')
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'

from pipeline import run_pipeline, run_full_analysis, PipelineConfig, data_path


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='EDM-Takens Unified Pipeline / Full Analysis')
    parser.add_argument('--data', default=data_path('game_log.csv'),
                        help='Path to CSV data file')
    parser.add_argument('--target', default='result',
                        help='Target column name')
    parser.add_argument('--auto-fix', action='store_true',
                        help='Auto-correct suboptimal configurations')
    parser.add_argument('--report-only', action='store_true',
                        help='Only show environment report, skip computation')
    parser.add_argument('--full-analysis', action='store_true',
                        help='Run pipeline + cross-validation + interpretation chain')
    parser.add_argument('--q', type=int, default=None,
                        help='Embedding dimension (auto-detect if omitted)')
    parser.add_argument('--max-e', type=int, default=8,
                        help='Maximum embedding dimension to search')

    args = parser.parse_args()

    config = PipelineConfig(
        data_path=args.data,
        target_col=args.target,
        q=args.q,
        max_E=args.max_e,
        auto_fix=args.auto_fix,
    )

    if args.full_analysis:
        run_full_analysis(config, auto_fix=args.auto_fix)
    else:
        run_pipeline(config, auto_fix=args.auto_fix,
                     report_only=args.report_only)


if __name__ == '__main__':
    main()
