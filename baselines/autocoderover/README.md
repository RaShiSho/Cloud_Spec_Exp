# AutoCodeRover OCI Adapter

该 adapter 使用上游 `local-issue` 模式修复 runner 创建的 OCI runtime worktree，随后读取
`selected_patch.json` 并把选中的 diff 应用回 worktree。

本次实现核对的是上游 `main` 的 `585d3e639aeda58ef0b6a151dd1cc2721a94d267`。正式实验还应
记录 `external/baselines/AutoCodeRover` 实际检出的 commit，避免上游变更导致参数或输出格式漂移。

## 关键兼容处理

- 上游 CLI 的 `--model` choices 只包含静态模型，但模型工厂又声明支持
  `litellm-generic-*`。`launch.py` 会在上游创建参数解析器前注册配置中的 LiteLLM 模型。
- 上游结构化索引只解析 Python。launcher 保留该索引，并把当前 runtime 的
  `.go/.c/.h/.rs` 文件加入文件级、文本级搜索；类/方法级搜索不会被伪装成可用。
- 上游只把目录形式的 `.git` 识别为仓库，无法识别 runner 创建的 linked worktree。
  launcher 改用 `git rev-parse --is-inside-work-tree`，避免上游重新初始化仓库并创建临时提交。
- 实验 YAML 的 `conda_env` 选择独立环境；runner 将其传给 wrapper，外部环境变量不可覆盖。
- 每次 invocation 写入独立的 `acr-runs/<timestamp>-<pid>`，避免失败重跑时误用旧补丁。
- `--timeout-seconds` 通过 GNU `timeout` 终止超时任务及其进程组，使 runner 能继续下一个 case。
- `wrapper_metadata.json` 使用 `acr_failed`、`patch_missing`、`patch_apply_failed` 和
  `patch_applied` 区分 adapter 阶段，并记录对应退出码。

默认全量配置选择 `model_profile: deepseek-official`、Conda 环境 `auto-code-rover`，单 case
内部上限 3300 秒，runner 外部上限 3600 秒。环境名不同时应修改 YAML 中的
`conda_env`。

该 fallback 只能让 AutoCodeRover 在非 Python 仓库中进行文本、行号和整文件检索，不能等价于
论文/上游在 Python SWE-bench 上使用的结构化 AST 检索。结果报告应明确记录这一适配差异。

## 全量运行

```bash
python scripts/run_oci_experiment.py \
  --config configs/experiment.autocoderover.yaml \
  --resume
```

`--resume` 首先核对所有选中结果的配置标识，仅在配置相同时跳过已有 `done` 结果，并清理、重跑中断态和 `error` case。要强制重跑某个
已完成 case，改用 `--case <case_id> --clean`。

配置不同或旧版结果缺少配置标识时，`--resume` 会报错并保留原结果。请更换输出目录，
或用 `--case <case_id> --clean` 明确替换旧结果。

模型与地址只来自 `configs/model_profiles.yaml`；密钥只读取 profile 的 `api_key_env`。
wrapper 接收 runner 的 `--model-config` 快照，不再接受 `--model` 或 `ACR_MODEL` 覆盖。
