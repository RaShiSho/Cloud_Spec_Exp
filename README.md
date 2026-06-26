# Cloud-Spec-Exp

本目录是用于复现“大模型在给定 bug 案例和修复基线下能否修复代码，并使行为与标准实现保持一致”的实验工作区。

## 工作区结构

- `baselines/`：记录和接入 SWE-agent、mini-SWE-agent、MetaGPT、RepairAgent、PatchAgent、Agentless、AutoCodeRover。
- `benchmarks/`：存放 bug case 元数据、输入样例、错误行为说明和期望行为描述。
- `oracles/`：存放标准实现或对照执行器的接入说明，例如 `runC`。
- `scripts/`：存放统一运行、评估和结果汇总脚本。
- `configs/`：存放实验配置样例和实际运行配置。
- `results/`：存放实验输出。大文件、日志和批量结果默认不提交。
- `docs/`：存放复现实验说明、baseline 调研记录和操作日志。

## 推荐流程

1. 在 `benchmarks/` 中整理 bug case。
2. 在 `oracles/` 中固定标准实现的调用方式。
3. 在 `configs/` 中复制 `experiment.example.yaml` 并填写真实实验配置。
4. 在 `baselines/` 中接入需要运行的 baseline。
5. 使用 `scripts/` 中的统一入口执行实验。
6. 将结果输出到 `results/`，只提交摘要和可复现配置。

## 当前默认选择

- 优先跑轻量且流程清晰的 `mini-SWE-agent` 和 `Agentless`。
- `AutoCodeRover` 作为更强但更重的对照 baseline。
- `MetaGPT`、`RepairAgent`、`PatchAgent` 需要先确认具体复现目标和可用仓库。

## Git 约定

提交信息使用：

```text
<type>(<scope>): <subject>
```

示例：

```text
chore(workspace): initialize reproduction workspace
```
