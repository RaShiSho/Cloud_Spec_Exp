Fix OCI runtime bug case runc-4769.

Target runtime: runc
Title: Behavior change when duplicate additionalGids are specified
Upstream issue: https://github.com/opencontainers/runc/issues/4769
Category: Process & Execution

Goal:
Modify the runtime source code so the candidate runtime behavior matches the configured reference runtime for the OCI reproduction case.
Do not edit the dataset, generated worktree metadata, or oracle scripts.

Writable target repository (the only location where source changes are allowed):
/home/aludy/scires/Cloud_Spec_Exp/external/worktrees/oci-repairagent/repairagent/runc-4769

Repository revision and cleanliness are verified by the launcher before the agent starts.
Use only the commands exposed in the current RepairAgent state.

Inspect, edit, build, and collect git diff only in the writable target repository.
Do not inspect or modify the source checkout under external/subjects; it may be at a different revision.
Use absolute paths when calling Editor tools, and ensure every edited path is inside the writable target repository.

Reproduction bundle absolute path (read-only):
/home/aludy/scires/Cloud_Spec_Exp/external/oci-differential-dataset/cases/runc-4769

Rootfs tar absolute path:
/home/aludy/scires/Cloud_Spec_Exp/external/oci-differential-dataset/alpine-base.tar.gz

Run reproduction commands from the reproduction bundle directory.

Build command that will be used after your changes:
make runc

Candidate runtime path after build:
runc

Expected differential behavior and validation notes:
Issue ID: runc-4769
Upstream URL: https://github.com/opencontainers/runc/issues/4769
Category: Process & Execution

Payload under test:
process.user: {"uid": 0, "gid": 0, "additionalGids": [1000, 2000, 3000, 3000]}; process args: ["/usr/bin/id"]

Expected differential behavior:
runc v1.3.0 preserves duplicate additionalGids, so `id` reports `groups=1000,2000,3000,3000`.
runc v1.2.6 deduplicates duplicate additionalGids, so `id` reports `groups=1000,2000,3000`.
crun 1.14.1 also preserves duplicate additionalGids, while youki follows the older runc behavior and deduplicates them.

Validation procedure:
1. Run this case with the affected runtime, for example `RUNTIME=/path/to/runc-v1.3.0 bash repro.sh`.
2. Run the same `buggy_config.json` with a reference runtime, for example `RUNTIME=/path/to/runc-v1.2.6 bash repro.sh`.
3. Compare stdout from `id`; the useful signal is whether the second `3000` is preserved or removed.
4. Run `CONFIG=base_config.json bash repro.sh` as a sanity check; the baseline should report `groups=1000,2000,3000`.
5. Treat missing runtime binaries, missing rootfs archive, or insufficient privileges as environment failures rather than successful reproductions.

Case README:
# runc-4769

## Upstream Issue Summary
- Title: Behavior change when duplicate additionalGids are specified
- URL: https://github.com/opencontainers/runc/issues/4769
- Category: Process & Execution
- Summary: This case reduces the issue to a small OCI process user configuration whose `additionalGids` list contains a duplicate GID.

## Runtime Version Assessment
The upstream report compares runc v1.3.0 with runc v1.2.6. runc v1.3.0 preserves duplicate `additionalGids`, while runc v1.2.6 deduplicates them. The report also notes that crun preserves duplicates and youki follows the older runc deduplication behavior.

## Buggy Version Identification
Issue text identifies `runc version 1.3.0` as the behavior-changing version. The reported behavior changed after opencontainers/runc PR #3999 removed the older path that indirectly deduplicated group IDs through a map.

## Local Reproduction Files
- `base_config.json`: clean OCI configuration with `additionalGids` set to `[1000, 2000, 3000]`.
- `buggy_config.json`: modified OCI configuration with `additionalGids` set to `[1000, 2000, 3000, 3000]`.
- `repro.sh`: helper script that prepares a temporary OCI bundle, extracts `../../alpine-base.tar.gz`, copies the selected config to `config.json`, and invokes the runtime.
- `expected_diff.txt`: expected behavioral difference and validation oracle.
- `README.md`: this case description.

## Reproduction Prerequisites
- Linux host with permission to run OCI runtimes.
- `alpine-base.tar.gz` present in the repository root.
- Runtime binary available on `PATH` or passed with `RUNTIME=/path/to/runtime`.
- A rootfs containing `/usr/bin/id`; the repository Alpine rootfs provides it.

## Reproduction Steps
1. Change into `cases/runc-4769`.
2. Run `bash repro.sh` with the default runtime.
3. Compare implementations by rerunning with explicit binaries, for example `RUNTIME=/path/to/runc-v1.3.0 bash repro.sh` and `RUNTIME=/path/to/runc-v1.2.6 bash repro.sh`.
4. Check the clean baseline with `CONFIG=base_config.json bash repro.sh`.
5. Compare stdout from `id` against `expected_diff.txt`.

## Result Validation
Payload: process.user: {"uid": 0, "gid": 0, "additionalGids": [1000, 2000, 3000, 3000]}; process args: ["/usr/bin/id"]

Oracle: runc v1.3.0 and crun preserve the duplicate group, producing `groups=1000,2000,3000,3000`. runc v1.2.6 and youki deduplicate it, producing `groups=1000,2000,3000`. The baseline config should always produce `groups=1000,2000,3000`.
