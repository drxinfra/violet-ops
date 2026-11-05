"""Summarise disk usage per mount and flag the ones above the threshold."""
import json, pathlib, shutil, sys

THRESHOLD = 0.85
MOUNTS = ["/", "/var/lib/postgresql", "/var/log"]


def usage(mount: str, threshold: float = THRESHOLD) -> dict:
    total, used, _free = shutil.disk_usage(mount)
    share = used / total
    return {"mount": mount, "used": round(share, 3), "alert": share >= threshold}


if __name__ == "__main__":
    rows = [usage(m) for m in MOUNTS if pathlib.Path(m).exists()]
    json.dump(rows, sys.stdout, indent=2)
    sys.exit(1 if any(r["alert"] for r in rows) else 0)
