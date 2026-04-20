#!/usr/bin/env python3
"""
Fetches HYD Retrofitting of Noise Barrier Projects from CSDI WFS +
HYD project detail pages (EN + TC). Geometry is Point.
Outputs data/hyd_noise.json used by the webapp.
"""

import datetime
import json
import re
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

DATASET_ID = "hyd_noise"
DATASET_NAME = {"en": "Noise Barrier Projects", "tc": "隔音屏障工程項目"}
DEPARTMENT = "HYD"
DEPARTMENT_FULL = {"en": "Highways Department", "tc": "路政署"}

WFS_URL = (
    "https://portal.csdi.gov.hk/server/services/common/"
    "hyd_rcd_1728896280736_45635/MapServer/WFSServer"
    "?service=wfs&request=GetFeature&typenames=Retrofitting_of_Noise_Barrier_Projects"
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
    3: {"en": "Completed",          "tc": "已完成"},
}

EN_FIELD_MAP = {
    "estimated project cost":                       "cost",
    "estimated cost":                               "cost",
    "project cost":                                 "cost",
    "anticipated construction commencement date":   "commencement_date",
    "actual construction commencement date":        "commencement_date",
    "construction commencement date":               "commencement_date",
    "commencement date":                            "commencement_date",
    "anticipated commissioning date":               "commissioning_date",
    "actual commissioning date":                    "commissioning_date",
    "anticipated completion date":                  "commissioning_date",
    "completion date":                              "commissioning_date",
    "commissioning date":                           "commissioning_date",
    "consultant":                                   "consultant",
    "consultant name":                              "consultant",
    "resident engineer":                            "consultant",
    "contractor":                                   "contractor",
    "contractor name":                              "contractor",
    "main contractor":                              "contractor",
}

TC_FIELD_MAP = {
    "估計工程費用":     "cost",
    "估計造價":         "cost",
    "工程費用":         "cost",
    "預計工程動工日期": "commencement_date",
    "實際工程動工日期": "commencement_date",
    "預計動工日期":     "commencement_date",
    "動工日期":         "commencement_date",
    "預計啟用日期":     "commissioning_date",
    "實際啟用日期":     "commissioning_date",
    "預計完工日期":     "commissioning_date",
    "完工日期":         "commissioning_date",
    "啟用日期":         "commissioning_date",
    "顧問公司":         "consultant",
    "顧問名稱":         "consultant",
    "顧問":             "consultant",
    "駐地盤工程師":     "consultant",
    "承建商":           "contractor",
    "總承建商":         "contractor",
}

SKIP_VALUES = {"", "-", "n/a", "under study", "tbc", "tbd", "待定", "研究中", "under review"}


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


def is_project_photo(src):
    if not src:
        return False
    if src.startswith(("/images/", "/en/images/", "/tc/images/")):
        return False
    if src.startswith("../") or src.startswith("/"):
        return False
    if not re.search(r"\.(jpg|jpeg|png|gif|webp)$", src, re.I):
        return False
    return True


def parse_h2p_fields(soup, field_map):
    info = {}
    for h2 in soup.find_all("h2"):
        label = h2.get_text(" ", strip=True).rstrip("：:").strip()
        mapped = field_map.get(label) or field_map.get(label.lower())
        if not mapped:
            continue
        p = h2.find_next_sibling("p")
        if not p:
            continue
        val = p.get_text(" ", strip=True)
        if val.lower() not in SKIP_VALUES and val:
            info[mapped] = val
    return info


def scrape_page(url, field_map):
    if not url:
        return {}
    soup = get_soup(url)
    if not soup:
        return {}
    info = {}

    h1 = soup.find("h1")
    if h1:
        info["page_title"] = h1.get_text(" ", strip=True)

    desc_h2 = soup.find(
        lambda t: t.name == "h2" and
        any(kw in t.get_text().lower() for kw in ("description", "描述", "簡介"))
    )
    if desc_h2:
        for sib in desc_h2.next_siblings:
            if getattr(sib, "name", None) == "p":
                txt = sib.get_text(" ", strip=True)
                if len(txt) > 15:
                    info["description"] = txt
                    break
            if getattr(sib, "name", None) == "h2":
                break

    info.update(parse_h2p_fields(soup, field_map))

    photos = []
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if is_project_photo(src):
            abs_src = urljoin(url, src)
            alt = img.get("alt", "")
            if abs_src not in [p["url"] for p in photos]:
                photos.append({"url": abs_src, "alt": alt})
        if len(photos) >= 4:
            break
    if photos:
        info["photos"] = photos

    return info


def code_from_url(url):
    m = re.search(r"/environment_protection/([^/]+)/", url)
    return m.group(1) if m else ""


def extract_point(geometry):
    if not geometry:
        return []
    coords = geometry.get("coordinates", [])
    return [coords] if coords else []


def main():
    print("Fetching HYD Noise Barrier Projects WFS...")
    features = fetch_geojson()
    print(f"Total: {len(features)} features\n")

    projects = []
    for i, feat in enumerate(features, 1):
        props = feat.get("properties", {})
        geom  = feat.get("geometry", {})

        obj_id  = props.get("OBJECTID")
        name_en = props.get("ProjectName", "").strip()
        status  = int(props.get("Status", 0))
        en_url  = props.get("URL", "").strip()
        t_url   = en_url.replace("/en/", "/tc/", 1) if "/en/" in en_url else ""
        code    = code_from_url(en_url)

        print(f"  [{i:02d}/{len(features)}] {code} S{status} | {name_en[:55]}...")

        en = scrape_page(en_url, EN_FIELD_MAP)
        time.sleep(0.25)
        tc = scrape_page(t_url, TC_FIELD_MAP) if t_url else {}
        time.sleep(0.25)

        def bilingual(field):
            return {"en": en.get(field, ""), "tc": tc.get(field, "")}

        photos  = en.get("photos") or tc.get("photos") or []
        name_tc = tc.get("page_title", "")

        projects.append({
            "id":         obj_id,
            "dataset":    DATASET_ID,
            "department": DEPARTMENT,
            "item":       code,
            "name":       name_en,
            "type":       None,
            "type_label": {"en": "Noise Barrier", "tc": "隔音屏障"},
            "status":     status,
            "status_label": STATUS_LABELS.get(status, {"en": str(status), "tc": str(status)}),
            "url":        {"en": en_url, "tc": t_url},
            "coordinates": extract_point(geom),
            "geometry":   None,
            "page_title":         {"en": en.get("page_title", name_en), "tc": name_tc},
            "description":        {"en": en.get("description", ""), "tc": tc.get("description", "")},
            "scope":              {"en": "", "tc": ""},
            "agreement_no":       code,
            "cost":               bilingual("cost"),
            "award_date":         {"en": "", "tc": ""},
            "commencement_date":  bilingual("commencement_date"),
            "commissioning_date": bilingual("commissioning_date"),
            "consultant":         bilingual("consultant"),
            "contractor":         bilingual("contractor"),
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
