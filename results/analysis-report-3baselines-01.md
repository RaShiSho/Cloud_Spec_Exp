# OCI 三 Baseline 重跑结果分析

分析目录：`results/oci-metagpt-agentless-mini-rerun/`

## 1. 结论

- 三个 baseline 均生成了 31/31 个 case 目录和 `metadata.json`，目录覆盖率均为 100%，不存在未运行或缺失 metadata 的 case。
- MetaGPT 真正进入了 Agent 阶段，3 个 case 通过 oracle：`crun-13`、`crun-237`、`crun-453`。按全部 31 个 case 计算，修复成功率为 9.7%。
- Agentless 的 31 个 case 均在导入阶段因 `ModuleNotFoundError: No module named 'datasets'` 退出，未进入 LLM 修复流程。
- mini-SWE-agent 的 31 个 case 均因 `/bin/sh: mini: not found` 退出，未启动 Agent。
- Agentless 没有生成 repair log、completion ID 或候选补丁，因此没有 case 被 deduplication 过滤。
- 93 个 `metadata.json` 中的 Token、Cost、`llm_calls` 均为 `null`。MetaGPT 日志也没有可可靠恢复的 usage/cost 数据；`investment=3.0` 是预算上限，`n_round=10` 是配置上限，均不能视为实际 Cost 或 `#R`。

## 2. 指标定义与覆盖率

- `Token_k = total_tokens / 1000`。
- `Time_m = pipeline_elapsed_seconds / 60`，包含准备、Agent、补丁、构建和 oracle。
- `Agent_m = agent_elapsed_seconds / 60`。
- `#R` 表示实际 LLM API 调用次数，不使用配置最大轮数替代。
- `—` 表示结果中没有可靠数据。
- `0*` 表示 metadata 原值为 `null`，但日志证明执行在任何 LLM 调用之前失败，因此实际 Token、Cost 和 `#R` 均为 0。

| Baseline | Case/Metadata | 实际进入 Agent | Oracle pass | Oracle fail | Token/Cost/#R 有记录 | Pipeline 总 Time_m | Agent 总 Time_m |
|---|---:|---:|---:|---:|---:|---:|---:|
| MetaGPT | 31/31 | 31 | 3 | 4 | 0/31 | 191.391 | 182.138 |
| Agentless | 31/31 | 0 | 0 | 0 | 0/31；实际为 0* | 0.180 | 0.044 |
| mini-SWE-agent | 31/31 | 0 | 0 | 0 | 0/31；实际为 0* | 0.067 | 0.001 |
| 合计 | 93/93 | 31 | 3 | 4 | 0/93 | 191.638 | 182.183 |

MetaGPT 的 4 个 raw oracle fail 中，`crun-1943`、`crun-876` 是明确的候选行为错误；`runc-2928`、`runc-4014` 在 rootless 环境中没有真正执行目标行为，失败来自严格 stdout/stderr 比较，应视为环境/评测不确定，而不是可靠的修复失败。

## 3. 失败原因分类

### MetaGPT

| 分类 | 数量 | Cases | 证据与解释 |
|---|---:|---|---|
| 修复成功 | 3 | `crun-13`, `crun-237`, `crun-453` | base 与 buggy 配置均和 reference 一致 |
| 明确修复失败 | 2 | `crun-1943`, `crun-876` | buggy 配置行为与 reference 不一致 |
| rootless 环境/比较不确定 | 2 | `runc-2928`, `runc-4014` | reference 和 candidate 均被“rootless container requires user namespaces”阻断；路径或日志前缀差异触发 oracle fail |
| Oracle 环境崩溃 | 1 | `crun-1783` | 清理临时 rootfs 时对 `media/floppy` 遇到 `PermissionError`，未生成 `oracle.json` |
| 超时且已有部分补丁 | 7 | `crun-1083`, `crun-353`, `runc-4772`, `youki-2994`, `youki-3132`, `youki-3266`, `youki-3293` | 600 秒 Agent 超时；stdout/stderr 均非空，不属于“超时无日志” |
| 超时且无补丁 | 4 | `crun-1161`, `crun-129`, `runc-2430`, `youki-3198` | 600 秒 Agent 超时；有日志但 patch 为 0 |
| Agent 命令/JSON 协议崩溃 | 4 | `crun-1307`, `runc-3944`, `runc-5073`, `youki-3320` | `JSONDecodeError`、invalid control character 或缺失 `command_name` |
| API 流中断 | 1 | `runc-5182` | `httpx.RemoteProtocolError: incomplete chunked read` |
| API 余额不足 | 1 | `youki-3431` | DeepSeek 返回 HTTP 402 `Insufficient Balance` |
| Agent 补丁导致构建失败 | 4 | `crun-1099`, `runc-3020`, `youki-2756`, `youki-3428` | 分别出现非法 C 转义、Go 语法错误、缺少 builder 方法、缺少函数 |
| 构建环境失败 | 2 | `youki-3186`, `youki-3199` | Rust toolchain `1.89.0` 缺少 manifest |

明确行为失败的具体差异：

- `crun-1943`：reference 因 poststart hook 失败返回 1；candidate 忽略失败并返回 0。
- `crun-876`：reference 写入无效 `cpu.weight=100` 时失败；candidate 成功运行并输出 `cpu-idle-876`。
- `runc-2928`：两侧都被 rootless 环境阻断，reference 额外输出非绝对 mount 警告；无法证明目标行为是否修复。
- `runc-4014`：两侧都被 rootless 环境阻断，主要差异是 stdout 中 runtime 路径不同；属于评测比较伪差异。

### Agentless

- 31/31 均为环境依赖失败：`ModuleNotFoundError: No module named 'datasets'`。
- 所有 case 都在加载 `agentless/repair/repair.py` 时退出，Token、Cost、`#R` 实际均为 0。
- 没有 `agentless-output`、repair log、Completion ID 或补丁，deduplication 过滤数为 0。

### mini-SWE-agent

- 31/31 均为环境入口失败：`/bin/sh: 1: mini: not found`。
- Agent 进程未启动，未生成 `trajectory.json`；Token、Cost、`#R` 实际均为 0。

## 4. 逐 Case 状态与指标

指标单元格顺序为 `Token_k / Cost_USD / #R / Time_m / Agent_m`。

状态代码：

- `S`：oracle pass。
- `F-B`：候选 buggy 行为明确错误。
- `I-R`：rootless 环境导致结果不确定。
- `I-O`：oracle 环境崩溃。
- `T+`：超时且有部分补丁；`T0`：超时且无补丁。
- `E-P`：Agent 命令/JSON 协议崩溃；`E-N`：API 网络流中断；`E-$`：API 余额不足。
- `B-P`：Agent 补丁导致构建失败；`B-E`：构建环境失败。
- `E-A`：Agentless 缺少 `datasets`；`E-M`：找不到 `mini` 命令。

| Case | MetaGPT | MetaGPT 指标 | Agentless | Agentless 指标 | mini | mini 指标 |
|---|---|---|---|---|---|---|
| crun-1083 | T+ | — / — / — / 10.005 / 10.002 | E-A | 0* / 0* / 0* / 0.004 / 0.001 | E-M | 0* / 0* / 0* / 0.001 / 0.000 |
| crun-1099 | B-P | — / — / — / 5.880 / 4.715 | E-A | 0* / 0* / 0* / 0.004 / 0.001 | E-M | 0* / 0* / 0* / 0.001 / 0.000 |
| crun-1161 | T0 | — / — / — / 10.004 / 10.002 | E-A | 0* / 0* / 0* / 0.004 / 0.001 | E-M | 0* / 0* / 0* / 0.001 / 0.000 |
| crun-129 | T0 | — / — / — / 10.004 / 10.002 | E-A | 0* / 0* / 0* / 0.003 / 0.001 | E-M | 0* / 0* / 0* / 0.001 / 0.000 |
| crun-13 | S | — / — / — / 4.087 / 3.876 | E-A | 0* / 0* / 0* / 0.005 / 0.003 | E-M | 0* / 0* / 0* / 0.001 / 0.000 |
| crun-1307 | E-P | — / — / — / 2.273 / 2.271 | E-A | 0* / 0* / 0* / 0.004 / 0.002 | E-M | 0* / 0* / 0* / 0.001 / 0.000 |
| crun-1783 | I-O | — / — / — / 10.246 / 4.954 | E-A | 0* / 0* / 0* / 0.004 / 0.001 | E-M | 0* / 0* / 0* / 0.001 / 0.000 |
| crun-1943 | F-B | — / — / — / 2.849 / 2.551 | E-A | 0* / 0* / 0* / 0.004 / 0.001 | E-M | 0* / 0* / 0* / 0.001 / 0.000 |
| crun-237 | S | — / — / — / 3.926 / 3.715 | E-A | 0* / 0* / 0* / 0.003 / 0.001 | E-M | 0* / 0* / 0* / 0.001 / 0.000 |
| crun-353 | T+ | — / — / — / 10.001 / 10.000 | E-A | 0* / 0* / 0* / 0.003 / 0.001 | E-M | 0* / 0* / 0* / 0.001 / 0.000 |
| crun-453 | S | — / — / — / 2.719 / 2.497 | E-A | 0* / 0* / 0* / 0.003 / 0.001 | E-M | 0* / 0* / 0* / 0.001 / 0.000 |
| crun-876 | F-B | — / — / — / 3.566 / 3.264 | E-A | 0* / 0* / 0* / 0.003 / 0.001 | E-M | 0* / 0* / 0* / 0.001 / 0.000 |
| runc-2430 | T0 | — / — / — / 10.006 / 10.002 | E-A | 0* / 0* / 0* / 0.009 / 0.001 | E-M | 0* / 0* / 0* / 0.003 / 0.000 |
| runc-2928 | I-R | — / — / — / 4.588 / 4.519 | E-A | 0* / 0* / 0* / 0.008 / 0.001 | E-M | 0* / 0* / 0* / 0.003 / 0.000 |
| runc-3020 | B-P | — / — / — / 2.602 / 2.588 | E-A | 0* / 0* / 0* / 0.008 / 0.001 | E-M | 0* / 0* / 0* / 0.003 / 0.000 |
| runc-3944 | E-P | — / — / — / 5.303 / 5.300 | E-A | 0* / 0* / 0* / 0.008 / 0.001 | E-M | 0* / 0* / 0* / 0.004 / 0.000 |
| runc-4014 | I-R | — / — / — / 7.608 / 7.551 | E-A | 0* / 0* / 0* / 0.008 / 0.001 | E-M | 0* / 0* / 0* / 0.004 / 0.000 |
| runc-4772 | T+ | — / — / — / 10.005 / 10.002 | E-A | 0* / 0* / 0* / 0.007 / 0.001 | E-M | 0* / 0* / 0* / 0.003 / 0.000 |
| runc-5073 | E-P | — / — / — / 5.115 / 5.112 | E-A | 0* / 0* / 0* / 0.008 / 0.001 | E-M | 0* / 0* / 0* / 0.004 / 0.000 |
| runc-5182 | E-N | — / — / — / 1.963 / 1.959 | E-A | 0* / 0* / 0* / 0.008 / 0.001 | E-M | 0* / 0* / 0* / 0.004 / 0.000 |
| youki-2756 | B-P | — / — / — / 3.238 / 2.410 | E-A | 0* / 0* / 0* / 0.006 / 0.001 | E-M | 0* / 0* / 0* / 0.003 / 0.000 |
| youki-2994 | T+ | — / — / — / 10.005 / 10.002 | E-A | 0* / 0* / 0* / 0.006 / 0.001 | E-M | 0* / 0* / 0* / 0.003 / 0.000 |
| youki-3132 | T+ | — / — / — / 10.004 / 10.002 | E-A | 0* / 0* / 0* / 0.007 / 0.001 | E-M | 0* / 0* / 0* / 0.003 / 0.000 |
| youki-3186 | B-E | — / — / — / 5.275 / 5.270 | E-A | 0* / 0* / 0* / 0.007 / 0.001 | E-M | 0* / 0* / 0* / 0.003 / 0.000 |
| youki-3198 | T0 | — / — / — / 10.002 / 10.000 | E-A | 0* / 0* / 0* / 0.006 / 0.001 | E-M | 0* / 0* / 0* / 0.003 / 0.000 |
| youki-3199 | B-E | — / — / — / 2.170 / 2.165 | E-A | 0* / 0* / 0* / 0.006 / 0.001 | E-M | 0* / 0* / 0* / 0.003 / 0.000 |
| youki-3266 | T+ | — / — / — / 10.004 / 10.002 | E-A | 0* / 0* / 0* / 0.007 / 0.001 | E-M | 0* / 0* / 0* / 0.003 / 0.000 |
| youki-3293 | T+ | — / — / — / 10.004 / 10.002 | E-A | 0* / 0* / 0* / 0.007 / 0.001 | E-M | 0* / 0* / 0* / 0.003 / 0.000 |
| youki-3320 | E-P | — / — / — / 1.954 / 1.952 | E-A | 0* / 0* / 0* / 0.007 / 0.001 | E-M | 0* / 0* / 0* / 0.003 / 0.000 |
| youki-3428 | B-P | — / — / — / 2.400 / 1.874 | E-A | 0* / 0* / 0* / 0.007 / 0.001 | E-M | 0* / 0* / 0* / 0.003 / 0.000 |
| youki-3431 | E-$ | — / — / — / 3.584 / 3.581 | E-A | 0* / 0* / 0* / 0.007 / 0.001 | E-M | 0* / 0* / 0* / 0.003 / 0.000 |

## 5. 可用于论文表格的统一汇总

| Baseline | Success | Evaluated | Success/All | Token_k | Cost_USD | #R | Time_m | Agent_m |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MetaGPT | 3 | 7 raw oracle verdicts | 3/31 (9.7%) | — | — | — | 191.391 | 182.138 |
| Agentless | 0 | 0 | 0/31 (0.0%) | 0* | 0* | 0* | 0.180 | 0.044 |
| mini-SWE-agent | 0 | 0 | 0/31 (0.0%) | 0* | 0* | 0* | 0.067 | 0.001 |

论文中不应直接把 Agentless 和 mini-SWE-agent 的 0/31 当作算法性能：两者都没有真正运行 Agent。MetaGPT 的 3/31 可以作为本批次的原始成功数，但 Token、Cost、`#R` 缺失，且部分 case 受到 rootless、Rust toolchain、oracle 清理权限和 API 余额等环境因素影响。
