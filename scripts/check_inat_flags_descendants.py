# scripts/check_inat_flags_descendants.py
"""
Monitor iNaturalist taxon flags for a taxon and ALL its descendants.

Designed for large clades (up to ~50k taxa):
- Expands descendants via /v1/taxa/{id}/children (BFS), paginated
- Caches descendant taxon IDs to disk and refreshes on a schedule (default: daily)
- Polls the public flags pages for each cached taxon ID (https://www.inaturalist.org/flags?taxon_id=...)
- Creates GitHub issues for new flags and saves seen flag IDs in seen_flags.json
- Robust seen-file handling, numeric flag ID filtering, retry/backoff, and "only mark seen on success"
"""

import os
import json
import time
import random
import datetime as dt
from typing import Dict, List, Set, Tuple, Optional

import requests
from bs4 import BeautifulSoup

# ----------------------------
# Configuration (via env vars)
# ----------------------------
USER_AGENT = os.environ.get(
    "USER_AGENT",
    "inat-flag-watcher/1.0 (contact: your-email@example.com)"
)

INAT_API = "https://api.inaturalist.org/v1/taxa"
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY")         # e.g. "org/repo"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")             # from secrets.GITHUB_TOKEN
ROOT_TAXON_IDS_RAW = os.environ.get("INAT_ROOT_TAXON_IDS", "")  # comma-separated
ROOT_TAXON_IDS = [tid.strip() for tid in ROOT_TAXON_IDS_RAW.split(",") if tid.strip()]

# Files written to repo root (so Actions can commit them)
SEEN_FILE = os.environ.get("SEEN_FILE", "seen_flags.json")
DESC_CACHE_FILE = os.environ.get("DESC_CACHE_FILE", "descendant_taxa_cache.json")

# Taxa pagination (iNat API supports large per_page; 200 is a safe choice)
PER_PAGE = int(os.environ.get("INAT_PER_PAGE", "200"))

# Politeness + runtime controls
SLEEP_CHILDREN = float(os.environ.get("SLEEP_CHILDREN", "0.2"))      # delay between children page fetches
SLEEP_FLAGS = float(os.environ.get("SLEEP_FLAGS", "0.3"))            # delay between flags page fetches
JITTER = float(os.environ.get("JITTER", "0.15"))                     # random jitter to avoid thundering herd
MAX_TAXA_PER_RUN = int(os.environ.get("MAX_TAXA_PER_RUN", "0"))       # 0 = no limit; set to cap work per run

# Cache refresh policy
CACHE_TTL_HOURS = int(os.environ.get("CACHE_TTL_HOURS", "24"))        # refresh descendants list every 24h

# HTTP retry policy
HTTP_RETRIES = int(os.environ.get("HTTP_RETRIES", "4"))
HTTP_BACKOFF_BASE = float(os.environ.get("HTTP_BACKOFF_BASE", "1.0"))

HEADERS = {"User-Agent": USER_AGENT}

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
            # Print response body when available (useful for GitHub 403/422)
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
            return set()
        except Exception:
            # tolerate empty/partial/corrupt file
            return set()
    return set()

def save_seen(seen_set: Set[str]) -> None:
    # atomic-ish write: write temp then replace
    tmp = SEEN_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(list(seen_set)), f, indent=2)
    os.replace(tmp, SEEN_FILE)

# ----------------------------
# Descendants caching
# ----------------------------
def _now_iso() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def load_desc_cache() -> Optional[Dict]:
    if not os.path.exists(DESC_CACHE_FILE):
        return None
    try:
        with open(DESC_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def save_desc_cache(root_id: str, taxon_ids: List[str]) -> None:
    cache = {
        "root_id": str(root_id),
        "updated_at": _now_iso(),
        "taxon_ids": taxon_ids,
    }
    tmp = DESC_CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp, DESC_CACHE_FILE)

def cache_is_fresh(cache: Dict) -> bool:
    try:
        updated_at = cache.get("updated_at")
        if not updated_at:
            return False
        # parse ISO like "2026-02-04T12:34:56Z"
        t = dt.datetime.strptime(updated_at, "%Y-%m-%dT%H:%M:%SZ")
        age = dt.datetime.utcnow() - t
        return age.total_seconds() <= CACHE_TTL_HOURS * 3600
    except Exception:
        return False

# ----------------------------
# iNaturalist: descendant expansion
# ----------------------------
def get_children(parent_id: str, page: int) -> List[dict]:
    url = f"{INAT_API}/{parent_id}/children"
    params = {"per_page": PER_PAGE, "page": page}
    r = http_get(url, params=params, headers=HEADERS, timeout=30)
    data = r.json()
    return data.get("results", []) or []

def get_descendant_taxa_bfs(root_taxon_id: str) -> Set[str]:
    """
    BFS over /taxa/{id}/children to collect root + all descendants.
    """
    root_taxon_id = str(root_taxon_id)
    ids: Set[str] = {root_taxon_id}
    queue: List[str] = [root_taxon_id]

    seen_parents = 0
    while queue:
        parent_id = queue.pop(0)
        seen_parents += 1
        page = 1
        while True:
            children = get_children(parent_id, page)
            if not children:
                break

            for t in children:
                tid = t.get("id")
                if tid is None:
                    continue
                tid = str(tid)
                if tid not in ids:
                    ids.add(tid)
                    queue.append(tid)

            if len(children) < PER_PAGE:
                break
            page += 1
            _sleep_with_jitter(SLEEP_CHILDREN)

        # light progress output
        if seen_parents % 250 == 0:
            print(f"[INFO] Descendants: visited parents={seen_parents}, collected taxa={len(ids)}")

        _sleep_with_jitter(SLEEP_CHILDREN)

    return ids

def get_descendants_cached_for_root(root_id: str) -> List[str]:
    """
    Loads descendants list from cache if fresh and matches root_id; otherwise recomputes and saves cache.
    Cache file is shared (single-root) by default; if you monitor multiple roots, it will be rebuilt per root.
    """
    cache = load_desc_cache()
    if cache and str(cache.get("root_id")) == str(root_id) and cache_is_fresh(cache):
        taxon_ids = cache.get("taxon_ids") or []
        print(f"[INFO] Using cached descendant list for root {root_id}: {len(taxon_ids)} taxa (fresh)")
        return [str(x) for x in taxon_ids]

    print(f"[INFO] Building descendant list for root {root_id} (cache miss/stale)...")
    ids = get_descendant_taxa_bfs(root_id)
    taxon_ids = sorted(ids, key=lambda x: int(x) if x.isdigit() else x)
    save_desc_cache(root_id, taxon_ids)
    print(f"[INFO] Cached descendant list for root {root_id}: {len(taxon_ids)} taxa")
    return taxon_ids

# ----------------------------
# Flags scraping
# ----------------------------
def fetch_flags_for_taxon(taxon_id: str) -> str:
    url = f"https://www.inaturalist.org/flags?taxon_id={taxon_id}"
    r = http_get(url, headers=HEADERS, timeout=30)
    return r.text

def parse_flags(html: str) -> List[Dict[str, str]]:
    """
    Extract flags as dicts {'id','title','link'}.
    Filters to numeric IDs only to reduce false positives.
    """
    soup = BeautifulSoup(html, "html.parser")
    results: List[Dict[str, str]] = []

    for a in soup.select("a[href*='/flags/']"):
        href = a.get("href") or ""
        if "/flags/" not in href:
            continue

        fid = href.split("/flags/")[-1].split("#")[0].split("?")[0].strip()
        if not fid.isdigit():
            continue

        text = a.get_text(strip=True) or f"Flag {fid}"
        link = "https://www.inaturalist.org" + href.split("#")[0]
        results.append({"id": fid, "title": text, "link": link})

    # dedupe by flag id
    dedup: Dict[str, Dict[str, str]] = {}
    for r in results:
        dedup[r["id"]] = r
    return list(dedup.values())

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

    # For large clades, cache descendants; rebuild at most once per TTL.
    # If multiple roots are provided, we rebuild cache per root (single cache file).
    all_taxon_ids: List[str] = []
    for root in ROOT_TAXON_IDS:
        try:
            descendants = get_descendants_cached_for_root(root)
        except Exception as e:
            print(f"[ERROR] Failed to fetch descendants for {root}: {e}")
            continue
        all_taxon_ids.extend(descendants)
        _sleep_with_jitter(1.0)

    # Deduplicate across roots (keep stable order)
    seen_taxa: Set[str] = set()
    unique_taxa: List[str] = []
    for tid in all_taxon_ids:
        if tid not in seen_taxa:
            seen_taxa.add(tid)
            unique_taxa.append(tid)

    total_taxa = len(unique_taxa)
    print(f"[INFO] Monitoring flags for {total_taxa} taxa total (across roots).")

    # Optional cap per run (useful for huge sets; run more frequently or shard by schedule)
    if MAX_TAXA_PER_RUN and total_taxa > MAX_TAXA_PER_RUN:
        unique_taxa = unique_taxa[:MAX_TAXA_PER_RUN]
        print(f"[INFO] MAX_TAXA_PER_RUN set; limiting this run to {len(unique_taxa)} taxa.")

    created_count = 0
    checked_count = 0

    for tid in unique_taxa:
        checked_count += 1
        try:
            html = fetch_flags_for_taxon(tid)
            flags = parse_flags(html)

            for flag in flags:
                fid = flag["id"]
                if fid in seen:
                    continue

                title = f"iNaturalist flag: taxon {tid} — {flag['title']}"
                body = (
                    f"**New iNaturalist flag** for taxon `{tid}`\n\n"
                    f"- Link: {flag['link']}\n"
                    f"- Title: {flag['title']}\n\n"
                    f"Please review the flag on iNaturalist: {flag['link']}"
                )

                # Only mark as seen if the issue was successfully created
                try:
                    issue = create_github_issue(title, body)
                    print("[INFO] Created issue:", issue.get("html_url"))
                    new_seen.add(fid)
                    created_count += 1
                except Exception as e:
                    print(f"[ERROR] Failed to create issue for flag {fid}: {e}")

            # progress
            if checked_count % 250 == 0:
                print(f"[INFO] Progress: checked taxa={checked_count}/{len(unique_taxa)}, new issues={created_count}")

        except Exception as e:
            print(f"[WARN] Failed to check flags for taxon {tid}: {e}")

        _sleep_with_jitter(SLEEP_FLAGS)

    save_seen(new_seen)
    print(f"[INFO] Done. checked={checked_count}, new_issues={created_count}, seen_flags_total={len(new_seen)}")

if __name__ == "__main__":
    main()
