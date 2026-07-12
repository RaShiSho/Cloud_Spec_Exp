# OCI Repair Result Report

## 统计口径

- `pass` 视为修复成功：候选 runtime 在 `base_config.json` 和 `buggy_config.json` 上均与 reference runtime 行为一致。
- `fail` 视为 oracle 行为不一致：候选 patch 能构建并运行 oracle，但 stdout/stderr/returncode 与 reference 不完全一致。
- `error` 视为运行失败，并按 `error_type` 细分为 baseline 未产出 patch、构建失败等。
- 若同一 baseline 对同一 case 有重复运行，优先采用成功的那次。若没有成功结果，则按 `fail`、`build error`、`baseline error` 的顺序保留更有诊断价值的失败结果。

## 总体结果

| Baseline | 去重后 case 数 | 成功 | 成功率 | oracle 行为不一致 | baseline 未产出 patch | 构建失败 |
|---|---:|---:|---:|---:|---:|---:|
| `mini-swe-agent` | 25 | 4 | 16.0% | 9 | 10 | 2 |
| `agentless-oci-adapted` | 30 | 4 | 13.3% | 8 | 7 | 11 |
| 合计 | 55 | 8 | 14.5% | 17 | 17 | 13 |

## 成功 case

`mini-swe-agent` 成功 4 个：

- `crun-1083`
- `crun-237`
- `runc-3944`
- `runc-5182`

`agentless-oci-adapted` 成功 4 个：

- `crun-13`
- `runc-3944`
- `runc-5182`
- `youki-3431`

其中 `youki-3431` 在 `oci-agentless` 与 `oci-agentless-rest` 中有失败记录，但在 `oci-mini-rest` 中成功，因此按成功计入。

## 失败分类与例子

### oracle 行为不一致

这类 case 已经生成 patch，也完成构建和 oracle 运行，但 candidate 与 reference 的行为不完全一致。

- `mini-swe-agent / crun-1099`：`base_config.json` 通过，但 `buggy_config.json` 不一致。reference 返回码为 `1`，stdout 包含 `666 0 0 a:c8`；candidate 返回码为 `0`，stdout 为 `600 0 0 a:c8` 并多出 `tun-open-ok`。
- `mini-swe-agent / crun-353`：`base_config.json` 通过，但 `buggy_config.json` 不一致。reference 返回码为 `1`，stderr 是 `runc run failed ... prestart hook #0: exit status 77`；candidate 返回码为 `77`，stderr 是 `error executing hook ... exit code: 77`。
- `mini-swe-agent / runc-2928`：reference 与 candidate 都因 `rootless container requires user namespaces` 失败，但 stderr 文案不完全一致，candidate 少了 `runc run failed:` 前缀。当前 oracle 精确比较 stderr，因此判为 `fail`。
- `agentless-oci-adapted / crun-1099`：`base_config.json` 通过，但 `buggy_config.json` 不一致。reference 返回码为 `0`，stdout 包含 `600 0 0 a:c8` 和 `tun-open-ok`；candidate 返回码为 `1`，stderr 为 `mknod /dev/net/tun: Operation not permitted`。
- `agentless-oci-adapted / crun-237`：`base_config.json` 和 `buggy_config.json` 都不一致。candidate 均因 `open .../bundle/rootfs/dev/net: No such file or directory` 失败，说明 patch 引入了基础场景回归。

### baseline 未产出 patch

这类 case 没有有效源码 diff，`candidate.patch` 为空，无法进入有效修复评估。

- `mini-swe-agent / crun-13`：baseline 超时，`metadata.json` 显示 `returncode=124`、`timeout after 600s`；stderr 中有 DeepSeek 连接中断和 DNS 临时失败重试。
- `mini-swe-agent / runc-5073`：baseline 返回 `0`，但 `patch_size=0`，属于运行完成但没有产生源码修改。
- `agentless-oci-adapted / crun-1083`：最终归类为 baseline 未产出 patch，说明 Agentless 没有给出可应用的模型补丁。
- `agentless-oci-adapted / youki-3431` 的重复运行体现了本报告的去重规则：`oci-agentless` 和 `oci-agentless-rest` 中曾出现 baseline 未产出 patch，但 `oci-mini-rest` 中有一次成功，因此最终按成功计。

### 构建失败

这类 case 产生了 patch，但候选 runtime 未能构建成功。

- `mini-swe-agent / crun-876`：C 编译失败，`build_stderr.log` 中出现 `cpu undeclared`、`len undeclared`、`fmt_buf undeclared`、`dirfd_cpu undeclared` 等错误，说明 patch 破坏了 `src/libcrun/cgroup-resources.c` 的编译。
- `mini-swe-agent / youki-3266`：`cargo build --release` 超时 600 秒，日志显示 crates.io index 更新阶段多次网络超时。
- `agentless-oci-adapted / crun-353`：C 编译失败，`run_process_with_stdin_timeout_envp` 调用参数数量不匹配，并出现 `too many arguments to function`。
- `agentless-oci-adapted / youki-3186`、`youki-3266`、`youki-3293`：Rust 工具链异常，stderr 为 `Missing manifest in toolchain '1.89.0-x86_64-unknown-linux-gnu'`。
- `agentless-oci-adapted / youki-3428`：构建超时，日志显示依赖下载过程中多次 `[28] Timeout was reached`。

## 备注

当前 `fail` 的含义需要谨慎解释。oracle 使用 `returncode/stdout/stderr` 精确比较，因此部分 `runc` case 的失败更接近日志格式、运行路径或 stderr 前缀不一致，不一定代表核心功能行为完全错误。若后续要报告“功能修复率”，建议把明显语义差异和日志文本差异分开统计。
