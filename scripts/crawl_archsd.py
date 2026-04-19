#!/usr/bin/env python3
"""
Fetches ARCHSD Capital Projects (Under Planning + Under Construction) from CSDI WFS.
Scrapes detail pages for project photos and stores page URLs.
Outputs data/archsd.json used by the webapp.
"""

import datetime
import json
import re
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

DATASET_ID = "archsd"
DATASET_NAME = {"en": "Capital Projects", "tc": "資本工程項目"}
DEPARTMENT = "ARCHSD"
DEPARTMENT_FULL = {"en": "Architectural Services Department", "tc": "建築署"}

BASE_URL = "https://www.archsd.gov.hk"
DETAIL_URL_EN = BASE_URL + "/en/projects/capital-projects-under-detail/{code}.html"
DETAIL_URL_TC = BASE_URL + "/tc/projects/capital-projects-under-detail/{code}.html"

WFS_PLANNING = (
    "https://portal.csdi.gov.hk/server/services/common/"
    "archsd_rcd_1637285145538_84229/MapServer/WFSServer"
    "?service=wfs&request=GetFeature&typenames=csdi:CapitalProjectUnderPlanning"
    "&outputFormat=geojson"
)
WFS_CONSTRUCTION = (
    "https://portal.csdi.gov.hk/server/services/common/"
    "archsd_rcd_1637294600558_18821/MapServer/WFSServer"
    "?service=wfs&request=GetFeature&typenames=CapitalProjetsUnderConstruction"
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


def fetch_geojson(wfs_url):
    features = []
    start, page_size = 0, 1000
    while True:
        url = wfs_url + f"&count={page_size}&startIndex={start}"
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        batch = r.json().get("features", [])
        features.extend(batch)
        print(f"  Fetched {len(features)} features...")
        if len(batch) < page_size:
            break
        start += page_size
    return features


def get_soup(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        r.encoding = "utf-8"
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"    WARNING: {url}: {e}", file=sys.stderr)
        return None


def scrape_photos(code):
    """Fetch EN detail page and extract project photos from /media/projects/ paths."""
    url = DETAIL_URL_EN.format(code=code)
    soup = get_soup(url)
    if not soup:
        return []
    photos = []
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if not src.startswith("/media/projects/"):
            continue
        if not re.search(r"\.(jpg|jpeg|png|webp)$", src, re.I):
            continue
        abs_src = BASE_URL + src
        alt = img.get("alt", "")
        if abs_src not in [p["url"] for p in photos]:
            photos.append({"url": abs_src, "alt": alt})
        if len(photos) >= 4:
            break
    return photos


def merge_multipoint(features):
    """
    Some projects appear as multiple Point features (one per site/building).
    Group by projectCode and average the coordinates.
    Returns one entry per projectCode with averaged coords.
    """
    groups = {}
    for feat in features:
        code = feat["properties"].get("projectCode", "")
        if code not in groups:
            groups[code] = {"feat": feat, "coords": []}
        geom = feat.get("geometry") or {}
        if geom.get("type") == "Point" and geom.get("coordinates"):
            groups[code]["coords"].append(geom["coordinates"])
    merged = []
    for code, g in groups.items():
        feat = g["feat"]
        coords_list = g["coords"]
        if coords_list:
            avg_lon = sum(c[0] for c in coords_list) / len(coords_list)
            avg_lat = sum(c[1] for c in coords_list) / len(coords_list)
            feat = dict(feat)
            feat["geometry"] = {"type": "Point", "coordinates": [round(avg_lon, 6), round(avg_lat, 6)]}
        merged.append(feat)
    return merged


def build_project(feat, status):
    props = feat.get("properties", {})
    geom  = feat.get("geometry", {})

    code        = props.get("projectCode", "").strip()
    name_en     = props.get("projectTitle", "").strip()
    name_tc     = props.get("projectTitleCht", "").strip()
    location_en = props.get("location", "").strip()
    location_tc = props.get("locationCht", "").strip()
    btype_en    = props.get("buildingType", "").strip()
    btype_tc    = props.get("buildingTypeCht", "").strip()
    ptype_en    = props.get("projectType", "").strip()
    ptype_tc    = props.get("projectTypeCht", "").strip()
    cost        = props.get("estimatedProjectCost", "").strip()
    start_en    = props.get("scheduledProjectStart", "").strip()
    start_tc    = props.get("scheduledProjectStart", "").strip()
    end_en      = props.get("scheduledProjectCompletion", "").strip()
    end_tc      = props.get("scheduledProjectCompletion", "").strip()

    # Contractor — prefer dedicated field, fall back to combined text
    contractor_en = (props.get("currentContractorName") or
                     props.get("currentContracts") or "").strip()
    contractor_tc = (props.get("currentContractorNameCht") or
                     props.get("currentContractsCht") or "").strip()

    coords_raw  = geom.get("coordinates", []) if geom else []
    coordinates = [coords_raw] if coords_raw else []

    return {
        "code": code,
        "name_en": name_en,
        "name_tc": name_tc,
        "status": status,
        "location_en": location_en,
        "location_tc": location_tc,
        "btype_en": btype_en,
        "btype_tc": btype_tc,
        "ptype_en": ptype_en,
        "ptype_tc": ptype_tc,
        "cost": cost,
        "start_en": start_en,
        "start_tc": start_tc,
        "end_en": end_en,
        "end_tc": end_tc,
        "contractor_en": contractor_en,
        "contractor_tc": contractor_tc,
        "coordinates": coordinates,
        "obj_id": props.get("OBJECTID"),
    }


def main():
    print("Fetching ARCHSD Under Planning WFS...")
    planning_raw = fetch_geojson(WFS_PLANNING)
    planning_raw = merge_multipoint(planning_raw)
    print(f"  {len(planning_raw)} planning projects\n")

    print("Fetching ARCHSD Under Construction WFS...")
    construction_raw = fetch_geojson(WFS_CONSTRUCTION)
    construction_raw = merge_multipoint(construction_raw)
    print(f"  {len(construction_raw)} construction projects\n")

    all_raw = [(f, 1) for f in planning_raw] + [(f, 2) for f in construction_raw]
    total = len(all_raw)

    projects = []
    for i, (feat, status) in enumerate(all_raw, 1):
        d = build_project(feat, status)
        code = d["code"]
        print(f"  [{i:03d}/{total}] {code} | S{status} | {d['name_en'][:50]}...")

        photos = scrape_photos(code)
        time.sleep(0.3)

        en_url = DETAIL_URL_EN.format(code=code)
        tc_url = DETAIL_URL_TC.format(code=code)

        desc_en = f"{d['ptype_en']} – {d['btype_en']}" if d['btype_en'] else d['ptype_en']
        desc_tc = f"{d['ptype_tc']} – {d['btype_tc']}" if d['btype_tc'] else d['ptype_tc']

        projects.append({
            "id":         d["obj_id"],
            "dataset":    DATASET_ID,
            "department": DEPARTMENT,
            "item":       code,
            "name":       d["name_en"],
            "type":       None,
            "type_label": {"en": d["btype_en"], "tc": d["btype_tc"]},
            "status":     status,
            "status_label": STATUS_LABELS[status],
            "url":        {"en": en_url, "tc": tc_url},
            "coordinates": d["coordinates"],
            "geometry":   None,
            "page_title":         {"en": d["name_en"], "tc": d["name_tc"]},
            "description":        {"en": desc_en,      "tc": desc_tc},
            "scope":              {"en": d["location_en"], "tc": d["location_tc"]},
            "agreement_no":       code,
            "cost":               {"en": d["cost"], "tc": d["cost"]},
            "award_date":         {"en": "", "tc": ""},
            "commencement_date":  {"en": d["start_en"], "tc": d["start_tc"]},
            "commissioning_date": {"en": d["end_en"],   "tc": d["end_tc"]},
            "consultant":         {"en": "", "tc": ""},
            "contractor":         {"en": d["contractor_en"], "tc": d["contractor_tc"]},
            "photos":             photos,
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

    photos_count = sum(1 for p in projects if p["photos"])
    print(f"\nSaved {len(projects)} projects → {out_path}")
    print(f"Photos found: {photos_count}/{len(projects)}")


if __name__ == "__main__":
    main()
