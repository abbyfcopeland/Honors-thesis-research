import os
import re
import csv
import time
import random
import requests
import json
from bs4 import BeautifulSoup
from datetime import datetime

# === Configuration ===
BASE_URL = "https://www.splcenter.org"
SEARCH_URL = BASE_URL + "/?s="
KEYWORDS = [
    'race bias', 'racial bias', 'race prejudice', 'racial prejudice', 'race discrimination',
    'racial discrimination', 'race disparity', 'racial disparity', 'race inequality', 'racial inequality',
    'race difference', 'racial difference', 'racism'
]
CUTOFF_DATE = datetime(2016, 10, 1)
OUTPUT_DIR = "splc_articles"
TXT_DIR = os.path.join(OUTPUT_DIR, "txt")
CSV_FILE = os.path.join(OUTPUT_DIR, "articles.csv")


# === Setup Directories ===
os.makedirs(TXT_DIR, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

def get_splc_search_links(keyword, page=1):
    if page == 1:
        url = f"{BASE_URL}/?s={keyword}"
    else:
        url = f"{BASE_URL}/page/{page}/?s={keyword}"

    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        print(f"❌ Failed to fetch search page for '{keyword}' (page {page}) — {url}")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    links = []

    # Only scrape from known article paths
    article_sections = [
        '/resources/hopewatch/',
        '/resources/hatewatch/',
        '/resources/reports/',
        '/resources/guides/',
        '/presscenter/',
        '/resources/stories/',
        '/resources/civil-rights-case-docket/',
        '/resources/extremist-files/',
    ]

    for a in soup.select("h3.wp-block-post-title a[href]"):
        href = a["href"]
        if any(section in href for section in article_sections):
            title = a.get_text(strip=True)
            links.append((title, href))
        else:
            print(f"⏭ Skipping non-article URL: {href}")

    return links

def scrape_article(url, keyword, index):
    time.sleep(random.uniform(1, 2))
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        print(f"❌ Failed to fetch article: {url}")
        return None

    soup = BeautifulSoup(response.text, 'html.parser')
    title_tag = soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else "Untitled"

    parsed_date = None

    # Try <time> tag with 'datetime' attribute
    date_tag = soup.find("time")
    if date_tag and date_tag.has_attr("datetime"):
        raw = date_tag["datetime"]
        try:
            parsed_date = datetime.fromisoformat(raw.split("T")[0])
        except Exception as e:
            print(f"❌ Failed to parse <time>: {e}")

    # Fallback 1: old span style
    if not parsed_date:
        fallback = soup.find("span", class_="date-display-single")
        if fallback:
            raw = fallback.get_text(strip=True)
            try:
                parsed_date = datetime.strptime(raw, "%B %d, %Y")
                print(f"✅ Parsed <span>: {parsed_date}")
            except Exception as e:
                print(f"❌ Failed to parse <span>: {e}")

    # Fallback 2: search <dd> tags with regex filtering
    if not parsed_date:
        dd_tags = soup.find_all("dd")
        for dd in dd_tags:
            raw = dd.get_text(strip=True)
            if re.search(r'\b\w+ \d{1,2}, \d{4}\b', raw):
                try:
                    parsed_date = datetime.strptime(raw, "%B %d, %Y")
                    print(f"✅ Parsed <dd>: {parsed_date}")
                    break
                except Exception as e:
                    print(f"❌ Failed to parse <dd>: {e}")

    # Fallback 3: JSON-LD structured data
    if not parsed_date:
        for script_tag in soup.find_all("script", type="application/ld+json"):
            try:
                json_data = script_tag.string
                if not json_data:
                    continue
                data = json.loads(json_data)
                nodes = data.get("@graph", []) if isinstance(data, dict) and "@graph" in data else [data]
                for node in nodes:
                    if isinstance(node, dict) and node.get("@type") == "WebPage" and "datePublished" in node:
                        raw = node["datePublished"]
                        parsed_date = datetime.fromisoformat(raw.split("T")[0])
                        print(f"✅ Parsed JSON-LD date: {parsed_date}")
                        break
            except Exception as e:
                print(f"❌ Failed to parse JSON-LD date: {e}")
            if parsed_date:
                break

    if not parsed_date:
        print(f"⏭ Skipping: {title} — no valid date found.")
        return None
    elif parsed_date < CUTOFF_DATE:
        print(f"⏭ Skipping: {title} — date {parsed_date.date()} is before cutoff.")
        return None

    # === Get author(s) ===
    author_tag = soup.find("p", class_="wp-block-splc-authors__name")
    authors = [author_tag.get_text(strip=True)] if author_tag else [" "]

    # === Extract article content ===
    paragraphs = []

    # Primary: use <div class="entry-content"> (WordPress body wrapper)
    body_div = soup.find("div", class_="entry-content")
    if body_div:
        paragraphs = body_div.find_all("p")

    # Fallback 1: legacy SPLC format (Drupal-style)
    if not paragraphs:
        legacy_div = soup.find("div", class_="field field-name-body")
        if legacy_div:
            paragraphs = legacy_div.find_all("p")

    # Fallback 2: all <p> tags inside <main>
    if not paragraphs:
        main_tag = soup.find("main")
        if main_tag:
            paragraphs = main_tag.find_all("p")

    # Fallback 3: all <p> tags (last resort)
    if not paragraphs:
        paragraphs = soup.find_all("p")

    # Assemble content
    content = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))

    # Save .txt
    safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', title)[:100]
    txt_filename = os.path.join(TXT_DIR, f"{safe_title}.txt")
    with open(txt_filename, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"✅ Saved: {title} — {parsed_date.strftime('%Y-%m-%d')}")

    return {
        'index': index,
        'Article title': title,
        'url': url,
        'authors': authors,
        'msg': content,
        'date': parsed_date.strftime('%Y-%m-%d') if parsed_date else '',
        'think tank': "Southern Poverty Law Center",
        'matched_keywords': [keyword],
        'txt_filename': txt_filename
    }

# === Main Script ===
seen_articles = {}
index = 1

for keyword in KEYWORDS:
    page = 1
    while True:
        print(f"\n🔎 Searching for: '{keyword}' — Page {page}")
        try:
            articles = get_splc_search_links(keyword, page)
        except Exception as e:
            print(f"⚠️ Error during search: {e}")
            break

        if not articles:
            print(f"🛑 No more results for '{keyword}' at page {page}.")
            break

        for title, url in articles:
            if url not in seen_articles:
                try:
                    article = scrape_article(url, keyword, index)
                    if article:
                        seen_articles[url] = article
                        index += 1
                except Exception as e:
                    print(f"⚠️ Failed to scrape {url}: {e}")
            elif keyword not in seen_articles[url]['matched_keywords']:
                seen_articles[url]['matched_keywords'].append(keyword)

        page += 1  # Move to next page

# === Save CSV ===
all_articles = list(seen_articles.values())
max_keywords = max(len(a['matched_keywords']) for a in all_articles) if all_articles else 0
max_authors = max(len(a['authors']) for a in all_articles) if all_articles else 0

fieldnames = ['index', 'Article title', 'url'] + \
             [f'author_{i+1}' for i in range(max_authors)] + \
             ['msg', 'date', 'think tank'] + \
             [f'matched keyword {i+1}' for i in range(max_keywords)]

with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for article in all_articles:
        row = {
            'index': article['index'],
            'Article title': article['Article title'],
            'url': article['url'],
            'msg': article['msg'],
            'date': article['date'],
            'think tank': article['think tank'],
        }
        for i, author in enumerate(article['authors']):
            row[f'author_{i+1}'] = author
        for i, kw in enumerate(article['matched_keywords']):
            row[f'matched keyword {i+1}'] = kw
        writer.writerow(row)

print(f"\n✅ Done! Scraped and saved {len(all_articles)} articles.")
