import time
from datetime import datetime
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
import csv
from pathlib import Path
import re
from urllib.parse import quote_plus
import sys

# === CONFIG ===
KEYWORDS = [
    'race bias', 'racial bias', 'race prejudice', 'racial prejudice', 'race discrimination',
    'racial discrimination', 'race disparity', 'racial disparity', 'race inequality', 'racial inequality',
    'race difference', 'racial difference', 'racism'
]
CATEGORIES = ["commentary", "blog", "free-society", "news-releases", "public-filings", "reviews-journals", "speeches", "study",
              "policy-analysis", "events","public-opinion-brief","policing-in-america"]
CUTOFF_DATE = datetime(2016, 10, 1)

# === OUTPUT ===
OUTPUT_DIR = Path("cato_scrape")
TEXT_DIR = OUTPUT_DIR / "texts"
CSV_FILE = OUTPUT_DIR / "cato_articles.csv"
TEXT_DIR.mkdir(parents=True, exist_ok=True)

article_registry = {}

def extract_date(soup):
    time_tag = soup.find("time")
    if time_tag and time_tag.has_attr("datetime"):
        try:
            return datetime.strptime(time_tag["datetime"][:10], "%Y-%m-%d")
        except:
            pass
    span_tag = soup.select_one("span.date-time__date")
    if span_tag:
        try:
            return datetime.strptime(span_tag.get_text(strip=True), "%B %d, %Y")
        except:
            pass
    meta_div = soup.select_one("div.meta.meta--default")
    if meta_div:
        date_text = meta_div.get_text(strip=True).split("•")[0].strip()
        try:
            return datetime.strptime(date_text, "%B %d, %Y")
        except:
            pass
    return None

# === LAUNCH BROWSER ===
options = uc.ChromeOptions()
options.add_argument("--headless=new")  # Enable this if running without UI
options.add_argument("--no-sandbox")
options.add_argument("--disable-gpu")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--window-size=1920,1080")
driver = uc.Chrome(options=options)

for keyword in KEYWORDS:
    print(f"\n🔍 Searching for keyword: {keyword}")
    page = 0
    while True:
        search_url = f"https://www.cato.org/search?query={quote_plus(keyword)}&daterange=1475294400%3A1753847999&page={page}"
        driver.get(search_url)
        time.sleep(5)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        links = soup.select("h5.search-result__title a")
        if not links:
            break
        print(f"📄 Page {page + 1} — Found {len(links)} links")

        for link in links:
            href = link.get("href")
            if not href:
                continue
            url = href if href.startswith("http") else "https://www.cato.org" + href
            if not any(cat in url for cat in CATEGORIES):
                continue
            if url in article_registry:
                article_registry[url]["keywords"].add(keyword)
                continue

            driver.get(url)
            time.sleep(3)
            article_soup = BeautifulSoup(driver.page_source, "html.parser")

            # Title
            title_tag = article_soup.find("h1", attrs={"property": "headline"}) or article_soup.find("h1")
            title = title_tag.get_text(strip=True) if title_tag else "Untitled"

            # Date
            pub_date = extract_date(article_soup)
            if not pub_date or pub_date < CUTOFF_DATE:
                continue
            date_str = pub_date.strftime("%Y-%m-%d")

            # Authors
            author_tags = article_soup.select(".authors span, div.authors span[property='author'], meta[name='author']")
            authors = set()
            for tag in author_tags:
                if tag.name == "meta":
                    authors.add(tag.get("content", "").strip())
                else:
                    authors.add(tag.get_text(strip=True))
            author_list = [a for a in authors if a]
            cleaned = []
            for raw in author_list:
                # split on “ and ” or commas that appear between names
                parts = re.split(r'\s+and\s+|,\s*', raw)
                cleaned.extend([p.strip() for p in parts if p.strip()])
            author_list = sorted(set(cleaned))

            # Content
            paragraphs = article_soup.select("article p")
            content = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))

            # Logging
            print(f"\n--- ARTICLE {len(article_registry) + 1} ---")
            print("🔗", url)
            print("📰 Title:", title)
            print("📅 Date:", date_str)
            print("✍️ Authors:", ", ".join(author_list) if author_list else "None found")
            print("📝 Content Preview:", content[:300] + "..." if len(content) > 300 else content)

            # Save full text
            filename = f"{len(article_registry) + 1}.txt"
            with open(TEXT_DIR / filename, "w", encoding="utf-8") as f:
                f.write(content)

            article_registry[url] = {
                "title": title,
                "url": url,
                "date": date_str,
                "authors": author_list,
                "content": content,
                "keywords": set([keyword])
            }

        page += 1
        time.sleep(2)

if not article_registry:
    print("No articles found – exiting.")
    driver.quit()
    sys.exit(0)
# === EXPORT CSV ===
max_keywords = max(len(a["keywords"]) for a in article_registry.values())
max_authors = max(len(a["authors"]) for a in article_registry.values())

fieldnames = ['index', 'Article title', 'url'] + \
             [f'author_{i+1}' for i in range(max_authors)] + \
             ['msg', 'date', 'think tank'] + \
             [f'matched keyword {i+1}' for i in range(max_keywords)]

with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()

    for idx, article in enumerate(article_registry.values(), start=1):
        row = {
            'index': idx,
            'Article title': article['title'],
            'url': article['url'],
            'msg': article['content'],
            'date': article['date'],
            'think tank': 'Cato',
        }
        for i, author in enumerate(article['authors']):
            row[f'author_{i+1}'] = author
        for i, kw in enumerate(article['keywords']):
            row[f'matched keyword {i+1}'] = kw
        writer.writerow(row)

print(f"\n✅ Done! Scraped and saved {len(article_registry)} articles to '{CSV_FILE}'.")

driver.quit()
