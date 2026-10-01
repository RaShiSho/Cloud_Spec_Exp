"""Compatibility entrypoint; keep one validated experiment runner."""
from run_oci_experiment import main

if __name__ == "__main__":
    raise SystemExit(main())
