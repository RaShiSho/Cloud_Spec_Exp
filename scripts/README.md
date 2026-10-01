# Scripts

本目录用于存放复现实验脚本。

主要入口：

- `prepare_oci_cases.py`：选择、验证 OCI case。
- `run_oci_experiment.py`：配置校验、打印最终模型配置、运行实验与核对续跑标识。
- `summarize_oci_results.py`：汇总 `results/` 中的批量输出。

模型只在 `configs/model_profiles.yaml` 配置。实验只设置 `model_profile` 名称，
适配器接收 runner 生成的 `model_config.json`，不接受模型字段的独立覆盖。
详见根目录 README 的“模型配置与密钥”。

回归检查：

```bash
python -m unittest discover -s scripts -p 'test_*.py'
conda run -n metagpt python scripts/test_model_transport.py
```

第二个命令应分别在六个 baseline 的依赖环境中执行，使用内存 HTTP transport 验证
各自安装的 SDK，不调用在线模型。`run_oci_experiment_modified.py` 仅转发至统一入口。
