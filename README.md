# Cloud-Spec-Exp

本项目用于实验性评估：在给定 OCI runtime 的 bug case、修复基线 baseline 和标准实现 reference runtime 的情况下，大模型 agent 是否能修改源码，使候选 runtime 的行为与 reference runtime 保持一致。

当前脚手架围绕 [74suiko/oci-differential-dataset](https://github.com/74suiko/oci-differential-dataset) 设计，默认把后续 clone 的数据集、baseline、runtime 源码和临时 worktree 放在 `external/` 下，避免大仓库内容进入本项目版本控制。

## 工作区结构

- `baselines/`：提交 baseline adapter 文档、Agentless 兼容 patch 等轻量接入文件。真实 baseline clone 应放在 `external/baselines/`。
- `benchmarks/`：预留给 benchmark 元数据、输入样例、错误行为说明和期望行为描述。
- `configs/`：实验配置样例和本地运行配置。
- `docs/`：实验复现说明、baseline 调研记录和操作日志。
- `external/`：本地 clone 的数据集、baseline、runtime 源码和临时 worktree。该目录被 `.gitignore` 忽略。
- `oracles/`：对照执行器和行为判定逻辑，例如 `oracles/run_oci_oracle.py`。
- `results/`：实验输出目录，包含每个 baseline/case 的日志、metadata、patch 和 oracle 结果。
- `scripts/`：实验准备、运行、汇总和辅助脚本。

## 环境变量

项目支持从仓库根目录 `.env` 自动读取环境变量。真实密钥不要提交到 git。

```bash
cp .env.example .env
nano .env
```

常用变量包括：

- `DEEPSEEK_API_KEY`：DeepSeek API key。
- `OPENAI_API_KEY`：OpenAI-compatible 客户端读取的 API key，可填 DeepSeek key。
- `OPENAI_API_BASE` / `OPENAI_BASE_URL`：OpenAI-compatible API base URL，例如 `https://api.deepseek.com`。
- `MSWEA_MODEL_NAME`：mini-SWE-agent 默认模型名。
- `MSWEA_COST_TRACKING`：mini-SWE-agent 费用统计策略。
- `PIP_INDEX_URL` / `PIP_DEFAULT_TIMEOUT`：可选 pip 镜像和超时配置。

已经在 shell 中 `export` 的变量优先级高于 `.env`。

## 配置文件

- `configs/experiment.first20.example.yaml`：前 20 个 case 的模板配置，使用 `benchmark.selection.mode: first_n` 和 `count: 20`。
- `configs/experiment.full.example.yaml`：全量数据集模板配置，使用 `benchmark.selection.mode: all`，会读取 `metadata.json` 中的全部 case。
- `configs/experiment.first20.local.yaml`：本地运行配置示例，包含你已经填过的一部分 `buggy_ref_by_case`。

全量配置默认启用 `mini-swe-agent` 和 `agentless-oci-adapted`。`autocoderover`、`metagpt`、`repairagent` 已写入配置，但默认 `enabled: false`。它们调用的是本项目 tracked `baselines/<name>/run_oci_repair.sh` OCI adapter skeleton，不是 upstream 原生命令；需要先在对应 wrapper 中实现真实 baseline 调用，再改为启用。

## Scripts

本节列出 `scripts/` 目录中的可用代码。除特别说明外，命令应在仓库根目录运行。

### `scripts/prepare_oci_cases.py`

读取实验 YAML 配置，加载 OCI 数据集 `metadata.json`，按配置选择 case，并校验每个 case 目录是否包含必需文件：

- `base_config.json`
- `buggy_config.json`
- `repro.sh`
- `expected_diff.txt`
- `README.md`

常用命令：

```bash
python scripts/prepare_oci_cases.py \
  --config configs/experiment.first20.local.yaml \
  --dry-run
```

可用参数：

| 参数 | 必填 | 说明 |
|---|---:|---|
| `--config <path>` | 是 | 实验 YAML 配置路径。 |
| `--output <path>` | 否 | 将选中的 case 清单和校验问题写入 JSON 文件。 |
| `--dry-run` | 否 | 只打印校验结果，不写入 `--output`。 |

输出内容包括 `case_count`、`cases` 和 `problems`。如果不是 dry-run 且发现问题，脚本返回码为 `2`。

### `scripts/run_oci_experiment.py`

主实验入口。它会按 baseline/case 创建 git worktree，生成任务 prompt，调用 baseline，收集 `git diff` 为 `candidate.patch`，构建候选 runtime，调用 oracle，并保存运行结果。

常用单 case 命令：

```bash
python scripts/run_oci_experiment.py \
  --config configs/experiment.first20.local.yaml \
  --baseline mini-swe-agent \
  --case crun-13 \
  --clean
```

常用 dry-run 命令：

```bash
python scripts/run_oci_experiment.py \
  --config configs/experiment.first20.local.yaml \
  --baseline mini-swe-agent \
  --limit 3 \
  --dry-run
```

可用参数：

| 参数 | 必填 | 说明 |
|---|---:|---|
| `--config <path>` | 是 | 实验 YAML 配置路径。 |
| `--baseline <name>` | 否 | 指定要运行的 baseline，可重复传入。不传时运行配置中所有 enabled baseline。 |
| `--case <case_id>` | 否 | 指定要运行的 case，可重复传入。不传时按配置选择 case。 |
| `--limit <n>` | 否 | 在 case 过滤后截取前 `n` 个 case。 |
| `--dry-run` | 否 | 只执行配置加载、case 选择和 preflight，不创建 worktree，不运行 baseline，不删除文件。 |
| `--clean` | 否 | 正式运行前清理当前 baseline/case 对应的旧结果目录和旧 worktree。和 `--dry-run` 一起使用时只报告计划，不删除。 |
| `--resume` | 否 | 跳过已有终态结果；自动清理并重跑中断态 case。不能与 `--clean` 同时使用。 |

主要输出：

- 终端 `stderr`：进度日志，例如加载配置、创建 worktree、运行 baseline、构建、运行 oracle。
- 终端 `stdout`：最终 JSON 结果，便于脚本解析。
- `results/<experiment>/<baseline>/<case_id>/metadata.json`：本次运行元数据。
- `results/<experiment>/<baseline>/<case_id>/task.md`：传给 baseline 的任务文本。
- `results/<experiment>/<baseline>/<case_id>/candidate.patch`：baseline 修改源码后产生的 git diff。
- `results/<experiment>/<baseline>/<case_id>/oracle.json`：oracle 判定结果。
- `stdout.log` / `stderr.log`：baseline 标准输出和错误输出。
- `build_stdout.log` / `build_stderr.log`：构建日志。
- `oracle_stdout.log` / `oracle_stderr.log`：oracle 命令日志。

注意事项：

- 不加 `--clean` 或 `--resume` 时，如果目标 worktree 已存在，脚本会报错。
- `--clean` 只清理本次选中的 baseline/case，不会清理整个实验目录。
- 长时间全量实验建议使用 `--resume`；首次运行也可直接使用该参数。
- preflight 会检查数据集、runtime source、baseline repo、`git`、`bash`、reference runtime 和 build command。

AutoCodeRover 全量命令：

```bash
python scripts/run_oci_experiment.py \
  --config configs/experiment.autocoderover.local.yaml \
  --resume
```

该配置只启用 AutoCodeRover，无需额外传入 `--baseline`。

### `scripts/summarize_oci_results.py`

汇总实验结果目录下的 `oracle.json`，生成机器可读的 `summary.json` 和便于阅读的 `summary.md`。

常用命令：

```bash
python scripts/summarize_oci_results.py \
  --results-dir results/oci-first20-smoke
```

可用参数：

| 参数 | 必填 | 说明 |
|---|---:|---|
| `--results-dir <path>` | 是 | 实验结果根目录，通常是 `results/<experiment>`。脚本会扫描 `<baseline>/<case>/oracle.json`。 |
| `--output-json <path>` | 否 | summary JSON 输出路径。默认写到 `<results-dir>/summary.json`。 |
| `--output-md <path>` | 否 | summary Markdown 输出路径。默认写到 `<results-dir>/summary.md`。 |

统计口径：

- `pass`：candidate 在 base 和 buggy 配置上都与 reference 一致。
- `fail`：candidate 行为与 reference 不一致。
- `error`：baseline、构建、oracle 或 setup 出错。
- `env_error`：`oracle.json` 中 `error_type` 为 `environment` 的环境错误。

### `scripts/populate_buggy_refs.py`

根据配置选择 case，识别对应的 buggy 版本，并写入配置中的 `buggy_ref_by_case`。

识别顺序为：

1. 请求 GitHub Issue events：`https://api.github.com/repos/{owner}/{repo}/issues/{issue}/events`，找到 `event == "closed"` 且带 `commit_id` 的事件，将该 `commit_id` 作为 `fix_commit`，写入 `<fix_commit>^`。
2. 如果 GitHub events 未定位到，则在本地 runtime 仓库中用 `git log --all --extended-regexp --regexp-ignore-case --grep=... --format=%H -n 1` 搜索 commit message，匹配 fix/close/resolve 与 issue 号，找到后写入 `<fix_commit>^`。
3. 如果本地也找不到，则请求 issue 本身，读取 `created_at`，并执行 `git rev-list -n 1 --before=<created_at> main`，将 issue 创建前 main 上最近提交直接作为 buggy 版本写入。

GitHub API 请求使用标准库实现，不新增依赖。如果设置了 `GITHUB_TOKEN`，脚本会自动携带 token 以提高 API rate limit。网络失败、限流、404 或 events 无匹配时不会中断整个 case，会自动进入 fallback。

常用 dry-run：

```bash
python scripts/populate_buggy_refs.py \
  --config configs/experiment.first20.local.yaml \
  --case crun-13
```

写入配置：

```bash
python scripts/populate_buggy_refs.py \
  --config configs/experiment.first20.local.yaml \
  --case crun-13 \
  --write \
  --overwrite
```

可用参数：

| 参数 | 必填 | 说明 |
|---|---:|---|
| `--config <path>` | 是 | 要读取并可选更新的实验 YAML 配置。 |
| `--case <case_id>` | 否 | 指定 case，可重复传入。不传时按配置的 benchmark selection 处理。 |
| `--runtime <name>` | 否 | 只处理指定 runtime，例如 `crun` 或 `runc`。 |
| `--overwrite` | 否 | 覆盖已有 `buggy_ref_by_case` 映射。默认遇到已有映射会跳过。 |
| `--write` | 否 | 将结果写回 YAML。默认是 dry-run，只打印候选。 |
| `--min-score <int>` | 否 | 兼容保留参数。当前 GitHub events 和 created_at fallback 不使用分数过滤。 |

输出为 JSON，包含 `case_id`、`runtime`、`method`、`fix_commit`、`buggy_ref`、`api_url`、`created_at`、`command`、`fallback_reasons`、`reason` 和 `status`。其中：

- `method: "github_events"` 表示通过 closed issue event 的 `commit_id` 找到 fix commit。
- `method: "local_git_grep"` 表示通过本地 git commit message 找到 fix commit。
- `method: "issue_created_at"` 表示通过 issue 创建时间前 main 上最近提交推断 buggy 版本。

### `scripts/oci_common.py`

公共工具库，不建议直接作为 CLI 运行。其他脚本主要通过它复用以下能力：

- `load_dotenv()`：读取仓库根目录 `.env`，支持 `KEY=value`、引号、空行和 `#` 注释，不覆盖已存在的 shell 环境变量。
- `load_config()`：读取 YAML 配置，并在读取前加载 `.env`。
- `load_oci_cases()`：读取数据集 metadata，按 `benchmark.selection.mode: first_n` 或 `all` 选择 case，并检查必需文件。
- `build_task_text()`：把 case README、expected diff、构建命令和 runtime 信息组装成 baseline prompt。
- `run_command()`：统一执行 subprocess，捕获 stdout/stderr、timeout 和错误信息。
- `write_json()` / `write_text()` / `append_jsonl()` / `load_jsonl()`：统一 UTF-8 文件读写。
- `scan_candidate_files()`：根据任务文本在 runtime 源码中粗略搜索候选文件，主要给 Agentless adapter 生成定位输入。

如果要在交互式 Python 中调用，可参考：

```bash
python -c "from scripts.oci_common import load_config; print(load_config('configs/experiment.first20.local.yaml').keys())"
```

### `scripts/test_oci_oracle_fake.py`

oracle 的轻量单元测试。它使用临时 fake case 和 fake runtime 验证 oracle 的四类基本行为：

- candidate 与 reference 一致时返回 `pass`。
- candidate 与 reference 不一致时返回 `fail`。
- reference runtime 缺失时返回 `error`。
- candidate 超时时返回 `error`，message 包含 timeout。

运行命令：

```bash
python scripts/test_oci_oracle_fake.py
```

该测试需要可用的 `bash`。如果当前环境没有可用 `bash`，测试会被跳过。

### `scripts/README.md`

脚本目录的简短说明文件。当前根 README 是更完整的使用入口；如果两者内容不一致，以根 README 为准。

## 推荐运行流程

1. 在 WSL/Linux 中准备 Python 虚拟环境和依赖。
2. 复制 `.env.example` 为 `.env`，填写 DeepSeek/OpenAI-compatible API 环境变量。
3. clone 数据集到 `external/oci-differential-dataset`。
4. clone baseline 到 `external/baselines/`。
5. clone runtime 源码到 `external/subjects/`。
6. 复制并修改配置文件，例如 `configs/experiment.first20.local.yaml`。
7. 用 `prepare_oci_cases.py --dry-run` 检查数据集和配置。
8. 用 `populate_buggy_refs.py` 补齐 `buggy_ref_by_case`。
9. 先用 `run_oci_experiment.py --case <case_id> --clean` 跑单 case smoke test。
10. 单 case 通过后，再扩大到多个 case 或完整前 20 个。
11. 用 `summarize_oci_results.py` 汇总结果。

## Git 约定

提交信息使用：

```text
<type>(<scope>): <subject>
```

示例：

```text
docs(readme): document experiment scripts
```
