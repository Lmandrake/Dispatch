# senslog

Tools for SLOG sensor-log files: a small container that field stations use to
ship readings back. Python 3.12, standard library only.

```
python3 -m senslog info  FILE
python3 -m senslog dump  FILE [--sensor N]
python3 -m senslog import CSV OUT [--station NAME] [--created TIME]
python3 -m senslog stats FILE
python3 -m senslog verify FILE...
python3 -m senslog filter IN OUT [--sensor N] [--start T] [--end T] [--label S] [--calibrated|--uncalibrated]
python3 -m senslog merge OUT IN... [--dedupe] [--station NAME]
```

Library:

```python
from senslog import Record, write_log, read_records, open_log
```

The on-disk format is in `docs/FORMAT.md`. Tests: `python3 -m pytest -q`.
