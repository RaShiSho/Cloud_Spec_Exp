# Baseline 调研记录

## SWE-agent

- 仓库：https://github.com/SWE-agent/SWE-agent
- 定位：面向 GitHub issue 的自主修复 agent。
- 工作流：agent 在代码仓库环境中查看文件、编辑代码、运行测试并迭代。
- 特点：功能完整、配置能力强，但复现实验的环境和参数较重。
- 建议：作为强 agent baseline 保留，优先级低于 `mini-SWE-agent`。

## mini-SWE-agent

- 仓库：https://github.com/SWE-agent/mini-swe-agent
- 定位：SWE-agent 的轻量版本。
- 工作流：主要通过 shell 工具查看、修改和测试代码。
- 特点：结构简单、便于批处理、适合作为轻量 agent baseline。
- 建议：优先接入。

## MetaGPT

- 仓库：https://github.com/geekan/MetaGPT
- 定位：多角色软件开发 agent 框架。
- 工作流：通过产品经理、架构师、工程师等角色分工完成需求到代码的生成。
- 特点：更适合从需求生成项目，不是精确 bug repair 的天然形态。
- 建议：除非实验要求覆盖该 baseline，否则降低优先级。
- 超时诊断、单案例 smoke test 和批量恢复命令见
  [`metagpt-timeout-recovery.md`](metagpt-timeout-recovery.md)。

## RepairAgent

- 定位：LLM 自动程序修复 agent。
- 已知特点：论文描述中包含动态 prompt、工具调用和有限状态机式修复流程。
- 风险：公开搜索下仓库定位不够稳定，复现前需要确认具体上游仓库和版本。
- 建议：先确认引用来源，再决定是否纳入。

## PatchAgent / PAGENT

- 参考论文：https://arxiv.org/abs/2506.17772
- 定位：更接近失败补丁的二次修补，而不是完整 issue 修复 agent。
- 工作流：针对已有失败 patch，结合静态分析和 LLM 修复 patch 中的问题。
- 建议：如果实验包含 baseline 失败 patch 的后处理，可以作为补充；不建议直接替代完整 agent baseline。

## Agentless

- 仓库：https://github.com/OpenAutoCoder/Agentless
- 定位：非交互式 LLM 修复 pipeline。
- 工作流：定位、修复、补丁验证三阶段。
- 特点：流程清晰、变量较少、适合接入统一 oracle。
- 建议：优先接入，适合作为当前任务的主 baseline 之一。

## AutoCodeRover

> **当前决策（2026-07-16）**：暂不将 AutoCodeRover 纳入本项目的正式 baseline 实验和结果比较。现有 adapter 与运行结果保留，用于记录适配过程和后续可行性研究，不作为 baseline 能力分数。

- 仓库：https://github.com/AutoCodeRoverSG/auto-code-rover
- 定位：面向 GitHub issue 和 SWE-bench 的自动修复 agent。
- 工作流：先检索相关代码上下文，再生成补丁；可利用结构化代码搜索和测试定位。
- 当前接入：使用上游 `local-issue` 模式；项目内 launcher 为 DeepSeek 注册 LiteLLM 动态模型、兼容 `.git` 为文件的 linked worktree，wrapper 收集并应用 `selected_patch.json` 指向的 diff。
- 非 Python 降级：上游只为 Python 构建 AST 索引；当前 adapter 仅把 Go/C/Rust 源文件补入文本、行号和整文件搜索，类/方法检索仍不可用，不能视为上游原始能力的等价复现。
- 环境：默认通过 `conda run --no-capture-output -n auto-code-rover python` 启动。该环境名可在 YAML 的 `conda_env` 中修改。
- 批处理：每个 case 使用独立输出目录和任务级 timeout；wrapper 记录 ACR、补丁发现和补丁应用阶段状态；runner 的 `--resume` 跳过 `done` case，清理并重跑中断或 `error` case。
- 风险：上游主分支未固定时，CLI、依赖和补丁输出格式仍可能变化；正式实验应记录实际 commit。
- 本次源码核对基准：`585d3e639aeda58ef0b6a151dd1cc2721a94d267`。

暂停采用的主要原因：

- 上游补丁应用流程面向 Python：修改后的目标文件无论扩展名都会进入 `pylint` 语法检查，导致 OCI runtime 的 C、Go、Rust 补丁即使能够解析和匹配，也无法被判定为可应用。
- 上游 AST 索引和搜索提示同样以 Python 类/方法为中心。当前文本级 fallback 会退化为整文件上下文，既不能等价复现 ACR 在 SWE-bench 上的结构化检索能力，也显著增加 token 消耗。
- 最近一次 `crun-13` 冒烟运行已完成模型搜索和补丁生成，但所有候选补丁均在提取或应用阶段失败，没有进入 runtime 构建与 OCI oracle，因此当前结果不能用于评价 ACR 的实际修复能力。

重新评估 AutoCodeRover 的前置条件：实现按语言区分的补丁应用与验证，提供 C/Go/Rust 的函数级结构化索引，并至少各选一个 crun、runc、youki case 跑通“生成补丁、应用、构建、oracle”完整链路。
