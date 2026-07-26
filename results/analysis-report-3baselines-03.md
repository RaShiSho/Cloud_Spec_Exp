# OCI 三 Baseline 重跑结果分析（第三版）

分析目录：`results/oci-metagpt-agentless-mini-rerun/`

本版以 Agentless 全量重跑后的标准产物 `metadata.json` 和 `oracle.json` 为准。此前针对旧候选二进制单独生成的 `oracle.retry*.json` 不计入本轮统计；特别是当前全量重跑中的 `crun-13` canonical Oracle 为 `fail`。

## 1. 结论

- 三个 baseline 均有 31/31 个 case 目录和 `metadata.json`，目录覆盖率均为 100%，不存在未运行或缺失 metadata 的 case。
- MetaGPT 通过 3 个 case：`crun-13`、`crun-237`、`crun-453`，成功率为 3/31（9.7%）。
- Agentless 的 31 个 case 均成功调用 LLM；修正绝对路径后，26 个生成并成功应用 git diff，较第二版统计的 3 个显著提升。最终 3 个通过 Oracle：`crun-237`、`youki-3320`、`youki-3431`，成功率为 3/31（9.7%）。
- Agentless 的其余结果包括 7 个明确行为不匹配、7 个 rootless 环境下的 raw oracle fail、3 个补丁导致的构建失败、4 个 Rust 环境构建失败、5 个定位文件覆盖不足导致的无 diff，以及 2 个 Oracle 总超时。
- mini-SWE-agent 的 31 个 case 均启动 Agent，8 个通过 oracle，成功率为 8/31（25.8%）；另有 11 个 raw oracle fail、8 个构建环境失败、2 个 oracle 清理崩溃、1 个进程被终止和 1 个超时。
- Agentless 的剩余 5 个无补丁结果不再是绝对路径规范化问题，而是模型选择的目标文件不在 top-5 定位文件中，日志均出现 `edited_file not found after normalize`。
- Agentless 的 31 条 repair log 各有 1 个 Completion ID，共 31 个唯一 ID，没有重复请求被 deduplication 过滤。
- 本轮 Agentless 和 mini-SWE-agent 使用 RootFlowAI 的 `gpt-5.5`；保留的 MetaGPT 结果使用 DeepSeek `deepseek-v4-flash`。因此三者不是同模型、同供应商条件下的严格横向比较。

## 2. 指标定义与覆盖率

- `Token_k = total_tokens / 1000`。
- `Time_m = pipeline_elapsed_seconds / 60`，包含准备、Agent、补丁、构建和 oracle。
- `Agent_m = agent_elapsed_seconds / 60`，仅包含 baseline 命令运行时间。
- `#R` 表示实际 LLM API 调用次数，不使用配置最大轮数替代。
- `—` 表示结果中没有可靠数据。
- Oracle pass/fail 是 runner 的原始判定；受到 rootless、清理权限、Oracle 超时或严格 stdout/stderr 比较影响的结果另行标注。

| Baseline | Case/Metadata | 进入 Agent | Oracle pass | Raw oracle fail | Token 覆盖 | Cost 覆盖 | #R 覆盖 | Pipeline 总 Time_m | Agent 总 Time_m |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| MetaGPT | 31/31 | 31 | 3 | 4 | 0/31 | 0/31 | 0/31 | 191.391 | 182.138 |
| Agentless | 31/31 | 31 | 3 | 14 | 31/31 | 0/31 | 31/31 | 91.649 | 23.130 |
| mini-SWE-agent | 31/31 | 31 | 8 | 11 | 31/31 | 31/31 | 31/31 | 167.053 | 150.290 |
| 合计 | 93/93 | 93 | 14 | 29 | 62/93 | 31/93 | 62/93 | 450.093 | 355.558 |

指标总量：

- Agentless：2,170,753 prompt tokens、56,288 completion tokens、2,227,041 total tokens，31 次 LLM 调用；日志未提供可靠实际 Cost。
- mini-SWE-agent：14,270,735 prompt tokens、200,299 completion tokens、14,471,034 total tokens，690 次 LLM 调用，框架记录 Cost 为 20.422083 USD。
- 两个有 usage 数据的 baseline 合计为 16,698,075 tokens、721 次 LLM 调用。由于 MetaGPT 和 Agentless 缺失 Cost，不能给出三个 baseline 的完整总 Cost。

mini-SWE-agent 的 `youki-3431` 在超时边界存在写入竞争：metadata 记录 25 次调用、0.766182 USD，最终 `trajectory.json` 的累计统计为 26 次调用、0.826580 USD。本报告对 `#R` 和 Cost 使用最终累计值；Token 仍只能汇总 25 条已序列化 response usage，因此 14,471,034 是可恢复的下界。

mini-SWE-agent 的 Cost 是框架/LiteLLM 写入的 `instance_cost`，不是与 RootFlowAI 账单独立核对后的实际扣费。Agentless 虽有完整 Token usage，但中转站响应和日志没有可靠的实际扣费字段，故 Cost 保持 `—`，不按公开模型价格估算。

## 3. 结果与失败原因分类

### MetaGPT

| 分类 | 数量 | Cases | 证据与解释 |
|---|---:|---|---|
| 修复成功 | 3 | `crun-13`, `crun-237`, `crun-453` | base 与 buggy 配置均和 reference 一致 |
| 明确修复失败 | 2 | `crun-1943`, `crun-876` | buggy 配置行为与 reference 不一致 |
| rootless 环境/比较不确定 | 2 | `runc-2928`, `runc-4014` | reference 和 candidate 均被 rootless 环境阻断；路径或日志前缀差异触发 oracle fail |
| Oracle 环境崩溃 | 1 | `crun-1783` | 清理临时 rootfs 时对 `media/floppy` 遇到 `PermissionError`，未生成 `oracle.json` |
| 超时且已有部分补丁 | 7 | `crun-1083`, `crun-353`, `runc-4772`, `youki-2994`, `youki-3132`, `youki-3266`, `youki-3293` | 600 秒 Agent 超时；stdout/stderr 均非空，不属于“超时无日志” |
| 超时且无补丁 | 4 | `crun-1161`, `crun-129`, `runc-2430`, `youki-3198` | 600 秒 Agent 超时；有日志但 patch 为 0 |
| Agent 命令/JSON 协议崩溃 | 4 | `crun-1307`, `runc-3944`, `runc-5073`, `youki-3320` | `JSONDecodeError`、invalid control character 或缺失 `command_name` |
| API 流中断 | 1 | `runc-5182` | `httpx.RemoteProtocolError: incomplete chunked read` |
| API 余额不足 | 1 | `youki-3431` | DeepSeek 返回 HTTP 402 `Insufficient Balance` |
| Agent 补丁导致构建失败 | 4 | `crun-1099`, `runc-3020`, `youki-2756`, `youki-3428` | 分别出现非法 C 转义、Go 语法错误、缺少 builder 方法、缺少函数 |
| 构建环境失败 | 2 | `youki-3186`, `youki-3199` | Rust toolchain `1.89.0` 缺少 manifest |

### Agentless

| 分类 | 数量 | Cases | 证据与解释 |
|---|---:|---|---|
| 修复成功 | 3 | `crun-237`, `youki-3320`, `youki-3431` | base 与 buggy 配置均和 reference 一致 |
| 明确/原始行为不匹配 | 7 | `crun-1083`, `crun-1161`, `crun-129`, `crun-13`, `crun-1307`, `crun-1943`, `crun-353` | buggy 配置的退出码、stdout 或 stderr 与 reference 不一致 |
| rootless 环境/比较不确定 | 7 | `runc-2430`, `runc-3020`, `runc-3944`, `runc-4014`, `runc-4772`, `runc-5073`, `runc-5182` | reference 与 candidate 均被 `rootless container requires user namespaces` 阻断；时间戳、runtime 路径或错误前缀差异触发 raw fail |
| Oracle 总超时 | 2 | `crun-1783`, `youki-2756` | Agent、补丁应用和构建均成功；Oracle 外层运行 1200 秒后超时，未生成 `oracle.json` |
| 定位文件覆盖不足，无 git diff | 5 | `crun-453`, `crun-876`, `runc-2928`, `youki-2994`, `youki-3266` | 模型返回规范的相对路径，但目标文件不在 top-5 `available` 文件中，适配器拒绝编辑 |
| Agent 补丁导致构建失败 | 3 | `crun-1099`, `youki-3132`, `youki-3428` | 分别出现 C 类型/成员错误、Rust 类型借用错误、Rust 所有权/生命周期错误 |
| 构建环境失败 | 4 | `youki-3186`, `youki-3198`, `youki-3199`, `youki-3293` | Rust toolchain `1.89.0-x86_64-unknown-linux-gnu` 缺少 manifest |

31 个 Agentless baseline 命令均返回 0，并留下 31 个唯一 Completion ID 和完整 usage。路径规范化修复已经生效：26/31 个模型输出形成非空补丁，26 个补丁全部由 `git apply` 成功应用；此前“27 个绝对路径被拒绝”的主瓶颈已消除。

仍未获得 raw oracle verdict 的 14 个 case 可完整解释为：5 个定位文件覆盖不足、3 个补丁构建失败、4 个构建环境失败和 2 个 Oracle 总超时。不存在未运行、Agent 启动失败、超时无 Agent 日志或 deduplication 过滤。

当前 `crun-13` 与此前手工 retry 结果不同：本轮模型把 `execvp` 改为 `execv`，导致 buggy 配置从 reference 的成功执行变为 `executable file not found`，因此本轮应记为明确失败，不能沿用旧候选二进制的 retry pass。

### mini-SWE-agent

| 分类 | 数量 | Cases | 证据与解释 |
|---|---:|---|---|
| 修复成功 | 8 | `crun-1083`, `crun-13`, `crun-237`, `crun-453`, `runc-3944`, `runc-4772`, `youki-2994`, `youki-3320` | oracle pass |
| 明确/原始行为不匹配 | 4 | `crun-1099`, `crun-129`, `crun-1943`, `crun-876` | candidate 的退出码、输出或错误行为与 reference 不一致 |
| rootless 环境/比较不确定 | 6 | `runc-2430`, `runc-2928`, `runc-3020`, `runc-4014`, `runc-5073`, `runc-5182` | 目标行为被 rootless 环境阻断，严格输出比较产生 raw fail |
| 严格 stderr 比较不确定 | 1 | `youki-3132` | reference 有 ambient capability 警告，candidate 无 stderr；仅该差异导致 raw fail |
| Oracle 清理崩溃 | 2 | `crun-1783`, `youki-2756` | 清理 `media/floppy` 时 `PermissionError`，oracle 子进程返回 1 且未生成 `oracle.json` |
| crun 构建环境/工具链失败 | 3 | `crun-1161`, `crun-1307`, `crun-353` | 前两者缺少 `libocispec/image-spec` 子模块/生成产物；后者在并行生成中出现 libocispec header/type 错误 |
| youki 构建环境失败 | 5 | `youki-3186`, `youki-3198`, `youki-3199`, `youki-3266`, `youki-3293` | Rust toolchain `1.89.0` 缺少 manifest |
| 进程被终止且有部分补丁 | 1 | `youki-3428` | Agent 运行约 475.8 秒后收到终止信号，已留下 5,820-byte git diff |
| 超时且有部分补丁 | 1 | `youki-3431` | 600 秒 runner 超时，已留下 3,866-byte git diff 和部分 trajectory |

## 4. 逐 Case 状态与指标

指标单元格顺序为 `Token_k / Cost_USD / #R / Time_m / Agent_m`。

状态代码：

- `S`：oracle pass。
- `F-B`：候选行为与 reference 明确或原始不一致。
- `I-R`：rootless 环境导致结果不确定；`I-C`：严格 stderr 比较导致结果不确定。
- `I-O`：Oracle 环境崩溃、总超时或未生成结果。
- `T+`：超时且有部分补丁；`T0`：超时且无补丁；`X+`：进程被终止且有部分补丁。
- `E-P`：Agent 命令/JSON 协议崩溃；`E-N`：API 网络流中断；`E-$`：API 余额不足。
- `E-D`：Agentless 定位/补丁解析未生成 git diff。
- `B-P`：Agent 补丁导致构建失败；`B-E`：构建环境或工具链失败。

| Case | MetaGPT | MetaGPT 指标 | Agentless | Agentless 指标 | mini | mini 指标 |
|---|---|---|---|---|---|---|
| crun-1083 | T+ | — / — / — / 10.005 / 10.002 | F-B | 121.197 / — / 1 / 2.500 / 0.962 | S | 100.662 / 0.2133 / 11 / 3.456 / 2.489 |
| crun-1099 | B-P | — / — / — / 5.880 / 4.715 | B-P | 116.857 / — / 1 / 2.982 / 1.395 | F-B | 511.243 / 0.6503 / 21 / 4.489 / 4.103 |
| crun-1161 | T0 | — / — / — / 10.004 / 10.002 | F-B | 115.714 / — / 1 / 1.813 / 0.403 | B-E | 1150.246 / 1.3599 / 35 / 7.860 / 7.567 |
| crun-129 | T0 | — / — / — / 10.004 / 10.002 | F-B | 75.506 / — / 1 / 2.010 / 0.984 | F-B | 921.290 / 1.0726 / 27 / 5.679 / 5.431 |
| crun-13 | S | — / — / — / 4.087 / 3.876 | F-B | 64.866 / — / 1 / 1.175 / 0.263 | S | 778.832 / 1.0045 / 28 / 6.612 / 6.356 |
| crun-1307 | E-P | — / — / — / 2.273 / 2.271 | F-B | 118.346 / — / 1 / 2.646 / 1.029 | B-E | 295.660 / 0.4233 / 20 / 3.997 / 3.699 |
| crun-1783 | I-O | — / — / — / 10.246 / 4.954 | I-O | 143.499 / — / 1 / 22.060 / 0.608 | I-O | 384.468 / 0.6319 / 22 / 10.353 / 4.974 |
| crun-1943 | F-B | — / — / — / 2.849 / 2.551 | F-B | 153.015 / — / 1 / 2.638 / 0.645 | F-B | 272.756 / 0.5055 / 18 / 4.079 / 3.764 |
| crun-237 | S | — / — / — / 3.926 / 3.715 | S | 83.363 / — / 1 / 1.685 / 0.694 | S | 344.342 / 0.6124 / 19 / 4.044 / 3.476 |
| crun-353 | T+ | — / — / — / 10.001 / 10.000 | F-B | 81.057 / — / 1 / 2.021 / 0.775 | B-E | 626.518 / 0.9222 / 27 / 4.648 / 4.434 |
| crun-453 | S | — / — / — / 2.719 / 2.497 | E-D | 88.638 / — / 1 / 0.576 / 0.573 | S | 366.187 / 0.5512 / 22 / 3.866 / 3.595 |
| crun-876 | F-B | — / — / — / 3.566 / 3.264 | E-D | 103.194 / — / 1 / 0.570 / 0.566 | F-B | 354.403 / 0.5771 / 24 / 4.313 / 4.008 |
| runc-2430 | T0 | — / — / — / 10.006 / 10.002 | I-R | 49.020 / — / 1 / 1.127 / 1.041 | I-R | 623.667 / 0.8596 / 24 / 4.847 / 4.826 |
| runc-2928 | I-R | — / — / — / 4.588 / 4.519 | E-D | 53.818 / — / 1 / 1.054 / 1.040 | I-R | 158.118 / 0.3838 / 14 / 2.823 / 2.799 |
| runc-3020 | B-P | — / — / — / 2.602 / 2.588 | I-R | 52.720 / — / 1 / 0.713 / 0.631 | I-R | 292.543 / 0.5365 / 19 / 3.414 / 3.392 |
| runc-3944 | E-P | — / — / — / 5.303 / 5.300 | I-R | 62.372 / — / 1 / 0.714 / 0.627 | S | 159.946 / 0.3654 / 15 / 1.858 / 1.833 |
| runc-4014 | I-R | — / — / — / 7.608 / 7.551 | I-R | 50.972 / — / 1 / 1.103 / 1.017 | I-R | 665.634 / 0.9251 / 27 / 5.420 / 5.398 |
| runc-4772 | T+ | — / — / — / 10.005 / 10.002 | I-R | 56.680 / — / 1 / 0.830 / 0.733 | S | 224.219 / 0.5343 / 22 / 4.203 / 4.173 |
| runc-5073 | E-P | — / — / — / 5.115 / 5.112 | I-R | 58.813 / — / 1 / 0.585 / 0.438 | I-R | 400.256 / 0.5467 / 22 / 2.858 / 2.835 |
| runc-5182 | E-N | — / — / — / 1.963 / 1.959 | I-R | 60.231 / — / 1 / 1.049 / 0.891 | I-R | 457.187 / 0.6104 / 25 / 3.516 / 3.493 |
| youki-2756 | B-P | — / — / — / 3.238 / 2.410 | I-O | 37.919 / — / 1 / 22.716 / 0.928 | I-O | 794.948 / 0.9713 / 28 / 13.220 / 7.568 |
| youki-2994 | T+ | — / — / — / 10.005 / 10.002 | E-D | 37.808 / — / 1 / 0.507 / 0.491 | S | 270.567 / 0.4163 / 18 / 5.370 / 4.701 |
| youki-3132 | T+ | — / — / — / 10.004 / 10.002 | B-P | 37.173 / — / 1 / 1.193 / 0.366 | I-C | 415.164 / 0.5537 / 20 / 6.420 / 5.747 |
| youki-3186 | B-E | — / — / — / 5.275 / 5.270 | B-E | 49.830 / — / 1 / 1.124 / 1.105 | B-E | 587.438 / 0.7269 / 28 / 7.073 / 7.066 |
| youki-3198 | T0 | — / — / — / 10.002 / 10.000 | B-E | 44.647 / — / 1 / 0.456 / 0.441 | B-E | 131.704 / 0.3061 / 14 / 2.115 / 2.108 |
| youki-3199 | B-E | — / — / — / 2.170 / 2.165 | B-E | 43.455 / — / 1 / 0.756 / 0.740 | B-E | 571.259 / 0.7365 / 24 / 6.251 / 6.245 |
| youki-3266 | T+ | — / — / — / 10.004 / 10.002 | E-D | 50.742 / — / 1 / 0.445 / 0.435 | B-E | 400.265 / 0.5593 / 21 / 6.315 / 6.308 |
| youki-3293 | T+ | — / — / — / 10.004 / 10.002 | B-E | 53.082 / — / 1 / 1.148 / 1.133 | B-E | 180.139 / 0.4033 / 17 / 5.081 / 5.074 |
| youki-3320 | E-P | — / — / — / 1.954 / 1.952 | S | 54.789 / — / 1 / 2.820 / 0.915 | S | 533.335 / 0.6957 / 23 / 4.931 / 4.900 |
| youki-3428 | B-P | — / — / — / 2.400 / 1.874 | B-P | 55.229 / — / 1 / 1.516 / 0.685 | X+ | 877.908 / 0.9405 / 29 / 7.937 / 7.930 |
| youki-3431 | E-$ | — / — / — / 3.584 / 3.581 | S | 52.489 / — / 1 / 9.119 / 0.576 | T+ | 620.130 / 0.8266 / 26 / 10.005 / 10.001 |

## 5. 可用于论文表格的统一汇总

| Baseline | Success | Evaluated | Success/All | Token_k | Cost_USD | #R | Time_m | Agent_m |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MetaGPT | 3 | 7 raw oracle verdicts | 3/31 (9.7%) | — | — | — | 191.391 | 182.138 |
| Agentless | 3 | 17 raw oracle verdicts | 3/31 (9.7%) | 2227.041 | — | 31 | 91.649 | 23.130 |
| mini-SWE-agent | 8 | 19 raw oracle verdicts | 8/31 (25.8%) | 14471.034¹ | 20.4221¹ | 690¹ | 167.053 | 150.290 |

¹ `youki-3431` 超时后，最终 trajectory 比 metadata 多记录 1 次调用及相应累计 Cost；Token 只包含已落盘的 25 条 response usage，属于可恢复下界。

论文中可以报告 Agentless 的 3/31 和 mini-SWE-agent 的 8/31，但应同时披露：

- Agentless 路径规范化修复后，补丁生成覆盖率由 3/31 提升至 26/31；剩余 5 个无补丁结果来自 top-5 定位文件未覆盖模型选择的目标文件。
- Agentless 未得到 raw oracle verdict 的 14/31 个 case，有明确的定位覆盖、构建失败或 Oracle 超时来源；不能归为未运行、无日志或 deduplication。
- Agentless 的 14 个 raw oracle fail 中有 7 个被 rootless 环境阻断；可确认的成功数是 3，但 raw fail 不应全部解释为算法修复失败。
- mini-SWE-agent 未得到 raw oracle verdict 的 12/31 个 case，有明确的构建环境、oracle 清理、终止或超时来源。
- Agentless 和 mini-SWE-agent 使用 `gpt-5.5`，MetaGPT 使用 `deepseek-v4-flash`，成功率和成本数据不构成严格控制变量实验。
- MetaGPT 的 usage/cost 缺失，Agentless 的实际 Cost 缺失，因此不能比较完整的三 baseline Token、Cost 和调用效率。
