# 变更日志

## [2.1.0] - 2026-07-15（对应 package.json 0.1.0）

### 新增
- **算法桥接一致性同步**：与 edm-takens 原生版本完成全量核对，6个核心文件同步更新
  - `_edm_bridge.py`：添加 `numProcess=1` 避免 Windows 多进程死锁
  - `_paths.py`：支持 `EDMTAKENS_DATA_DIR` 环境变量覆盖数据路径
  - `final_interpretation.py`：`ccm_with_convergence()` 保留 `lib_sizes` 参数以支持自测
  - `enhanced_cross_validate.py`：函数签名添加 `variables` 和 `target_col`，添加异常处理
  - `environment_check.py`：环境验证逻辑与源同步
  - `pipeline.py`：管线导入与路径设置与源同步

- **数据质量诊断**：`data_quality.py` 提供缺失率、唯一值率、自相关、趋势、平稳性、异常值检测
- **分析强度分级**：`analysis_profiles.py` 根据数据特征自动推荐 light/medium/heavy 三档参数

### 修复
- **CCM Windows 死锁**：恢复 `legacy='ccm_24'` 模式，避免 pyEDM 2.5+ 多进程问题
- **变量过滤异常**：`final_interpretation.py` 添加 `available_variables` 和 `skipped_variables` 初始化
- **跨验证灵活性**：`run_enhanced_validation()` 支持自定义变量和目标列

### 改进
- **异常处理**：每个变量分析都有 try/except 保护，避免单变量失败导致整体崩溃
- **路径独立性**：支持环境变量覆盖，便于部署和测试

## [2.0.0] - 2026-07-13

### 新增
- **Web 界面 MVP**：Vite + vanilla JS 前端 + FastAPI 后端
- **异步任务系统**：JobManager 接口 + SQLite 持久化
- **实时日志流**：NDJSON 格式流式输出分析进度
- **历史任务管理**：归档、下载、删除、清理旧数据
- **数据质量预览**：上传 CSV 后自动诊断数据质量

### 架构
- 前端：Vite + 原生 JavaScript，极客/终端风格样式
- 后端：FastAPI，封装 edm-takens 核心算法
- 数据流：HTTP REST API + NDJSON 流式日志

## [1.0.0] - 2026-07-12

### 初始版本
- 从 edm-takens 原生版本复制核心算法
- 仅修改 `_paths.py` 支持 Web 环境
- 基础 CLI 接口：`run_pipeline.py`

---

## 版本说明

- **主版本号**：不兼容的 API 变更
- **次版本号**：向后兼容的功能新增
- **修订号**：向后兼容的问题修复
