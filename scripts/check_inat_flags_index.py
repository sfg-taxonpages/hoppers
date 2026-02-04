# scripts/check_inat_flags_index.py

import os
import json
import time
import random
import re
from typing import Dict, List, Set, Optional

import requests
from bs4 import BeautifulSoup

USER_AGENT = os.environ.get("USER_AGENT", "inat-flag-watcher/1.0 (contact: your-email@example.com)")
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY")  # "org/repo"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

ROOT_TAXON_IDS_RAW = os.environ.get("INAT_ROOT_TAXON_IDS", "")
ROOT_TAXON_IDS = [t.strip() for t in ROOT_TAXON_IDS_RAW.split(",") if t.strip()]

SEEN_FILE = os.environ.get("SEEN_FILE", "seen_flags.json")

# Mirror your UI filter defaults
RESOLVED = os.environ.get("INAT_RESOLVED", "no")          # "no" for unresolved
DELETED = os.environ.get("INAT_DELETED", "any")           # "any"
FLAG_TYPES_RAW = os.environ.get("INAT_FLAG_TYPES", "inappropriate,other")
FLAG_TYPES = [x.strip() for x in FLAG_TYPES_RAW.split(",") if x.strip()]

# Pagination / politeness
MAX_PAGES = int(os.environ.get("INAT_MAX_PAGES", "50"))     # safety cap
SLEEP_PAGES = float(os.environ.get("SLEEP_PAGES", "0.8"))
JITTER = float(os.environ.get("JITTER", "0.2"))

HTTP_RETRIES = int(os.environ.get("HTTP_RETRIES", "4"))
HTTP_BACKOFF_BASE = float(os.environ.get("HTTP_BACKOFF_BASE", "1.0"))

FLAGS_URL = "https://www.inaturalist.org/flags"

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

FLAG_ID_RE = re.compile(r"/flags/(\d+)\b")


def _sleep_with_jitter(base: float) -> None:
    time.sleep(max(0.0, base + random.uniform(0.0, JITTER)))


def http_get(url: str, *, params: Optional[dict] = None, timeout: int = 30) -> requests.Response:
    backoff = HTTP_BACKOFF_BASE
    last_exc = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            print("[DEBUG] GET OK:", r.url)  # important: confirm we really hit /flags?... with your params
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


def build_flags_params(root_taxon_id: str, page: int) -> dict:
    # Match your working browser URL pattern more closely
    params = {
        "utf8": "✓",
        "flaggable_type": "Taxon",
        "taxon_id": str(root_taxon_id),
        "deleted": DELETED,
        "resolved": RESOLVED,
        "page": page,
        "commit": "Filter",
    }
    if FLAG_TYPES:
        params["flags[]"] = FLAG_TYPES
    return params


def extract_flag_ids(html: str) -> List[str]:
    """
    Robust extraction: first try anchors, then regex fallback (covers JS-rendered / data attributes).
    """
    ids: Set[str] = set()

    # 1) anchor-based
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        m = FLAG_ID_RE.search(a["href"])
        if m:
            ids.add(m.group(1))

    # 2) regex anywhere in HTML (this is the key fix)
    for m in FLAG_ID_RE.finditer(html):
        ids.add(m.group(1))

    return sorted(ids, key=int)


def main() -> None:
    if not ROOT_TAXON_IDS:
        print("No INAT_ROOT_TAXON_IDS provided.")
        return
    if not (GITHUB_REPO and GITHUB_TOKEN):
        print("GITHUB_REPOSITORY and GITHUB_TOKEN are required.")
        return

    seen = load_seen()
    new_seen = set(seen)
    created = 0

    for root in ROOT_TAXON_IDS:
        print(f"[INFO] Root taxon {root}: fetching flags index…")
        pages_no_new = 0

        for page in range(1, MAX_PAGES + 1):
            params = build_flags_params(root, page)
            html = http_get(FLAGS_URL, params=params).text

            # keep your debug
            if page == 1:
                print("[DEBUG] fetched html length:", len(html))
                print("[DEBUG] first 200 chars:", html[:200].replace("\n", " "))

            flag_ids = extract_flag_ids(html)

            if not flag_ids:
                print(f"[INFO] No flags found on page {page}; stop.")
                break

            new_on_page = 0
            for fid in flag_ids:
                if fid in seen:
                    continue

                link = f"https://www.inaturalist.org/flags/{fid}"
                title = f"iNaturalist taxon flag (root {root}): Flag {fid}"
                body = (
                    f"- Root taxon: `{root}`\n"
                    f"- Flag ID: `{fid}`\n"
                    f"- Link: {link}\n"
                )

                try:
                    issue = create_github_issue(title, body)
                    print("[INFO] Created issue:", issue.get("html_url"))
                    new_seen.add(fid)  # mark seen only on success
                    created += 1
                    new_on_page += 1
                except Exception as e:
                    print(f"[ERROR] Failed to create issue for flag {fid}: {e}")

            if new_on_page == 0:
                pages_no_new += 1
            else:
                pages_no_new = 0

            if pages_no_new >= 2:
                print("[INFO] Two consecutive pages with no new flags; stop.")
                break

            _sleep_with_jitter(SLEEP_PAGES)

    save_seen(new_seen)
    print(f"[INFO] Done. new_issues={created}, seen_total={len(new_seen)}")


if __name__ == "__main__":
    main()
