# Results

本目录用于存放实验输出。

## 命名建议

```text
results/<experiment-name>/<baseline>/<case-id>/
```

每个 case 目录建议包含：

- `metadata.json`：运行环境、commit、模型和参数。
- `candidate.patch`：候选补丁。
- `oracle.json`：标准实现判定结果。
- `stdout.log` / `stderr.log`：运行日志。

默认 `.gitignore` 会忽略批量结果、日志和 patch 文件。需要提交的结果摘要建议整理成小型 Markdown 或 JSON 文件。
