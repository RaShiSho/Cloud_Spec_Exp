# OCI 容器运行时缺陷自动修复最终实验报告

实验结果目录：

- MetaGPT、Agentless、mini-SWE-agent：`results/oci-metagpt-agentless-mini-rerun/`
- RepairAgent：`results/oci-repairagent/repairagent/`

统计日期：2026-07-26

本报告综合：

- [`analysis-report-3baselines-04.md`](analysis-report-3baselines-04.md)
- [`analysis-report-repairagent-final.md`](analysis-report-repairagent-final.md)

关键总量同时由上述两个结果目录中的 `metadata.json` 和 `oracle.json` 复核。

## 1. 实验运行方式

本实验使用 `scripts/run_oci_experiment.py` 顺序执行 OCI 容器运行时修复任务。每个 baseline × case 均在独立 Git worktree 中运行，避免不同实验之间共享源码改动。

| 阶段 | 执行内容 | 主要产物 |
|---|---|---|
| 1. 选择任务 | 从数据集 `metadata.json` 和配置中的 `buggy_ref_by_case` 选择 case | case、runtime、buggy source ref |
| 2. 准备源码 | 将 runc、crun 或 youki 检出到对应历史缺陷版本的独立 worktree | 隔离的候选源码 |
| 3. 构造提示词 | 合并 issue 信息、`expected_diff.txt`、case README、构建命令和路径约束 | `task.md` |
| 4. 运行 Agent | 在 baseline 专用 Conda 环境中执行修复，单 case 外层时限 600 秒 | Agent 日志、trajectory、候选修改 |
| 5. 收集补丁 | 从 worktree 或 baseline 产物收集非空 Git diff | `patch_size_bytes` |
| 6. 独立构建 | runner 在 Agent 结束后重新构建候选 runtime | build stdout/stderr |
| 7. Oracle 验证 | reference runc 与 candidate 分别运行 `base_config.json`、`buggy_config.json` | `oracle.json` |
| 8. 记录指标 | 汇总 Token、Cost、LLM 调用次数和两类耗时 | `metadata.json` |

Oracle 对退出码、stdout 和 stderr 进行严格比较。仅当 base 和 buggy 两组 candidate 行为均与 reference 完全一致时记为成功。超时、环境错误和未生成补丁不计为成功。

### 1.1 实验规模

| Runtime | Case 数 | 构建命令 | Candidate |
|---|---:|---|---|
| runc | 9 | `make runc` | `runc` |
| crun | 12 | `./autogen.sh && ./configure && make -j$(nproc)` | `crun` |
| youki | 11 | `cargo build --release` | `target/release/youki` |
| 合计 | 32 | — | — |

四个 baseline 均运行全部 32 个 case，共 128 次实验。

### 1.2 Baseline 设置

| Baseline | 实际模型/API | 主要参数 | Conda 环境 |
|---|---|---|---|
| MetaGPT | RootFlowAI `gpt-5.5` | `n_round=10`，`investment=3.0`，`max_auto_summarize_code=0` | `metagpt` |
| Agentless | RootFlowAI `gpt-5.5` | top-5 定位文件，1 sample，diff + CoT，单线程 | `agentless` |
| mini-SWE-agent | RootFlowAI `gpt-5.5` | 默认 `mini.yaml`，保存 trajectory，提交后立即退出 | `mini-swe` |
| RepairAgent | RootFlowAI `gpt-5.5` | `max_cycles=40`，OCI search/edit/build adapter，自动完成 | `repairagent` |

MetaGPT 与其余三个 baseline 使用不同模型和供应商，因此成功率、Token 和耗时不构成严格控制变量比较。保存结果中的 `metadata.json.baseline_result.command` 是实际执行命令的权威记录。

## 2. 指标与判定口径

| 指标 | 定义 |
|---|---|
| Success | `oracle.json.status == "pass"` |
| Evaluated | 获得 raw Oracle pass/fail；不包含 Oracle error |
| Token_k | `total_tokens / 1000` |
| Cost_USD | 框架明确记录的成本；不按模型公开价格推算 |
| #R | 实际 LLM API 调用次数 |
| Time_m | 完整 pipeline 时间，含准备、Agent、补丁、构建和 Oracle |
| Agent_m | 仅 baseline 命令耗时 |
| Patch coverage | `patch_size_bytes > 0` 的 case 数 |

`≥` 表示可恢复下界；`—` 表示缺少可靠数据。标准统计只使用顶层 `metadata.json` 和 `oracle.json`，不计单独生成的 `oracle.retry*.json`。

## 3. 总体结果

| Baseline | Success | Evaluated | Success/All | Patch | Build pass | Token_k | Cost_USD | #R | Time_m | Agent_m |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| MetaGPT | 3 | 7 | 3/32（9.4%） | 22/32 | 8/32 | — | — | — | 201.448 | 192.138 |
| Agentless | 3 | 18 | 3/32（9.4%） | 27/32 | 20/32 | 2282.897 | — | 32 | 92.375 | 23.725 |
| mini-SWE-agent | 8 | 20 | 8/32（25.0%） | 32/32 | 22/32 | ≥14579.485¹ | 20.7023¹ | 702¹ | 169.204 | 152.407 |
| RepairAgent | 8 | 29 | 8/32（25.0%） | 30/32 | 30/32 | ≥6202.646² | — | 497³ | 154.919 | 116.156 |
| 合计 | 22 | 74 | 22/128（17.2%） | 111/128 | 80/128 | ≥23065.028⁴ | — | ≥1231⁴ | 617.946 | 484.427 |

1. mini-SWE-agent 的 `youki-3431` 最终 trajectory 比 metadata 多 1 次调用及相应累计 Cost；Token 缺少该次 response usage。
2. RepairAgent 的 30 个正常完成 case 缺少自动完成前末次 usage，Token 为下界。
3. RepairAgent 的 `#R` 为校正值：417 次已打印周期 + 30 次自动完成前末次调用 + 50 次 repetition re-prompt。
4. 合计 Token 和 `#R` 仅覆盖 Agentless、mini-SWE-agent、RepairAgent；MetaGPT usage 缺失。

mini-SWE-agent 的 Cost 来自框架/LiteLLM 累计值，未与中转站账单独立核对。其他 baseline 没有可靠 Cost，不能计算完整实验总费用。

### 3.1 指标覆盖率

| 数据项 | MetaGPT | Agentless | mini-SWE-agent | RepairAgent | 总覆盖 |
|---|---:|---:|---:|---:|---:|
| Case 目录与 metadata | 32/32 | 32/32 | 32/32 | 32/32 | 128/128 |
| Raw Oracle verdict | 7/32 | 18/32 | 20/32 | 29/32 | 74/128 |
| Token | 0/32 | 32/32 | 32/32 | 32/32 | 96/128 |
| Cost | 0/32 | 0/32 | 32/32 | 0/32 | 32/128 |
| #R | 0/32 | 32/32 | 32/32 | 32/32 | 96/128 |

不存在未创建结果目录或缺失 metadata 的 case。未取得 raw verdict 的原因来自 Agent、构建或 Oracle 阶段，而不是实验未调度。

### 3.2 Token 与调用

| Baseline | Prompt tokens | Completion tokens | Total tokens | #R | 平均 Token_k/#R |
|---|---:|---:|---:|---:|---:|
| MetaGPT | — | — | — | — | — |
| Agentless | 2,225,634 | 57,263 | 2,282,897 | 32 | 71.341 |
| mini-SWE-agent | 14,376,121 | 203,364 | ≥14,579,485 | 702 | ≥20.769 |
| RepairAgent | 6,091,218 | 111,428 | ≥6,202,646 | 497 | ≥12.480 |
| 已知合计 | 22,692,973 | 372,055 | ≥23,065,028 | 1,231 | — |

Agentless 每个 case 固定获得 1 次模型 completion；mini-SWE-agent 和 RepairAgent 采用多轮交互。不同框架的单次请求承载内容不同，平均 Token/#R 仅用于描述资源结构。

## 4. 修复成功结果

### 4.1 按 Runtime 汇总

| Baseline | crun | runc | youki | 合计 |
|---|---:|---:|---:|---:|
| MetaGPT | 3/12 | 0/9 | 0/11 | 3/32 |
| Agentless | 1/12 | 0/9 | 2/11 | 3/32 |
| mini-SWE-agent | 4/12 | 2/9 | 2/11 | 8/32 |
| RepairAgent | 4/12 | 0/9 | 4/11 | 8/32 |

RepairAgent 的 runc 0/9 不能解释为 Go 修复能力为零：其 9 个 runc case 均被 rootless user namespace 环境阻断，没有得到有效的目标行为比较。

### 4.2 成功 case 矩阵

| Case | MetaGPT | Agentless | mini-SWE-agent | RepairAgent |
|---|:---:|:---:|:---:|:---:|
| `crun-1083` | — | — | ✓ | — |
| `crun-1161` | — | — | — | ✓ |
| `crun-13` | ✓ | — | ✓ | ✓ |
| `crun-237` | ✓ | ✓ | ✓ | ✓ |
| `crun-453` | ✓ | — | ✓ | ✓ |
| `runc-3944` | — | — | ✓ | — |
| `runc-4772` | — | — | ✓ | — |
| `youki-2994` | — | — | ✓ | — |
| `youki-3198` | — | — | — | ✓ |
| `youki-3320` | — | ✓ | ✓ | ✓ |
| `youki-3428` | — | — | — | ✓ |
| `youki-3431` | — | ✓ | — | ✓ |

四个 baseline 共确认修复 12 个不同 case。`crun-237` 是唯一被四者全部修复的 case。mini-SWE-agent 与 RepairAgent 的成功集合并集已覆盖全部 12 个 case，体现出两类多轮 Agent 的互补性。

## 5. 失败与不确定结果

| 结果类别 | MetaGPT | Agentless | mini-SWE-agent | RepairAgent |
|---|---:|---:|---:|---:|
| 修复成功 | 3 | 3 | 8 | 8 |
| 明确行为不匹配 | 2 | 7 | 4 | 11 |
| 环境/比较/Oracle 不确定 | 3 | 10 | 10 | 11 |
| Agent 超时或被终止，保留/未保留部分结果 | 12 | 0 | 2 | 0 |
| Agent 协议/API/FSM 崩溃 | 6 | 0 | 0 | 2 |
| 定位覆盖不足，无补丁 | 0 | 5 | 0 | 0 |
| Agent 补丁导致构建失败 | 4 | 3 | 0 | 0 |
| 构建环境失败 | 2 | 4 | 8 | 0 |
| 合计 | 32 | 32 | 32 | 32 |

主要影响因素：

| 问题 | 影响 |
|---|---|
| Rootless user namespace | 26 个 baseline-case 结果被标记为不确定；runc 最集中 |
| 严格 stderr 比较 | mini-SWE-agent、RepairAgent 的 `youki-3132` 仅因 warning 差异未通过 |
| Oracle 清理/总超时 | `crun-1783`、`youki-2756` 等缺少有效 verdict |
| Rust toolchain manifest 缺失 | 多个 youki 候选无法完成有效构建 |
| Agentless top-5 定位限制 | 5 个 case 的目标文件不在可编辑集合，未形成 git diff |
| MetaGPT 稳定性 | 出现超时、JSON/命令协议错误、API 流中断和余额不足 |

Raw Oracle fail 不等于算法失败。rootless、清理权限、超时和严格文本比较应与明确行为不匹配分开报告。

## 6. Baseline 分析

| Baseline | 主要优势 | 主要限制 |
|---|---|---|
| MetaGPT | 修复 3 个 crun case；部分超时任务仍留下候选补丁 | 12 个 Agent 超时；协议/API 错误较多；无可靠 usage/cost |
| Agentless | 32 个命令均正常返回；单 case 仅 1 次 LLM 调用；27 个补丁全部成功应用 | top-5 定位限制导致 5 个无补丁；最终成功率 9.4% |
| mini-SWE-agent | 8 个成功；32/32 生成补丁；覆盖 2 个可确认 runc 成功 | Token 与 Agent 时间最高；构建环境和超时影响较多 |
| RepairAgent | 8 个成功；30 个候选全部通过外层构建；patch coverage 93.8% | Token 为下界；Cost 缺失；2 个 FSM 崩溃；runc Oracle 全受环境阻断 |

Agentless 的 pipeline 时间明显高于 Agent 时间，主要来自构建和两个 1200 秒 Oracle 总超时。MetaGPT 与 mini-SWE-agent 的总时间则主要消耗在 Agent 阶段。

## 7. 结论

| 结论项 | 结果 |
|---|---|
| 最高确认成功率 | mini-SWE-agent、RepairAgent：8/32（25.0%） |
| 最低 LLM 调用数 | Agentless：32 次 |
| 最高补丁覆盖 | mini-SWE-agent：32/32 |
| 最高独立构建通过 | RepairAgent：30/32 |
| 四 baseline 成功并集 | 12/32 个不同 case |
| 最大评测障碍 | rootless user namespace 与严格输出比较 |

本实验表明，多轮 Agent 在 OCI runtime 修复上取得了更高的确认成功数，但资源消耗、环境稳定性和 Oracle 可执行性显著影响最终结论。下一轮实验应优先修复 rootless/user namespace、Rust toolchain、Oracle 清理与 stderr 归一化问题，再在相同模型、供应商和预算下重新比较 baseline。

## 8. 公共提示词构成

四个 baseline 共用同一任务主体，模板如下：

```text
Fix OCI runtime bug case {case_id}.

Target runtime: {runtime}
Title: {issue_title}
Upstream issue: {issue_url}
Category: {category}

Goal:
Modify the runtime source code so the candidate runtime behavior
matches the configured reference runtime for the OCI reproduction case.
Do not edit the dataset, generated worktree metadata, or oracle scripts.

Writable target repository:
{worktree_dir}

Required first command:
cd {worktree_dir} && git rev-parse HEAD && git status --short

Inspect, edit, build, and collect git diff only in the writable repository.

Reproduction bundle:
{case_dir}

Rootfs tar:
{rootfs_tar}

Build command:
{build_command}

Candidate runtime:
{runtime_path}

Expected differential behavior and validation notes:
{expected_diff.txt}

Case README:
{README.md}
```

路径约束存在一处 baseline 差异：

| Baseline | 任务传递方式 | 附加约束 |
|---|---|---|
| MetaGPT | wrapper 读取 `task.md` | 编辑器使用 worktree 内绝对路径 |
| Agentless | 转换为 OCI task JSONL，并提供 top-5 定位文件 | SEARCH/REPLACE header 必须使用仓库相对路径 |
| mini-SWE-agent | 通过 `mini -t` 传入完整任务 | 编辑器使用 worktree 内绝对路径 |
| RepairAgent | wrapper 读取 `task.md`，再进入 OCI FSM | 只开放源码搜索、事务编辑和构建工具 |

外部复现时应同时保留公共提示词、baseline 自带 system prompt、模型版本、API endpoint、温度、最大轮数和超时；只公开公共任务文本不足以完全复现实验行为。

现有顶层 metadata 记录了 runtime `source_ref`，但没有统一记录四个上游 baseline 仓库的 Git commit。对外发布复现包时还应补充 baseline commit、Conda environment export 和操作系统/kernel/cgroup 信息。
