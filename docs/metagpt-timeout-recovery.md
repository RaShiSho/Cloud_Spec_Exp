# MetaGPT OCI 超时恢复操作手册

本手册用于处理 `results/oci-metagpt` 中的 `crun-13` 失败。请先将仓库修改同步到
WSL/Linux，再执行以下命令。原始结果目录保持不变；诊断运行和冒烟测试使用独立路径。

## 1. 进入仓库并执行前置检查

```bash
cd /home/aludy/scires/Cloud_Spec_Exp

test -n "${DEEPSEEK_API_KEY:-}"
test -x "$(command -v timeout)"
test -x "$(command -v runc)"
test -f external/oci-differential-dataset/alpine-base.tar.gz
git -C external/subjects/crun rev-parse \
  'c047a49b8d798e210054e411a999e83f6c05bdbf^'

conda run -n metagpt python -m unittest \
  scripts.test_oci_common_prompt \
  scripts.test_metagpt_launcher \
  scripts.test_run_oci_experiment_runner \
  -v

python scripts/run_oci_experiment.py \
  --config configs/experiment.metagpt.yaml \
  --baseline metagpt \
  --case crun-13 \
  --dry-run
```

预演输出的 JSON 中，`problems` 必须是空数组。

## 2. 可选：直接运行 adapter 进行实时诊断

如果冒烟测试仍然卡住，请执行本节命令。它会绕过外层 runner 的输出捕获，并在 adapter
超时时保存可能已经产生的部分源码补丁。

```bash
DBG="/tmp/crun-13-metagpt-$(date +%s)"
OUT="/tmp/crun-13-metagpt-output-$(date +%s)"
TASK="/tmp/crun-13-metagpt-task-$(date +%s).md"

git -C external/subjects/crun worktree add --detach \
  "$DBG" \
  'c047a49b8d798e210054e411a999e83f6c05bdbf^'

cp results/oci-metagpt/metagpt/crun-13/task.md "$TASK"
printf '\nReproduction bundle absolute path: %s\nRootfs tar absolute path: %s\n' \
  "$PWD/external/oci-differential-dataset/cases/crun-13" \
  "$PWD/external/oci-differential-dataset/alpine-base.tar.gz" \
  >> "$TASK"
mkdir -p "$OUT"

set -o pipefail
METAGPT_CONDA_ENV=metagpt \
PYTHONUNBUFFERED=1 \
bash baselines/metagpt/run_oci_repair.sh \
  --baseline-repo "$PWD/external/baselines/MetaGPT" \
  --repo "$DBG" \
  --task-file "$TASK" \
  --output-dir "$OUT" \
  --model deepseek-v4-flash \
  --api-type deepseek \
  --timeout-seconds 900 \
  --n-round 10 \
  --investment 3.0 \
  --max-auto-summarize-code 0 \
  2>&1 | tee "$OUT/live.log"
ADAPTER_RC=${PIPESTATUS[0]}
echo "adapter_rc=$ADAPTER_RC"

git -C "$DBG" status --short | tee "$OUT/git-status.txt"
git -C "$DBG" diff --binary > "$OUT/candidate.partial.patch"
jq . "$OUT/wrapper_metadata.json"
jq . "$OUT/launcher_metadata.json"
grep -nE \
  'Current thread|Stack|run_command|pwd|http|asyncio|Engineer|generate_repo' \
  "$OUT/live.log" || true
```

launcher 现在每五分钟输出一次 Python 线程堆栈。堆栈位于
`terminal.py`/`subprocess` 表示正在等待终端进程；位于 `httpx`/`openai` 表示正在等待
LLM 请求；位于 `asyncio.gather` 表示正在等待角色任务或环境轮次结束。

## 3. 创建隔离的冒烟测试配置

```bash
SMOKE=/tmp/experiment.metagpt.smoke.yaml
cp configs/experiment.metagpt.yaml "$SMOKE"

sed -i 's/name: oci-metagpt/name: oci-metagpt-smoke/' "$SMOKE"
sed -i \
  's#output_dir: results/oci-metagpt#output_dir: results/oci-metagpt-smoke#' \
  "$SMOKE"
sed -i \
  '0,/timeout_seconds: 3600/s//timeout_seconds: 1200/' \
  "$SMOKE"
sed -i \
  's/    timeout_seconds: 3600/    timeout_seconds: 1200/' \
  "$SMOKE"
sed -i \
  's/task_timeout_seconds: 3300/task_timeout_seconds: 900/' \
  "$SMOKE"

grep -nE \
  'name:|output_dir:|timeout_seconds:|task_timeout_seconds:' \
  "$SMOKE"
```

## 4. 运行单案例冒烟测试

```bash
PYTHONUNBUFFERED=1 \
python scripts/run_oci_experiment.py \
  --config "$SMOKE" \
  --baseline metagpt \
  --case crun-13 \
  --clean \
  2>&1 | tee results/oci-metagpt-smoke-runner.log
```

## 5. 验证冒烟测试结果

```bash
RESULT=results/oci-metagpt-smoke/metagpt/crun-13

test -s "$RESULT/candidate.patch"
test -f "$RESULT/build_stdout.log"
test -f "$RESULT/build_stderr.log"

jq -e \
  '.status == "completed"' \
  "$RESULT/metagpt-output/launcher_metadata.json"

jq -e \
  '.status == "done" and .patch_size_bytes > 0' \
  "$RESULT/metadata.json"

jq -e \
  '.status == "pass" and (.comparisons | length) > 0' \
  "$RESULT/oracle.json"
```

如果 launcher 已正常完成、非空补丁也已成功构建，但 oracle 状态为 `fail`，则本次运行属于
有效的修复尝试，只是生成了错误补丁。如果 launcher 或构建没有完成，则仍属于基础设施或
adapter 失败，不能计为修复失败。

## 6. 冒烟测试通过后再扩大运行范围

先运行三个案例：

```bash
python scripts/run_oci_experiment.py \
  --config configs/experiment.metagpt.yaml \
  --baseline metagpt \
  --limit 3 \
  --resume \
  2>&1 | tee results/oci-metagpt-first3.log
```

确认前三个案例正常后，再恢复运行配置中的完整案例集：

```bash
python scripts/run_oci_experiment.py \
  --config configs/experiment.metagpt.yaml \
  --baseline metagpt \
  --resume \
  2>&1 | tee results/oci-metagpt-batch.log
```

`--resume` 会跳过已有终态结果，并清理、重试中断或错误案例。不要同时使用 `--resume` 和
`--clean`。
