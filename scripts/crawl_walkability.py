#!/usr/bin/env python3
"""
Crawls HYD Walkability Projects from CSDI WFS + HYD project pages (EN + TC).
Outputs data/walkability.json used by the webapp.

To add a new dataset later, copy this file and update WFS_URL, TYPE_LABELS,
DATASET_ID, and the field maps.
"""

import datetime
import json
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ─── Config ───────────────────────────────────────────────────────────────────

DATASET_ID = "walkability"
DATASET_NAME = {
    "en": "Walkability Projects",
    "tc": "暢行易行項目",
}
DEPARTMENT = "HYD"
DEPARTMENT_FULL = {
    "en": "Highways Department",
    "tc": "路政署",
}

WFS_URL = (
    "https://portal.csdi.gov.hk/server/services/common/"
    "hyd_rcd_1728896144629_85412/MapServer/WFSServer"
    "?service=wfs&request=GetFeature&typenames=Walkability_Projects"
    "&outputFormat=geojson"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; HKGovProjectsBot/1.0; "
        "+https://github.com/your-org/hk-gov-projects)"
    )
}

STATUS_LABELS = {
    1: {"en": "Planning",           "tc": "規劃中"},
    2: {"en": "Under Construction", "tc": "施工中"},
    3: {"en": "Completed",          "tc": "已完成"},
}

TYPE_LABELS = {
    "UA":  {"en": "Universal Accessibility",   "tc": "暢道通行設施"},
    "HEL": {"en": "Hillside Escalator / Lift", "tc": "坡道電梯╱升降機"},
    "WC":  {"en": "Walkway Cover",             "tc": "有蓋行人通道"},
    "DF":  {"en": "District Facilities",       "tc": "地區設施"},
}

# EN h2 label → output field
EN_FIELD_MAP = {
    "agreement no":                           "agreement_no",
    "agreement no.":                          "agreement_no",
    "contract no":                            "contract_no",
    "contract no.":                           "contract_no",
    "consultancy fee":                        "cost",
    "contract sum":                           "cost",
    "estimated project cost":                 "cost",
    "estimated cost":                         "cost",
    "award date":                             "award_date",
    "commencement date":                      "commencement_date",
    "construction commencement date":         "commencement_date",
    "anticipated construction commencement date": "commencement_date",
    "actual construction commencement date":  "commencement_date",
    "commissioning date":                     "commissioning_date",
    "anticipated commissioning date":         "commissioning_date",
    "actual commissioning date":              "commissioning_date",
    "anticipated completion date":            "commissioning_date",
    "completion date":                        "commissioning_date",
    "consultant name":                        "consultant",
    "consultant":                             "consultant",
    "resident engineer":                      "consultant",
    "contractor":                             "contractor",
    "contractor name":                        "contractor",
    "scope":                                  "scope",
}

# TC h2 label → output field
TC_FIELD_MAP = {
    "顧問合約編號":   "agreement_no",
    "合約編號":       "contract_no",
    "工程合約編號":   "contract_no",
    "估計工程費用":   "cost",
    "合約總價":       "cost",
    "估計造價":       "cost",
    "工程費用":       "cost",
    "批出日期":       "award_date",
    "動工日期":       "commencement_date",
    "實際動工日期":   "commencement_date",
    "預計動工日期":   "commencement_date",
    "施工開始日期":   "commencement_date",
    "完工日期":       "commissioning_date",
    "預計完工日期":   "commissioning_date",
    "實際完工日期":   "commissioning_date",
    "啟用日期":       "commissioning_date",
    "顧問名稱":       "consultant",
    "顧問":           "consultant",
    "駐地盤工程師":   "consultant",
    "總承建商":       "contractor",
    "承建商":         "contractor",
    "工程範圍":       "scope",
}

SKIP_VALUES = {"", "-", "n/a", "under review", "to be determined", "tbc", "tbd",
               "待定", "審議中", "研究中"}

# ─── Helpers ──────────────────────────────────────────────────────────────────

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
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"    WARNING: {url}: {e}", file=sys.stderr)
        return None


def tc_url(en_url):
    """Convert an EN HYD URL to its TC equivalent."""
    return en_url.replace("/en/", "/tc/", 1) if "/en/" in en_url else None


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
    """Parse <h2>Label</h2><p>Value</p> pairs using the given field map."""
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


def parse_individual_page(soup, page_url, field_map, is_tc=False):
    info = {}
    if not soup:
        return info

    h1 = soup.find("h1")
    if h1:
        info["page_title"] = h1.get_text(" ", strip=True)

    # Description: <p> after "Project Description" / 項目描述 h2
    desc_keywords = ("description", "描述", "簡介")
    desc_h2 = soup.find(
        lambda t: t.name == "h2" and
        any(kw in t.get_text().lower() for kw in desc_keywords)
    )
    if desc_h2:
        for sib in desc_h2.next_siblings:
            if sib.name == "p":
                txt = sib.get_text(" ", strip=True)
                if len(txt) > 15:
                    info["description"] = txt
                    break
            if sib.name == "h2":
                break

    if "description" not in info:
        for p in soup.find_all("p"):
            txt = p.get_text(" ", strip=True)
            if len(txt) > 50:
                info["description"] = txt
                break

    info.update(parse_h2p_fields(soup, field_map))

    photos = []
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if is_project_photo(src):
            abs_src = urljoin(page_url, src)
            alt = img.get("alt", "")
            if abs_src not in [p["url"] for p in photos]:
                photos.append({"url": abs_src, "alt": alt})
        if len(photos) >= 4:
            break
    if photos:
        info["photos"] = photos

    return info


def parse_aggregate_page(soup, page_url, anchor, field_map):
    info = {}
    if not soup or not anchor:
        return info

    target_img = None
    for img in soup.find_all("img"):
        if anchor.lower() in img.get("src", "").lower():
            target_img = img
            break
    if not target_img:
        el = soup.find(id=anchor)
        if el:
            target_img = el.find("img")
    if not target_img:
        return info

    abs_src = urljoin(page_url, target_img.get("src", ""))
    container = target_img
    for _ in range(8):
        parent = container.parent
        if parent and parent.name in ("li", "tr", "div", "article"):
            container = parent
            break
        container = parent if parent else container

    texts = [t.strip() for t in container.stripped_strings if t.strip()]
    for t in texts:
        if len(t) > 8:
            info["page_title"] = t
            break

    for t in texts:
        m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4}", t, re.I)
        if m:
            info["commissioning_date"] = m.group(0)
            break
        # TC date pattern: 2020年6月
        m = re.search(r"\d{4}年\d{1,2}月", t)
        if m:
            info["commissioning_date"] = m.group(0)
            break
        m = re.search(r"\d{4}(\s+Q[1-4])?", t)
        if m and len(t) < 30:
            info["commissioning_date"] = t
            break

    if abs_src:
        info["photos"] = [{"url": abs_src, "alt": info.get("page_title", "")}]
    return info


def scrape_page(url, field_map):
    if not url:
        return {}
    parsed = urlparse(url)
    anchor = parsed.fragment
    clean_url = url.split("#")[0]
    soup = get_soup(clean_url)
    if not soup:
        return {}
    if anchor and re.search(r"projects_(completed|under_construction)", clean_url):
        return parse_aggregate_page(soup, clean_url, anchor, field_map)
    return parse_individual_page(soup, clean_url, field_map)


def extract_coordinates(geometry):
    if not geometry:
        return []
    gtype = geometry.get("type", "")
    coords = geometry.get("coordinates", [])
    if gtype == "Point":
        return [coords] if coords else []
    if gtype == "MultiPoint":
        return coords
    return []


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("Fetching WFS GeoJSON...")
    features = fetch_geojson()
    print(f"Total: {len(features)} features\n")

    projects = []
    for i, feat in enumerate(features, 1):
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})

        obj_id = props.get("OBJECTID")
        name = props.get("ProjectName", "")
        ptype = props.get("ProjectType", "")
        status = int(props.get("Status", 0))
        en_url = props.get("URL", "")
        t_url = tc_url(en_url) if en_url else None

        print(f"  [{i:02d}/{len(features)}] {ptype} S{status} | {name[:50]}...")

        en = scrape_page(en_url, EN_FIELD_MAP)
        time.sleep(0.25)
        tc = scrape_page(t_url, TC_FIELD_MAP) if t_url else {}
        time.sleep(0.25)

        def bilingual(field):
            """Return {en, tc} dict for a field, falling back gracefully."""
            return {
                "en": en.get(field, ""),
                "tc": tc.get(field, ""),
            }

        photos = en.get("photos") or tc.get("photos") or []

        projects.append({
            "id": obj_id,
            "dataset": DATASET_ID,
            "department": DEPARTMENT,
            "name": name,
            "type": ptype,
            "type_label": TYPE_LABELS.get(ptype, {"en": ptype, "tc": ptype}),
            "status": status,
            "status_label": STATUS_LABELS.get(status, {"en": str(status), "tc": str(status)}),
            "url": {"en": en_url, "tc": t_url or ""},
            "coordinates": extract_coordinates(geom),
            # bilingual content
            "page_title":        bilingual("page_title"),
            "description":       bilingual("description"),
            "scope":             bilingual("scope"),
            "agreement_no":      en.get("agreement_no") or en.get("contract_no") or
                                 tc.get("agreement_no") or tc.get("contract_no") or "",
            "cost":              bilingual("cost"),
            "award_date":        bilingual("award_date"),
            "commencement_date": bilingual("commencement_date"),
            "commissioning_date":bilingual("commissioning_date"),
            "consultant":        bilingual("consultant"),
            "contractor":        bilingual("contractor"),
            "photos": photos,
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
