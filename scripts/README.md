# Scripts

本目录用于存放复现实验脚本。

建议后续提供三个稳定入口：

- `run_baseline`：运行单个 baseline 和单个 case。
- `evaluate_patch`：调用 oracle 判定候选 patch。
- `summarize_results`：汇总 `results/` 中的批量输出。

脚本应尽量只依赖 `configs/*.yaml` 中的配置，不把路径、模型名和 API 参数硬编码在脚本内部。
