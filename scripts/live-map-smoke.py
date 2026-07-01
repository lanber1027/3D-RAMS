from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent import run_site_briefing  # noqa: E402


def main() -> int:
    if os.getenv("RUN_LIVE_MAP_SMOKE", "").strip().lower() not in {"1", "true", "yes", "on"}:
        print("Skipping live map smoke: set RUN_LIVE_MAP_SMOKE=true to call live public map APIs.")
        return 0

    os.environ["ENABLE_LIVE_MAP_FEATURES"] = "true"
    latitude = float(os.getenv("LIVE_MAP_SMOKE_LATITUDE", "51.4929"))
    longitude = float(os.getenv("LIVE_MAP_SMOKE_LONGITUDE", "-0.1211"))
    result = run_site_briefing({"latitude": latitude, "longitude": longitude, "useBedrock": False})
    summary = {
        "sceneMode": result["scene"].get("mode"),
        "liveFeatureStatus": result.get("liveFeatureStatus"),
        "mapFeatureCount": len(result.get("mapFeatures", [])),
        "annotationPositionModes": sorted({item.get("positionMode") for item in result.get("annotations", [])}),
    }
    print(json.dumps(summary, indent=2))
    if summary["sceneMode"] not in {"live-cesium", "live-partial"}:
        print("Live map smoke failed: scene did not enter live mode.", file=sys.stderr)
        return 1
    if summary["mapFeatureCount"] < 1:
        print("Live map smoke failed: no live map features returned.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
