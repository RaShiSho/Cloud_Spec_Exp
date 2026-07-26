# OCI RepairAgent 最终实验结果分析

分析目录：`results/oci-repairagent/repairagent/`

分析日期：2026-07-26

本报告沿用 `analysis-report-3baselines-03.md` 的指标定义和失败分类方式，以每个 case 顶层的 `metadata.json`、`oracle.json` 为结果判定依据，并使用 `repairagent-output/repairagent-runs/` 中的模型响应、状态上下文和候选补丁记录校正 RepairAgent 特有的调用次数边界。

## 1. 结论

- RepairAgent 共有 32/32 个 case 目录和 `metadata.json`，包含新增的 `runc-4769`，目录覆盖率为 100%。
- 8 个 case 通过 Oracle：`crun-13`、`crun-1161`、`crun-237`、`crun-453`、`youki-3198`、`youki-3320`、`youki-3428`、`youki-3431`，成功率为 8/32（25.0%）。
- 30/32 个 case 保留了非空候选补丁，RepairAgent launcher 正常完成，且外层构建全部通过；其中 29 个得到 raw Oracle verdict，另有 `crun-1783` 在 Oracle 阶段总超时。
- 其余 2 个 case（`youki-3186`、`youki-3266`）没有保留补丁。两者均先受本地 Rust `1.89.0` toolchain manifest 缺失影响，候选构建失败并回滚，随后上游 RepairAgent 在构造 suggested fixes prompt 时因 `TypeError` 崩溃。
- 21 个 raw Oracle fail 中，11 个可观察到候选行为与 reference 明确不一致，9 个 runc case 被 rootless user namespace 环境阻断，`youki-3132` 仅因 reference 独有的 ambient capability warning 触发严格 stderr 比较失败。
- RepairAgent 的自动完成机制按预期工作：30 个保留补丁并构建通过的 case 均记录 `completion_reason=retained_candidate_build_passed`，没有再次出现成功候选后的空转或 baseline timeout。
- 可恢复的 API usage 为 6,091,218 prompt tokens、111,428 completion tokens、合计 6,202,646 tokens；由于正常完成信号发生在末周期 usage 输出之前，该总量是下界。
- 校正后的实际 LLM API 调用数为 497，而不是顶层 metadata 中的 417。差额由 30 次自动完成前的末次调用和 50 次重复命令 re-prompt 构成。
- Cost 无可靠数据。`gpt-5.5` 不在上游 RepairAgent 的价格表中，框架虽然打印 `$0.0000`，同时明确输出 `Unknown model 'gpt-5.5' for cost tracking, skipping`；因此不能把 0 视为实际费用。

## 2. 指标定义、数据来源与覆盖率

- `Token_k = total_tokens / 1000`。
- `Time_m = pipeline_elapsed_seconds / 60`，包含准备、Agent、补丁收集、外层构建和 Oracle。
- `Agent_m = agent_elapsed_seconds / 60`，仅包含 baseline 命令运行时间。
- `#R` 表示实际 LLM API 调用次数，不使用 `max_cycles=40` 代替。
- `Patch_B` 为顶层 `metadata.json` 中记录的候选 git diff 字节数。
- `≥` 表示该 Token 数是可恢复下界。
- `—` 表示结果中没有可靠数据。
- Oracle pass/fail 是 runner 的原始判定；受到 rootless、严格 stderr 比较或 Oracle 超时影响的结果另行标注。

### 2.1 数据源职责

| 数据源 | 本报告使用内容 | 不能替代的内容 |
|---|---|---|
| 顶层 `metadata.json` | pipeline 状态、补丁大小、构建结果、raw Oracle 状态、Token 累计快照、耗时 | 自动完成前的末次 usage、重复请求的准确调用次数 |
| 顶层 `oracle.json` | base/buggy 两组 reference 与 candidate 的退出码、stdout、stderr 和最终 verdict | 未生成 Oracle 文件的超时或 baseline 失败 |
| `repairagent-runs/.../responses/model_responses_oci_1` | 已选择的逐周期模型响应、末周期响应存在性、命令轨迹 | 单次 usage；重复检测后被替换的首次响应 |
| `repairagent-runs/.../saved_contexts/saved_context_oci_1` | FSM 状态、历史命令、读取与搜索轨迹、候选失败上下文 | 外层构建和 Oracle verdict |
| `repairagent-runs/.../plausible_patches/plausible_patches_oci_1.json` | plausible patch 的来源、内容和数量 | 外层 Oracle 的行为正确性 |
| `hyperparams.json`、`model_logging_temp.txt` | 最大周期、重复处理策略、模型和温度等复现实验参数 | 实际 `#R`、Token、Cost 和耗时 |

### 2.2 覆盖率与总量

| Baseline | Case/Metadata | 进入 Agent | 非空补丁 | 外层构建通过 | Raw Oracle verdict | Oracle pass | Token 覆盖 | Cost 覆盖 | #R 覆盖 | Pipeline 总 Time_m | Agent 总 Time_m |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RepairAgent | 32/32 | 32 | 30 | 30 | 29 | 8 | 32/32¹ | 0/32 | 32/32 | 154.919 | 116.156 |

指标总量：

- Prompt tokens：6,091,218。
- Completion tokens：111,428。
- Total tokens：6,202,646¹。
- 实际 LLM API 调用：497。
- 非空候选补丁：30/32（93.8%）。
- raw Oracle verdict：29/32（90.6%）。
- Oracle pass：8/32（25.0%）；若只以取得 raw verdict 的 case 为分母，则为 8/29（27.6%），但论文主结果应使用 8/32。

¹ 30 个正常完成的 case 在修复命令执行并保存 plausible patch 后，由 adapter 抛出内部完成信号；控制流因此没有到达上游每周期末尾的 Token 汇总打印。末次 API usage 无法从响应文件恢复，故逐 case 和总 Token 均是下界。`youki-3186`、`youki-3266` 在下一周期构造 prompt 时崩溃，没有发出新的 API 请求，其已打印累计 usage 不受这一边界影响。

### 2.3 `#R` 校正

顶层 metrics 中的 `llm_calls=417` 是 runner 对 `Tokens: ... | Cost: ...` 周期累计行的计数，不等于真实 API 请求数。根据上游交互循环、RepairAgent 轨迹和 adapter 完成记录：

- 417 次：执行完命令并打印周期 usage 的调用。
- 30 次：成功候选触发自动完成，末周期模型响应已保存，但 usage 行未打印。
- 50 次：`repetition_handling=RESTRICT` 检测到重复命令后额外发起的 re-prompt。日志每次检测会分别在检测函数和调用方打印一次 warning，因此 100 条 `REPETITION DETECTED!` 对应 50 次额外请求。
- 最终 `#R = 417 + 30 + 50 = 497`。

Token 累计器会纳入已经完成的 repetition re-prompt usage，因此不能把 50 次请求的 Token 简单再次相加；缺失的只有触发 adapter 自动完成但尚未打印累计行的末周期 usage。

## 3. 结果与失败原因分类

| 分类 | 状态码 | 数量 | Cases | 证据与解释 |
|---|---|---:|---|---|
| 修复成功 | `S` | 8 | `crun-13`, `crun-1161`, `crun-237`, `crun-453`, `youki-3198`, `youki-3320`, `youki-3428`, `youki-3431` | base 与 buggy 配置均和 reference 一致 |
| 明确/原始行为不匹配 | `F-B` | 11 | `crun-1083`, `crun-1099`, `crun-129`, `crun-1307`, `crun-1943`, `crun-353`, `crun-876`, `youki-2756`, `youki-2994`, `youki-3199`, `youki-3293` | buggy 行为或 base 行为的退出码、stdout、stderr 与 reference 明确不同 |
| rootless 环境/比较不确定 | `I-R` | 9 | `runc-2430`, `runc-2928`, `runc-3020`, `runc-3944`, `runc-4014`, `runc-4769`, `runc-4772`, `runc-5073`, `runc-5182` | reference 或 candidate 被 `rootless container requires user namespaces` 阻断；时间戳、runtime 路径、错误前缀或补丁副作用触发 raw fail |
| 严格 stderr 比较不确定 | `I-C` | 1 | `youki-3132` | 两侧退出码均为 0 且 stdout 均为空；reference 有 ambient capability warning，candidate 无 stderr |
| Oracle 总超时 | `I-O` | 1 | `crun-1783` | Agent 正常完成、689-byte 补丁保留、外层构建通过；Oracle 外层运行 1200 秒后超时，未生成 `oracle.json` |
| Agent/FSM 崩溃 | `E-P` | 2 | `youki-3186`, `youki-3266` | Rust toolchain 缺失导致候选回滚后，上游 `construct_suggested_fixes()` 把 list 当作 dict，抛出 `TypeError: list indices must be integers or slices, not str` |

### 3.1 明确行为不匹配的主要表现

- `crun-1083`：reference 输出 memory limit `67108864`，candidate 输出 `max`。
- `crun-1099`：reference 仍产生预期 device 输出，candidate 在 `mknod /dev/net/tun` 处报 `Operation not permitted`。
- `crun-129`、`crun-1307`、`crun-353`：candidate 的 hook/mount 错误路径、退出码或错误文本仍与 reference 不一致。
- `crun-1943`：reference 返回 1 且无 stdout，candidate 返回 255 并输出 `poststart-false-1943`。
- `crun-876`：reference 在 cgroup 写入阶段失败，candidate 成功运行并输出 `cpu-idle-876` 和 `1`，raw 行为不一致。
- `youki-2756`：candidate 的 `youki exec` 命令行解析失败，无法接受 `-c`。
- `youki-2994`：candidate 输出的 OCI state 版本、状态、路径和附加字段与 reference 不一致。
- `youki-3199`：reference 在 buggy 配置输出 `i686`，candidate 仍输出 `x86_64`。
- `youki-3293`：reference capability mask 为 `0000000020000420`，candidate 为 `0000000020000020`。

### 3.2 流程是否跑通

从 adapter 和 runner 的工程流程看，实验主体已经跑通：

1. 32 个 case 全部创建 worktree 并进入 RepairAgent。
2. 30 个 case 生成候选、完成内部构建验证、保存 plausible patch，并由 adapter 正常结束。
3. 这 30 个候选全部通过外层独立构建。
4. 29 个进入并完成 Oracle，得到 8 pass 和 21 fail。
5. `crun-1783` 的失败点已推进到 Oracle，而不是 RepairAgent baseline。

但不能把本轮描述为“32 个 case 全部完成端到端有效评测”：

- 2 个 case 在 baseline 内崩溃，未产生可评测候选。
- 1 个 case 的 Oracle 总超时，缺少 verdict。
- 9 个 runc raw fail 被 rootless 环境阻断，无法据此确认目标缺陷是否修复。
- 1 个 youki raw fail 仅来自严格 stderr warning 差异，算法结论存在不确定性。

因此可确认的下界是 8 个成功；可确认的明确行为失败是 11 个；其余 13 个应保留环境、比较规则或框架失败标签。

## 4. 逐 Case 状态与指标

状态代码：

- `S`：Oracle pass。
- `F-B`：候选行为与 reference 明确或原始不一致。
- `I-R`：rootless 环境导致结果不确定。
- `I-C`：严格 stderr 比较导致结果不确定。
- `I-O`：Oracle 总超时或未生成结果。
- `E-P`：Agent/FSM prompt 或协议处理崩溃。

| Case | 状态 | Token_k | Cost_USD | #R | Time_m | Agent_m | Patch_B |
|---|---|---:|---:|---:|---:|---:|---:|
| crun-1083 | F-B | ≥342.840 | — | 26 | 5.021 | 4.576 | 1670 |
| crun-1099 | F-B | ≥127.995 | — | 13 | 3.976 | 3.530 | 719 |
| crun-1161 | S | ≥372.368 | — | 24 | 5.822 | 5.369 | 665 |
| crun-129 | F-B | ≥129.708 | — | 14 | 3.237 | 2.945 | 922 |
| crun-13 | S | ≥89.480 | — | 11 | 4.129 | 3.823 | 800 |
| crun-1307 | F-B | ≥42.439 | — | 7 | 5.163 | 4.708 | 1371 |
| crun-1783 | I-O | ≥16.011 | — | 4 | 23.667 | 3.244 | 689 |
| crun-1943 | F-B | ≥117.425 | — | 13 | 4.210 | 3.732 | 743 |
| crun-237 | S | ≥568.330 | — | 32 | 5.942 | 5.594 | 2332 |
| crun-353 | F-B | ≥413.807 | — | 28 | 6.080 | 5.745 | 581 |
| crun-453 | S | ≥13.875 | — | 4 | 2.547 | 2.203 | 651 |
| crun-876 | F-B | ≥295.782 | — | 23 | 5.142 | 4.691 | 889 |
| runc-2430 | I-R | ≥394.599 | — | 24 | 3.916 | 3.887 | 865 |
| runc-2928 | I-R | ≥24.614 | — | 5 | 1.085 | 1.056 | 781 |
| runc-3020 | I-R | ≥17.270 | — | 4 | 0.630 | 0.601 | 1243 |
| runc-3944 | I-R | ≥60.582 | — | 8 | 1.259 | 1.231 | 1027 |
| runc-4014 | I-R | ≥343.250 | — | 24 | 2.863 | 2.833 | 2713 |
| runc-4769 | I-R | ≥501.926 | — | 28 | 4.189 | 4.148 | 1434 |
| runc-4772 | I-R | ≥65.605 | — | 9 | 1.217 | 1.187 | 944 |
| runc-5073 | I-R | ≥28.287 | — | 5 | 0.875 | 0.844 | 1186 |
| runc-5182 | I-R | ≥136.709 | — | 15 | 1.606 | 1.574 | 632 |
| youki-2756 | F-B | ≥48.096 | — | 7 | 2.912 | 2.857 | 1735 |
| youki-2994 | F-B | ≥36.374 | — | 6 | 3.635 | 3.594 | 1591 |
| youki-3132 | I-C | ≥303.740 | — | 22 | 5.259 | 5.223 | 848 |
| youki-3186 | E-P | 329.067 | — | 22 | 3.815 | 3.810 | 0 |
| youki-3198 | S | ≥274.215 | — | 25 | 11.327 | 4.623 | 993 |
| youki-3199 | F-B | ≥172.407 | — | 15 | 4.534 | 4.498 | 2154 |
| youki-3266 | E-P | 37.465 | — | 5 | 1.205 | 1.201 | 0 |
| youki-3293 | F-B | ≥338.884 | — | 25 | 5.999 | 5.961 | 1352 |
| youki-3320 | S | ≥29.591 | — | 5 | 4.148 | 4.108 | 631 |
| youki-3428 | S | ≥394.158 | — | 30 | 7.770 | 7.721 | 2538 |
| youki-3431 | S | ≥135.747 | — | 14 | 11.740 | 5.034 | 665 |

## 5. 按 Runtime 汇总

| Runtime | Success | All | Success/All | Token_k | Cost_USD | #R | Time_m | Agent_m |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| crun | 4 | 12 | 4/12（33.3%） | ≥2530.060 | — | 199 | 74.935 | 50.163 |
| runc | 0 | 9 | 0/9（0.0%） | ≥1572.842 | — | 122 | 17.640 | 17.361 |
| youki | 4 | 11 | 4/11（36.4%） | ≥2099.744 | — | 176 | 62.344 | 48.632 |
| 合计 | 8 | 32 | 8/32（25.0%） | ≥6202.646 | — | 497 | 154.919 | 116.156 |

runc 的 0/9 不能直接解释为 RepairAgent 对 Go 项目的修复能力为 0：9 个 case 的 reference 或 candidate 均遇到 rootless user namespace 阻断，本轮没有一个 runc case 在目标行为层面得到有效的 pass/fail 比较。它们应在修复权限环境后重新执行 Oracle。

## 6. 可用于论文表格的统一汇总

| Baseline | Success | Evaluated | Success/All | Token_k | Cost_USD | #R | Time_m | Agent_m | Patch coverage |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RepairAgent | 8 | 29 raw Oracle verdicts | 8/32（25.0%） | ≥6202.646¹ | — | 497² | 154.919 | 116.156 | 30/32（93.8%） |

论文或横向比较中应同时披露：

- RepairAgent 使用 `gpt-5.5`，若与使用不同模型、供应商或修复预算的 baseline 比较，不属于严格控制变量实验。
- 8/32 是可确认成功率；不能把 21 个 raw fail 全部解释为算法失败，其中 9 个受 rootless 环境阻断，1 个仅受严格 stderr warning 比较影响。
- 30/32 个 case 的候选生成、自动完成、外层构建流程已跑通；剩余 2 个是 Rust 工具链与上游 prompt 数据结构共同触发的 baseline 崩溃。
- `crun-1783` 已生成并构建候选，但 Oracle 总超时；它不属于 baseline timeout 或无补丁。
- Cost 缺失，不能根据 `$0.0000` 推断免费，也不应按公开价格自行估算。
- Token 是 30 个自动完成 case 缺失末次 usage 后的可恢复下界；`#R` 已通过内部轨迹和重复检测日志校正。

¹ 正常完成 case 的末次 API usage 未进入累计打印，Token 为下界。

² `#R` 包含 417 个已打印周期、30 个自动完成前末次调用和 50 个重复检测 re-prompt。

## 7. 复现与数据完整性注意事项

- 结果目录中的 `runc-4769/metadata.json` 记录本轮使用的 `source_ref` 为 `8b0e7511cf9207d06803fe8658956f960e13968e`。
- 当前工作区的 `configs/experiment.repairagent.yaml` 尚未包含 `runc-4769` 的 `buggy_ref_by_case` 映射。现有结果可以分析，但在当前 checkout 上不能仅凭该配置精确重跑 32-case 集合；复现实验前应先把数据集确定的 mapping 同步回配置，并核对它与上述 `source_ref` 一致。
- `repairagent-runs/` 不应整体忽略。它不能替代顶层结果，但本报告的末周期调用校正、重复 re-prompt 计数、plausible patch 证明和两个 baseline 崩溃的上下文都依赖这些运行资产。
- 对 runc 9 个 case 的算法结论需要在具备 user namespace/rootless 条件的环境中重跑 Oracle；对 `youki-3132` 应明确决定论文评测是否要求 stderr 字节级一致。
