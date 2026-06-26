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

- 仓库：https://github.com/AutoCodeRoverSG/auto-code-rover
- 定位：面向 GitHub issue 和 SWE-bench 的自动修复 agent。
- 工作流：先检索相关代码上下文，再生成补丁；可利用结构化代码搜索和测试定位。
- 特点：定位能力强，但环境、依赖和运行链路较重。
- 建议：作为 Agentless 后的增强 baseline 接入。
