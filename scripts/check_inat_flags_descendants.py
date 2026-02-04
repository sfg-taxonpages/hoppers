# scripts/check_inat_flags_descendants.py
"""
Monitor iNaturalist TAXON flags for a root taxon (including descendants) by querying
the flags index once (paginated), instead of pinging every descendant taxon.

Uses the same filters as the iNaturalist flags UI, e.g.
https://www.inaturalist.org/flags?...&flaggable_type=Taxon&taxon_id=125816&resolved=no

Strategy:
- For each root taxon id:
  - Fetch /flags (or /flags.json if it works) with flaggable_type=Taxon, taxon_id=<root>, resolved=no
  - Page through results
  - For each new flag ID, create a GitHub issue
  - Save seen flag IDs in seen_flags.json
"""

import os
import json
import time
import random
from typing import Dict, List, Set, Optional
import requests
from bs4 import BeautifulSoup

# ----------------------------
# Configuration (via env vars)
# ----------------------------
USER_AGENT = os.environ.get("USER_AGENT", "inat-flag-watcher/1.0 (contact: your-email@example.com)")
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY")   # "org/repo"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
ROOT_TAXON_IDS_RAW = os.environ.get("INAT_ROOT_TAXON_IDS", "")
ROOT_TAXON_IDS = [tid.strip() for tid in ROOT_TAXON_IDS_RAW.split(",") if tid.strip()]

SEEN_FILE = os.environ.get("SEEN_FILE", "seen_flags.json")

# Pagination / politeness
PER_PAGE = int(os.environ.get("INAT_PER_PAGE", "200"))       # for flags listing
SLEEP_FLAGS = float(os.environ.get("SLEEP_FLAGS", "0.5"))
JITTER = float(os.environ.get("JITTER", "0.15"))

# HTTP retry policy
HTTP_RETRIES = int(os.environ.get("HTTP_RETRIES", "4"))
HTTP_BACKOFF_BASE = float(os.environ.get("HTTP_BACKOFF_BASE", "1.0"))

HEADERS = {"User-Agent": USER_AGENT}

INAT_FLAGS_URL = "https://www.inaturalist.org/flags"
INAT_FLAGS_JSON_URL = "https://www.inaturalist.org/flags.json"

# If you want to include other flag “types” like your UI URL does, leave these.
# If you want ALL, you can omit flags[] entirely.
DEFAULT_FLAG_TYPES = ["inappropriate", "other"]


# ----------------------------
# Utility: retrying HTTP calls
# ----------------------------
def _sleep_with_jitter(base: float) -> None:
    time.sleep(max(0.0, base + random.uniform(0.0, JITTER)))

def http_get(url: str, *, params: Optional[dict] = None, headers: Optional[dict] = None, timeout: int = 30) -> requests.Response:
    h = headers or HEADERS
    backoff = HTTP_BACKOFF_BASE
    last_exc = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            r = requests.get(url, params=params, headers=h, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e:
            last_exc = e
            print(f"[WARN] GET failed (attempt {attempt}/{HTTP_RETRIES}) {url} :: {e}")
            _sleep_with_jitter(backoff)
            backoff *= 2
    raise RuntimeError(f"GET failed after retries: {url} :: {last_exc}")

def http_post(url: str, *, json_payload: dict, headers: dict, timeout: int = 30) -> requests.Response:
    backoff = HTTP_BACKOFF_BASE
    last_exc = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            r = requests.post(url, json=json_payload, headers=headers, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e:
            last_exc = e
            resp_text = ""
            try:
                if isinstance(e, requests.HTTPError) and e.response is not None:
                    resp_text = e.response.text[:500]
            except Exception:
                pass
            print(f"[WARN] POST failed (attempt {attempt}/{HTTP_RETRIES}) {url} :: {e} :: {resp_text}")
            _sleep_with_jitter(backoff)
            backoff *= 2
    raise RuntimeError(f"POST failed after retries: {url} :: {last_exc}")


# ----------------------------
# Seen flags persistence
# ----------------------------
def load_seen() -> Set[str]:
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return set(str(x) for x in data)
        except Exception:
            return set()
    return set()

def save_seen(seen_set: Set[str]) -> None:
    tmp = SEEN_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(list(seen_set)), f, indent=2)
    os.replace(tmp, SEEN_FILE)


# ----------------------------
# GitHub issue creation
# ----------------------------
def create_github_issue(title: str, body: str) -> Dict:
    url = f"https://api.github.com/repos/{GITHUB_REPO}/issues"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
    }
    payload = {"title": title, "body": body, "labels": ["iNaturalist flag"]}
    r = http_post(url, json_payload=payload, headers=headers, timeout=30)
    return r.json()


# ----------------------------
# Flags fetching (JSON first, HTML fallback)
# ----------------------------
def _base_flags_params(root_taxon_id: str, page: int) -> dict:
    # Mirrors your UI filter URL (minus the utf8/checkmark + blank fields)
    params = {
        "flaggable_type": "Taxon",
        "taxon_id": str(root_taxon_id),
        "resolved": "no",
        "page": page,
        "per_page": PER_PAGE,
    }
    # add flags[]=... like in your URL (optional)
    for ft in DEFAULT_FLAG_TYPES:
        params.setdefault("flags[]", [])
        params["flags[]"].append(ft)
    return params

def fetch_flags_page_json(root_taxon_id: str, page: int) -> Optional[dict]:
    """
    Try /flags.json. If it fails (non-200 or non-JSON), return None and we fall back to HTML.
    """
    params = _base_flags_params(root_taxon_id, page)
    try:
        r = http_get(INAT_FLAGS_JSON_URL, params=params, headers=HEADERS, timeout=30)
        return r.json()
    except Exception as e:
        print(f"[INFO] flags.json not usable (page {page}) for root {root_taxon_id}: {e}")
        return None

def fetch_flags_page_html(root_taxon_id: str, page: int) -> str:
    params = _base_flags_params(root_taxon_id, page)
    r = http_get(INAT_FLAGS_URL, params=params, headers=HEADERS, timeout=30)
    return r.text

def parse_flags_from_html(html: str) -> List[Dict[str, str]]:
    """
    Parse flags listing HTML; extract:
      - flag id (numeric)
      - flag link
      - best-effort title text
      - best-effort taxon id from any /taxa/<id> link in the same row/card (if present)
    """
    soup = BeautifulSoup(html, "html.parser")
    out: Dict[str, Dict[str, str]] = {}

    # Grab all /flags/<id> links
    for a in soup.select("a[href*='/flags/']"):
        href = a.get("href") or ""
        if "/flags/" not in href:
            continue
        fid = href.split("/flags/")[-1].split("#")[0].split("?")[0].strip()
        if not fid.isdigit():
            continue

        link = "https://www.inaturalist.org" + href.split("#")[0]
        title = a.get_text(strip=True) or f"Flag {fid}"

        # Try to find a nearby taxon link (rough, but helpful)
        taxon_id = ""
        container = a
        for _ in range(4):
            if container is None:
                break
            # search within current container for a /taxa/<id> link
            taxon_a = container.select_one("a[href*='/taxa/']")
            if taxon_a:
                thref = taxon_a.get("href") or ""
                # /taxa/125816-True-Hoppers
                if "/taxa/" in thref:
                    tid = thref.split("/taxa/")[-1].split("-")[0].split("?")[0].strip()
                    if tid.isdigit():
                        taxon_id = tid
                        break
            container = container.parent

        out[fid] = {
            "id": fid,
            "title": title,
            "link": link,
            "taxon_id": taxon_id,
        }

    return list(out.values())

def parse_flags_from_json(data: dict) -> List[Dict[str, str]]:
    """
    Best-effort parsing for /flags.json response.
    Structure can vary; we only require:
      - id
      - url/link
      - some label/title-ish field
      - taxon id if present
    """
    results = data.get("results")
    if not isinstance(results, list):
        # some endpoints use "flags" etc.
        results = data.get("flags")
    if not isinstance(results, list):
        return []

    out: List[Dict[str, str]] = []
    for f in results:
        try:
            fid = str(f.get("id", "")).strip()
            if not fid.isdigit():
                continue
            # try to build a link
            link = f.get("url") or f"https://www.inaturalist.org/flags/{fid}"
            title = f.get("flag") or f.get("reason") or f.get("message") or f"Flag {fid}"

            taxon_id = ""
            # iNat may include flaggable info
            flaggable = f.get("flaggable") or {}
            if isinstance(flaggable, dict):
                tid = flaggable.get("id")
                if tid is not None and str(tid).isdigit():
                    taxon_id = str(tid)

            out.append({"id": fid, "title": str(title), "link": str(link), "taxon_id": taxon_id})
        except Exception:
            continue
    return out


def iter_all_flags_for_root(root_taxon_id: str) -> List[Dict[str, str]]:
    """
    Page through all unresolved taxon flags for this root taxon (descendants included as per UI filter),
    returning a flat list of flag dicts.
    """
    all_flags: Dict[str, Dict[str, str]] = {}
    page = 1
    json_mode = None  # unknown until first attempt

    while True:
        if json_mode is None:
            data = fetch_flags_page_json(root_taxon_id, page)
            if data is not None:
                json_mode = True
                flags = parse_flags_from_json(data)
            else:
                json_mode = False
                html = fetch_flags_page_html(root_taxon_id, page)
                flags = parse_flags_from_html(html)
        elif json_mode:
            data = fetch_flags_page_json(root_taxon_id, page)
            if data is None:
                # fallback mid-run if needed
                json_mode = False
                html = fetch_flags_page_html(root_taxon_id, page)
                flags = parse_flags_from_html(html)
            else:
                flags = parse_flags_from_json(data)
        else:
            html = fetch_flags_page_html(root_taxon_id, page)
            flags = parse_flags_from_html(html)

        if not flags:
            break

        for f in flags:
            all_flags[f["id"]] = f

        # If fewer than PER_PAGE flags returned, assume last page.
        # (Works for both JSON and HTML-based parsing)
        if len(flags) < PER_PAGE:
            break

        page += 1
        _sleep_with_jitter(SLEEP_FLAGS)

    return list(all_flags.values())


# ----------------------------
# Main
# ----------------------------
def main() -> None:
    if not ROOT_TAXON_IDS:
        print("No INAT_ROOT_TAXON_IDS provided. Set env var to comma-separated root taxon IDs.")
        return
    if not (GITHUB_REPO and GITHUB_TOKEN):
        print("GITHUB_REPOSITORY and GITHUB_TOKEN environment variables are required.")
        return

    seen = load_seen()
    new_seen = set(seen)
    created_count = 0

    for root in ROOT_TAXON_IDS:
        print(f"[INFO] Fetching unresolved taxon flags for root taxon {root} (via flags index)…")
        try:
            flags = iter_all_flags_for_root(root)
        except Exception as e:
            print(f"[ERROR] Failed to fetch flags for root {root}: {e}")
            continue

        print(f"[INFO] Root {root}: retrieved {len(flags)} flags (unresolved, filtered).")

        for flag in flags:
            fid = flag["id"]
            if fid in seen:
                continue

            tid = flag.get("taxon_id") or "unknown"
            title = f"iNaturalist flag: taxon {tid} — {flag.get('title', f'Flag {fid}')}"
            body = (
                f"**New iNaturalist taxon flag**\n\n"
                f"- Root taxon filter: `{root}`\n"
                f"- Flag ID: `{fid}`\n"
                f"- Taxon ID (best effort): `{tid}`\n"
                f"- Link: {flag.get('link','')}\n"
                f"- Title: {flag.get('title','')}\n\n"
                f"Please review the flag on iNaturalist: {flag.get('link','')}"
            )

            # Only mark as seen if issue creation succeeded
            try:
                issue = create_github_issue(title, body)
                print("[INFO] Created issue:", issue.get("html_url"))
                new_seen.add(fid)
                created_count += 1
            except Exception as e:
                print(f"[ERROR] Failed to create issue for flag {fid}: {e}")

        _sleep_with_jitter(1.0)

    save_seen(new_seen)
    print(f"[INFO] Done. new_issues={created_count}, seen_flags_total={len(new_seen)}")


if __name__ == "__main__":
    main()
