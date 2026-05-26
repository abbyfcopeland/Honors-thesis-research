import requests, time
import csv
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta
from calendar import monthrange

# === Constants ===
ALGOLIA_APP_ID = "XGC391W2WE"
ALGOLIA_API_KEY = "52dcafdcc61d4c5885aeccd7d2e4d788"
ALGOLIA_URL = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/*/queries"

HEADERS = {
    "Content-Type": "application/json",
    "X-Algolia-API-Key": ALGOLIA_API_KEY,
    "X-Algolia-Application-Id": ALGOLIA_APP_ID
}

CUTOFF_YEAR = 2016
CUTOFF_TIMESTAMP = 1475280000



START_DATE = datetime(2016, 10, 1)
END_DATE = datetime.now()
MONTHS = []
current = START_DATE
while current <= END_DATE:
    MONTHS.append((current.year, current.month))
    current += relativedelta(months=1)


KEYWORDS = [
    'race bias', 'racial bias', 'race prejudice', 'racial prejudice', 'race discrimination',
    'racial discrimination', 'race disparity', 'racial disparity', 'race inequality', 'racial inequality',
    'race difference', 'racial difference', 'racism'
]

OUTPUT_DIR = Path("brookings_scrape")
TEXT_DIR = OUTPUT_DIR / "texts"
CSV_FILE = OUTPUT_DIR / "brookings_articles.csv"
TEXT_DIR.mkdir(parents=True, exist_ok=True)


# Article registry to avoid duplicates and track keyword hits
article_registry = {}

def extract_full_article(url, max_retries: int = 1, timeout: int = 10) -> str:
    attempt = 0
    while attempt <= max_retries:
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()  # network / 4xx / 5xx errors
            soup = BeautifulSoup(resp.content, "html.parser")

            # --- grab paragraphs from typical Brookings blocks ---
            blocks = soup.select("div.byo-block.wysiwyg-block, div.core-block")
            paragraphs = [
                p.get_text(" ", strip=True)
                for block in blocks
                for p in block.find_all("p")
                if p.get_text(strip=True)
            ]

            return "\n\n".join(paragraphs)  # success → return text

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            print(f"⏳ Timeout/connection error on {url} (try {attempt + 1})")
        except requests.exceptions.RequestException as e:
            print(f"❌ HTTP error on {url} (try {attempt + 1}): {e}")
        except Exception as e:
            print(f"⚠️  Parsing failure on {url} (try {attempt + 1}): {e}")


        attempt += 1 # If we reach here, that attempt failed
        if attempt <= max_retries:
            time.sleep(2)  # brief pause before retry

    # All attempts failed
    print(f"🚫 Giving up on {url}")
    return ""
def query_articles(keyword, year, month):
    # --- numeric filter bounds for one calendar month ---
    start_dt = datetime(year, month, 1)
    end_day  = monthrange(year, month)[1]
    end_dt   = datetime(year, month, end_day, 23, 59, 59)
    start_ts = int(start_dt.timestamp())
    end_ts   = int(end_dt.timestamp())

    page = 0
    fetched_this_query = 0           # fresh counter
    CAP_HARD = 1000                  # Algolia’s max

    while True:
        body = {
            "requests": [{
                "indexName": "prod_searchable_posts",
                "params": (
                    f"query={keyword}"
                    "&hitsPerPage=100"
                    f"&page={page}"
                    f"&numericFilters=post_date>={start_ts},post_date<={end_ts}"
                )
            }]
        }

        resp = requests.post(ALGOLIA_URL, headers=HEADERS, json=body, timeout=20)
        resp.raise_for_status()
        data = resp.json()["results"][0]


        if page == 0:
            nb_hits  = data.get("nbHits", 0)
            nb_pages = data.get("nbPages", 0)
            cap_note = "⚠️ (HIT CAP!)" if nb_hits >= CAP_HARD else ""
            print(f"   ↳ nbHits={nb_hits} nbPages={nb_pages} {cap_note}")

        hits = data["hits"]
        if not hits:
            break

        fetched_this_query += len(hits)

        # ----------  iterate each hit ----------
        for hit in hits:
            post_date   = hit.get("post_date", 0)
            dt          = datetime.fromtimestamp(post_date)
            content_type= hit.get("content_type", [])
            post_id     = hit.get("objectID")

            # guard rails
            if post_date < CUTOFF_TIMESTAMP or dt.year != year or dt.month != month:
                continue
            if any(x in content_type for x in ["Podcast", "Event", "Book", "Collection"]):
                continue
            if not any(x in content_type for x in ["Commentary", "Research", "News"]):
                continue

            # ---- store article (unchanged logic) ----
            title       = hit.get("post_title", "No Title")
            url         = hit.get("permalink", "No URL")
            authors     = hit.get("authors", []) or ["Unknown"]
            date_string = dt.strftime("%Y-%m-%d")

            if post_id not in article_registry:
                content = extract_full_article(url) or hit.get("content", "")
                filename = TEXT_DIR / f"{post_id}.txt"
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(content)

                article_registry[post_id] = {
                    "title": title,
                    "url": url,
                    "date": date_string,
                    "authors": authors,
                    "content": content,
                    "keywords": {k: 0 for k in KEYWORDS}
                }

            article_registry[post_id]["keywords"][keyword] = 1
        # ------------------------------------------

        # stop paginating if Algolia cap already reached
        if fetched_this_query >= CAP_HARD:
            print("Reached Algolia 1000-hit cap for this query – consider weekly splits if that matters.")
            break

        page += 1
        time.sleep(0.7)

    print(f"🧮  Hits processed for '{keyword}' {year}-{month:02d}: {fetched_this_query}")

# Main loop
for keyword in KEYWORDS:
    print(f"🔍 Scraping keyword: {keyword}")
    for year, month in MONTHS:
        print(f"📅 {year}-{month:02d}", end=" ")
        query_articles(keyword, year, month)


# Prepare CSV output
# === Save CSV in SPLC-style format ===
all_articles = list(article_registry.values())
max_keywords = max(len([k for k, v in a['keywords'].items() if v]) for a in all_articles) if all_articles else 0
max_authors = max(len(a['authors']) for a in all_articles) if all_articles else 0

fieldnames = ['index', 'Article title', 'url'] + \
             [f'author_{i+1}' for i in range(max_authors)] + \
             ['msg', 'date', 'think tank'] + \
             [f'matched keyword {i+1}' for i in range(max_keywords)]

with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()

    for idx, article in enumerate(article_registry.values(), start=1):
        matched_keywords = [kw for kw, present in article['keywords'].items() if present]
        row = {
            'index': idx,
            'Article title': article['title'],
            'url': article['url'],
            'msg': article['content'],
            'date': article['date'],
            'think tank': 'Brookings',
        }
        for i, author in enumerate(article['authors']):
            row[f'author_{i+1}'] = author
        for i, kw in enumerate(matched_keywords):
            row[f'matched keyword {i+1}'] = kw

        writer.writerow(row)

print(f"\n✅ Done! Scraped and saved {len(all_articles)} articles to '{CSV_FILE}'.")