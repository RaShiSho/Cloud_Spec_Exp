Fix OCI runtime bug case youki-3320.

Target runtime: youki
Title: rbind,ro mount is read-only but not recursively
Upstream issue: https://github.com/youki-dev/youki/issues/3320
Category: Filesystem & Mounts

Goal:
Modify the runtime source code so the candidate runtime behavior matches the configured reference runtime for the OCI reproduction case.
Do not edit the dataset, generated worktree metadata, or oracle scripts.

Writable target repository (the only location where source changes are allowed):
/home/aludy/scires/Cloud_Spec_Exp/external/worktrees/oci-metagpt/metagpt/youki-3320

Required first command:
cd /home/aludy/scires/Cloud_Spec_Exp/external/worktrees/oci-metagpt/metagpt/youki-3320 && git rev-parse HEAD && git status --short

Inspect, edit, build, and collect git diff only in the writable target repository.
Do not inspect or modify the source checkout under external/subjects; it may be at a different revision.
Use absolute paths when calling Editor tools, and ensure every edited path is inside the writable target repository.

Reproduction bundle absolute path (read-only):
/home/aludy/scires/Cloud_Spec_Exp/external/oci-differential-dataset/cases/youki-3320

Rootfs tar absolute path:
/home/aludy/scires/Cloud_Spec_Exp/external/oci-differential-dataset/alpine-base.tar.gz

Run reproduction commands from the reproduction bundle directory.

Build command that will be used after your changes:
cargo build --release

Candidate runtime path after build:
target/release/youki

Expected differential behavior and validation notes:
Issue ID: youki-3320
Upstream URL: https://github.com/youki-dev/youki/issues/3320
Category: Filesystem & Mounts

Payload under test:
process args: ["sh", "-c", "echo -n 'Top(/mnt/foo): '; touch /mnt/foo 2>/dev/null && echo RW || echo RO; echo -n 'Sub(/mnt/subvol/bar): '; touch /mnt/subvol/bar 2>/dev/null && echo RW || echo RO"]; linux.resources.devices: [{"allow": false, "access": "rwm"}]; additional mounts: [{"destination": "/mnt", "type": "bind", "source": "/tmp/mounts_recursive", "options": ["rbind", "ro"]}]

Expected differential behavior:
Both the top-level bind mount and recursive submount should be read-only. A buggy runtime allows writes through a recursive submount.

Validation procedure:
1. Run this case with a known-good or reference runtime.
2. Run the same `buggy_config.json` with the runtime version suspected to contain the historical issue.
3. Compare exit status, stdout, stderr, and documented side effects.
4. Treat missing host features, missing cgroup controllers, missing seccomp support, missing runtime binaries, or insufficient privileges as environment failures rather than successful reproductions.

Case README:
# youki-3320

## Upstream Issue Summary
- Title: rbind,ro mount is read-only but not recursively
- URL: https://github.com/youki-dev/youki/issues/3320
- Category: Filesystem & Mounts
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
1. Change into `cases/youki-3320`.
2. Run `bash repro.sh` with the default runtime.
3. Compare implementations by rerunning with explicit binaries, for example `RUNTIME=/path/to/reference-runtime bash repro.sh` and `RUNTIME=/path/to/buggy-runtime bash repro.sh`.
4. Check the clean baseline with `CONFIG=base_config.json bash repro.sh` when useful.
5. Compare exit code, stdout, stderr, and side effects against `expected_diff.txt`.

## Result Validation
Payload: process args: ["sh", "-c", "echo -n 'Top(/mnt/foo): '; touch /mnt/foo 2>/dev/null && echo RW || echo RO; echo -n 'Sub(/mnt/subvol/bar): '; touch /mnt/subvol/bar 2>/dev/null && echo RW || echo RO"]; linux.resources.devices: [{"allow": false, "access": "rwm"}]; additional mounts: [{"destination": "/mnt", "type": "bind", "source": "/tmp/mounts_recursive", "options": ["rbind", "ro"]}]

Oracle: Both the top-level bind mount and recursive submount should be read-only. A buggy runtime allows writes through a recursive submount.
