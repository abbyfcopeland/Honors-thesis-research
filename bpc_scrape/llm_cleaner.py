#!/usr/bin/env python3
"""
llm_clean_csv.py — CSV cleaner that adds a `clean_msg` column.

Usage:
  python3 llm_clean_csv.py input.csv output.csv
  python3 llm_clean_csv.py input.csv output.csv --keep-notes --rpm 30
  python3 llm_clean_csv.py input.csv output.csv --api-key sk-... --head 100
  python3 llm_clean_csv.py input.csv output.csv --input-col msg --output-col clean_msg
"""

import argparse, csv, json, os, re, sys, time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# --- 3rd party ---
try:
    from openai import OpenAI
except Exception:
    print("[fatal] Missing dependency. Install: pip install -U openai", file=sys.stderr)
    raise

# Optional: load .env if present (project-local secrets)
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

# ---------- Defaults ----------
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
DEFAULT_RPM = 60  # requests per minute

DEFAULT_DROP_REGEXES = [
    r"^share\s+on\s+(facebook|twitter|linkedin|reddit)\b",
    r"^subscribe\s+to\s+our\s+newsletter\b",
    r"^\s*\(?photo\s+credit\b.*\)?$",
    r"^about\s+the\s+(author|center|institute)\b",
    r"^\s*related\s+(posts|articles)\b",
    r"^\s*press\s+contact:\b",
    r"^\s*follow\s+us\b",
    r"^\s*tags?:\s*",
    r"^\s*download\s+the\s+(report|pdf|fact\s*sheet|factsheet)\b",
    r"^\s*media\s+inquiries\b",
    r"^\s*copyright\s+\d{4}\b",
]

INLINE_NOISE = [
    r"\s+\u00a0\s+",   # non-breaking spaces padding
]

SYSTEM = (
    "You are a meticulous text cleaner. Do not add facts or invent content. "
    "Never summarize or paraphrase beyond fixing errors."
)

USER_TASK = (
    "Clean the following scraped text.\n\n"
    "Goals:\n"
    "1) Repair words spuriously split by stray spaces/newlines (e.g., 'go vern ment' -> 'government').\n"
    "2) Remove boilerplate/tagline lines and social-share cruft that are not part of the body.\n"
    "3) Preserve meaning, numbers, proper nouns, and citations; do NOT hallucinate.\n"
    "4) Keep the original paragraphing when possible.\n\n"
    "Boundaries:\n"
    "- Do not rewrite style or tone.\n"
    "- Do not remove valid section headers.\n"
    "- If unsure whether a line is boilerplate, keep it.\n"
    "- Do not introduce new whitespace inside intact words. Never output forms like 'Th is', 'F or', 'c are'.\n"
    "- When you see suspicious intra-word splits (e.g., 'C are', 'f or', 'Medic are'), JOIN them into the most likely real word ('Care', 'for', 'Medicare').\n"
    "- Preserve acronyms and dotted abbreviations exactly (U.S., U.K., D.C.).\n"
    "- If uncertain whether two tokens form a single word or two valid words, prefer the single dictionary word.\n"
)

JSON_SCHEMA = {
    "name": "CleanedMessage",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "cleaned": {"type": "string", "description": "The cleaned text."},
            "dropped_lines": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Exact lines removed as boilerplate."
            },
            "notes": {"type": "string", "description": "Brief notes on ambiguous fixes (optional)."}
        },
        "required": ["cleaned", "dropped_lines"]
    },
    "strict": True
}

@dataclass
class Config:
    model: str = DEFAULT_MODEL
    rpm: int = DEFAULT_RPM
    input_col: str = "msg"
    output_col: str = "clean_msg"
    keep_notes: bool = False
    head: Optional[int] = None
    api_key: Optional[str] = None
    patterns: Optional[str] = None

def _rate_limit(rpm: int, last_time: Optional[float]) -> float:
    """Simple per-minute pacing."""
    if rpm <= 0:
        return time.time()
    gap = 60.0 / float(rpm)
    now = time.time()
    if last_time is None:
        return now
    sleep_for = (last_time + gap) - now
    if sleep_for > 0:
        time.sleep(sleep_for)
        return time.time()
    return now

def load_drop_patterns(extra_patterns_path: Optional[str]) -> List[str]:
    pats = list(DEFAULT_DROP_REGEXES)
    if extra_patterns_path and os.path.exists(extra_patterns_path):
        with open(extra_patterns_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    pats.append(line)
    return pats

def preclean(text: str) -> str:
    """Normalize NBSP, CRLFs, and rejoin hyphenated line breaks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for pat in INLINE_NOISE:
        text = re.sub(pat, " ", text)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    return text

def build_messages(drop_regexes: List[str], raw_text: str) -> List[Dict[str, Any]]:
    drop_block = "\n".join(f"- {p}" for p in drop_regexes)
    user_prompt = (
        f"{USER_TASK}\n"
        "Boilerplate patterns to remove (regexes, case-insensitive):\n"
        f"{drop_block}\n\n"
        "TEXT:\n"
        f"{raw_text}"
    )
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_prompt},
    ]

def call_llm(client: OpenAI, model: str, messages: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Prefer Structured Outputs (json_schema); schema-aware fallback to json_object.
    Always return dict with: cleaned (str), dropped_lines (list[str]), notes (optional str).
    """
    import json as _json, re as _re

    # Primary: structured outputs
    try:
        chat = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.0,
            response_format={"type": "json_schema", "json_schema": JSON_SCHEMA},
        )
        content = chat.choices[0].message.content or ""
        return _json.loads(content)
    except Exception as e1:
        # Fallback: json_object requires the word "JSON" in the prompt + include schema explicitly
        schema_text = _json.dumps(JSON_SCHEMA["schema"], ensure_ascii=False)
        chat = client.chat.completions.create(
            model=model,
            messages=[
                *messages,
                {"role": "user",
                 "content": (
                     "Return ONLY a JSON object that matches this exact schema. "
                     "Do not include any text before or after the JSON.\n\n"
                     f"Schema:\n{schema_text}\n"
                 )},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        content = chat.choices[0].message.content or ""
        try:
            return _json.loads(content)
        except Exception as e2:
            # Last-ditch: extract trailing JSON blob
            m = _re.search(r"\{[\s\S]*\}\s*$", content)
            if not m:
                raise RuntimeError(f"structured-output-failed: {e1}; json-object-failed: {e2}; content[:200]={content[:200]!r}")
            return _json.loads(m.group(0))

def clean_one(client: OpenAI, cfg: Config, drop_regexes: List[str], raw_text: str) -> Tuple[str, List[str], str]:
    raw_text = preclean(raw_text)
    messages = build_messages(drop_regexes, raw_text)
    data = call_llm(client, cfg.model, messages)

    # Extract with safety defaults
    cleaned = (data.get("cleaned") or "").strip()
    dropped = data.get("dropped_lines", []) or []
    notes = data.get("notes", "") or ""

    # Guard: if cleaned is empty but we had input, fall back to original
    if not cleaned and raw_text.strip():
        notes = (notes + " | " if notes else "") + "fallback_to_original: empty_cleaned"
        cleaned = raw_text

    return cleaned, dropped, notes

def process_csv(in_csv: str, out_csv: str, cfg: Config) -> None:

    client = OpenAI(api_key=cfg.api_key or os.getenv("OPENAI_API_KEY"))
    drop_regexes = load_drop_patterns(cfg.patterns)

    with open(in_csv, "r", encoding="utf-8", newline="") as f_in, \
         open(out_csv, "w", encoding="utf-8", newline="") as f_out:

        reader = csv.DictReader(f_in)
        # Strip BOM from any header, not just the first
        if reader.fieldnames:
            reader.fieldnames = [fn.replace("\ufeff", "") for fn in reader.fieldnames]

        if not reader.fieldnames:
            print("[fatal] Input CSV has no header row.", file=sys.stderr)
            sys.exit(2)
        if cfg.input_col not in reader.fieldnames:
            print(f"[fatal] Input column '{cfg.input_col}' not found. Available: {reader.fieldnames}", file=sys.stderr)
            sys.exit(2)

        fieldnames = list(reader.fieldnames)
        if cfg.output_col not in fieldnames:
            fieldnames.append(cfg.output_col)
        if cfg.keep_notes:
            if "dropped_lines" not in fieldnames:
                fieldnames.append("dropped_lines")
            if "llm_notes" not in fieldnames:
                fieldnames.append("llm_notes")

        writer = csv.DictWriter(f_out, fieldnames=fieldnames)
        writer.writeheader()

        last_call = None
        for i, row in enumerate(reader):
            if cfg.head is not None and i >= cfg.head:
                break

            msg = row.get(cfg.input_col, "") or ""
            if not msg.strip():
                # Preserve empty values
                row[cfg.output_col] = msg
                if cfg.keep_notes:
                    row["dropped_lines"] = "[]"
                    row["llm_notes"] = ""
                writer.writerow(row)
                continue

            last_call = _rate_limit(cfg.rpm, last_call)

            # Retry loop with exponential backoff
            cleaned, dropped, notes = msg, [], ""
            for attempt in range(5):
                try:
                    cleaned, dropped, notes = clean_one(client, cfg, drop_regexes, msg)
                    break
                except Exception as e:
                    wait = min(2 ** attempt, 30)
                    if attempt == 4:
                        notes = f"error: {e}"
                        # If all attempts fail, keep original text (not blank)
                        cleaned = msg
                        print(f"[error] row {i}: {e}", file=sys.stderr)
                        break
                    time.sleep(wait)

            # Belt & suspenders: warn if empty clean
            if not (cleaned or "").strip() and (msg or "").strip():
                print(f"[warn] row {i}: empty cleaned; writing original", file=sys.stderr)
                cleaned = msg

            row[cfg.output_col] = cleaned
            if cfg.keep_notes:
                row["dropped_lines"] = json.dumps(dropped, ensure_ascii=False)
                row["llm_notes"] = notes

            writer.writerow(row)
            if i % 50 == 0:
                print(f"[progress] wrote row {i}", file=sys.stderr)


def make_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="LLM-powered CSV cleaner: adds a 'clean_msg' column.")
    p.add_argument("input_csv", help="Path to input CSV with a 'msg' column (configurable via --input-col).")
    p.add_argument("output_csv", help="Path to output CSV; this script will write it.")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Model (default: gpt-4o-mini).")
    p.add_argument("--api-key", help="OpenAI API key; otherwise use OPENAI_API_KEY env var.")
    p.add_argument("--rpm", type=int, default=DEFAULT_RPM, help="Requests per minute (default: 60).")
    p.add_argument("--head", type=int, default=None, help="Process only the first N rows (smoke test).")
    p.add_argument("--keep-notes", action="store_true", help="Add dropped_lines and llm_notes columns.")
    p.add_argument("--input-col", default="msg", help="Name of input text column (default: msg).")
    p.add_argument("--output-col", default="clean_msg", help="Name of output text column (default: clean_msg).")
    p.add_argument("--patterns", default=None, help="Optional path to newline-delimited regex file for boilerplate lines.")
    return p

def main() -> None:
    ap = make_argparser()
    args = ap.parse_args()
    cfg = Config(
        model=args.model,
        rpm=args.rpm,
        input_col=args.input_col,
        output_col=args.output_col,
        keep_notes=bool(args.keep_notes),
        head=args.head,
        api_key=args.api_key,
        patterns=args.patterns,
    )

    if not os.path.exists(args.input_csv):
        print(f"[fatal] Input not found: {args.input_csv}", file=sys.stderr)
        sys.exit(2)

    process_csv(args.input_csv, args.output_csv, cfg)
    print(f"[ok] wrote: {args.output_csv}")

if __name__ == "__main__":
    main()
