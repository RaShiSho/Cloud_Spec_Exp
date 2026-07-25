# MetaGPT OCI 修复实验结果报告

## 统计口径

- 数据目录：`results/oci-metagpt/metagpt/`。
- 共检查 31 个 case 目录；每个目录均包含 `metadata.json`、`oracle.json`、`stdout.log`、`stderr.log`、`launcher_metadata.json`、`wrapper_metadata.json` 和 `task.md`。
- 只有 `oracle.status == "pass"` 的 case 计为成功。模型声称完成、生成非空 diff、构建成功，都不能替代 oracle 判定。
- `oracle.status == "fail"` 计为 oracle 不匹配；未进入 oracle 的结果按实际终止阶段划分为构建失败、命令协议中止、未产生补丁或超时。
- 本批结果中没有实际保存 `candidate.patch` 文件；补丁大小来自 `metadata.json` 的 `patch_size_bytes`，补丁内容根据 MetaGPT 日志和 oracle 记录复核。因此，本报告可以判断流程结果，但当前同步副本不足以独立复核全部候选补丁。

## 实验配置与结果完整性

| 项目 | 值 |
|---|---|
| MetaGPT revision | `11cdf466d042aece04fc6cfd13b28e1a70341b1f` |
| 模型 | `deepseek-v4-flash` |
| API 类型 | `deepseek` |
| 最大轮数 | 10 |
| investment | 3.0 |
| 单 case 外层超时 | 600 秒 |
| Terminal 兼容补丁 | 31/31 应用成功 |
| worktree/workspace 绑定 | 31/31 成功 |
| 产生非空补丁 | 9/31 |
| 进入统一构建阶段 | 6/31 |
| 进入 oracle 阶段 | 5/31 |
| oracle 通过 | 3/31 |

所有 31 个 case 都有主流程日志。6 个进入统一构建阶段的 case 有构建日志，其中 5 个继续生成了 oracle 的标准输出和标准错误日志。可用的 `elapsed_seconds` 合计约 10,600.92 秒（2.94 小时），按全部 31 个 case 折算的平均值约 341.97 秒，中位数约 506.06 秒；`runc-3020` 没有记录该字段，因此合计值略低于实际耗时。

## 总体结果

| 总数 | 成功 | 成功率 | Oracle 不匹配 | 构建失败 | 命令协议中止 | 未产生补丁 | 超时 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 31 | 3 | 9.7% | 2 | 1 | 3 | 10 | 12 |

按运行时拆分如下：

| Runtime | 总数 | 成功 | 成功率 | Oracle 不匹配 | 构建失败 | 命令协议中止 | 未产生补丁 | 超时 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| crun | 12 | 1 | 8.3% | 2 | 0 | 2 | 2 | 5 |
| runc | 8 | 1 | 12.5% | 0 | 1 | 1 | 1 | 4 |
| youki | 11 | 1 | 9.1% | 0 | 0 | 0 | 7 | 3 |

整体漏斗为：31 个任务启动，9 个产生非空补丁，6 个进入统一构建，5 个进入 oracle，最终 3 个通过。若只看已经进入 oracle 的 5 个 case，通过率是 60%，但这是经过前序阶段筛选后的条件通过率，不能替代 3/31 的整体成功率。

## 成功 case

### `crun-453`

- 结果：oracle 通过；补丁 489 字节；统一构建返回码为 0。
- 修复内容：在 `src/libcrun/seccomp.c` 中增加有条件的 `SCMP_ACT_LOG` 动作映射。
- Oracle 证据：base 场景与参考实现都返回 0 并输出 `clean-base`；buggy 场景与参考实现都返回 0 并输出 `seccomp-log-action-453`。
- 结果文件：[oracle.json](oci-metagpt/metagpt/crun-453/oracle.json)

### `runc-3944`

- 结果：oracle 通过；补丁 1,192 字节；统一构建返回码为 0。
- 修复内容：在 `libcontainer/configs/validate/validator.go` 中，将 mount destination 不是绝对路径时的硬错误调整为 `logrus.Warnf`。
- Oracle 证据：base 与 buggy 场景的候选输出均和参考输出精确一致。测试环境本身不允许 rootless user namespace，但候选实现与参考实现的警告和错误输出一致，因此 oracle 仍判定通过。
- 结果文件：[oracle.json](oci-metagpt/metagpt/runc-3944/oracle.json)

### `youki-2994`

- 结果：oracle 通过；补丁 1,492 字节；统一构建返回码为 0。
- 修复内容：在 `builder_impl.rs` 中，把 `createRuntime` hooks 从创建容器进程之前移动到 `container_main_process` 之后，使 cgroup/device 限制先于 hook 生效。
- Oracle 证据：base 与 buggy 场景都返回 0，标准输出和标准错误均与参考实现一致。
- 结果文件：[oracle.json](oci-metagpt/metagpt/youki-2994/oracle.json)

## 失败分类与证据

### Oracle 不匹配：2 个

#### `crun-129`

- 产生 2,157 字节补丁，统一构建成功，但 oracle 失败。
- MetaGPT 尝试通过在 `cleanup_watch` 之前发送 `sync_socket_send_sync` 修复死锁。
- base 场景与参考实现一致；buggy 场景中参考实现返回 1，并在标准错误中报告 runc hook 错误，而候选实现同样返回 1、标准错误却为空。精确比较因此失败。
- 结果文件：[oracle.json](oci-metagpt/metagpt/crun-129/oracle.json)

#### `crun-1943`

- 产生 1,036 字节补丁，统一构建成功，但 oracle 失败。
- 补丁把 poststart hook 判断从 `ret < 0` 改为 `ret != 0`。
- base 场景与参考实现一致；buggy 场景中参考实现返回 1、标准输出为空且标准错误包含错误信息，候选实现却返回 255、输出 `poststart-false-1943` 且标准错误为空。
- 结果文件：[oracle.json](oci-metagpt/metagpt/crun-1943/oracle.json)

### 构建失败：1 个

#### `runc-3020`

- 产生 1,275 字节补丁，MetaGPT launcher 正常完成，但统一构建返回码为 2，因此没有进入 oracle。
- 构建日志同时报告未使用的 `logrus` import，以及 `ConfigValidator.rootlessEUID` 已在 `rootless.go` 中声明。该补丁重写了较大范围的 `validator.go`，引入了重复方法和未使用 import。
- 结果文件：[build_stderr.log](oci-metagpt/metagpt/runc-3020/build_stderr.log)

### 命令协议中止：3 个

这 3 个 case 都被 wrapper 的无效命令保护逻辑终止：

- `crun-13`：没有补丁；累计 3 次无效响应，最后错误为命令对象缺少 `command_name`，日志末尾为 `{}`。
- `crun-353`：没有补丁；累计 3 次无效响应，包含 `No JSON data`。
- `runc-4014`：已经产生 2,888 字节的部分补丁，但累计 3 次无效响应后中止；此前已经定位 `PidsLimit` 指针语义变化，随后模型返回 `{}`。

当前保护逻辑按累计次数而不是连续次数统计无效响应。一个 case 即使在两次无效响应之间恢复了正常工具调用，后续再次出现格式错误仍可能被提前终止。这会把尚可恢复的模型会话归类为失败，建议改为连续无效响应计数，并在成功解析一次工具命令后清零。

### 未产生补丁：10 个

其中 7 个直接受到 DeepSeek 账户余额错误影响：

- `youki-3198` 在运行约 150 秒后收到 HTTP 402 `Insufficient Balance`。
- `youki-3199`、`youki-3266`、`youki-3293`、`youki-3320`、`youki-3428`、`youki-3431` 均在约 7 秒内重复收到 HTTP 402，未开始有效修复。

其余 3 个是工具调用或模型输出问题：

- `crun-1083`：Terminal 参数类型错误，`args` 被传为字符串而不是映射；会话短暂恢复后以 `NoRepositoryChanges` 结束。
- `crun-1783`：模型返回 `null`，触发 `TypeError: 'NoneType' object is not iterable`，没有 diff。
- `runc-5182`：Editor linter 报错后又出现包含非法控制字符的 JSON，计划中的 Python 修改命令没有真正执行，最终没有 diff。

### 外层超时：12 个

以下 case 均到达约 600 秒外层超时，launcher 元数据仍处于生成或运行状态：

- `crun-1099`：停留在 `DataAnalyst.write_and_exec_code`。
- `crun-1161`：达到最大 action rounds 后等待人工输入，最后动作是 Editor 搜索。
- `crun-1307`：仍在阅读源码，最后动作是 `Editor.open_file`。
- `crun-237`：停留在 DataAnalyst 执行流程。
- `crun-876`：达到最大 action rounds 后等待人工输入。
- `runc-2430`：继续搜索宿主机/libseccomp 环境，没有形成补丁。
- `runc-2928`：已产生 637 字节部分补丁并在 MetaGPT 内部构建成功，随后执行带 `sudo` 的复现命令并等待到超时。
- `runc-4772`：停留在 DataAnalyst 执行流程。
- `runc-5073`：MetaGPT 内部构建成功，随后执行带 `sudo` 的复现命令并超时，没有保存候选补丁。
- `youki-2756`：仍在分析 device wildcard 规则，超时前没有修改。
- `youki-3132`：DataAnalyst 在已经运行的事件循环内再次调用 `asyncio.run()`，恢复过程中耗尽外层时间。
- `youki-3186`：已产生 2,482 字节部分补丁，处于构建/测试阶段，达到最大 action rounds 后等待人工输入。

其中 `crun-1161`、`crun-876`、`youki-3186` 明确进入“等待人工输入”状态；在无人值守实验中，这种状态不会自行完成，外层超时只能最终杀死进程。`runc-2928` 和 `runc-5073` 则说明 agent 不应在评测环境中直接进入交互式 `sudo` 路径。

## 全部 case 明细

| Case | 结果 | 补丁字节 | 耗时（秒） | 关键证据 |
|---|---|---:|---:|---|
| `crun-13` | 命令协议中止 | 0 | 330.17 | 3 次无效命令，缺少 `command_name` |
| `crun-129` | Oracle 不匹配 | 2,157 | 511.07 | 构建成功；buggy stderr 与参考不一致 |
| `crun-237` | 超时 | 0 | 600.27 | DataAnalyst 执行阶段停滞 |
| `crun-353` | 命令协议中止 | 0 | 314.75 | 3 次无效命令，包含 `No JSON data` |
| `crun-453` | 成功 | 489 | 142.95 | 构建成功，oracle 通过 |
| `crun-876` | 超时 | 0 | 600.40 | 最大 action rounds 后等待人工输入 |
| `crun-1083` | 未产生补丁 | 0 | 184.97 | Terminal 参数类型错误，随后 `NoRepositoryChanges` |
| `crun-1099` | 超时 | 0 | 600.32 | 停留在 DataAnalyst |
| `crun-1161` | 超时 | 0 | 600.27 | 最大 action rounds 后等待人工输入 |
| `crun-1307` | 超时 | 0 | 600.29 | 仍在源码检查 |
| `crun-1783` | 未产生补丁 | 0 | 65.27 | 模型返回 `null`，触发 TypeError |
| `crun-1943` | Oracle 不匹配 | 1,036 | 258.64 | 构建成功；buggy 返回码及输出不一致 |
| `runc-2430` | 超时 | 0 | 600.39 | 停留在宿主机/libseccomp 环境检查 |
| `runc-2928` | 超时 | 637 | 600.35 | 已有部分补丁；交互式 `sudo` 复现阻塞 |
| `runc-3020` | 构建失败 | 1,275 | 未记录 | 重复方法及未使用 import |
| `runc-3944` | 成功 | 1,192 | 173.58 | 构建成功，oracle 通过 |
| `runc-4014` | 命令协议中止 | 2,888 | 506.06 | 已有部分补丁；累计 3 次无效响应 |
| `runc-4772` | 超时 | 0 | 600.76 | 停留在 DataAnalyst |
| `runc-5073` | 超时 | 0 | 601.12 | 内部构建完成；`sudo` 复现阻塞 |
| `runc-5182` | 未产生补丁 | 0 | 112.47 | Editor 与 JSON 工具调用失败 |
| `youki-2756` | 超时 | 0 | 600.24 | 分析 device wildcard，未完成修改 |
| `youki-2994` | 成功 | 1,492 | 605.10 | 构建成功，oracle 通过 |
| `youki-3132` | 超时 | 0 | 600.36 | 活动事件循环内调用 `asyncio.run()` |
| `youki-3186` | 超时 | 2,482 | 600.33 | 部分补丁；最大 action rounds 后等待 |
| `youki-3198` | 未产生补丁 | 0 | 149.95 | DeepSeek HTTP 402 |
| `youki-3199` | 未产生补丁 | 0 | 6.90 | DeepSeek HTTP 402 |
| `youki-3266` | 未产生补丁 | 0 | 6.67 | DeepSeek HTTP 402 |
| `youki-3293` | 未产生补丁 | 0 | 6.94 | DeepSeek HTTP 402 |
| `youki-3320` | 未产生补丁 | 0 | 6.88 | DeepSeek HTTP 402 |
| `youki-3428` | 未产生补丁 | 0 | 6.75 | DeepSeek HTTP 402 |
| `youki-3431` | 未产生补丁 | 0 | 6.70 | DeepSeek HTTP 402 |

## 基础设施与框架层观察

1. **此前的 Terminal 启动和 workspace 绑定问题已经修复。** 31 个 case 都记录了 Terminal 兼容补丁已应用、workspace 绑定成功，证明 MetaGPT 已经能够进入实际的源码分析和工具调用阶段。
2. **浏览器依赖仍不完整。** 16 个 case 出现 Playwright/Chromium 因缺少 `libnspr4.so` 启动失败。该错误不是所有任务的决定性失败原因——例如 `youki-2994` 最终仍通过——但会降低需要浏览 issue 或外部资料时的成功率。
3. **Editor linter 兼容性仍有问题。** 11 个 case 出现 `__init__ takes exactly 1 argument (2 given)`。成功 case 中也出现过该错误，说明 agent 有时能绕过它，但工具可靠性明显受损。
4. **API 余额使一批结果失去模型能力评估价值。** 7 个 youki case 因 HTTP 402 没有得到完整推理机会，尤其后 6 个几乎立即失败。
5. **无人值守控制不充分。** 最大 action rounds 后等待人工输入、交互式 `sudo`、DataAnalyst 卡住等路径最终都依赖外层 600 秒超时收尾，浪费实验时间且无法保留稳定的中间状态。
6. **结果归档缺少候选补丁。** 当前 `.gitignore` 忽略 `results/**/*.patch`，因此 `candidate.patch` 没有进入同步后的结果目录。若成功结果需要可复核和可复现，应为 `candidate.patch` 增加例外规则，或单独生成包含补丁哈希和内容的轻量归档。

## 结论与修复优先级

本次 MetaGPT 全量实验的严格成功率为 **3/31（9.7%）**。它证明经过 Terminal 兼容和 workspace 绑定修复后，MetaGPT 确实可以分析仓库、修改代码、完成构建并通过精确 oracle；但 31 个结果中只有 5 个实际进入 oracle，不能把其余失败全部归因于模型修复能力。

建议按以下顺序处理：

1. 在全量重跑前完成 API 余额预检；预检失败时停止整个批次，避免生成大量无效 case 结果。
2. 修复 Browser 的系统依赖和 Editor linter 参数兼容，减少可避免的工具降级。
3. 将无效命令保护改为“连续失败计数”，每次成功工具调用后清零；同时保留最后一段原始模型响应以便诊断。
4. 在无人值守模式下自动继续或明确失败，不允许进入等待人工输入状态；拦截交互式 `sudo`，改用已有权限的复现脚本或立即返回不可执行原因。
5. 对产生部分补丁的超时 case，在终止前保存 diff 和阶段元数据；`runc-2928`、`runc-4014`、`youki-3186` 已有非空修改，不应只保留一个笼统错误状态。
6. 调整结果归档规则，确保 `candidate.patch` 可随成功结果保存。否则只能依赖日志和补丁字节数，无法从仓库中的结果目录独立重放成功修复。
