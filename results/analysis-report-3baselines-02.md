# OCI 三 Baseline 重跑结果分析（第二版）

分析目录：`results/oci-metagpt-agentless-mini-rerun/`

## 1. 结论

- 三个 baseline 均有 31/31 个 case 目录和 `metadata.json`，目录覆盖率均为 100%，不存在未运行或缺失 metadata 的 case。
- MetaGPT 通过 3 个 case：`crun-13`、`crun-237`、`crun-453`，成功率为 3/31（9.7%）。
- Agentless 的 31 个 case 均成功调用 LLM，但只有 3 个生成可应用的 git diff；2 个进入 oracle 后受 rootless 环境影响，另 1 个因 Rust toolchain 缺失而构建失败。可靠通过数为 0/31。
- mini-SWE-agent 的 31 个 case 均启动 Agent，8 个通过 oracle，成功率为 8/31（25.8%）；另有 11 个 raw oracle fail、8 个构建环境失败、2 个 oracle 清理崩溃、1 个进程被终止和 1 个超时。
- Agentless 的 28 个无补丁结果不是未运行、环境启动失败或 deduplication 过滤：其中 27 个是模型返回绝对路径，而适配器只接受相对路径；`runc-3944` 是 SEARCH 块未匹配源码。
- Agentless 的 31 条 repair log 各有 1 个 Completion ID，共 31 个唯一 ID，没有重复请求被去重。
- 本轮 Agentless 和 mini-SWE-agent 使用 RootFlowAI 的 `gpt-5.5`；保留的 MetaGPT 结果使用 DeepSeek `deepseek-v4-flash`。因此三者不是同模型、同供应商条件下的严格横向比较。

## 2. 指标定义与覆盖率

- `Token_k = total_tokens / 1000`。
- `Time_m = pipeline_elapsed_seconds / 60`，包含准备、Agent、补丁、构建和 oracle。
- `Agent_m = agent_elapsed_seconds / 60`，仅包含 baseline 命令运行时间。
- `#R` 表示实际 LLM API 调用次数，不使用配置最大轮数替代。
- `—` 表示结果中没有可靠数据。
- Oracle pass/fail 是 runner 的原始判定；受到 rootless、清理权限或严格 stdout/stderr 比较影响的结果另行标注。

| Baseline | Case/Metadata | 进入 Agent | Oracle pass | Raw oracle fail | Token 覆盖 | Cost 覆盖 | #R 覆盖 | Pipeline 总 Time_m | Agent 总 Time_m |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| MetaGPT | 31/31 | 31 | 3 | 4 | 0/31 | 0/31 | 0/31 | 191.391 | 182.138 |
| Agentless | 31/31 | 31 | 0 | 2 | 31/31 | 0/31 | 31/31 | 26.376 | 26.031 |
| mini-SWE-agent | 31/31 | 31 | 8 | 11 | 31/31 | 31/31 | 31/31 | 167.053 | 150.290 |
| 合计 | 93/93 | 93 | 11 | 17 | 62/93 | 31/93 | 62/93 | 384.820 | 358.459 |

指标总量：

- Agentless：2,171,244 prompt tokens、66,321 completion tokens、2,237,565 total tokens，31 次 LLM 调用；日志未提供可靠实际 Cost。
- mini-SWE-agent：14,270,735 prompt tokens、200,299 completion tokens、14,471,034 total tokens，690 次 LLM 调用，框架记录 Cost 为 20.422083 USD。
- 两个有 usage 数据的 baseline 合计为 16,708,599 tokens、721 次 LLM 调用。由于 MetaGPT 和 Agentless 缺失 Cost，不能给出三个 baseline 的完整总 Cost。

mini-SWE-agent 的 `youki-3431` 在超时边界存在写入竞争：metadata 记录 25 次调用、0.766182 USD，最终 `trajectory.json` 的累计统计为 26 次调用、0.826580 USD。本报告对 `#R` 和 Cost 使用最终累计值；Token 仍只能汇总 25 条已序列化 response usage，因此 14,471,034 是可恢复的下界。

mini-SWE-agent 的 Cost 是框架/LiteLLM 写入的 `instance_cost`，不是与 RootFlowAI 账单独立核对后的实际扣费。Agentless 虽有完整 Token usage，但中转站响应和日志没有可靠的实际扣费字段，故 Cost 保持 `—`，不按公开模型价格估算。

## 3. 结果与失败原因分类

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

| 分类 | 数量 | Cases | 证据与解释 |
|---|---:|---|---|
| 适配器后处理无 git diff | 27 | 除 `runc-2430`, `runc-2928`, `runc-3944`, `youki-3293` 外的 27 个 case | LLM 返回绝对 worktree 路径；适配器的可编辑文件表只含相对路径，日志出现 `edited_file not found after normalize`，最终 diff 为空 |
| SEARCH 块未匹配 | 1 | `runc-3944` | repair response 使用相对路径，但 SEARCH 内容与源码不匹配；fallback parser 报错后未生成 diff |
| rootless/严格比较不确定 | 2 | `runc-2430`, `runc-2928` | 已生成补丁并构建成功，但 reference 与 candidate 均被 rootless 环境阻断；stderr 前缀或 mount 警告差异触发 raw oracle fail |
| 构建环境失败 | 1 | `youki-3293` | 已生成补丁，但 Rust toolchain `1.89.0` 缺少 manifest |
| 修复成功 | 0 | — | 无可靠 oracle pass |

31 个 Agentless 命令均返回 0、均有唯一 Completion ID 和 usage，说明模型调用已经跑通。主要失败点位于 Agentless OCI 适配器的路径规范化和补丁解析阶段，而不是缺少依赖、没有调用模型或 deduplication。

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

mini-SWE-agent 的 31 个 case 均留下非空 git diff。未得到 raw oracle verdict 的 12 个结果来自 8 个构建环境失败、2 个 oracle 清理崩溃、1 个进程终止和 1 个超时；不存在未运行、超时无日志或 deduplication 过滤。

## 4. 逐 Case 状态与指标

指标单元格顺序为 `Token_k / Cost_USD / #R / Time_m / Agent_m`。

状态代码：

- `S`：oracle pass。
- `F-B`：候选行为与 reference 明确或原始不一致。
- `I-R`：rootless 环境导致结果不确定；`I-C`：严格 stderr 比较导致结果不确定。
- `I-O`：oracle 环境崩溃。
- `T+`：超时且有部分补丁；`T0`：超时且无补丁；`X+`：进程被终止且有部分补丁。
- `E-P`：Agent 命令/JSON 协议崩溃；`E-N`：API 网络流中断；`E-$`：API 余额不足。
- `E-D`：Agentless 适配器/补丁解析未生成 git diff。
- `B-P`：Agent 补丁导致构建失败；`B-E`：构建环境或工具链失败。

| Case | MetaGPT | MetaGPT 指标 | Agentless | Agentless 指标 | mini | mini 指标 |
|---|---|---|---|---|---|---|
| crun-1083 | T+ | — / — / — / 10.005 / 10.002 | E-D | 121.088 / — / 1 / 0.958 / 0.954 | S | 100.662 / 0.2133 / 11 / 3.456 / 2.489 |
| crun-1099 | B-P | — / — / — / 5.880 / 4.715 | E-D | 117.636 / — / 1 / 1.621 / 1.617 | F-B | 511.243 / 0.6503 / 21 / 4.489 / 4.103 |
| crun-1161 | T0 | — / — / — / 10.004 / 10.002 | E-D | 115.743 / — / 1 / 0.291 / 0.287 | B-E | 1150.246 / 1.3599 / 35 / 7.860 / 7.567 |
| crun-129 | T0 | — / — / — / 10.004 / 10.002 | E-D | 75.919 / — / 1 / 1.095 / 1.093 | F-B | 921.290 / 1.0726 / 27 / 5.679 / 5.431 |
| crun-13 | S | — / — / — / 4.087 / 3.876 | E-D | 66.849 / — / 1 / 0.890 / 0.887 | S | 778.832 / 1.0045 / 28 / 6.612 / 6.356 |
| crun-1307 | E-P | — / — / — / 2.273 / 2.271 | E-D | 115.957 / — / 1 / 0.270 / 0.266 | B-E | 295.660 / 0.4233 / 20 / 3.997 / 3.699 |
| crun-1783 | I-O | — / — / — / 10.246 / 4.954 | E-D | 143.555 / — / 1 / 0.621 / 0.617 | I-O | 384.468 / 0.6319 / 22 / 10.353 / 4.974 |
| crun-1943 | F-B | — / — / — / 2.849 / 2.551 | E-D | 153.708 / — / 1 / 0.801 / 0.797 | F-B | 272.756 / 0.5055 / 18 / 4.079 / 3.764 |
| crun-237 | S | — / — / — / 3.926 / 3.715 | E-D | 83.764 / — / 1 / 0.730 / 0.727 | S | 344.342 / 0.6124 / 19 / 4.044 / 3.476 |
| crun-353 | T+ | — / — / — / 10.001 / 10.000 | E-D | 83.642 / — / 1 / 1.609 / 1.606 | B-E | 626.518 / 0.9222 / 27 / 4.648 / 4.434 |
| crun-453 | S | — / — / — / 2.719 / 2.497 | E-D | 88.266 / — / 1 / 0.444 / 0.441 | S | 366.187 / 0.5512 / 22 / 3.866 / 3.595 |
| crun-876 | F-B | — / — / — / 3.566 / 3.264 | E-D | 104.245 / — / 1 / 0.873 / 0.869 | F-B | 354.403 / 0.5771 / 24 / 4.313 / 4.008 |
| runc-2430 | T0 | — / — / — / 10.006 / 10.002 | I-R | 49.173 / — / 1 / 1.132 / 1.022 | I-R | 623.667 / 0.8596 / 24 / 4.847 / 4.826 |
| runc-2928 | I-R | — / — / — / 4.588 / 4.519 | I-R | 53.550 / — / 1 / 0.963 / 0.905 | I-R | 158.118 / 0.3838 / 14 / 2.823 / 2.799 |
| runc-3020 | B-P | — / — / — / 2.602 / 2.588 | E-D | 52.659 / — / 1 / 0.615 / 0.605 | I-R | 292.543 / 0.5365 / 19 / 3.414 / 3.392 |
| runc-3944 | E-P | — / — / — / 5.303 / 5.300 | E-D | 62.326 / — / 1 / 0.549 / 0.540 | S | 159.946 / 0.3654 / 15 / 1.858 / 1.833 |
| runc-4014 | I-R | — / — / — / 7.608 / 7.551 | E-D | 53.442 / — / 1 / 0.618 / 0.609 | I-R | 665.634 / 0.9251 / 27 / 5.420 / 5.398 |
| runc-4772 | T+ | — / — / — / 10.005 / 10.002 | E-D | 54.594 / — / 1 / 1.305 / 1.297 | S | 224.219 / 0.5343 / 22 / 4.203 / 4.173 |
| runc-5073 | E-P | — / — / — / 5.115 / 5.112 | E-D | 58.845 / — / 1 / 0.411 / 0.401 | I-R | 400.256 / 0.5467 / 22 / 2.858 / 2.835 |
| runc-5182 | E-N | — / — / — / 1.963 / 1.959 | E-D | 62.693 / — / 1 / 0.609 / 0.599 | I-R | 457.187 / 0.6104 / 25 / 3.516 / 3.493 |
| youki-2756 | B-P | — / — / — / 3.238 / 2.410 | E-D | 38.389 / — / 1 / 0.693 / 0.683 | I-O | 794.948 / 0.9713 / 28 / 13.220 / 7.568 |
| youki-2994 | T+ | — / — / — / 10.005 / 10.002 | E-D | 38.581 / — / 1 / 0.675 / 0.668 | S | 270.567 / 0.4163 / 18 / 5.370 / 4.701 |
| youki-3132 | T+ | — / — / — / 10.004 / 10.002 | E-D | 39.416 / — / 1 / 0.997 / 0.990 | I-C | 415.164 / 0.5537 / 20 / 6.420 / 5.747 |
| youki-3186 | B-E | — / — / — / 5.275 / 5.270 | E-D | 49.707 / — / 1 / 1.022 / 1.015 | B-E | 587.438 / 0.7269 / 28 / 7.073 / 7.066 |
| youki-3198 | T0 | — / — / — / 10.002 / 10.000 | E-D | 44.050 / — / 1 / 1.013 / 1.006 | B-E | 131.704 / 0.3061 / 14 / 2.115 / 2.108 |
| youki-3199 | B-E | — / — / — / 2.170 / 2.165 | E-D | 44.017 / — / 1 / 0.990 / 0.983 | B-E | 571.259 / 0.7365 / 24 / 6.251 / 6.245 |
| youki-3266 | T+ | — / — / — / 10.004 / 10.002 | E-D | 50.075 / — / 1 / 0.209 / 0.202 | B-E | 400.265 / 0.5593 / 21 / 6.315 / 6.308 |
| youki-3293 | T+ | — / — / — / 10.004 / 10.002 | B-E | 53.872 / — / 1 / 2.530 / 2.519 | B-E | 180.139 / 0.4033 / 17 / 5.081 / 5.074 |
| youki-3320 | E-P | — / — / — / 1.954 / 1.952 | E-D | 54.197 / — / 1 / 0.699 / 0.693 | S | 533.335 / 0.6957 / 23 / 4.931 / 4.900 |
| youki-3428 | B-P | — / — / — / 2.400 / 1.874 | E-D | 55.492 / — / 1 / 0.732 / 0.725 | X+ | 877.908 / 0.9405 / 29 / 7.937 / 7.930 |
| youki-3431 | E-$ | — / — / — / 3.584 / 3.581 | E-D | 52.115 / — / 1 / 0.412 / 0.405 | T+ | 620.130 / 0.8266 / 26 / 10.005 / 10.001 |

## 5. 可用于论文表格的统一汇总

| Baseline | Success | Evaluated | Success/All | Token_k | Cost_USD | #R | Time_m | Agent_m |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MetaGPT | 3 | 7 raw oracle verdicts | 3/31 (9.7%) | — | — | — | 191.391 | 182.138 |
| Agentless | 0 | 2 raw oracle verdicts，均有环境不确定性 | 0/31 (0.0%) | 2237.565 | — | 31 | 26.376 | 26.031 |
| mini-SWE-agent | 8 | 19 raw oracle verdicts | 8/31 (25.8%) | 14471.034¹ | 20.4221¹ | 690¹ | 167.053 | 150.290 |

¹ `youki-3431` 超时后，最终 trajectory 比 metadata 多记录 1 次调用及相应累计 Cost；Token 只包含已落盘的 25 条 response usage，属于可恢复下界。

论文中可以报告 Agentless 的 0/31 和 mini-SWE-agent 的 8/31，但应同时披露：

- Agentless 的主要瓶颈是 OCI 适配器未正确处理模型输出的绝对路径，28/31 个结果没有形成可评测补丁。
- mini-SWE-agent 未得到 raw oracle verdict 的 12/31 个 case，有明确的构建环境、oracle 清理、终止或超时来源；不能笼统归为算法修复失败。
- Agentless 和 mini-SWE-agent 使用 `gpt-5.5`，MetaGPT 使用 `deepseek-v4-flash`，成功率和成本数据不构成严格控制变量实验。
- MetaGPT 的 usage/cost 缺失，Agentless 的实际 Cost 缺失，因此不能比较完整的三 baseline Token、Cost 和调用效率。
