# OCI Experiment Summary

Total results: 4

## By Baseline

| Baseline | pass | fail | error | env_error | incomplete |
|---|---:|---:|---:|---:|---:|
| agentless-oci-adapted | 0 | 0 | 1 | 0 | 0 |
| metagpt | 0 | 0 | 1 | 0 | 0 |
| mini-swe-agent | 0 | 0 | 1 | 0 | 0 |
| repairagent | 1 | 0 | 0 | 0 | 0 |

## Results

| Baseline | Case | Status | Error Type | Message |
|---|---|---|---|---|
| agentless-oci-adapted | crun-13 | error | baseline | baseline produced no git diff |
| metagpt | crun-13 | error | baseline | baseline command timed out: timeout after 600s |
| mini-swe-agent | crun-13 | error | baseline | baseline command failed with return code 1: ERROR conda.cli.main_run:execute(148): `conda run python /home/aludy/scires/Cloud_Spec_Exp/scripts/launch_profiled_baseline.py --kind mini_swe_agent --baseline-repo /home/aludy/scires/Cloud_Spec_Exp/external/baselines/mini-swe-agent --model-config /home/aludy/scires/Cloud_Spec_Exp/results/framework-smoke-20261001/controlled/mini-swe-agent/crun-13/model_config.json --task-file /home/aludy/scires/Cloud_Spec_Exp/results/framework-smoke-20261001/controlled/mini-swe-agent/crun-13/task.md --output /home/aludy/scires/Cloud_Spec_Exp/results/framework-smoke-20261001/controlled/mini-swe-agent/crun-13/trajectory.json` failed. (See above for error) |
| repairagent | crun-13 | pass |  | candidate behavior matches reference for base_config.json and buggy_config.json |
