# Oracles

`run_oci_oracle.py` 执行数据集的 `repro.sh`，分别比较候选 runtime 和参考 runtime
在 `base_config.json`、`buggy_config.json` 下的结果。

## 目标

oracle 需要给出统一的判定结果：

- `pass`：候选修复行为与标准实现一致。
- `fail`：候选修复仍存在行为差异。
- `error`：运行环境、编译、超时或输入数据异常导致无法判定。

## 接口

统一脚本可以接受：

```text
--case <case_id>
--case-dir <case_directory>
--candidate <candidate_path>
--reference <reference_path>
--rootfs-tar <rootfs_archive>
--output <result_json>
--timeout <seconds_per_execution>
```

输出 JSON 包含：

- `case_id`
- `status`
- `message`
- `elapsed_seconds`
- `comparisons`
- `expected_diff`

## 判定与日志

参考 runtime 的基础配置必须执行成功。准备阶段未调用 runtime、权限不足、缺少环境
能力或超时会返回 `error`；buggy 配置本身预期的非零退出仍可参与比较。

`comparisons` 保留两侧原始 stdout/stderr，并提供 `normalized_reference` 和
`normalized_candidate`。比较只归一化本次执行的 runtime/bundle 路径、容器 ID、
日志前缀中的时间戳，以及 OCI state JSON 中的正数 PID。退出码、错误消息、状态、
annotations、缺失或无效 PID 和普通工作负载数值均保留，避免掩盖真实行为差异。
运行上下文记录在每侧的 `execution_context` 中，便于审计归一化依据。

`expected_diff.txt` 作为诊断材料保留；当前不会自动将其中的自然语言转换成断言。

## 超时清理

在 POSIX 系统上，repro、baseline 和构建命令各自使用独立进程组。超时先发送 TERM，
宽限期后发送 KILL，并回收直接子进程。外层实验脚本终止 oracle 时，也会给 oracle
时间清理其管理的进程组。超时或中断后，oracle 额外执行对应容器的 `delete -f`，
再移除 bundle；如果观测到 runtime 通过 sudo 执行，清理也使用非交互 sudo。
清理失败会记录 `cleanup_warning` 并保留临时目录，避免删除仍被使用的 bundle。
`--timeout` 指每次执行的时限；进程终止与容器清理有额外的有限宽限时间。
