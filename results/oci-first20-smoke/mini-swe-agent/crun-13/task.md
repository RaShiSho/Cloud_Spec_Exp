Fix OCI runtime bug case crun-13.

Target runtime: crun
Title: $PATH lookup before exec'ing the container process
Upstream issue: https://github.com/containers/crun/issues/13
Category: Process & Execution

Goal:
Modify the runtime source code so the candidate runtime behavior matches the configured reference runtime for the OCI reproduction case.
Do not edit the dataset, generated worktree metadata, or oracle scripts.

Build command that will be used after your changes:
./autogen.sh && ./configure && make -j$(nproc)

Candidate runtime path after build:
crun

Expected differential behavior and validation notes:
Issue ID: crun-13
Upstream URL: https://github.com/containers/crun/issues/13
Category: Process & Execution

Payload under test:
process args: ["sh", "-c", "echo process-path-13; command -v sh"]; linux.resources.devices: [{"allow": false, "access": "rwm"}]

Expected differential behavior:
Run the same buggy_config.json with a reference runtime and an affected runtime. A valid reproduction is a stable difference in exit status, stdout, stderr, runtime state, or documented side effects for the same OCI payload.

Validation procedure:
1. Run this case with a known-good or reference runtime.
2. Run the same `buggy_config.json` with the runtime version suspected to contain the historical issue.
3. Compare exit status, stdout, stderr, and documented side effects.
4. Treat missing host features, missing cgroup controllers, missing seccomp support, missing runtime binaries, or insufficient privileges as environment failures rather than successful reproductions.

Case README:
# crun-13

## Upstream Issue Summary
- Title: $PATH lookup before exec'ing the container process
- URL: https://github.com/containers/crun/issues/13
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
1. Change into `cases/crun-13`.
2. Run `bash repro.sh` with the default runtime.
3. Compare implementations by rerunning with explicit binaries, for example `RUNTIME=/path/to/reference-runtime bash repro.sh` and `RUNTIME=/path/to/buggy-runtime bash repro.sh`.
4. Check the clean baseline with `CONFIG=base_config.json bash repro.sh` when useful.
5. Compare exit code, stdout, stderr, and side effects against `expected_diff.txt`.

## Result Validation
Payload: process args: ["sh", "-c", "echo process-path-13; command -v sh"]; linux.resources.devices: [{"allow": false, "access": "rwm"}]

Oracle: Run the same buggy_config.json with a reference runtime and an affected runtime. A valid reproduction is a stable difference in exit status, stdout, stderr, runtime state, or documented side effects for the same OCI payload.
