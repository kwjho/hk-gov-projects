#!/usr/bin/env python3
"""
Fetches WSD Major Infrastructure Projects from CSDI WFS.
Data is self-contained (EN + TC descriptions already in GeoJSON).
Outputs data/wsd.json used by the webapp.
"""

import datetime
import json
import sys

import requests

DATASET_ID = "wsd"
DATASET_NAME = {"en": "Major Infrastructure Projects", "tc": "主要基建工程項目"}
DEPARTMENT = "WSD"
DEPARTMENT_FULL = {"en": "Water Services Department", "tc": "水務署"}

WFS_URL = (
    "https://portal.csdi.gov.hk/server/services/common/"
    "wsd_rcd_1696486647021_69503/MapServer/WFSServer"
    "?service=wfs&request=GetFeature&typenames=Major_Infrastructure_Projects"
    "&outputFormat=geojson"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; HKGovProjectsBot/1.0; "
        "+https://github.com/your-org/hk-gov-projects)"
    )
}

# WSD only has UC and C — map to shared status integers
PROGRESS_MAP = {
    "C":  3,   # Completed
    "UC": 2,   # Under Construction
}

STATUS_LABELS = {
    2: {"en": "Under Construction", "tc": "施工中"},
    3: {"en": "Completed",          "tc": "已完成"},
}


def fetch_geojson():
    features = []
    start, page_size = 0, 1000
    while True:
        url = WFS_URL + f"&count={page_size}&startIndex={start}"
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        batch = r.json().get("features", [])
        features.extend(batch)
        print(f"  Fetched {len(features)} features...")
        if len(batch) < page_size:
            break
        start += page_size
    return features


def polygon_centroid(geometry):
    """Compute a simple centroid [lon, lat] from a MultiPolygon or Polygon."""
    if not geometry:
        return None
    gtype = geometry.get("type", "")
    coords = geometry.get("coordinates", [])
    all_points = []
    if gtype == "Polygon":
        all_points = coords[0] if coords else []
    elif gtype == "MultiPolygon":
        for poly in coords:
            all_points.extend(poly[0] if poly else [])
    if not all_points:
        return None
    lon = sum(p[0] for p in all_points) / len(all_points)
    lat = sum(p[1] for p in all_points) / len(all_points)
    return [round(lon, 6), round(lat, 6)]


def main():
    print("Fetching WSD WFS GeoJSON...")
    features = fetch_geojson()
    print(f"Total: {len(features)} features\n")

    projects = []
    for feat in features:
        props = feat.get("properties", {})
        geom  = feat.get("geometry", {})

        obj_id   = props.get("OBJECTID")
        item     = props.get("ITEM")
        name     = props.get("PROJECT", "").strip()
        overview_en = props.get("OVERVIEW", "").strip()
        overview_tc = props.get("OVERVIEW_CHINESE", "").strip()
        progress = props.get("PROGRESS", "").strip().upper()
        status   = PROGRESS_MAP.get(progress, 2)

        print(f"  [{obj_id}] {name} | {progress} → status {status}")

        centroid = polygon_centroid(geom)

        projects.append({
            "id":         obj_id,
            "dataset":    DATASET_ID,
            "department": DEPARTMENT,
            "item":       item,
            "name":       name,
            "type":       None,
            "type_label": {"en": "", "tc": ""},
            "status":     status,
            "status_label": STATUS_LABELS.get(status, {"en": str(status), "tc": str(status)}),
            "url":        {"en": "", "tc": ""},
            "overview":   {"en": overview_en, "tc": overview_tc},
            # centroid for map popup anchor
            "coordinates": [centroid] if centroid else [],
            # full polygon geometry for map rendering
            "geometry":   geom,
            # fields left blank (not available for WSD)
            "page_title":        {"en": name, "tc": name},
            "description":       {"en": overview_en, "tc": overview_tc},
            "scope":             {"en": "", "tc": ""},
            "agreement_no":      "",
            "cost":              {"en": "", "tc": ""},
            "award_date":        {"en": "", "tc": ""},
            "commencement_date": {"en": "", "tc": ""},
            "commissioning_date":{"en": "", "tc": ""},
            "consultant":        {"en": "", "tc": ""},
            "contractor":        {"en": "", "tc": ""},
            "photos":            [],
        })

    output = {
        "dataset_id":      DATASET_ID,
        "dataset_name":    DATASET_NAME,
        "department":      DEPARTMENT,
        "department_full": DEPARTMENT_FULL,
        "generated_at":    datetime.datetime.now(datetime.UTC).isoformat(),
        "total":           len(projects),
        "projects":        projects,
    }

    out_path = f"data/{DATASET_ID}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(projects)} projects → {out_path}")


if __name__ == "__main__":
    main()
