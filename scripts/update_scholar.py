# scripts/update_scholar.py
import os, re, sys, html
from datetime import datetime

# pip install scholarly
from scholarly import scholarly

README_PATH = os.getenv("README_PATH", "README.md")
SCHOLAR_URL  = os.getenv("SCHOLAR_PROFILE_URL", "").strip()
SCHOLAR_USER = os.getenv("SCHOLAR_USER_ID", "").strip()
MAX_ITEMS = int(os.getenv("SCHOLAR_MAX_ITEMS", "5"))

START = "<!-- SCHOLAR:START -->"
END = "<!-- SCHOLAR:END -->"

def extract_user_from_url(url: str) -> str:
    # e.g. https://scholar.google.com/citations?user=ABCDEFG&hl=en
    m = re.search(r"[?&]user=([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else ""

def get_author(user_id: str):
    try:
        author = scholarly.search_author_id(user_id)
        return scholarly.fill(author, sections=["publications"])
    except Exception as e:
        print(f"[warn] author fetch failed: {e}")
        return None

def coalesce_pub_url(pub):
    url = pub.get("pub_url")
    if url:
        return url
    title = pub.get("bib", {}).get("title", "")
    q = re.sub(r"\s+", "+", title)
    return f"https://scholar.google.com/scholar?q={q}"

def build_table(author, max_items=5):
    pubs = author.get("publications", [])
    rows = []

    # 정렬 우선순위: 최신 연도 ↓, 같은 연도면 citation ↓
    def sort_key(p):
        bib = p.get("bib", {})
        year = bib.get("pub_year") or bib.get("year") or -1
        try:
            year = int(year)
        except Exception:
            year = -1
        cites = p.get("num_citations", 0)
        return (-year, -cites)

    pubs_sorted = sorted(pubs, key=sort_key)[:max_items]

    for p in pubs_sorted:
        bib = p.get("bib", {})
        title = bib.get("title", "Untitled")
        year = bib.get("pub_year") or bib.get("year") or ""
        venue = bib.get("venue") or bib.get("journal") or bib.get("publisher") or ""
        authors = bib.get("author", "")
        url = coalesce_pub_url(p)
        cites = p.get("num_citations", 0)

        title = html.escape(title)
        venue = html.escape(venue)
        authors = html.escape(authors)

        rows.append(
            f"| **{title}** | {authors} | {venue} | {year} | {cites} | [link]({url}) |"
        )

    header = "| Title | Authors | Venue | Year | Citations | Link |\n|---|---|---|---:|---:|---|"
    return header + "\n" + "\n".join(rows) if rows else "_No publications found_"

def main():
    user_id = SCHOLAR_USER or extract_user_from_url(SCHOLAR_URL)
    if not user_id:
        print("❌ Set SCHOLAR_USER_ID or SCHOLAR_PROFILE_URL env.")
        sys.exit(1)

    author = get_author(user_id)
    if not author:
        print("❌ Failed to load author.")
        sys.exit(1)

    table_md = build_table(author, MAX_ITEMS)
    with open(README_PATH, "r", encoding="utf-8") as f:
        md = f.read()

    if START not in md or END not in md:
        print(f"❌ Place {START} ... {END} markers in README.md")
        sys.exit(1)

    new = re.sub(
        rf"{re.escape(START)}[\s\S]*?{re.escape(END)}",
        f"{START}\n{table_md}\n{END}",
        md,
    )

    if new != md:
        with open(README_PATH, "w", encoding="utf-8") as f:
            f.write(new)
        print("✅ README updated.")
    else:
        print("ℹ️ No changes.")

if __name__ == "__main__":
    main()
