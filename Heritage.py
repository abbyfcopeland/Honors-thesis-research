import os
import re
import csv
import time
from bs4 import BeautifulSoup
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

options = Options()
options.add_argument('--headless')
options.add_argument('--disable-gpu')

service = Service(executable_path=ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=options)

# === Configuration ===
BASE_URL = "https://www.heritage.org"
KEYWORDS = [
    'race bias', 'racial bias', 'race prejudice', 'racial prejudice', 'race discrimination',
    'racial discrimination', 'race disparity', 'racial disparity', 'race inequality', 'racial inequality',
    'race difference', 'racial difference', 'racism'
]
OUTPUT_DIR = "heritage_articles"
TXT_DIR = os.path.join(OUTPUT_DIR, "txt")
CSV_FILE = os.path.join(OUTPUT_DIR, "articles.csv")
REQUEST_DELAY = 1  # seconds between requests
CUTOFF_DATE = datetime(2016, 10, 1)

# === Setup Directories ===
os.makedirs(TXT_DIR, exist_ok=True)

# === Helper Functions ===
def get_search_results(keyword, page):
    soup = BeautifulSoup(driver.page_source, 'html.parser')

    results = []
    for link in soup.select("a[href^='/']"):
        href = link.get('href')
        if not href or '/search?' in href:
            continue

        if any(x in href for x in ['/report/', '/commentary/', '/article/']):
            full_url = BASE_URL + href
            results.append((full_url, keyword))

    return results

def get_article_data(url):
    print(f"Fetching article: {url}")
    driver.get(url)
    time.sleep(REQUEST_DELAY)

    soup = BeautifulSoup(driver.page_source, 'html.parser')

    # Extract title
    title_tag = soup.find('h1')
    title = title_tag.get_text(strip=True) if title_tag else ""

    # Extract date
    date = ""
    date_match = soup.find(string=re.compile(r'\w+ \d{1,2}, \d{4}'))  # e.g., "May 4, 2021"
    if date_match:
        try:
            # Use regex to extract the actual date substring from messy text
            extracted = re.search(r'([A-Za-z]{3,9})\s(\d{1,2}),\s(\d{4})', date_match)
            if extracted:
                date_text = extracted.group(0)  # clean "June 22, 2021"
                try:
                    parsed_date = datetime.strptime(date_text, "%B %d, %Y")
                except ValueError:
                    parsed_date = datetime.strptime(date_text, "%b %d, %Y")
                date = parsed_date.strftime("%Y-%m-%d")
            else:
                print(f"❌ No valid date found in messy text: {date_match.strip()}")
                date = "Unretrieved"
        except Exception as e:
            print(f"❌ Date parsing failed for: {title} | Text: {date_match.strip()} | Error: {e}")
            date = "Unretrieved"



    # Extract all authors
    # Extract all authors (de-duped)
    author_set = set()

    # 1. Linked authors (href to /staff/)
    linked_author_tags = soup.find_all('a', href=re.compile('/staff/'))
    for tag in linked_author_tags:
        name = tag.get_text(strip=True)
        if name:
            author_set.add(name.strip())

    # 2. Unlinked authors (e.g., within <span class="author-card__name nolink"><span>NAME</span></span>)
    unlinked_author_tags = soup.select('span.author-card__name.nolink span')
    for tag in unlinked_author_tags:
        name = tag.get_text(strip=True)
        if name:
            author_set.add(name.strip())

    # 3. Fallback: <meta name="author" content="Name">
    if not author_set:
        meta_author = soup.find('meta', attrs={"name": "author"})
        if meta_author and meta_author.get("content"):
            author_set.add(meta_author["content"].strip())

    # Final cleaned list (sorted to maintain consistency)
    authors = sorted(author_set)
    # Extract content
    content_parts = []

    # Extract Key Takeaways (if present)
    takeaway_wrapper = soup.find('div', class_='key-takeaways__wrapper')
    if takeaway_wrapper:
        takeaways = takeaway_wrapper.find_all('p')
        if takeaways:
            content_parts.append("KEY TAKEAWAYS:")
            content_parts.extend([f"- {p.get_text(strip=True)}" for p in takeaways])
            content_parts.append("")  # Add spacing

    # Try several containers, including nested possibilities
    body = (
            soup.find('div', class_='article__body-copy') or
            soup.select_one('div.article__body-copy > div') or
            soup.find('div', class_='article-content') or
            soup.find('div', class_='field--name-body') or
            soup.find('div', class_='node__content') or
            soup.find('div', attrs={'property': 'content:encoded'})
    )

    if body:
        paragraphs = body.find_all('p')
        content_parts.extend([p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)])

    content = "\n".join(content_parts)

    if not content:
        print(f"⚠️ No content found for: {url}")


    return {
        'title': title,
        'url': url,
        'date': date,
        'authors': authors,
        'content': content
    }

# === Main Scraper ===
seen_articles = {}

for keyword in KEYWORDS:
    print(f"\n🔍 Searching for keyword: '{keyword}'")

    page = 0
    while True:
        print(f"[{keyword}] Page {page}...")

        #fetch search results
        search_url = f"{BASE_URL}/search?contains={keyword.replace(' ', '+')}&page={page}"
        driver.get(search_url)
        time.sleep(REQUEST_DELAY)

        search_results = get_search_results(keyword, page)

        if not search_results:
            print(f"⚠️ No more results found for '{keyword}' after page {page}.")
            break

        for url, matched_keyword in search_results:
            if url not in seen_articles:
                try:
                    article = get_article_data(url)

                    if article['date'] != "Unretrieved":
                        article_date = datetime.strptime(article['date'], "%Y-%m-%d")
                        if article_date < CUTOFF_DATE:
                            print(f"⏭ Skipping (too old): {article['title']} ({article['date']})")
                            continue
                    else:
                        print(f"⚠️ No retrievable date for: {article['title']} (continuing)")

                    # Track keyword matches
                    seen_articles[url] = {
                        'index': len(seen_articles) + 1,
                        'Article title': article['title'],
                        'url': article['url'],
                        'authors': article['authors'],
                        'msg': article['content'],
                        'date': article['date'],
                        'think tank': 'Heritage Foundation',
                        'matched_keywords': [matched_keyword],
                    }

                    # Save article text
                    safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', article['title'])[:100]
                    txt_filename = os.path.join(TXT_DIR, f"{safe_title}.txt")
                    with open(txt_filename, 'w', encoding='utf-8') as f:
                        f.write(article['content'])

                    seen_articles[url]['txt_filename'] = txt_filename

                    print(f"✅ Saved: {article['title']}")

                except Exception as e:
                    print(f"❌ Failed to scrape {url}: {e}")

            else:
                # Already seen: add this keyword if it's new
                if matched_keyword not in seen_articles[url]['matched_keywords']:
                    seen_articles[url]['matched_keywords'].append(matched_keyword)

            time.sleep(REQUEST_DELAY)
        page += 1

# Flatten matched keywords into separate columns
all_articles = list(seen_articles.values())

# Get max number of keyword and author matches to generate correct headers
max_keywords = max(len(a['matched_keywords']) for a in all_articles)
max_authors = max(len(a['authors']) for a in all_articles)
# header row in CSV
fieldnames = ['index', 'Article title', 'url'] + \
             [f'author_{i+1}' for i in range(max_authors)] + \
             ['msg', 'date', 'think tank'] + \
             [f'matched keyword {i+1}' for i in range(max_keywords)]

# === Save CSV ===
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

        # Add authors
        for i, author in enumerate(article['authors']):
            row[f'author_{i + 1}'] = author

        # Add keywords
        for i, kw in enumerate(article['matched_keywords']):
            row[f'matched keyword {i+1}'] = kw

        writer.writerow(row)

print(f"\n✅ Scraping complete. Saved {len(all_articles)} articles.")

# === Clean up ===
driver.quit()
