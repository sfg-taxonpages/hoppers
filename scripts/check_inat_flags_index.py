import os, json, time, random, re
from typing import Dict, List, Set, Optional
import requests

USER_AGENT = os.environ.get("USER_AGENT", "inat-flag-watcher/1.0 (contact: your-email@example.com)")
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

ROOT_TAXON_IDS_RAW = os.environ.get("INAT_ROOT_TAXON_IDS", "")
ROOT_TAXON_IDS = [t.strip() for t in ROOT_TAXON_IDS_RAW.split(",") if t.strip()]

SEEN_FILE = os.environ.get("SEEN_FILE", "seen_flags.json")

RESOLVED = os.environ.get("INAT_RESOLVED", "no")
DELETED = os.environ.get("INAT_DELETED", "any")
FLAG_TYPES_RAW = os.environ.get("INAT_FLAG_TYPES", "inappropriate,other")
FLAG_TYPES = [x.strip() for x in FLAG_TYPES_RAW.split(",") if x.strip()]

MAX_PAGES = int(os.environ.get("INAT_MAX_PAGES", "50"))
SLEEP_PAGES = float(os.environ.get("SLEEP_PAGES", "0.8"))
JITTER = float(os.environ.get("JITTER", "0.2"))

HTTP_RETRIES = int(os.environ.get("HTTP_RETRIES", "4"))
HTTP_BACKOFF_BASE = float(os.environ.get("HTTP_BACKOFF_BASE", "1.0"))

FLAGS_URL = "https://www.inaturalist.org/flags"
FLAG_ID_RE = re.compile(r"/flags/(\d+)\b")

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.inaturalist.org/",
    "Connection": "keep-alive",
}

def _sleep(base: float) -> None:
    time.sleep(max(0.0, base + random.uniform(0.0, JITTER)))

def http_get(session: requests.Session, url: str, params: dict, timeout: int = 30) -> requests.Response:
    backoff = HTTP_BACKOFF_BASE
    last_exc = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            r = session.get(url, params=params, headers=HEADERS, timeout=timeout, allow_redirects=True)
            print("[DEBUG] status:", r.status_code)
            print("[DEBUG] final url:", r.url)
            if r.history:
                chain = " -> ".join([h.url for h in r.history] + [r.url])
                print("[DEBUG] redirect chain:", chain)
            r.raise_for_status()
            return r
        except Exception as e:
            last_exc = e
            print(f"[WARN] GET failed (attempt {attempt}/{HTTP_RETRIES}) {e}")
            _sleep(backoff)
            backoff *= 2
    raise RuntimeError(f"GET failed after retries: {last_exc}")

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
    r = requests.post(url, json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

def build_flags_params(root_taxon_id: str, page: int) -> dict:
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
    ids = {m.group(1) for m in FLAG_ID_RE.finditer(html)}
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

    session = requests.Session()
    session.headers.update(HEADERS)

    for root in ROOT_TAXON_IDS:
        print(f"[INFO] Root taxon {root}: fetching flags index…")
        pages_no_new = 0

        for page in range(1, MAX_PAGES + 1):
            params = build_flags_params(root, page)
            r = http_get(session, FLAGS_URL, params=params)
            html = r.text

            if page == 1:
                print("[DEBUG] fetched html length:", len(html))
                print("[DEBUG] first 300 chars:", html[:300].replace("\n", " "))
                with open("debug_flags_page1.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("[DEBUG] wrote debug_flags_page1.html")
                print("[DEBUG] contains '/flags/' ?", ("/flags/" in html))

            flag_ids = extract_flag_ids(html)
            if not flag_ids:
                print(f"[INFO] No flags on page {page}; stop.")
                break

            new_on_page = 0
            for fid in flag_ids:
                if fid in seen:
                    continue
                link = f"https://www.inaturalist.org/flags/{fid}"
                title = f"iNaturalist taxon flag (root {root}): Flag {fid}"
                body = f"- Root taxon: `{root}`\n- Flag ID: `{fid}`\n- Link: {link}\n"
                try:
                    issue = create_github_issue(title, body)
                    print("[INFO] Created issue:", issue.get("html_url"))
                    new_seen.add(fid)
                    created += 1
                    new_on_page += 1
                except Exception as e:
                    print(f"[ERROR] Failed to create issue for flag {fid}: {e}")

            pages_no_new = pages_no_new + 1 if new_on_page == 0 else 0
            if pages_no_new >= 2:
                print("[INFO] Two consecutive pages with no new flags; stop.")
                break

            _sleep(SLEEP_PAGES)

    save_seen(new_seen)
    print(f"[INFO] Done. new_issues={created}, seen_total={len(new_seen)}")

if __name__ == "__main__":
    main()
