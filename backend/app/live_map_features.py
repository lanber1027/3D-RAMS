from __future__ import annotations

import re
import time
from typing import Any

import httpx

from .config import RuntimeConfig


PLANNING_DATASETS = [
    "flood-risk-zone",
    "conservation-area",
    "listed-building",
    "scheduled-monument",
    "site-of-special-scientific-interest",
    "green-belt",
    "brownfield-land",
]

OSM_FEATURE_QUERIES = [
    'way["building"](around:{radius},{lat},{lon});',
    'way["highway"](around:{radius},{lat},{lon});',
    'way["waterway"](around:{radius},{lat},{lon});',
    'way["railway"](around:{radius},{lat},{lon});',
    'way["power"](around:{radius},{lat},{lon});',
    'node["barrier"](around:{radius},{lat},{lon});',
]


def load_live_map_features(location: dict[str, Any], config: RuntimeConfig) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.perf_counter()
    latitude = float(location["latitude"])
    longitude = float(location["longitude"])
    features: list[dict[str, Any]] = []
    successful_sources: list[str] = []
    failed_sources: list[dict[str, str]] = []

    try:
        planning_features = _fetch_planning_features(latitude, longitude, config)
        features.extend(planning_features)
        successful_sources.append("planning.data.gov.uk/entity.json")
    except Exception as exc:
        failed_sources.append({"source": "planning.data.gov.uk/entity.json", "reason": exc.__class__.__name__})

    try:
        osm_features = _fetch_osm_features(latitude, longitude, config)
        features.extend(osm_features)
        successful_sources.append("overpass/osm")
    except Exception as exc:
        failed_sources.append({"source": "overpass/osm", "reason": exc.__class__.__name__})

    deduped = _dedupe_features(features)[:80]
    status = "live" if successful_sources and not failed_sources else "partial" if successful_sources else "failed"
    return deduped, {
        "status": status,
        "successfulSources": successful_sources,
        "failedSources": failed_sources,
        "featureCount": len(deduped),
        "radiusMeters": config.live_feature_radius_meters,
        "latencyMs": int((time.perf_counter() - started) * 1000),
        "mode": "live-public-features",
    }


def _fetch_planning_features(latitude: float, longitude: float, config: RuntimeConfig) -> list[dict[str, Any]]:
    params: list[tuple[str, str]] = [
        ("latitude", f"{latitude:.7f}"),
        ("longitude", f"{longitude:.7f}"),
        ("limit", "50"),
        ("field", "entity"),
        ("field", "name"),
        ("field", "dataset"),
        ("field", "reference"),
        ("field", "geometry"),
        ("field", "point"),
        ("field", "start-date"),
    ]
    params.extend(("dataset", dataset) for dataset in PLANNING_DATASETS)
    response = httpx.get(
        f"{config.planning_data_api_base.rstrip('/')}/entity.json",
        params=params,
        headers={"User-Agent": "3D-RAMS-hackathon-live-map/0.1"},
        timeout=6.0,
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("entities") or payload.get("data") or payload.get("results") or []
    features: list[dict[str, Any]] = []
    for row in rows[:50]:
        dataset = str(row.get("dataset") or "planning-designation")
        point = _point_from_wkt(row.get("point")) or _point_from_wkt(row.get("geometry")) or {"latitude": latitude, "longitude": longitude}
        label = row.get("name") or row.get("reference") or dataset.replace("-", " ").title()
        feature_id = f"planning-{row.get('entity') or row.get('reference') or _slug(label)}"
        features.append(
            {
                "id": feature_id,
                "type": "designation",
                "layer": "planning",
                "label": str(label)[:120],
                "provider": "Planning Data API",
                "source": "planning.data.gov.uk/entity.json",
                "sourceIds": ["planning-data-live"],
                "evidenceIds": ["planning-data-live"],
                "confidence": "medium",
                "risk_note": f"Live Planning Data reports {dataset.replace('-', ' ')} at or intersecting the confirmed coordinate. Verify current status before site work.",
                "dataMode": "live-public",
                "freshness": "live lookup at run time",
                "attribution": "Planning Data API, Open Government Licence v3.0.",
                "geometry": _geometry_from_wkt(row.get("geometry"), fallback_point=point),
                "centroid": point,
                "reference": row.get("reference"),
                "dataset": dataset,
            }
        )
    return features


def _fetch_osm_features(latitude: float, longitude: float, config: RuntimeConfig) -> list[dict[str, Any]]:
    radius = config.live_feature_radius_meters
    body = "[out:json][timeout:6];(" + "".join(
        query.format(radius=radius, lat=f"{latitude:.7f}", lon=f"{longitude:.7f}") for query in OSM_FEATURE_QUERIES
    ) + ");out center geom 80;"
    response = httpx.post(
        config.overpass_api_url,
        data={"data": body},
        headers={"User-Agent": "3D-RAMS-hackathon-live-map/0.1"},
        timeout=8.0,
    )
    response.raise_for_status()
    elements = (response.json() or {}).get("elements") or []
    features: list[dict[str, Any]] = []
    for element in elements[:80]:
        tags = element.get("tags") or {}
        geometry = _osm_geometry(element)
        centroid = _osm_centroid(element, geometry, latitude, longitude)
        layer, feature_type, risk_note = _osm_layer(tags)
        label = tags.get("name") or tags.get("ref") or _osm_label(layer, tags)
        features.append(
            {
                "id": f"osm-{element.get('type', 'element')}-{element.get('id')}",
                "type": feature_type,
                "layer": layer,
                "label": str(label)[:120],
                "provider": "OpenStreetMap via Overpass API",
                "source": "overpass/osm",
                "sourceIds": ["osm-live"],
                "evidenceIds": ["osm-live"],
                "confidence": "medium" if tags.get("name") else "low",
                "risk_note": risk_note,
                "dataMode": "live-public",
                "freshness": "live lookup at run time",
                "attribution": "OpenStreetMap contributors via Overpass API.",
                "geometry": geometry,
                "centroid": centroid,
                "tags": {key: tags[key] for key in sorted(tags)[:12]},
            }
        )
    return features


def _osm_layer(tags: dict[str, Any]) -> tuple[str, str, str]:
    if tags.get("building"):
        return "buildings", "building", "Nearby building or structure interface. Check public interface, access constraints, and exclusion zones."
    if tags.get("waterway"):
        return "water", "watercourse", "Live OSM waterway feature near the site. Check bank, flood, and drainage conditions."
    if tags.get("railway"):
        return "rail", "interface", "Live OSM railway feature near the site. Check access boundary, permits, and interface controls."
    if tags.get("power"):
        return "power", "interface", "Live OSM power feature near the site. Check electrical boundaries and overhead/underground service risk."
    if tags.get("barrier"):
        return "access", "access_track", "Live OSM barrier/access feature near the site. Confirm gates, controls, and emergency access."
    return "access", "access_track", "Live OSM highway/access feature near the site. Confirm approach route, vehicle suitability, and pedestrian interface."


def _osm_label(layer: str, tags: dict[str, Any]) -> str:
    if layer == "buildings":
        return f"Building: {tags.get('building', 'mapped footprint')}"
    if tags.get("highway"):
        return f"Access route: {tags['highway']}"
    if tags.get("waterway"):
        return f"Waterway: {tags['waterway']}"
    if tags.get("railway"):
        return f"Railway: {tags['railway']}"
    if tags.get("power"):
        return f"Power asset: {tags['power']}"
    return "Mapped site interface"


def _osm_geometry(element: dict[str, Any]) -> dict[str, Any]:
    points = [
        [float(point["lon"]), float(point["lat"])]
        for point in element.get("geometry", [])
        if point.get("lat") is not None and point.get("lon") is not None
    ]
    if len(points) >= 4 and points[0] == points[-1]:
        return {"type": "Polygon", "coordinates": [points]}
    if len(points) >= 2:
        return {"type": "LineString", "coordinates": points}
    if element.get("lon") is not None and element.get("lat") is not None:
        return {"type": "Point", "coordinates": [float(element["lon"]), float(element["lat"])]}
    center = element.get("center") or {}
    if center.get("lon") is not None and center.get("lat") is not None:
        return {"type": "Point", "coordinates": [float(center["lon"]), float(center["lat"])]}
    return {"type": "Point", "coordinates": [0.0, 0.0]}


def _osm_centroid(element: dict[str, Any], geometry: dict[str, Any], fallback_lat: float, fallback_lon: float) -> dict[str, float]:
    center = element.get("center") or {}
    if center.get("lat") is not None and center.get("lon") is not None:
        return {"latitude": float(center["lat"]), "longitude": float(center["lon"])}
    return _centroid_from_geometry(geometry) or {"latitude": fallback_lat, "longitude": fallback_lon}


def _geometry_from_wkt(value: Any, *, fallback_point: dict[str, float]) -> dict[str, Any]:
    point = _point_from_wkt(value)
    if point:
        return {"type": "Point", "coordinates": [point["longitude"], point["latitude"]]}
    return {"type": "Point", "coordinates": [fallback_point["longitude"], fallback_point["latitude"]]}


def _point_from_wkt(value: Any) -> dict[str, float] | None:
    if not value:
        return None
    match = re.search(r"POINT\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)", str(value), re.IGNORECASE)
    if match:
        return {"longitude": float(match.group(1)), "latitude": float(match.group(2))}
    return None


def _centroid_from_geometry(geometry: dict[str, Any]) -> dict[str, float] | None:
    coordinates = geometry.get("coordinates")
    points: list[list[float]] = []
    if geometry.get("type") == "Point" and isinstance(coordinates, list) and len(coordinates) >= 2:
        return {"longitude": float(coordinates[0]), "latitude": float(coordinates[1])}
    if geometry.get("type") == "LineString" and isinstance(coordinates, list):
        points = coordinates
    if geometry.get("type") == "Polygon" and isinstance(coordinates, list) and coordinates:
        points = coordinates[0]
    clean = [point for point in points if isinstance(point, list) and len(point) >= 2]
    if not clean:
        return None
    return {
        "longitude": sum(float(point[0]) for point in clean) / len(clean),
        "latitude": sum(float(point[1]) for point in clean) / len(clean),
    }


def _dedupe_features(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for feature in features:
        key = str(feature.get("id"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(feature)
    return deduped


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")[:80] or "feature"
