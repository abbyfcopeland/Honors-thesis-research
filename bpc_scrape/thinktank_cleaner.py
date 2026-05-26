import sys, re
from pathlib import Path
import pandas as pd
from typing import Optional, List

# Optional: BeautifulSoup for better HTML → text (falls back if missing)
try:
    from bs4 import BeautifulSoup  # type: ignore
    BS4_OK = True
except Exception:
    BS4_OK = False

# ------------------ Patterns ------------------
GENERIC_LINE_PATTERNS: List[str] = [
    r"^\s*Share (on )?(Facebook|Twitter|LinkedIn|Email).*$",
    r"^\s*(Subscribe|Sign up) for (updates|newsletters|emails).*$",
    r"^\s*Related (posts|content|articles).*$",
    r"^\s*Read (more|the report).*$",
    r"^\s*(Back to top|Next|Previous)\s*$",
    r"^\s*Cookie(s)? (notice|policy).*$",
    r"^\s*Donate (now|today).*$",
]

INLINE_PATTERNS: List[str] = [
    r"\[\d+\]",                               # [12]
    r"\(\d+\)",                               # (3)
    r"\(see (figure|table)\s*\d+(\.\d+)?\)",  # (see figure 3.2)
    r"(?<=\S)\s*\d+\s*$",                     # trailing stand-alone number
]

SITE_LINES = {
    "bpc": [
        r"^With your support, BPC can continue to .* opportunity for all Americans\.$",
        r"^BPC drives principled and politically viable policy solutions.*aggressive advocacy\.$",
        r"^Download the Factsheet\.?$",
        r"^More information here\.?$",
        r"^Return to Top\s*[↑⇑]?$",
        r"^Read BPC’s full set of offset options here.*$",
        r"^Sincerely,.*$",
        r"^Photo by .*$",
    ],
    "brookings": [
        r"^Back to top\s*[↑⇑]?$",
        r"^Continue reading\.?$",
        r"^If you want more content like this, subscribe.*$",
        r"^Want to receive the Hutchins Roundup.*Sign up here.*$",
        r"^This (brief|piece) is part of the Brookings .* project\.$",
        r"^This piece is part of 19A: The Brookings Gender Equality Series.*$",
        r"^Read more in the Brookings Big Ideas for America series\s*[»›]?$",
        r"^The Brookings Institution is committed to quality, independence, and impact\.$",
    ],
    "cato": [
        r"^This is a modal window\.$",
        r"^Beginning of dialog window\..*$",
        r"^End of dialog window\.$",
        r"^\[?Cross-?posted from Alt-?M\.org\]?\.?$",
        r"^Summing It All Up$",
        r"^Chart of the Week$",
        r"^The Links$",
        r".*\b(Senior|Adjunct|Research|Visiting|Emeritus|Distinguished)\b.*Cato Institute$",
        r".*\b(Chair|Fellow|Director|Vice President|Policy Analyst)\b.*Cato Institute$",
        r".*\bR\.?\s*Evan Scharf Chair for the Public Understanding of Economics.*$",
        r"^©?\s*Cato Institute.*$",
        r"^Cato Institute\s*•\s*1000 Massachusetts Ave\.,?\s*NW.*$",
        r"^Cato Institute is a 501\(c\)\(3\)\.?$",
        r"^(Support|Donate to|Join) Cato.*$",
        r"^Sign up for Cato (emails|updates|newsletters).*$",
        r"^Subscribe to (the )?Cato (Daily|Podcast|Journal).*$",
    ],
    "heritage": [
        r"^KEY TAKEAWAYS:?$",
        r"^Ibid\.?\ufeff?$",
        r"^Id\.?$",
        r"^This piece originally appeared in (The )?Daily Signal.*$",
        r"^This piece originally appeared in (the )?National Review.*$",
        r"^This piece originally appeared in the (New York Post|Washington (Times|Examiner)|Daily Caller|Fox News).*?$",
        r"^This piece originally appeared in .*?$",
        r"^The Kevin Roberts Show is brought to you by .* Heritage Foundation.*$",
    ],
}

SITE_DOMAIN_MAP = {
    "brookings": ["brookings.edu"],
    "aei": ["aei.org"],
    "bpc": ["bipartisanpolicy.org"],
    "heritage": ["heritage.org", "dailysignal.com"],
    "cato": ["cato.org", "libertarianism.org"],
}

# ------------------ Helpers ------------------
def html_to_text_preserve_paras(html_or_text: str) -> str:
    if not isinstance(html_or_text, str):
        html_or_text = str(html_or_text or "")
    if BS4_OK:
        for parser in ("html5lib", "lxml", "html.parser"):
            try:
                soup = BeautifulSoup(html_or_text or "", parser)
                for tag in soup(["nav","footer","aside","script","style","noscript","form","iframe"]):
                    try:
                        tag.decompose()
                    except Exception:
                        pass
                if soup and soup.text is not None:
                    return soup.get_text("\n", strip=True)
            except Exception:
                continue
    text = re.sub(r"(?is)<(script|style|noscript|iframe|footer|nav|aside)[\s\S]*?</\1>", " ", html_or_text or "")
    text = re.sub(r"(?is)<[^>]+>", "\n", text)
    text = (text.replace("&nbsp;"," ").replace("&amp;","&").replace("&lt;","<").replace("&gt;",">"))
    text = re.sub(r"\r\n?", "\n", text)
    return text

def infer_site_key(source_hint: str = "", url_hint: str = "") -> str:
    s = (source_hint or "").lower()
    u = (url_hint or "").lower()
    for key, domains in SITE_DOMAIN_MAP.items():
        if key in s:
            return key
        if any(d in u for d in domains):
            return key
    if "heritage" in s: return "heritage"
    if "brookings" in s: return "brookings"
    if "bipartisan policy center" in s or "bpc" in s: return "bpc"
    if "aei" in s or "american enterprise institute" in s: return "aei"
    if "cato" in s: return "cato"
    return ""

def normalize_unicode_spaces(text: str) -> str:
    if not isinstance(text, str):
        text = str(text or "")
    text = (text
            .replace("\u00A0", " ")  # NBSP
            .replace("\u2007", " ")  # figure space
            .replace("\u2009", " ")  # thin space
            .replace("\u202F", " ")  # narrow NBSP
            .replace("\u2060", ""))  # word joiner
    return re.sub(r"[ \t]{2,}", " ", text)

def fix_split_first_letter(text: str) -> str:
    # 'C aregiving' -> 'Caregiving' (only single initial cap + lowercase word)
    return re.sub(r"\b([A-Z])\s+([a-z][a-z]+)\b", r"\1\2", text)

def fix_mushed_words_general(text: str) -> str:
    if not isinstance(text, str):
        text = str(text or "")

    # 1) Add missing space after punctuation
    text = re.sub(r"([,;:])(?=\S)", r"\1 ", text)
    text = re.sub(r"\.(?=[A-Z])", ". ", text)

    # 2) lower→Upper camel hump in prose
    text = re.sub(r"(?<=[a-z])(?=[A-Z][a-z])", " ", text)

    # 3) number↔letter boundaries
    text = re.sub(r"(?<=[0-9])(?=[A-Za-z])", " ", text)
    text = re.sub(r"(?<=[A-Za-z])(?=[0-9])", " ", text)

    # 4) ACRONYM (2+ caps) glued to lowercase word
    text = re.sub(r"([A-Z]{2,})(?=[a-z])", r"\1 ", text)

    # 5) Insert a space before common short words if glued to previous word
    preps = r"(?:in|of|to|for|on|by|and|or|but|as|with|from|at|than)"
    text = re.sub(rf"([A-Za-z])(?=(?:{preps})\b)", r"\1 ", text)

    # 6) Auxiliaries glued to following word: 'hasaccrued' -> 'has accrued'
    aux = r"(?:has|was|is|are|were|be|been|being|had|have|having|do|does|did|can|could|should|would|will|shall|may|might|must)"
    text = re.sub(rf"\b({aux})\b(?=[a-z])", r"\1 ", text)

    # 7) Previous word glued to auxiliaries: 'statuswas' -> 'status was'
    text = re.sub(rf"([A-Za-z])(?={aux}\b)", r"\1 ", text)

    # 8) Known one-off seen in scraped prose
    text = re.sub(r"\bevenfewer\b", "even fewer", text, flags=re.I)

    # 9) Hyphenated compounds split after single-letter prefix: 'l and-grant' -> 'land-grant'
    text = re.sub(r"\b([A-Za-z])\s+(-[A-Za-z-]+)\b", r"\1\2", text)

    # 10) Acronym + stray space before plural 's' : 'HBCU s' -> 'HBCUs'
    text = re.sub(r"\b([A-Z]{2,})\s+s\b", r"\1s", text)

    return re.sub(r" {2,}", " ", text).strip()

def drop_or_strip(line: str, drop_regexes: List[str]) -> Optional[str]:
    for p in drop_regexes:
        if re.match(p, line, flags=re.I):
            return None
    out = line
    for p in INLINE_PATTERNS:
        out = re.sub(p, "", out, flags=re.I)
    # Remove leading bullet markers like "- " or "• "
    out = re.sub(r"^[•\-]+\s*", "", out)
    out = re.sub(r"[ \t]+", " ", out).strip()
    return out if out else None

def insert_space_after_shortword_before_capital(text: str) -> str:
    if not isinstance(text, str):
        text = str(text or "")
    preps = r"(?:a|an|in|on|at|to|for|from|by|of|and|or|the|but|as|via|per|nor)"
    text = re.sub(rf"\b{preps}(?=[A-Z][a-z])", lambda m: m.group(0) + " ", text)
    text = re.sub(rf"\b{preps}(?=(?:[A-Z]{{2,}})(?![a-z]))", lambda m: m.group(0) + " ", text)
    return text

# ------------------ Main cleaner ------------------
def clean_text_strict(msg: str, source_hint: str = "", url_hint: str = "") -> str:
    t = html_to_text_preserve_paras(msg)
    lines = [ln.rstrip() for ln in t.splitlines()]

    site_key = infer_site_key(source_hint, url_hint)
    drop_patterns = GENERIC_LINE_PATTERNS + SITE_LINES.get(site_key, [])

    kept = []
    for ln in lines:
        if not ln.strip():
            continue
        ln2 = drop_or_strip(ln, drop_patterns)
        if ln2 is not None:
            kept.append(ln2)

    # Deduplicate adjacent identical lines
    out_lines, prev = [], None
    for ln in kept:
        if ln != prev:
            out_lines.append(ln)
        prev = ln

    text = "\n".join(out_lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    # normalize and spacing repairs
    text = normalize_unicode_spaces(text)
    text = fix_split_first_letter(text)       # e.g., 'C aregiving'
    text = fix_mushed_words_general(text)     # e.g., 'hasaccrued', 'deficitsin'
    text = insert_space_after_shortword_before_capital(text)

    return text

def insert_column_next_to(df: pd.DataFrame, base_col: str, new_col: str, values) -> pd.DataFrame:
    if new_col in df.columns:
        df = df.drop(columns=[new_col])
    idx = list(df.columns).index(base_col) + 1
    left = df.iloc[:, :idx]
    right = df.iloc[:, idx:]
    return pd.concat([left, pd.Series(values, name=new_col), right], axis=1)

# ------------------ CLI ------------------
def main(input_csv: str, output_csv: Optional[str] = None) -> None:
    inp = Path(input_csv)
    outp = Path(output_csv) if output_csv else inp.with_suffix(".cleaned.csv")

    df = pd.read_csv(inp, dtype=str, keep_default_na=False)
    if "msg" not in df.columns:
        raise SystemExit("ERROR: required column 'msg' not found in the CSV.")

    source_col = next((c for c in ["think tank","source","site","organization","org","institution"] if c in df.columns), None)
    url_col = "url" if "url" in df.columns else None

    if source_col or url_col:
        cleaned = df.apply(lambda r: clean_text_strict(
            r["msg"],
            r.get(source_col, "") if source_col else "",
            r.get(url_col, "") if url_col else ""
        ), axis=1)
    else:
        cleaned = df["msg"].map(clean_text_strict)

    df = insert_column_next_to(df, "msg", "msg_cleaned", cleaned)
    df.to_csv(outp, index=False)
    print(f"Saved: {outp}  (rows={len(df)}, columns={len(df.columns)})")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python clean_msg_column_py38.py <input.csv> [output.csv]")
        sys.exit(1)
    input_csv = sys.argv[1]
    output_csv = sys.argv[2] if len(sys.argv) > 2 else None
    main(input_csv, output_csv)
