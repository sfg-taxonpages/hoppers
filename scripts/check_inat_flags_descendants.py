# scripts/check_inat_flags_descendants.py
"""
Monitor iNaturalist taxon flags for a taxon and ALL its descendants.
- Uses the iNaturalist v1 /taxa endpoint to fetch descendants (taxon_id param).
- Polls the public flags pages for each descendant (https://www.inaturalist.org/flags?taxon_id=...)
- Creates GitHub issues for new flags and saves seen flag IDs in seen_flags.json
"""

import os
import json
import time
import requests
from bs4 import BeautifulSoup

USER_AGENT = os.environ.get("USER_AGENT", "inat-flag-watcher/1.0 (contact: your-email@example.com)")
INAT_API = "https://api.inaturalist.org/v1/taxa"
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
ROOT_TAXON_IDS = os.environ.get("INAT_ROOT_TAXON_IDS", "")  # comma separated e.g. "123,456"
SEEN_FILE = "seen_flags.json"
PER_PAGE = 200  # taxa per page for /taxa (max safe page size)

HEADERS = {"User-Agent": USER_AGENT}

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_seen(seen_set):
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(list(seen_set)), f, indent=2)

def get_descendant_taxa(root_taxon_id):
    """Return a set of taxon IDs for the root and all descendants by paging /taxa?taxon_id=<root>."""
    ids = set()
    page = 1
    while True:
        params = {"taxon_id": root_taxon_id, "per_page": PER_PAGE, "page": page, "order_by": "id"}
        r = requests.get(INAT_API, params=params, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        results = data.get("results", []) or data.get("taxa") or data.get("results", [])
        # results is a list of taxon dicts
        if not results:
            break
        for t in results:
            tid = t.get("id")
            if tid:
                ids.add(str(tid))
        # pagination info
        total_results = data.get("total_results") or data.get("total")
        page += 1
        # stop if fewer than page size returned
        if len(results) < PER_PAGE:
            break
    return ids

def fetch_flags_for_taxon(taxon_id):
    """Fetch the public flags listing page HTML for a taxon (web UI), return HTML text."""
    url = f"https://www.inaturalist.org/flags?taxon_id={taxon_id}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text

def parse_flags(html):
    """Parse HTML and extract flags as dicts {'id','title','link'}. Deduplicate by id."""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for a in soup.select("a[href*='/flags/']"):
        href = a.get("href")
        text = a.get_text(strip=True)
        if href and "/flags/" in href:
            fid = href.split("/flags/")[-1].split("#")[0].split("?")[0]
            link = "https://www.inaturalist.org" + href.split("#")[0]
            results.append({"id": fid, "title": text or f"Flag {fid}", "link": link})
    # dedupe in case page has duplicates
    seen = {}
    for r in results:
        seen[r["id"]] = r
    return list(seen.values())

def create_github_issue(title, body):
    """Create an issue in the same repo using GITHUB_TOKEN."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/issues"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT
    }
    payload = {"title": title, "body": body, "labels": ["iNaturalist flag"]}
    r = requests.post(url, json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

def main():
    if not ROOT_TAXON_IDS:
        print("No INAT_ROOT_TAXON_IDS provided. Set env var to comma-separated root taxon IDs.")
        return
    if not (GITHUB_REPO and GITHUB_TOKEN):
        print("GITHUB_REPOSITORY and GITHUB_TOKEN environment variables are required.")
        return

    root_ids = [tid.strip() for tid in ROOT_TAXON_IDS.split(",") if tid.strip()]
    seen = load_seen()
    new_seen = set(seen)

    # Expand each root taxon into all descendants (and itself)
    all_taxon_ids = set()
    for root in root_ids:
        try:
            descendants = get_descendant_taxa(root)
        except Exception as e:
            print(f"Failed to fetch descendants for {root}: {e}")
            continue
        print(f"Root {root} → {len(descendants)} descendant taxa")
        all_taxon_ids.update(descendants)
        # be polite
        time.sleep(1)

    # For each descendant taxon, check flags page and create issues for new flags
    for tid in sorted(all_taxon_ids):
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
                    "Please review the flag on iNaturalist: " + flag['link']
                )
                try:
                    issue = create_github_issue(title, body)
                    print("Created issue:", issue.get("html_url"))
                except Exception as e:
                    print(f"Failed to create issue for flag {fid}: {e}")
                new_seen.add(fid)
            # polite pause to avoid hammering site
            time.sleep(0.5)
        except Exception as e:
            print(f"Failed to check flags for taxon {tid}: {e}")

    save_seen(new_seen)
    print("Done. seen flags total:", len(new_seen))

if __name__ == "__main__":
    main()
