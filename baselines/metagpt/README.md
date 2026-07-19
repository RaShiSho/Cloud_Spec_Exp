# MetaGPT OCI Adapter

该 adapter 把 OCI case prompt 作为 MetaGPT 的增量需求，并将 runner 创建的 runtime
worktree 作为 `project_path`。MetaGPT 直接修改 worktree，随后由统一 runner 收集 `git diff`、
构建 runtime 并调用 OCI oracle。

## 上游依据

- 上游 `metagpt.software_company.generate_repo` 支持 `project_path`，CLI 对应
  `metagpt <requirement> --project-path <existing-project>`。
- MetaGPT 官方增量开发文档以相同入口演示现有项目的 bug 修复，并建议 bug 修复使用
  `n_round=10`、`max_auto_summarize_code=0`。
- 上游 `Config.default()` 的加载优先级是环境变量、仓库 `config/config2.yaml`、用户
  `~/.metagpt/config2.yaml`；它对这些 mapping 做浅层覆盖。

`launch.py` 因而在隔离的临时 HOME 中写入不含真实密钥的 bootstrap 配置，使其覆盖上游
仓库里的示例 `llm` mapping。导入 MetaGPT 后，再只在内存中注入 API key。真实 key 不会
进入 `wrapper_metadata.json`、`launcher_metadata.json` 或 bootstrap 配置。

## Terminal 兼容层

已验证的上游 revision `11cdf466d042aece04fc6cfd13b28e1a70341b1f` 会把换行结尾的
Terminal marker 永久保留在读取缓冲区的最后一个分段中，并继续等待不会到来的下一个
字节。上游 shell 提前退出时，原实现对 EOF 也会继续循环。

本 adapter 在运行时通过 `terminal_compat.py` 修复这两个问题，不修改
`external/baselines/MetaGPT`：reader 会先在原始字节缓冲区中查找 marker，命中后立即
返回；遇到 EOF 则抛出包含 shell return code 的异常。兼容层还保留 Terminal observer、
前台返回文本和 daemon queue 行为，并将安装状态记录到 `launcher_metadata.json` 的
`terminal_compat` 字段。

`scripts/diagnose_metagpt_terminal.py` 与正式 launcher 使用同一个安装函数。可用
`--raw-upstream-terminal` 暂时禁用兼容层以复现上游问题，但正式实验不应使用该选项。

## 环境

建议把上游仓库 clone 到 `external/baselines/MetaGPT`，并使用独立 Conda 环境：

```bash
git clone https://github.com/FoundationAgents/MetaGPT.git external/baselines/MetaGPT
conda create -n metagpt python=3.10 -y
conda run -n metagpt python -m pip install -e external/baselines/MetaGPT
```

同步仓库后先运行兼容层回归和真实 Terminal 探针：

```bash
conda run -n metagpt python -m unittest \
  scripts.test_metagpt_terminal_compat \
  scripts.test_metagpt_launcher \
  -v

PYTHONUNBUFFERED=1 timeout --signal=TERM --kill-after=5s 20s \
  conda run --no-capture-output -n metagpt python \
  scripts/diagnose_metagpt_terminal.py \
  --baseline-repo external/baselines/MetaGPT
```

配置至少一个 key：`METAGPT_API_KEY`、`DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY`。API base
依次读取 `METAGPT_BASE_URL`、`OPENAI_API_BASE`、`OPENAI_BASE_URL`；DeepSeek 默认回退到
`https://api.deepseek.com`。

专属配置中的 baseline model 使用 provider 原生名 `deepseek-v4-flash`，而不是全局供
LiteLLM 风格客户端使用的 `deepseek/deepseek-v4-flash`。MetaGPT 当前的 DeepSeek provider
会把 model 名直接传给 OpenAI-compatible client。

正式实验应记录 `launcher_metadata.json` 中的 `baseline_revision`。MetaGPT 的 CLI 和角色
编排仍在变化，只记录分支名不足以复现实验。

## 运行

```bash
python scripts/run_oci_experiment.py \
  --config configs/experiment.metagpt.rest.yaml \
  --case youki-2756 \
  --clean
```

单 case 通过后，可移除 `--case` 并使用 `--resume` 批量运行。adapter 的内部 timeout
短于 runner timeout，可避免 MetaGPT 子进程在 runner 超时后继续占用资源。

## 已知适配差异

MetaGPT 原始 Software Company 面向自然语言生成和增量开发，并非专为 OCI runtime 或
SWE-bench 设计。它可能在 worktree 中生成 PRD、设计文档或测试文件；统一 runner 会把这些
内容与源码修改一起纳入候选 patch。当前 upstream `main` 中部分传统 QA/Engineer 角色开关
也可能被新角色编排忽略，因此最终有效性必须以 build 和 OCI oracle 为准。
