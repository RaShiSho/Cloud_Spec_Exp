# PatchAgent OCI Adapter

该目录接入的是论文 **PATCHAGENT: A Practical Program Repair Agent Mimicking Human
Expertise** 及其官方公开实现，不是 arXiv 2506.17772 的 PAGENT。

## 上游与论文依据

- 论文：<https://www.usenix.org/conference/usenixsecurity25/presentation/yu-zheng>
- 官方实现：<https://github.com/cla7aye15I4nd/PatchAgent>
- 论文 artifact：<https://github.com/cla7aye15I4nd/patchagent-artifact>

论文把 PatchAgent 定义为 PoC 驱动的端到端漏洞修复 Agent，输入包括漏洞描述、至少一个
可复现 PoC 和功能测试。Agent 通过 `viewcode`、基于 LSP 的符号定位和 `validate` 交替完成
故障定位、补丁生成与验证，并使用 report purification、chain compression、auto
correction、counterexample feedback 四类交互优化。

当前官方仓库的默认 generator 会组合 2 种反例数量、4 个 temperature 和 2 种 auto-hint
设置，最多产生 16 个修复轮次，每轮默认最多 30 次 Agent 迭代。`--fast` 使用上游提供的
单轮随机配置和 15 次迭代，仅适合 smoke test。

## 安装

官方公开版要求 Linux、Python 3.12+、Git，并在 C/C++ 完整模式中依赖 LLVM 16/clangd
和 Universal Ctags。建议使用独立环境：

```bash
git clone https://github.com/cla7aye15I4nd/PatchAgent.git \
  external/baselines/PatchAgent
conda create -n patchagent python=3.12 -y
conda run -n patchagent python -m pip install -e \
  external/baselines/PatchAgent
```

正式实验应记录 `launcher_metadata.json` 中的 `baseline_revision`，不要只记录分支名。

设置 `PATCHAGENT_API_KEY`、`DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY`。API base 的优先级为
命令行 `--base-url`、`PATCHAGENT_BASE_URL`、`OPENAI_BASE_URL`、`OPENAI_API_BASE`；
均未设置时使用 `https://api.deepseek.com`。

## OCI 适配

`launch.py` 保留上游 `PatchTask`、CLike Agent、多轮 generator、三种工具、自动修正和反例
反馈。上游 builder 被替换为 OCI builder：

1. 将 runner 创建的干净 worktree 复制到隔离 workspace。
2. 把 `task.md` 作为初始缺陷报告。
3. 用语言无关的文本符号索引为 C、Go、Rust 提供 `locate`，并绕过上游 C-only 的
   libclang AST fallback；`viewcode` 仍使用上游实现。
4. `validate` 检查 diff 格式、应用补丁并执行 runtime `build_command`。
5. 找到可构建补丁后，将 diff 应用回 runner worktree。
6. runner 随后重新构建并执行统一 OCI differential oracle。

完整运行：

```bash
python scripts/run_oci_experiment.py \
  --config configs/experiment.patchagent.yaml \
  --case crun-13 \
  --clean
```

smoke test 可在配置命令末尾临时添加 `--fast`。

## 适配差异与结果解释

这不是论文实验设置的等价复现：

- 官方公开版只声明支持 C/C++ 与 Java；Go、Rust 在这里退化为文本符号定位，不能提供
  clangd 的 definition/hover 和论文中的完整 chain compression。
- OCI case 当前没有可直接传给 PatchAgent builder 的 sanitizer PoC。初始报告由 issue
  prompt 代替，候选 patch 的内部验证只包含格式、应用与构建。
- 安全行为和功能正确性由 Agent 退出后的统一 OCI oracle 判定，因此 Agent 会把“首个可构建
  patch”当作内部成功；若 oracle 失败，结果仍应记为失败。
- 论文的 92.13% 是五种模型结果的 union，并非单模型成功率；不能与本配置的单个 DeepSeek
  运行直接比较。

输出目录包含：

- `trajectory.json`：上游 PatchAgent 对话和工具调用；
- `generated_patch.diff`：Agent 选中的补丁；
- `launcher_metadata.json`：上游 revision、模型、参数和适配状态；
- `workspace/`：隔离的 PatchAgent builder 工作区。
