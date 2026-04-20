#!/usr/bin/env python3
"""
Fetches CEDD Natural Hillside Catchments with Works from CSDI WFS.
No detail pages — all data is in the WFS.
Status is inferred from DATE_START (future → Planning, past → Construction).
Outputs data/cedd_catchments.json used by the webapp.
"""

import datetime
import json
import re
import sys

import requests

DATASET_ID = "cedd_catchments"
DATASET_NAME = {"en": "Natural Hillside Catchment Works", "tc": "防治山泥傾瀉工程"}
DEPARTMENT = "CEDD"
DEPARTMENT_FULL = {"en": "Civil Engineering and Development Department", "tc": "土木工程拓展署"}

WFS_URL = (
    "https://portal.csdi.gov.hk/server/services/common/"
    "cedd_rcd_1636520077654_856/MapServer/WFSServer"
    "?service=wfs&request=GetFeature&typenames=Catchments"
    "&outputFormat=geojson"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; HKGovProjectsBot/1.0; "
        "+https://github.com/your-org/hk-gov-projects)"
    )
}

STATUS_LABELS = {
    1: {"en": "Under Planning",     "tc": "規劃中"},
    2: {"en": "Under Construction", "tc": "施工中"},
}

QTR_MONTH = {"1st": 1, "2nd": 4, "3rd": 7, "4th": 10}


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


def parse_quarter_date(s):
    """Parse '2nd Qtr of 2023' → datetime.date, or None."""
    if not s or not s.strip():
        return None
    m = re.match(r"(\d+(?:st|nd|rd|th))\s+Qtr\s+of\s+(\d{4})", s.strip(), re.IGNORECASE)
    if not m:
        return None
    month = QTR_MONTH.get(m.group(1).lower()[:3] + m.group(1)[3:])  # e.g. "2nd"
    # simpler: re-extract ordinal
    ord_str = re.match(r"(\d+)", m.group(1)).group(1)
    qtr = int(ord_str)
    month = (qtr - 1) * 3 + 1
    year = int(m.group(2))
    return datetime.date(year, month, 1)


def infer_status(date_start_str):
    """Planning (1) if start date is in the future, else Construction (2)."""
    today = datetime.date.today()
    start = parse_quarter_date(date_start_str)
    if start and start > today:
        return 1
    return 2


def multipolygon_centroid(geometry):
    """Average all vertices of a MultiPolygon for map marker / fallback placement."""
    if not geometry:
        return None
    all_pts = []
    gtype = geometry.get("type", "")
    coords = geometry.get("coordinates", [])
    if gtype == "Polygon":
        for ring in coords:
            all_pts.extend(ring)
    elif gtype == "MultiPolygon":
        for polygon in coords:
            for ring in polygon:
                all_pts.extend(ring)
    if not all_pts:
        return None
    avg_lon = sum(p[0] for p in all_pts) / len(all_pts)
    avg_lat = sum(p[1] for p in all_pts) / len(all_pts)
    return [round(avg_lon, 6), round(avg_lat, 6)]


def main():
    print("Fetching CEDD Catchments WFS...")
    features = fetch_geojson()
    print(f"Total: {len(features)} features\n")

    today = datetime.date.today()
    projects = []
    for i, feat in enumerate(features, 1):
        props = feat.get("properties", {})
        geom  = feat.get("geometry")

        obj_id   = props.get("OBJECTID")
        contract = (props.get("WC_CONTRAC") or "").strip()
        location = (props.get("ST_LOCATIO") or "").strip()
        district = (props.get("ST_DISTRIC") or "").strip()
        feature  = (props.get("SA_FEATURE") or "").strip()
        d_start  = (props.get("DATE_START") or "").strip()
        d_comp   = (props.get("DATE_COMP_") or "").strip()

        status = infer_status(d_start)

        name_en = f"{location} – Natural Hillside Catchments with Works"
        name_tc = f"{location} – 防治山泥傾瀉工程"

        centroid = multipolygon_centroid(geom)

        print(f"  [{i:03d}/{len(features)}] {contract} S{status} | {location[:50]}...")

        projects.append({
            "id":         obj_id,
            "dataset":    DATASET_ID,
            "department": DEPARTMENT,
            "item":       contract,
            "name":       name_en,
            "type":       None,
            "type_label": {"en": "Catchment Works", "tc": "防治山泥傾瀉工程"},
            "status":     status,
            "status_label": STATUS_LABELS[status],
            "url":        {"en": "", "tc": ""},
            "coordinates": [centroid] if centroid else [],
            "geometry":   geom,
            "page_title":         {"en": name_en, "tc": name_tc},
            "description":        {"en": "", "tc": ""},
            "scope":              {"en": f"{location}, {district}" if district else location,
                                   "tc": f"{location}, {district}" if district else location},
            "agreement_no":       contract,
            "cost":               {"en": "", "tc": ""},
            "award_date":         {"en": "", "tc": ""},
            "commencement_date":  {"en": d_start, "tc": d_start},
            "commissioning_date": {"en": d_comp,  "tc": d_comp},
            "consultant":         {"en": "", "tc": ""},
            "contractor":         {"en": "", "tc": ""},
            "photos":             [],
        })

    planning    = sum(1 for p in projects if p["status"] == 1)
    construction = sum(1 for p in projects if p["status"] == 2)

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
    print(f"  Planning: {planning}  Construction: {construction}")


if __name__ == "__main__":
    main()
