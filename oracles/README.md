# Oracles

本目录用于接入标准实现或对照执行器，例如 `runC`。

## 目标

oracle 需要给出统一的判定结果：

- `pass`：候选修复行为与标准实现一致。
- `fail`：候选修复仍存在行为差异。
- `error`：运行环境、编译、超时或输入数据异常导致无法判定。

## 建议接口

统一脚本可以接受：

```text
--case <case_id>
--candidate <candidate_path>
--reference <reference_path>
--output <result_json>
```

输出建议使用 JSON，至少包含：

- `case_id`
- `status`
- `message`
- `elapsed_seconds`
- `diff_summary`

初始化阶段暂不实现具体 oracle，等 `runC` 的路径、输入协议和输出格式确定后再补充。
