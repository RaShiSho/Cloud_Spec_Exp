# Benchmarks

本目录用于存放实验 bug case。

建议每个 case 至少包含：

- `case_id`：稳定唯一标识。
- `repo`：待修复项目来源。
- `buggy_commit`：错误版本。
- `baseline_patch`：可选，已有修复基线或候选补丁。
- `problem_statement`：给 agent 的 bug 描述。
- `inputs`：用于触发行为差异的输入样例。
- `expected_behavior`：基于标准实现的行为描述。
- `oracle`：调用 `runC` 或其他标准实现的方式。

如果 case 数量较多，建议使用 `benchmarks/cases/*.yaml` 保存元数据，并把大型源码快照或数据集放到外部路径。
