# RepairAgent OCI Adapter

该 adapter 以官方 [`sola-st/RepairAgent`](https://github.com/sola-st/RepairAgent) 为上游，
保留 RepairAgent 的有限状态机、动态上下文、命令循环和行级 fix 格式，将 Java/Defects4J
专用工具层替换为 OCI runtime 工具层。

## 上游依据与限制

本次源码核对基准为 `sola-st/RepairAgent` 的
`701dbb37ee1404eb6de36fbee6f29a5063106aa4`。实际实验 revision 会记录到
`wrapper_metadata.json` 和 `launcher_metadata.json`，不应只依赖本文档中的 hash。

上游并不是通用仓库 repair agent：

- `repairagent.py run` 的输入是 Defects4J 的 `Project BugIndex`，并主动 checkout Java 项目；
- `BaseAgent` 从固定格式的第三个 goal 解析项目名和 bug 编号；
- 初始 bug 信息、测试、定位和 mutation 均读取 Defects4J 数据；
- 搜索和方法提取依赖 Java AST；
- `write_fix` 使用行号编辑并运行 `defects4j compile && defects4j test`。

因此，仅把 `--repo` 传给原生 CLI 不会运行 OCI case。当前 adapter 属于工具层移植，不是
RepairAgent 在 Defects4J 上原始实验的等价复现。结果报告应明确这一点。

## OCI 工具层

`launch.py` 为每个 case 创建隔离运行目录，并在导入上游 agent 前完成以下替换：

- 初始 `get_info` 使用 runner 生成的 `task.md` 和受扩展名约束的源码清单；
- `read_range`、文本搜索和函数样式符号扫描支持 Go、C/header、Rust；
- `write_fix` 保留上游的行级 change dictionary，限制路径不能逃出目标 worktree；
- 每个候选修改后运行配置中的 runtime `build_command`；构建失败时恢复该候选修改，构建成功时保留修改；
- 禁用依赖 Defects4J buggy-line 数据和 Java mutation 模板的辅助 mutation 调用；
- agent 退出后必须存在 tracked diff，否则 launcher 返回 `65`，wrapper 记录 `patch_missing`。

这里的内部“测试”只是 runtime 构建，不等价于 OCI 行为验证。统一 runner 随后仍会重新构建
并调用 `oracles/run_oci_oracle.py`；最终有效性只以该 oracle 为准。

## 环境

建议使用独立 Conda 环境。上游当前依赖较旧的 Auto-GPT/OpenAI/LangChain 组合，应优先使用
其 core requirements，而不要混装到项目主环境。该 requirements 并未锁定所有传递依赖，
正式实验还应导出实际环境：

```bash
git clone https://github.com/sola-st/RepairAgent.git external/baselines/RepairAgent
conda create -n repairagent python=3.10 -y
conda run -n repairagent python -m pip install \
  -r external/baselines/RepairAgent/repair_agent/requirements-core.txt
```

adapter 依次读取 `REPAIRAGENT_API_KEY`、`DEEPSEEK_API_KEY`、`OPENAI_API_KEY`。
API base 依次读取 `REPAIRAGENT_BASE_URL`、`OPENAI_API_BASE`、`OPENAI_BASE_URL`，默认
`https://api.deepseek.com`。上游配置实际识别的是 `OPENAI_API_BASE_URL`，wrapper 会完成映射。

专属配置使用 provider 原生模型名 `deepseek-v4-flash`。上游 OpenAI-compatible client 会把
该名称直接传给服务端；全局的 LiteLLM 风格名称 `deepseek/deepseek-v4-flash` 不适用于这里。

## 运行

先做配置与路径检查：

```bash
python scripts/run_oci_experiment.py \
  --config configs/experiment.repairagent.yaml \
  --case crun-13 \
  --dry-run
```

再执行单 case：

```bash
python scripts/run_oci_experiment.py \
  --config configs/experiment.repairagent.yaml \
  --case crun-13 \
  --clean
```

单 case 完整通过“agent、build、OCI oracle”后，才建议移除 `--case` 并使用 `--resume`。

## 产物

- `wrapper_metadata.json`：wrapper 参数、上游 revision、阶段状态；
- `launcher_metadata.json`：隔离运行目录、工具层模式、最终 patch 大小；
- `repairagent-runs/<timestamp-pid>/`：上游 prompt、response、上下文和实验日志；
- runner 上层目录中的 `candidate.patch`、构建日志和 `oracle.json`：统一评测结果。
