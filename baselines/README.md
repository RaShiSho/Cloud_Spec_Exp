# Baselines

本目录用于接入和记录修复 baseline。初始化阶段不克隆仓库，避免网络、依赖和版本问题影响工作区。

## 建议接入顺序

1. `mini-SWE-agent`：轻量 agent baseline，适合快速建立批量实验链路。
2. `Agentless`：流程清晰，可拆分为定位、修复和验证，适合接入 `runC` oracle。
3. `AutoCodeRover`：结构化检索更强，但环境和运行链路更重。
4. `SWE-agent`：功能完整但配置较重，可作为强 agent 对照。
5. `MetaGPT`：偏多角色软件生成框架，不是精确 bug repair 的首选。
6. `RepairAgent`、`PatchAgent`：先确认可复现仓库和任务定义，再决定是否接入。

## 记录要求

每个 baseline 建议保留：

- 上游仓库地址和 commit hash。
- 安装步骤。
- 输入 case 格式。
- 运行命令。
- 输出 patch 位置。
- 与 `oracles/` 的对接方式。
