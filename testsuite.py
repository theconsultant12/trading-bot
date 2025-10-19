import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
from typing import Optional, List, Tuple
import os
import xml.etree.ElementTree as ET
from lxml import etree

HEADERS = {"User-Agent": "Olusola Fowosire <oaf992@gmail.com>"}
ATOM_FEED_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=13F-HR&owner=include&count=100&output=atom"
SEC_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data"

def extract_cik_from_url(url: str) -> Optional[str]:
    match = re.search(r"/data/(\d{5,})/", url)
    return match.group(1) if match else None

def get_recent_ciks() -> List[str]:
    response = requests.get(ATOM_FEED_URL, headers=HEADERS)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "xml")

    ciks = set()
    for entry in soup.find_all("entry"):
        link = entry.find("link")
        if link and link.get("href"):
            cik = extract_cik_from_url(link["href"])
            if cik:
                ciks.add(cik)
    return sorted(ciks)

def get_recent_filing_folders(cik: str, days: int = 5) -> List[Tuple[str, datetime]]:
    """
    For a given CIK, return all subfolder URLs with last-modified date within `days`.
    """
    url = f"{SEC_ARCHIVE_BASE}/{cik}/"
    print(f"\n🔍 Fetching subfolders for CIK {cik}: {url}")

    recent_folders = []
    cutoff = datetime.utcnow() - timedelta(days=days)

    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        for row in soup.find_all("tr")[1:]:  # Skip header row
            cols = row.find_all("td")
            if len(cols) < 3:
                continue
            anchor = cols[0].find("a")
            date_str = cols[2].text.strip()

            if anchor and anchor.text.strip().isdigit():
                folder = anchor.text.strip()
                try:
                    modified = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                    if modified >= cutoff:
                        full_url = f"{url}{folder}/"
                        recent_folders.append((full_url, modified))
                except ValueError:
                    continue

    except Exception as e:
        print(f"⚠️ Failed for CIK {cik}: {e}")
    
    return recent_folders

def find_inf_table_url(folder_url: str) -> Optional[str]:
    """
    Checks if infotable.xml exists in a filing folder.
    Returns the full URL if found.
    """
    try:
        response = requests.get(folder_url, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        for link in soup.find_all("a"):
            href = link.get("href", "").lower()
            if "infotable.xml" in href:
                print(f"✅ Found infotable.xml: {folder_url}")
                return folder_url

    except Exception as e:
        print(f"⚠️ Error checking folder {folder_url}: {e}")

    return None

def download_inf_table(url: str, save_dir="infotables"):
    """
    Downloads infotable.xml to local disk.
    """
    os.makedirs(save_dir, exist_ok=True)
    filename = url.split("/")[-2] + "_infotable.xml"  # use accession as prefix
    filepath = os.path.join(save_dir, filename)

    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()

        with open(filepath, "wb") as f:
            f.write(response.content)
        print(f"✅ Downloaded: {filepath}")

    except Exception as e:
        print(f"❌ Failed to download {url}: {e}")

def populate_infotables(days: int = 5):
    all_recent_urls = []
    ciks = get_recent_ciks()
    print(f"\n✅ Found {len(ciks)} recent CIKs.\n")

    for cik in ciks:
        recent_folders = get_recent_filing_folders(cik, days=days)
        all_recent_urls.extend(recent_folders)

    # Sort across all CIKs (newest to oldest)
    all_recent_urls.sort(key=lambda x: x[1], reverse=True)

    print(f"\n📦 Total recent filing folders (last 5 days): {len(all_recent_urls)}\n")

    for folder_url, modified in all_recent_urls:
        print(f"{modified} — {folder_url}")
        inf_url = find_inf_table_url(folder_url)
        if inf_url:
            download_inf_table(inf_url)
# --- Main Execution ---


def parse_inf_table_with_lxml(filepath: str) -> list[dict]:
    """
    Uses lxml to parse an infotable.xml file and extract holding data.
    """
    print(f"📄 Parsing (lxml): {filepath}")
    holdings = []

    try:
        parser = etree.XMLParser(recover=True)  # tolerate broken XML
        tree = etree.parse(filepath, parser)
        root = tree.getroot()

        for i, info in enumerate(root.xpath("//infoTable")):
            try:
                name = info.findtext("nameOfIssuer")
                cusip = info.findtext("cusip")
                value = int(info.findtext("value"))
                shares = int(info.findtext("sshPrnamt"))

                holdings.append({
                    "stock": name,
                    "cusip": cusip,
                    "value_$1000s": value,
                    "shares": shares,
                    "source": os.path.basename(filepath)
                })
            except Exception as e:
                print(f"⚠️ Skipped row {i+1}: {e}")
    except Exception as e:
        print(f"❌ Could not parse {filepath}: {e}")

    return holdings

def parse_all_infotables(folder: str = "infotables") -> list[dict]:
    """
    Parses all XML files in a directory and aggregates holdings.
    """
    all_holdings = []
    files = [f for f in os.listdir(folder) if f.endswith(".xml")]

    print(f"\n📂 Found {len(files)} infotable.xml files in '{folder}'\n")

    for file in files:
        path = os.path.join(folder, file)
        holdings = parse_inf_table_with_lxml(path)
        all_holdings.extend(holdings)

    print(f"\n✅ Total holdings parsed: {len(all_holdings)}")
    return all_holdings

# --- Run Parser ---

if __name__ == "__main__":
    populate_infotables(5)
    results = parse_all_infotables()

    for r in results:
        print(f"{r['stock']:<30} | Shares: {r['shares']:,} | Value: ${r['value_$1000s'] * 1000:,} | File: {r['source']}")

