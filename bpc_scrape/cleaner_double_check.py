#!/usr/bin/env python3
"""
Reads a specific CSV, keeps rows whose `msg` column contains
ANY of the race-related keywords (case-insensitive), and writes them to
`search_term_cleaned_full.csv`.

Adds a new column `python_matched_keywords` that lists which keywords matched
for that row, without touching any existing matched keyword columns.
"""

import csv
from pathlib import Path

# ---- HARD-CODED INPUT FILE HERE ----
INPUT_CSV = "thinktanks_merged.csv"   # ← change this to your 18k-article CSV
OUTPUT_CSV = "search_term_cleaned_full.csv"

# ---- YOUR KEYWORDS (as provided) ----
KEYWORDS = [ 'race bias', 'racial bias', 'race prejudice', 'racial prejudice', 'race discrimination',
    'racial discrimination', 'race disparity', 'racial disparity', 'race inequality', 'racial inequality',
    'race difference', 'racial difference', 'racism'
]

MSG_COL = "msg"
NEW_MATCHES_COL = "python_matched_keywords"


def main():
    input_path = Path(INPUT_CSV)
    output_path = Path(OUTPUT_CSV)

    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}")
        return

    keywords_lower = [k.lower() for k in KEYWORDS]

    total = 0
    kept = 0

    with input_path.open("r", newline="", encoding="utf-8") as infile, \
         output_path.open("w", newline="", encoding="utf-8") as outfile:

        reader = csv.DictReader(infile)

        # Start from original columns
        fieldnames = list(reader.fieldnames)

        # Add our new column if it isn't already there
        if NEW_MATCHES_COL not in fieldnames:
            fieldnames.append(NEW_MATCHES_COL)

        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()

        for row in reader:
            total += 1
            msg = (row.get(MSG_COL) or "")
            msg_lower = msg.lower()

            # Find which keywords matched in this row
            matched = [kw for kw, kw_l in zip(KEYWORDS, keywords_lower) if kw_l in msg_lower]

            # Only keep rows with at least one match
            if matched:
                # Join matched keywords as a comma-separated string in the new column
                row[NEW_MATCHES_COL] = ", ".join(matched)

                # Write full row with all original columns plus the new column
                writer.writerow(row)
                kept += 1

            if total % 1000 == 0:
                print(f"[progress] processed {total} rows (kept {kept})")

    print(f"[done] processed {total} rows, kept {kept} rows.")
    print(f"[done] output saved to {output_path}")


if __name__ == "__main__":
    main()