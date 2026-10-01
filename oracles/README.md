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
