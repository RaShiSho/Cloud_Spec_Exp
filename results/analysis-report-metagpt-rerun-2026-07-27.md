# MetaGPT 全量重跑实验分析报告

实验结果目录：`results/oci-metagpt-agentless-mini-rerun/metagpt/`

统计日期：2026-07-27

本报告依照 [`oci-final-experiment-report.md`](oci-final-experiment-report.md) 的标准，
重新分析 MetaGPT 全量重跑后的 32 个 case。统计只使用各 case 顶层
`metadata.json`、`oracle.json` 和对应的 `metagpt-output/launcher_metadata.json`，
不计单独生成的 `oracle.retry*.json`。

## 1. 指标与判定口径

| 指标 | 定义 |
|---|---|
| Success | `oracle.json.status == "pass"` |
| Evaluated | 获得 raw Oracle pass/fail；不包含 Oracle error 或未生成 verdict |
| Token_k | 可靠的 `total_tokens / 1000` |
| Cost_USD | 框架明确记录且 Token usage 有效时的成本 |
| #R | 实际触发 MetaGPT usage 更新的 LLM 调用次数 |
| Time_m | 完整 pipeline 时间，包含准备、Agent、补丁、构建和 Oracle |
| Agent_m | 仅 baseline 命令耗时 |
| Patch coverage | `patch_size_bytes > 0` 的 case 数 |

`—` 表示缺少可靠数据。Raw Oracle fail 不自动等于算法修复失败：rootless、reference
超时、严格 stderr/路径/时间戳比较等情况单独归入环境或比较不确定。

## 2. 总体结果

| Baseline | Success | Evaluated | Success/All | Patch | Build pass | Token_k | Cost_USD | #R | Time_m | Agent_m |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| MetaGPT rerun | 5 | 14 | 5/32（15.6%） | 29/32 | 16/32 | — | — | ≥510¹ | 235.443 | 204.637 |

1. 30 个 case 记录了共 510 次调用；`runc-4769` 和 `runc-4772` 在 600 秒超时后没有留下
   `metagpt-output/launcher_metadata.json`，因此全量 `#R` 只能报告为下界。

Agent 阶段占总 pipeline 时间约 86.9%；其余准备、构建和 Oracle 合计约 30.807 分钟。

### 2.1 指标覆盖率

| 数据项 | 覆盖 | 说明 |
|---|---:|---|
| Case 目录与 metadata | 32/32 | 全部 case 均已调度并生成顶层 metadata |
| 非空补丁 | 29/32 | `youki-3198`、`youki-3428`、`youki-3431` 无补丁 |
| 外层构建通过 | 16/32 | 12 个 crun 和 4 个 runc |
| Raw Oracle verdict | 14/32 | 5 pass、9 fail |
| Token | 0/32 | 30 个文件记录为 0，但与 510 次调用矛盾，不视为有效 |
| Cost | 0/32 | 30 个文件记录为 0.0，因 Token usage 无效而不视为有效 |
| #R | 30/32 | 已知 510 次；2 个超时 case 缺失 |
| Pipeline/Agent 时间 | 32/32 | 两类时间均完整 |

### 2.2 Token 与 Cost 采集异常

30 个 `launcher_metadata.json` 均显示：

- 模型为 `gpt-5.5`；
- usage tracking 状态为 `applied`；
- `llm_calls > 0`，合计 510；
- `prompt_tokens == completion_tokens == total_tokens == 0`；
- `cost_usd == 0.0`；
- Cost 来源为显式配置的每千 Token 费率。

这些 0 不能代表真实零消耗。实际原因是 MetaGPT 的 CostManager 确实在每次响应后被调用，
但传给采集器的 prompt/completion usage 均为 0；stdout/stderr 也没有保留可回填的原始
usage。因此：

- 本报告保留 `#R`；
- Token 和 Cost 全部记为 `—`；
- 不使用 `0 Token / 0 USD` 参与汇总或 baseline 比较；
- 现有结果无法通过给定价格可靠回填 Cost。

## 3. 按 Runtime 汇总

| Runtime | Success | Evaluated | Raw fail | Patch | Build pass | #R | Time_m | Agent_m |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| crun | 5/12 | 10/12 | 5 | 12/12 | 12/12 | 232 | 84.776 | 54.473 |
| runc | 0/9 | 4/9 | 4 | 9/9 | 4/9 | ≥133¹ | 52.999 | 52.587 |
| youki | 0/11 | 0/11 | 0 | 8/11 | 0/11 | 145 | 97.669 | 97.577 |
| 合计 | 5/32 | 14/32 | 9 | 29/32 | 16/32 | ≥510 | 235.443 | 204.637 |

1. runc 的 `runc-4769`、`runc-4772` 缺少调用产物。

所有确认成功均来自 crun。runc 的 4 个 raw fail 均受到 rootless user namespace 或严格
动态文本比较影响；youki 的 11 个 case 全部在外层构建和 Oracle 之前结束。

## 4. 逐 Case 结果

| Case | Runtime | 结果 | Build | Patch_B | Token_k | Cost_USD | #R | Time_m | Agent_m | 主要说明 |
|---|---|---|:---:|---:|---:|---:|---:|---:|---:|---|
| `crun-1083` | crun | 成功 | ✓ | 848 | — | — | 16 | 4.589 | 4.121 | Oracle pass |
| `crun-1099` | crun | Raw fail | ✓ | 9785 | — | — | 19 | 5.207 | 4.609 | buggy 行为和退出码不同 |
| `crun-1161` | crun | 成功 | ✓ | 639 | — | — | 20 | 5.959 | 5.492 | Oracle pass |
| `crun-129` | crun | Raw fail | ✓ | 834 | — | — | 24 | 5.277 | 4.881 | 同为 hook 失败，仅 stderr 文本不同 |
| `crun-13` | crun | 成功 | ✓ | 4220 | — | — | 24 | 5.606 | 5.276 | Oracle pass |
| `crun-1307` | crun | Raw fail | ✓ | 742 | — | — | 21 | 5.017 | 4.542 | 同为 mount 失败，仅 stderr 文本不同 |
| `crun-1783` | crun | 未评测 | ✓ | 712 | — | — | 22 | 25.550 | 4.953 | Oracle 总超时 1200 秒 |
| `crun-1943` | crun | Oracle error | ✓ | 1401 | — | — | 16 | 9.805 | 4.299 | reference 的 buggy_config 超时 |
| `crun-237` | crun | 成功 | ✓ | 2814 | — | — | 16 | 3.767 | 3.438 | Oracle pass |
| `crun-353` | crun | Raw fail | ✓ | 368 | — | — | 23 | 5.624 | 5.287 | hook 退出码和 stderr 不同 |
| `crun-453` | crun | 成功 | ✓ | 549 | — | — | 14 | 3.590 | 3.256 | Oracle pass |
| `crun-876` | crun | Raw fail | ✓ | 620 | — | — | 17 | 4.785 | 4.319 | reference cgroup 环境失败，candidate 成功 |
| `runc-2430` | runc | Raw fail | ✓ | 5249 | — | — | 18 | 3.688 | 3.578 | rootless user namespace 阻断 |
| `runc-2928` | runc | 未评测 | — | 2616 | — | — | 24 | 5.426 | 5.416 | Agent 后清理隔离 HOME 权限失败 |
| `runc-3020` | runc | Raw fail | ✓ | 928 | — | — | 18 | 3.093 | 3.024 | rootless user namespace 阻断 |
| `runc-3944` | runc | Raw fail | ✓ | 916 | — | — | 13 | 2.384 | 2.308 | buggy 匹配；base 仅时间戳/前缀不同 |
| `runc-4014` | runc | Raw fail | ✓ | 788 | — | — | 14 | 2.543 | 2.477 | rootless 加路径/时间戳严格比较 |
| `runc-4769` | runc | 未评测 | — | 751 | — | — | — | 10.057 | 10.000 | Agent 600 秒超时，usage 产物缺失 |
| `runc-4772` | runc | 未评测 | — | 1076 | — | — | — | 10.005 | 10.002 | Agent 600 秒超时，usage 产物缺失 |
| `runc-5073` | runc | 未评测 | — | 1774 | — | — | 22 | 8.454 | 8.444 | Agent 后清理 Go toolchain 权限失败 |
| `runc-5182` | runc | 未评测 | — | 783 | — | — | 24 | 7.349 | 7.338 | Agent 后清理 Go toolchain 权限失败 |
| `youki-2756` | youki | 未评测 | — | 6587 | — | — | 13 | 10.019 | 10.002 | Agent 600 秒超时 |
| `youki-2994` | youki | 未评测 | — | 1420 | — | — | 11 | 10.008 | 10.002 | Agent 600 秒超时 |
| `youki-3132` | youki | 未评测 | — | 9120 | — | — | 15 | 10.007 | 10.000 | Agent 600 秒超时 |
| `youki-3186` | youki | 未评测 | — | 23707 | — | — | 13 | 10.008 | 10.002 | Agent 600 秒超时 |
| `youki-3198` | youki | 未评测 | — | 0 | — | — | 12 | 10.009 | 10.002 | Agent 600 秒超时且无补丁 |
| `youki-3199` | youki | 未评测 | — | 6084 | — | — | 14 | 10.008 | 10.002 | Agent 600 秒超时 |
| `youki-3266` | youki | 未评测 | — | 602 | — | — | 10 | 10.008 | 10.002 | Agent 600 秒超时 |
| `youki-3293` | youki | 未评测 | — | 2039 | — | — | 13 | 10.009 | 10.000 | Agent 600 秒超时 |
| `youki-3320` | youki | 未评测 | — | 1243 | — | — | 21 | 10.008 | 10.002 | Agent 600 秒超时 |
| `youki-3428` | youki | 未评测 | — | 0 | — | — | 7 | 4.298 | 4.285 | 上下文超限，最终无补丁 |
| `youki-3431` | youki | 未评测 | — | 0 | — | — | 16 | 3.286 | 3.280 | API 流中断，最终无补丁 |

## 5. 修复成功结果

| Case | Patch_B | #R | Time_m | Agent_m |
|---|---:|---:|---:|---:|
| `crun-1083` | 848 | 16 | 4.589 | 4.121 |
| `crun-1161` | 639 | 20 | 5.959 | 5.492 |
| `crun-13` | 4220 | 24 | 5.606 | 5.276 |
| `crun-237` | 2814 | 16 | 3.767 | 3.438 |
| `crun-453` | 549 | 14 | 3.590 | 3.256 |

与旧最终报告相比，`crun-13`、`crun-237`、`crun-453` 继续通过；本轮新增
`crun-1083` 和 `crun-1161` 两个确认成功 case。

## 6. 失败与不确定结果

| 结果类别 | Case 数 | Case |
|---|---:|---|
| 修复成功 | 5 | `crun-1083`、`crun-1161`、`crun-13`、`crun-237`、`crun-453` |
| 明确行为不匹配 | 2 | `crun-1099`、`crun-353` |
| 严格输出比较或环境不确定 | 7 | `crun-129`、`crun-1307`、`crun-876`、`runc-2430`、`runc-3020`、`runc-3944`、`runc-4014` |
| Oracle 超时或 error | 2 | `crun-1783`、`crun-1943` |
| Agent 600 秒超时 | 11 | `runc-4769`、`runc-4772` 及 9 个 youki case |
| 隔离 HOME/Go cache 清理权限失败 | 3 | `runc-2928`、`runc-5073`、`runc-5182` |
| API 上下文超限或流中断，无补丁 | 2 | `youki-3428`、`youki-3431` |
| 合计 | 32 | — |

### 6.1 Raw fail 的解释

- `crun-1099` 的 buggy 输出和退出码均与 reference 不同，属于明确行为不匹配。
- `crun-353` 的 hook 退出码为 77，而 reference 外层返回 1，同时 stderr 不同，属于明确
  行为不匹配。
- `crun-129`、`crun-1307` 的 reference 与 candidate 均执行失败，主要差异是错误文本。
- `crun-876` 的 reference 因宿主 cgroup 写入失败，而 candidate 成功，不能在当前环境下
  将 raw fail 简单解释为补丁错误。
- 4 个 runc raw fail 均出现 rootless user namespace；`runc-3944` 的 buggy 配置实际匹配，
  只因 base 配置中的动态 stderr 不同而被判 fail。

### 6.2 Agent 和环境失败

- 11 个 case 达到 600 秒 Agent 时限，其中 9 个为 youki。多数超时 case 已留下补丁，但
  runner 按标准不会继续构建和 Oracle。
- 3 个 runc case 的 MetaGPT 工作已产生补丁，最终因隔离 HOME 中 Go module/toolchain
  文件不可删除而返回非零；这属于 wrapper 清理权限问题，不是模型没有生成候选修改。
- `youki-3428` 遇到模型上下文窗口超限，`youki-3431` 遇到不完整 chunked stream；两者
  最终均触发 `NoRepositoryChanges`。

## 7. 与旧最终报告中的 MetaGPT 结果比较

| 指标 | 旧结果 | 本次重跑 | 变化 |
|---|---:|---:|---:|
| Success | 3/32 | 5/32 | +2 |
| Evaluated | 7/32 | 14/32 | +7 |
| Patch coverage | 22/32 | 29/32 | +7 |
| Build pass | 8/32 | 16/32 | +8 |
| Token coverage | 0/32 | 0/32¹ | 无有效改善 |
| Cost coverage | 0/32 | 0/32¹ | 无有效改善 |
| #R coverage | 0/32 | 30/32 | +30 |
| Pipeline Time_m | 201.448 | 235.443 | +33.995 |
| Agent Time_m | 192.138 | 204.637 | +12.499 |

1. 新文件中 Token/Cost 字段非空，但全部为 0；由于存在 510 次 LLM 调用，这些值不满足
   可靠统计条件。

## 8. 结论

本次 MetaGPT 重跑将确认成功数从 3 提升到 5，评测覆盖从 7 提升到 14，补丁覆盖和构建
通过数也明显增加。结果仍高度集中在 crun：runc 被 rootless 和清理权限问题影响，youki
则主要受到 600 秒 Agent 时限、上下文窗口和 API 流稳定性影响。

资源指标方面，`#R` 已能覆盖 30 个 case，但 Token/Cost 采集仍未成功。下一次实验前应先
修复 MetaGPT provider 到 CostManager 之间 usage 恒为 0 的问题，并用单 case 验证
`prompt_tokens > 0`、`completion_tokens > 0` 和 `cost_usd > 0` 后再做全量重跑。
