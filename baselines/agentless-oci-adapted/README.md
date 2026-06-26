# Agentless OCI Adapter

This directory stores the tracked compatibility layer for running Agentless on OCI differential cases.

The upstream Agentless repair entrypoint is SWE-bench-oriented. It expects benchmark rows from Hugging Face with `instance_id`, `problem_statement`, `repo`, and `base_commit`, then reconstructs repository contents through SWE-bench helpers. OCI differential cases are not SWE-bench tasks, so this project records the adaptation explicitly.

## Expected Clone Layout

Clone Agentless outside tracked project files:

```text
external/baselines/Agentless
```

Apply the patch before running `agentless-oci-adapted`:

```bash
cd external/baselines/Agentless
git apply ../../../baselines/agentless-oci-adapted/agentless_oci_dataset.patch
```

## Adapter Contract

The experiment runner writes two files per case:

- `agentless_task.jsonl`: one JSON object containing `instance_id`, `problem_statement`, and `repo_path`.
- `agentless_locs.jsonl`: one JSON object containing `instance_id`, `found_files`, and `found_edit_locs`.

The patched Agentless command uses repair-only mode:

```bash
python agentless/repair/repair.py \
  --oci_task_file <agentless_task.jsonl> \
  --loc_file <agentless_locs.jsonl> \
  --output_folder <agentless-output> \
  --target_id <case-id> \
  --diff_format \
  --cot \
  --gen_and_process
```

Report this baseline as `Agentless-OCI-adapted`, not as an unmodified Agentless run.
