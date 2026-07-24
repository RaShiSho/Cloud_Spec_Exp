Fix OCI runtime bug case youki-3199.

Target runtime: youki
Title: Add Linux personality support
Upstream issue: https://github.com/youki-dev/youki/issues/3199
Category: Linux-specific Configuration

Goal:
Modify the runtime source code so the candidate runtime behavior matches the configured reference runtime for the OCI reproduction case.
Do not edit the dataset, generated worktree metadata, or oracle scripts.

Writable target repository (the only location where source changes are allowed):
/home/aludy/scires/Cloud_Spec_Exp/external/worktrees/oci-metagpt/metagpt/youki-3199

Required first command:
cd /home/aludy/scires/Cloud_Spec_Exp/external/worktrees/oci-metagpt/metagpt/youki-3199 && git rev-parse HEAD && git status --short

Inspect, edit, build, and collect git diff only in the writable target repository.
Do not inspect or modify the source checkout under external/subjects; it may be at a different revision.
Use absolute paths when calling Editor tools, and ensure every edited path is inside the writable target repository.

Reproduction bundle absolute path (read-only):
/home/aludy/scires/Cloud_Spec_Exp/external/oci-differential-dataset/cases/youki-3199

Rootfs tar absolute path:
/home/aludy/scires/Cloud_Spec_Exp/external/oci-differential-dataset/alpine-base.tar.gz

Run reproduction commands from the reproduction bundle directory.

Build command that will be used after your changes:
cargo build --release

Candidate runtime path after build:
target/release/youki

Expected differential behavior and validation notes:
Issue ID: youki-3199
Upstream URL: https://github.com/youki-dev/youki/issues/3199
Category: Linux-specific Configuration

Payload under test:
process args: ["uname", "-m"]; linux.resources.devices: [{"allow": false, "access": "rwm"}]; linux.personality: {"domain": "LINUX32"}

Expected differential behavior:
Run the same buggy_config.json with a reference runtime and an affected runtime. A valid reproduction is a stable difference in exit status, stdout, stderr, runtime state, or documented side effects for the same OCI payload.

Validation procedure:
1. Run this case with a known-good or reference runtime.
2. Run the same `buggy_config.json` with the runtime version suspected to contain the historical issue.
3. Compare exit status, stdout, stderr, and documented side effects.
4. Treat missing host features, missing cgroup controllers, missing seccomp support, missing runtime binaries, or insufficient privileges as environment failures rather than successful reproductions.

Case README:
# youki-3199

## Upstream Issue Summary
- Title: Add Linux personality support
- URL: https://github.com/youki-dev/youki/issues/3199
- Category: Linux-specific Configuration
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
1. Change into `cases/youki-3199`.
2. Run `bash repro.sh` with the default runtime.
3. Compare implementations by rerunning with explicit binaries, for example `RUNTIME=/path/to/reference-runtime bash repro.sh` and `RUNTIME=/path/to/buggy-runtime bash repro.sh`.
4. Check the clean baseline with `CONFIG=base_config.json bash repro.sh` when useful.
5. Compare exit code, stdout, stderr, and side effects against `expected_diff.txt`.

## Result Validation
Payload: process args: ["uname", "-m"]; linux.resources.devices: [{"allow": false, "access": "rwm"}]; linux.personality: {"domain": "LINUX32"}

Oracle: Run the same buggy_config.json with a reference runtime and an affected runtime. A valid reproduction is a stable difference in exit status, stdout, stderr, runtime state, or documented side effects for the same OCI payload.
