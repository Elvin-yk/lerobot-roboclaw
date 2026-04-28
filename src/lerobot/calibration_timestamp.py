from datetime import datetime
from pathlib import Path


def record_calibration_timestamp(calibration_fpath: Path) -> None:
    arm_name = calibration_fpath.stem
    time_fpath = calibration_fpath.parent.parent / "time.txt"
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    lines = time_fpath.read_text().splitlines() if time_fpath.exists() else []
    entry = f"{arm_name}: {timestamp}"
    updated = False
    for idx, line in enumerate(lines):
        name, sep, _ = line.partition(":")
        if sep and name.strip() == arm_name:
            lines[idx] = entry
            updated = True
            break

    if not updated:
        lines.append(entry)

    time_fpath.write_text("\n".join(lines) + "\n")
