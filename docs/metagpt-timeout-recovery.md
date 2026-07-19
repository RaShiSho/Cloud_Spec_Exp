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

### 1.1 用外部 Python 文件验证 Terminal

如果终端不可靠地支持多行粘贴，不要再使用 `python - <<'PY'`。例如，回显中出现
`PYyncio.run(main())nal.close()r(output))`，说明终端回显或输入存在错位风险。当前 traceback
能够进入第 3 行的 import，不能仅凭乱码断言 Python 实际收到的源码一定损坏；改用外部
文件并执行 `py_compile` 可以消除这个不确定性。

此外，`from metagpt.tools.libs.terminal import Terminal` 会在执行 `main()` 之前加载
`Config.default()`。直接导入会读到上游 `config/config2.yaml` 中的 `YOUR_API_KEY`，所以
这次 traceback 发生在导入阶段，并不表示 `pwd` 执行失败。正式 adapter 会用隔离 HOME
写入 bootstrap 配置，再把真实 key 仅注入进程内存；直接探针也必须保持相同的导入顺序。

仓库内的 `scripts/diagnose_metagpt_terminal.py` 已经实现这个最小探针：它自动创建并清理
临时 HOME，在导入 MetaGPT 前写入只用于配置校验的假 key，然后执行并关闭 Terminal。
同步仓库到 WSL 后，先做不导入 MetaGPT 的语法检查：

```bash
cd /home/aludy/scires/Cloud_Spec_Exp
conda run -n metagpt python -m py_compile scripts/diagnose_metagpt_terminal.py
```

再从外部执行脚本。整条命令保持在一行内，避免多行粘贴损坏：

```bash
PYTHONUNBUFFERED=1 timeout --signal=TERM --kill-after=5s 20s conda run --no-capture-output -n metagpt python scripts/diagnose_metagpt_terminal.py --baseline-repo external/baselines/MetaGPT; PROBE_RC=$?; echo "probe_rc=$PROBE_RC"
```

验收标准：输出包含 `开始执行 pwd`、非空的 `终端输出`、`MetaGPT Terminal 探针通过`，且
`probe_rc=0`。MetaGPT Terminal 默认可能在自己的 workspace 中启动 shell，所以 `pwd`
不一定等于当前仓库路径；路径非空即可。其他结果按下列方式判断：

- 再次出现 `YOUR_API_KEY`：执行的不是已同步的新脚本，或 MetaGPT 在脚本导入前已被其他
  启动钩子导入。检查 `python -c 'import sys; print(sys.path)'` 和脚本绝对路径。
- `probe_rc=124`：20 秒外层 timeout 到期；如果已经输出 `开始执行 pwd`，故障位于
  Terminal 的 shell 启动、读取或关闭阶段，而不是 LLM 配置阶段。
- `probe_rc=137`：进程收到 TERM 后 5 秒仍未退出，被强制杀死；检查是否残留 shell 子进程。
- 在 `开始执行 pwd` 前 traceback：仍属于 import/依赖错误，按 traceback 中第一个项目文件
  定位，不能据此判断 Terminal 是否可用。

这个探针不会请求 LLM，因此假 key 是有意设计，不能用于正式实验。正式运行仍必须在启动
runner 的同一个 WSL shell 中设置 `METAGPT_API_KEY`、`DEEPSEEK_API_KEY` 或
`OPENAI_API_KEY`，并继续通过 adapter 注入；不要把真实 key 写入脚本或 YAML。

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
