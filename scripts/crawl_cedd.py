#!/usr/bin/env python3
"""
Fetches CEDD Major Projects from CSDI WFS.
Data is self-contained (EN + TC titles, point coordinates, status).
Outputs data/cedd.json used by the webapp.
"""

import datetime
import json

import requests

DATASET_ID = "cedd"
DATASET_NAME = {"en": "Major Projects", "tc": "主要工程項目"}
DEPARTMENT = "CEDD"
DEPARTMENT_FULL = {"en": "Civil Engineering and Development Department", "tc": "土木工程拓展署"}

WFS_URL = (
    "https://portal.csdi.gov.hk/server/services/common/"
    "cedd_rcd_1696843963291_60361/MapServer/WFSServer"
    "?service=wfs&request=GetFeature&typenames=geotagging"
    "&outputFormat=geojson"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; HKGovProjectsBot/1.0; "
        "+https://github.com/your-org/hk-gov-projects)"
    )
}

CATEGORY_MAP = {
    "Under Planning":      1,
    "Under Construction":  2,
    "Completed":           3,
}

STATUS_LABELS = {
    1: {"en": "Under Planning",      "tc": "規劃中"},
    2: {"en": "Under Construction",  "tc": "施工中"},
    3: {"en": "Completed",           "tc": "已完成"},
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


def main():
    print("Fetching CEDD WFS GeoJSON...")
    features = fetch_geojson()
    print(f"Total: {len(features)} features\n")

    projects = []
    for feat in features:
        props = feat.get("properties", {})
        geom  = feat.get("geometry", {})

        obj_id   = props.get("OBJECTID")
        code     = props.get("ProjectCode", "").strip()
        name_en  = props.get("English_Title", "").strip()
        name_tc  = props.get("Traditional_Chinese_Title", "").strip()
        category = props.get("CategoryID", "").strip()
        status   = CATEGORY_MAP.get(category, 1)

        # Coordinates from GeoJSON geometry (Point)
        coords = geom.get("coordinates", []) if geom else []
        coordinates = [coords] if coords else []

        print(f"  [{obj_id}] {code} | {name_en[:50]} | {category} → {status}")

        projects.append({
            "id":         obj_id,
            "dataset":    DATASET_ID,
            "department": DEPARTMENT,
            "item":       code,
            "name":       name_en,
            "type":       None,
            "type_label": {"en": "", "tc": ""},
            "status":     status,
            "status_label": STATUS_LABELS[status],
            "url":        {"en": "", "tc": ""},
            "overview":   {"en": "", "tc": ""},
            "coordinates": coordinates,
            "geometry":   None,
            "page_title":         {"en": name_en, "tc": name_tc},
            "description":        {"en": "", "tc": ""},
            "scope":              {"en": "", "tc": ""},
            "agreement_no":       code,
            "cost":               {"en": "", "tc": ""},
            "award_date":         {"en": "", "tc": ""},
            "commencement_date":  {"en": "", "tc": ""},
            "commissioning_date": {"en": "", "tc": ""},
            "consultant":         {"en": "", "tc": ""},
            "contractor":         {"en": "", "tc": ""},
            "photos":             [],
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
