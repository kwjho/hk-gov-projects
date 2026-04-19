#!/usr/bin/env python3
"""
Fetches CEDD Major Projects from CSDI WFS + CEDD project detail pages (EN + TC).
Matches WFS features to website entries by coordinate.
Outputs data/cedd.json used by the webapp.
"""

import datetime
import json
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

DATASET_ID = "cedd"
DATASET_NAME = {"en": "Major Projects", "tc": "主要工程項目"}
DEPARTMENT = "CEDD"
DEPARTMENT_FULL = {"en": "Civil Engineering and Development Department", "tc": "土木工程拓展署"}

BASE_URL = "https://www.cedd.gov.hk"
INDEX_EN = BASE_URL + "/eng/our-projects/major-projects/index.html"
INDEX_TC = BASE_URL + "/tc/our-projects/major-projects/index.html"

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
    "Under Planning":     1,
    "Under Construction": 2,
    "Completed":          3,
}

STATUS_LABELS = {
    1: {"en": "Under Planning",     "tc": "規劃中"},
    2: {"en": "Under Construction", "tc": "施工中"},
    3: {"en": "Completed",          "tc": "已完成"},
}

EN_FIELD_MAP = {
    "project number":                          "agreement_no",
    "brief description of project scope":      "scope",
    "project scope":                           "scope",
    "cost":                                    "cost",
    "project cost":                            "cost",
    "estimated project cost":                  "cost",
    "estimated cost":                          "cost",
    "completion date":                         "commissioning_date",
    "anticipated completion date":             "commissioning_date",
    "actual completion date":                  "commissioning_date",
    "commencement date":                       "commencement_date",
    "construction commencement date":          "commencement_date",
    "anticipated commencement date":           "commencement_date",
    "contractor":                              "contractor",
    "main contractor":                         "contractor",
    "consultant":                              "consultant",
    "resident engineer":                       "consultant",
}

TC_FIELD_MAP = {
    "項目編號":     "agreement_no",
    "工程範圍簡介": "scope",
    "工程範圍簡述": "scope",
    "工程範圍":     "scope",
    "工程費用":     "cost",
    "估計工程費用": "cost",
    "估計造價":     "cost",
    "完工日期":     "commissioning_date",
    "完成日期":     "commissioning_date",
    "預計完工日期": "commissioning_date",
    "實際完工日期": "commissioning_date",
    "動工日期":     "commencement_date",
    "預計動工日期": "commencement_date",
    "承建商":       "contractor",
    "顧問":         "consultant",
}

SKIP_VALUES = {"", "-", "n/a", "tbc", "tbd", "待定", "研究中"}


def get_soup(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        r.encoding = "utf-8"  # server omits charset; force correct decoding
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"    WARNING: {url}: {e}", file=sys.stderr)
        return None


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


def scrape_index(url):
    """Returns list of {page_id, title, url, lon, lat} from an index page."""
    soup = get_soup(url)
    if not soup:
        return []
    items = []
    for li in soup.select("li[data-longitude]"):
        a = li.find("a")
        if not a:
            continue
        href = a.get("href", "")
        m = re.search(r"index-id-(\d+)\.html", href)
        if not m:
            continue
        try:
            lon = float(li.get("data-longitude", "").strip())
            lat = float(li.get("data-latitude", "").strip())
        except ValueError:
            continue
        items.append({
            "page_id": int(m.group(1)),
            "title":   a.get_text(strip=True),
            "url":     BASE_URL + href,
            "lon":     lon,
            "lat":     lat,
        })
    return items


def coord_key(lon, lat, decimals=4):
    return (round(lon, decimals), round(lat, decimals))


def parse_h3_fields(soup, field_map):
    """Parse <h3>Label:</h3> followed by <p>, raw text node, or <ol>/<ul>."""
    info = {}
    if not soup:
        return info
    for h3 in soup.find_all("h3"):
        label = h3.get_text(" ", strip=True).rstrip(":：").strip().lower()
        mapped = field_map.get(label)
        if not mapped:
            continue
        val_parts = []
        for sib in h3.next_siblings:
            sib_name = getattr(sib, "name", None)
            if sib_name == "h3":
                break
            if sib_name == "p":
                val_parts.append(sib.get_text(" ", strip=True))
                break
            if sib_name in ("ol", "ul"):
                val_parts.append("; ".join(
                    li.get_text(" ", strip=True) for li in sib.find_all("li")
                ))
                break
            # plain text node
            if isinstance(sib, str) and sib.strip():
                val_parts.append(sib.strip())
                break
        val = " ".join(val_parts).strip()
        if val and val.lower() not in SKIP_VALUES:
            info[mapped] = val
    return info


def scrape_detail(url, field_map):
    if not url:
        return {}
    soup = get_soup(url)
    return parse_h3_fields(soup, field_map)


def main():
    print("Fetching WFS GeoJSON...")
    features = fetch_geojson()
    print(f"Total WFS features: {len(features)}\n")

    print("Scraping EN index page...")
    en_items = scrape_index(INDEX_EN)
    print(f"  Found {len(en_items)} EN projects")

    print("Scraping TC index page...")
    tc_items = scrape_index(INDEX_TC)
    print(f"  Found {len(tc_items)} TC projects\n")

    # Build coord-keyed lookup for EN; page_id lookup for TC
    en_by_coord  = {coord_key(it["lon"], it["lat"]): it for it in en_items}
    tc_by_page_id = {it["page_id"]: it for it in tc_items}

    matched = 0
    projects = []
    for i, feat in enumerate(features, 1):
        props = feat.get("properties", {})
        geom  = feat.get("geometry", {})

        obj_id   = props.get("OBJECTID")
        code     = props.get("ProjectCode", "").strip()
        name_en  = props.get("English_Title", "").strip()
        name_tc  = props.get("Traditional_Chinese_Title", "").strip()
        category = props.get("CategoryID", "").strip()
        status   = CATEGORY_MAP.get(category, 1)

        coords_raw  = geom.get("coordinates", []) if geom else []
        coordinates = [coords_raw] if coords_raw else []
        wfs_lon = coords_raw[0] if len(coords_raw) >= 2 else 0
        wfs_lat = coords_raw[1] if len(coords_raw) >= 2 else 0

        # Match to website by coordinate
        ck       = coord_key(wfs_lon, wfs_lat)
        en_item  = en_by_coord.get(ck)
        tc_item  = tc_by_page_id.get(en_item["page_id"]) if en_item else None
        en_url   = en_item["url"] if en_item else None
        tc_url   = tc_item["url"] if tc_item else None
        title_tc = tc_item["title"] if tc_item else name_tc

        if en_item:
            matched += 1

        print(f"  [{i:03d}/{len(features)}] {code} | {('✓' if en_item else '✗')} | {name_en[:45]}...")

        en_info = scrape_detail(en_url, EN_FIELD_MAP)
        time.sleep(0.3)
        tc_info = scrape_detail(tc_url, TC_FIELD_MAP)
        time.sleep(0.3)

        def bilingual(field):
            return {"en": en_info.get(field, ""), "tc": tc_info.get(field, "")}

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
            "url":        {"en": en_url or "", "tc": tc_url or ""},
            "coordinates": coordinates,
            "geometry":   None,
            "page_title":         {"en": name_en, "tc": title_tc},
            "description":        {"en": en_info.get("scope", ""), "tc": tc_info.get("scope", "")},
            "scope":              bilingual("scope"),
            "agreement_no":       code,
            "cost":               bilingual("cost"),
            "award_date":         {"en": "", "tc": ""},
            "commencement_date":  bilingual("commencement_date"),
            "commissioning_date": bilingual("commissioning_date"),
            "consultant":         bilingual("consultant"),
            "contractor":         bilingual("contractor"),
            "photos":             [],
        })

    print(f"\nMatched {matched}/{len(features)} WFS features to website pages")

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

    print(f"Saved {len(projects)} projects → {out_path}")


if __name__ == "__main__":
    main()
