# 复现实验 Runbook

## 1. 准备 bug case

在 `benchmarks/` 中为每个 bug case 准备稳定元数据：

- case id
- buggy 版本
- 给 agent 的问题描述
- 输入样例
- 标准实现或 `runC` 的调用方式

## 2. 接入 oracle

在 `oracles/` 中封装统一判定接口。每次 baseline 产出候选 patch 后，统一调用 oracle 判断行为是否与标准实现一致。

建议把 oracle 输出固定为 JSON，避免后续结果汇总依赖日志解析。

## 3. 接入 baseline

优先顺序：

1. `mini-SWE-agent`
2. `Agentless`
3. `AutoCodeRover`
4. `SWE-agent`
5. 其他明确要求的 baseline

每个 baseline 接入时都要记录上游 commit、安装命令、运行命令和输出 patch 路径。

## 4. 运行实验

复制配置样例：

```text
configs/experiment.example.yaml -> configs/experiment.local.yaml
```

在 `configs/model_profiles.yaml` 填写完整模型配置，实验中只设置 `model_profile` 名称。
密钥放入该 profile 的 `api_key_env` 所指定的变量（shell 或根目录 `.env`）；两个来源值
不同则报错。填写 case、baseline 和 oracle 配置后，先运行统一入口的 `--dry-run`，
核对打印的模型、地址和密钥来源，再执行实验。

续跑使用 `--resume`。配置不同或旧结果缺少配置标识时会报错，原结果保留；请更换
输出目录，或用 `--case <case-id> --clean` 明确替换选中的旧任务。相同配置下，已完成
任务跳过，失败及中断任务重跑。

## 5. 汇总结果

至少统计：

- oracle 是否通过
- 回归测试是否通过
- 运行耗时
- token 使用量
- patch 大小
- 失败类型

大体量原始结果留在 `results/`，不要默认提交到 Git。

## 6. 复现实验记录

每次正式实验建议记录：

- 日期和操作者
- 机器和系统环境
- baseline commit
- 模型版本
- 配置文件
- 成功率和主要失败原因
