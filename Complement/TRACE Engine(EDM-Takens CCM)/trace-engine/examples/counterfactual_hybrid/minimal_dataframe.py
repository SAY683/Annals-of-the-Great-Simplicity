"""
最小化 DataFrame（pandas 未安装时的轻量替代）
=============================================
（从 counterfactual_bridge.py 抽取）

提供 _MinimalDataFrame / _ILocIndexer / _MinimalRow 三个类，
仅覆盖 DoWhy 桥接所需的最小 pandas 语义子集。

依赖说明:
  本模块仅依赖 numpy，不维护模块级依赖检查块。
"""

import numpy as np


class _ILocIndexer:
    def __init__(self, data, columns, col_idx):
        self.data = np.asarray(data)
        self.columns = columns
        self._col_idx = col_idx

    def __getitem__(self, idx):
        if isinstance(idx, int):
            return _MinimalRow(self.data[idx], self.columns, self._col_idx)
        if isinstance(idx, tuple):
            row_idx, col_idx = idx
            result = self.data[row_idx]
            if isinstance(col_idx, (slice, list, np.ndarray)):
                return result[..., col_idx]
            return result[col_idx]
        return self.data[idx]


class _MinimalRow:
    def __init__(self, row_data, columns, col_idx):
        self._data = np.asarray(row_data)
        self._col_idx = col_idx

    @property
    def values(self):
        return self._data

    def __repr__(self):
        return str(self._data)

    def to_dict(self):
        return {}


class _MinimalDataFrame:
    def __init__(self, data: np.ndarray, columns: list):
        self.data = np.asarray(data)
        self.columns = list(columns)
        self._col_idx = {c: i for i, c in enumerate(columns)}
        self.iloc = _ILocIndexer(self.data, self.columns, self._col_idx)

    @property
    def values(self):
        return self.data

    def __getitem__(self, key):
        if isinstance(key, str):
            return self.data[:, self._col_idx[key]]
        if isinstance(key, list) and key and isinstance(key[0], str):
            # list[str] 映射到列索引，返回新的 _MinimalDataFrame（兼容 pandas 语义）
            idx = [self._col_idx[k] for k in key]
            return _MinimalDataFrame(self.data[:, idx], list(key))
        return self.data[:, key]

    def __len__(self):
        return len(self.data)
