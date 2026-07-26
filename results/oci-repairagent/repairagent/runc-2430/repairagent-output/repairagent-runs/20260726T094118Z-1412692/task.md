Fix OCI runtime bug case runc-2430.

Target runtime: runc
Title: support seccomp flags such as SECCOMP_FILTER_FLAG_SPEC_ALLOW (OCI Runtime Spec v1.0.2)
Upstream issue: https://github.com/opencontainers/runc/issues/2430
Category: Linux-specific Configuration

Goal:
Modify the runtime source code so the candidate runtime behavior matches the configured reference runtime for the OCI reproduction case.
Do not edit the dataset, generated worktree metadata, or oracle scripts.

Writable target repository (the only location where source changes are allowed):
/home/aludy/scires/Cloud_Spec_Exp/external/worktrees/oci-repairagent/repairagent/runc-2430

Repository revision and cleanliness are verified by the launcher before the agent starts.
Use only the commands exposed in the current RepairAgent state.

Inspect, edit, build, and collect git diff only in the writable target repository.
Do not inspect or modify the source checkout under external/subjects; it may be at a different revision.
Use absolute paths when calling Editor tools, and ensure every edited path is inside the writable target repository.

Reproduction bundle absolute path (read-only):
/home/aludy/scires/Cloud_Spec_Exp/external/oci-differential-dataset/cases/runc-2430

Rootfs tar absolute path:
/home/aludy/scires/Cloud_Spec_Exp/external/oci-differential-dataset/alpine-base.tar.gz

Run reproduction commands from the reproduction bundle directory.

Build command that will be used after your changes:
make runc

Candidate runtime path after build:
runc

Expected differential behavior and validation notes:
Issue ID: runc-2430-fuzz-crash1
Derived from: fuzz-workspace/run-smoke-20260719-180837/crashes/id-1784455727806-7843c273
Related upstream issue: https://github.com/opencontainers/runc/issues/2430
Category: Linux-specific Configuration

Payload under test:
process args: ["/bin/sh", "-c", "echo seccomp-flag-ok"]; linux.seccomp.flags: ["SECCOMP_FILTER_FLAG_SPEC_ALLOW"]; linux.seccomp.defaultAction: "SCMP_ACT_ALLOW"

Expected differential behavior:
Runtimes with OCI v1.0.2 seccomp flag support start and print `seccomp-flag-ok`. In the observed fuzz run, crun and youki exited 0 and printed the marker, while runc exited 1 with `seccomp flags are not yet supported by runc`.

Validation procedure:
1. Run `RUNTIME=/path/to/runc bash repro.sh` and record exit status, stdout, and stderr.
2. Run `RUNTIME=/path/to/crun bash repro.sh` or `RUNTIME=/path/to/youki bash repro.sh` as references.
3. Treat missing seccomp support, missing runtime binaries, insufficient privileges, or unsupported host kernels as environment failures rather than successful reproductions.
4. This case is a fuzz-derived regression duplicate of the runc-2430 seccomp flag compatibility class; keep it to preserve the exact crash artifact that produced the differential result.

Case README:
# runc-2430-fuzz-crash1

## Fuzz Discovery Summary
- Source crash: `fuzz-workspace/run-smoke-20260719-180837/crashes/id-1784455727806-7843c273`.
- Related upstream issue: https://github.com/opencontainers/runc/issues/2430
- Category: Linux-specific Configuration
- Summary: This case preserves the exact fuzz-discovered OCI configuration where `runc` rejected `SECCOMP_FILTER_FLAG_SPEC_ALLOW`, while `crun` and `youki` started the container successfully.

## Runtime Version Assessment
The observed run used `runc 1.1.14`, `crun 1.17`, and `youki 0.6.0` inside the local `oci-diff-runner:latest` image. In that environment, `runc` exited non-zero with `seccomp flags are not yet supported by runc`; `crun` and `youki` printed `seccomp-flag-ok`.

## Local Reproduction Files
- `base_config.json`: clean OCI configuration before injecting the seccomp flag payload.
- `buggy_config.json`: exact fuzz-discovered configuration from Crash 1.
- `repro.sh`: helper script that prepares a temporary OCI bundle, extracts `../../alpine-base.tar.gz`, copies the selected config to `config.json`, and invokes the runtime.
- `expected_diff.txt`: expected behavioral difference and validation oracle.
- `README.md`: this case description.

## Reproduction Prerequisites
- Linux host with permission to run OCI runtimes.
- `alpine-base.tar.gz` present in the repository root.
- Runtime binary available on `PATH` or passed with `RUNTIME=/path/to/runtime`.
- Kernel and libseccomp support sufficient for seccomp filtering.

## Reproduction Steps
1. Change into `cases/runc-2430-fuzz-crash1`.
2. Run `RUNTIME=/path/to/runc bash repro.sh`.
3. Run `RUNTIME=/path/to/crun bash repro.sh` or `RUNTIME=/path/to/youki bash repro.sh`.
4. Compare exit status, stdout, and stderr against `expected_diff.txt`.
5. Check the clean baseline with `CONFIG=base_config.json bash repro.sh` when useful.

## Result Validation
Payload: process args: ["/bin/sh", "-c", "echo seccomp-flag-ok"]; linux.seccomp.defaultAction: `SCMP_ACT_ALLOW`; linux.seccomp.flags: [`SECCOMP_FILTER_FLAG_SPEC_ALLOW`].

Oracle: runtimes with OCI v1.0.2 seccomp flag support start and print `seccomp-flag-ok`; runtimes without support fail while parsing or applying the seccomp flag.
