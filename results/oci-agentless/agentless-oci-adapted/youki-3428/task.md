Fix OCI runtime bug case youki-3428.

Target runtime: youki
Title: [Bug]: config.json env is not inherited into processes spawned with exec
Upstream issue: https://github.com/youki-dev/youki/issues/3428
Category: Process & Execution

Goal:
Modify the runtime source code so the candidate runtime behavior matches the configured reference runtime for the OCI reproduction case.
Do not edit the dataset, generated worktree metadata, or oracle scripts.

Build command that will be used after your changes:
cargo build --release

Candidate runtime path after build:
target/release/youki

Expected differential behavior and validation notes:
Issue ID: youki-3428
Upstream URL: https://github.com/youki-dev/youki/issues/3428
Category: Process & Execution

Payload under test:
process args: ["sleep", "100000"]; linux.resources.devices: [{"allow": false, "access": "rwm"}]

Expected differential behavior:
Processes spawned with exec should inherit AAA=bbb from config.json. Missing AAA=bbb indicates the bug.

Validation procedure:
1. Run this case with a known-good or reference runtime.
2. Run the same `buggy_config.json` with the runtime version suspected to contain the historical issue.
3. Compare exit status, stdout, stderr, and documented side effects.
4. Treat missing host features, missing cgroup controllers, missing seccomp support, missing runtime binaries, or insufficient privileges as environment failures rather than successful reproductions.

Case README:
# youki-3428

## Upstream Issue Summary
- Title: [Bug]: config.json env is not inherited into processes spawned with exec
- URL: https://github.com/youki-dev/youki/issues/3428
- Category: Process & Execution
- Summary: This case reduces the upstream issue to a small OCI bundle that can be used for differential runtime testing.

## Runtime Version Assessment
Use the runtime version discussed in the upstream issue as the affected implementation and compare it with a fixed or reference runtime. Some cases require specific host support such as cgroup v1, cgroup v2, seccomp, eBPF device filtering, user namespaces, or hook execution support.

## Local Reproduction Files
- `base_config.json`: clean OCI configuration before injecting the issue-specific payload.
- `buggy_config.json`: modified OCI configuration containing the payload.
- `repro.sh`: helper script that prepares a temporary OCI bundle, extracts `../../alpine-base.tar.gz`, copies the selected config to `config.json`, and invokes the runtime.
- `expected_diff.txt`: expected behavioral difference and validation oracle.
- `README.md`: this case description.

## Reproduction Prerequisites
- Linux host with permission to run OCI runtimes.
- `alpine-base.tar.gz` present in the repository root.
- Runtime binary available on `PATH` or passed with `RUNTIME=/path/to/runtime`.
- Case-specific kernel or cgroup features available when required by `expected_diff.txt`.

## Reproduction Steps
1. Change into `cases/youki-3428`.
2. Run `bash repro.sh` with the default runtime.
3. Compare implementations by rerunning with explicit binaries, for example `RUNTIME=/path/to/reference-runtime bash repro.sh` and `RUNTIME=/path/to/buggy-runtime bash repro.sh`.
4. Check the clean baseline with `CONFIG=base_config.json bash repro.sh` when useful.
5. Compare exit code, stdout, stderr, and side effects against `expected_diff.txt`.

## Result Validation
Payload: process args: ["sleep", "100000"]; linux.resources.devices: [{"allow": false, "access": "rwm"}]

Oracle: Processes spawned with exec should inherit AAA=bbb from config.json. Missing AAA=bbb indicates the bug.
