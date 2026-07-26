Fix OCI runtime bug case youki-3132.

Target runtime: youki
Title: [Bug]: Normal logs logged at Error level in container create
Upstream issue: https://github.com/youki-dev/youki/issues/3132
Category: Lifecycle & State

Goal:
Modify the runtime source code so the candidate runtime behavior matches the configured reference runtime for the OCI reproduction case.
Do not edit the dataset, generated worktree metadata, or oracle scripts.

Writable target repository (the only location where source changes are allowed):
/home/aludy/scires/Cloud_Spec_Exp/external/worktrees/oci-repairagent/repairagent/youki-3132

Repository revision and cleanliness are verified by the launcher before the agent starts.
Use only the commands exposed in the current RepairAgent state.

Inspect, edit, build, and collect git diff only in the writable target repository.
Do not inspect or modify the source checkout under external/subjects; it may be at a different revision.
Use absolute paths when calling Editor tools, and ensure every edited path is inside the writable target repository.

Reproduction bundle absolute path (read-only):
/home/aludy/scires/Cloud_Spec_Exp/external/oci-differential-dataset/cases/youki-3132

Rootfs tar absolute path:
/home/aludy/scires/Cloud_Spec_Exp/external/oci-differential-dataset/alpine-base.tar.gz

Run reproduction commands from the reproduction bundle directory.

Build command that will be used after your changes:
cargo build --release

Candidate runtime path after build:
target/release/youki

Expected differential behavior and validation notes:
Issue ID: youki-3132
Upstream URL: https://github.com/youki-dev/youki/issues/3132
Category: Lifecycle & State

Payload under test:
process args: ["true"]; linux.resources.devices: [{"allow": false, "access": "rwm"}]

Expected differential behavior:
Run the same buggy_config.json with a reference runtime and an affected runtime. A valid reproduction is a stable difference in exit status, stdout, stderr, runtime state, or documented side effects for the same OCI payload.

Validation procedure:
1. Run this case with a known-good or reference runtime.
2. Run the same `buggy_config.json` with the runtime version suspected to contain the historical issue.
3. Compare exit status, stdout, stderr, and documented side effects.
4. Treat missing host features, missing cgroup controllers, missing seccomp support, missing runtime binaries, or insufficient privileges as environment failures rather than successful reproductions.

Case README:
# youki-3132

## Upstream Issue Summary
- Title: [Bug]: Normal logs logged at Error level in container create
- URL: https://github.com/youki-dev/youki/issues/3132
- Category: Lifecycle & State
- Summary: This case reduces the upstream issue to a small OCI bundle that can be used for differential runtime testing.

## Runtime Version Assessment
Use the runtime version discussed in the upstream issue as the affected implementation and compare it with a fixed or reference runtime. Some cases require specific host support such as cgroup v1, cgroup v2, seccomp, eBPF device filtering, user namespaces, or hook execution support.

## Buggy Version Identification
The issue text does not name an exact youki release; it reports the behavior on Pop OS after a recent kernel update and says it had been observed for roughly four to five months. The issue body shows two independent error-level log paths: cgroup mount retry logging and ambient capability logging. The issue page is closed and links PR #3150 and PR #3157 as relevant fixes. Local git history maps PR #3150 to `9560eb10405738668025ae69870401e28633e6c3` (`fix: capet Ambient log level`, 2025-04-19), whose parent is `df8f3aaadb61a6d488bcee08aa9c323fb5ac5dca`; it maps PR #3157 to `6b02740e8f339d558a1ddbd8ff6b1793fb9c04f0` (`fix: mount retry and logging (#3157)`, 2025-05-22), whose parent is `8b85144c0da42db558eec8e82899859cd278eaf9`. Use those parent commits as the two pre-fix buggy baselines for the ambient-capability and cgroup-mount log paths respectively. `git describe` places the PR #3150 parent at `v0.5.3-30-gdf8f3aaadb61` and the PR #3157 parent at `v0.5.3-53-g8b85144c0da4`, both before `v0.5.4`.

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
1. Change into `cases/youki-3132`.
2. Run `bash repro.sh` with the default runtime.
3. Compare implementations by rerunning with explicit binaries, for example `RUNTIME=/path/to/reference-runtime bash repro.sh` and `RUNTIME=/path/to/buggy-runtime bash repro.sh`.
4. Check the clean baseline with `CONFIG=base_config.json bash repro.sh` when useful.
5. Compare exit code, stdout, stderr, and side effects against `expected_diff.txt`.

## Result Validation
Payload: process args: ["true"]; linux.resources.devices: [{"allow": false, "access": "rwm"}]

Oracle: Run the same buggy_config.json with a reference runtime and an affected runtime. A valid reproduction is a stable difference in exit status, stdout, stderr, runtime state, or documented side effects for the same OCI payload.

## Additional Validation Note (2026-07-19)
Using only `buggy_config.json` with the provided `alpine-base.tar.gz` rootfs, the original log-level issue was not reproduced with the current `repro.sh`. The payload only runs `true`, and the script does not enable or capture a runtime log stream that can distinguish normal messages logged at `ERROR` level from expected output. In the previous isolated run, runc and crun completed without useful output, while youki timed out without exposing the specific log-level symptom. Reproducing the original issue appears to require the affected youki revision plus explicit log-level capture or the cgroup/ambient-capability logging conditions from the upstream report.
