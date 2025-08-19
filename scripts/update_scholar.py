# scripts/update_scholar.py
import os, re, sys, html, time
from datetime import datetime
from scholarly import scholarly

README_PATH   = os.getenv("README_PATH", "README.md")
SCHOLAR_URL   = os.getenv("SCHOLAR_PROFILE_URL", "").strip()
SCHOLAR_USER  = os.getenv("SCHOLAR_USER_ID", "").strip()
MAX_ITEMS     = int(os.getenv("SCHOLAR_MAX_ITEMS", "6"))
OUTPUT_STYLE  = os.getenv("SCHOLAR_OUTPUT_STYLE", "table").lower()  # "table" or "list"

START = "<!-- SCHOLAR:START -->"
END   = "<!-- SCHOLAR:END -->"

def extract_user_from_url(url: str) -> str:
    m = re.search(r"[?&]user=([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else ""

def get_author(user_id: str, retry=2, delay=2):
    last_err = None
    for _ in range(retry + 1):
        try:
            author = scholarly.search_author_id(user_id)
            return scholarly.fill(author, sections=["publications"])
        except Exception as e:
            last_err = e
            time.sleep(delay)
    print(f"[warn] author fetch failed: {last_err}")
    return None

def coalesce_pub_url(pub: dict) -> str:
    url = pub.get("pub_url")
    if url:
        return url
    title = pub.get("bib", {}).get("title", "")
    q = re.sub(r"\s+", "+", title.strip())
    return f"https://scholar.google.com/scholar?q={q}"

def sort_key(p):
    bib = p.get("bib", {})
    year = bib.get("pub_year") or bib.get("year") or -1
    try:
        year = int(year)
    except Exception:
        year = -1
    cites = p.get("num_citations", 0) or 0
    return (year, cites)

def format_authors(bib_author_field: str) -> str:
    if not bib_author_field:
        return ""
    authors = [author.strip() for author in bib_author_field.split("and")]
    if len(authors) == 1:
        return html.escape(authors[0]).replace(" ", "&nbsp;")
    return f"{html.escape(authors[0]).replace(' ', '&nbsp;')} *et&nbsp;al.*"

def make_table(rows: list) -> str:
    header = "| Title | Authors | Year | Citations |\n|:---|:---:|:---:|:---:|"
    return header + "\n" + "\n".join(rows) if rows else "_No publications found_"

def make_list(rows: list) -> str:
    return "\n".join(f"- {r}" for r in rows) if rows else "_No publications found_"

def build_block(author: dict, max_items: int = 6, output_style: str = "table") -> str:
    pubs = author.get("publications", [])
    pubs_sorted = sorted(pubs, key=sort_key, reverse=True)[:max_items]

    if output_style == "list":
        items = []
        for p in pubs_sorted:
            bib = p.get("bib", {})
            title = html.escape(bib.get("title", "Untitled"))
            year  = bib.get("pub_year") or bib.get("year") or "n.d."
            authors = format_authors(bib.get("author", ""))
            cites = p.get("num_citations", 0) or 0
            url = coalesce_pub_url(p)
            # "Title(🔗) + Author(First author et al.) + Year + Citations"
            items.append(f"[**{title}**]({url}) • {authors} • {year} • Citations: {cites}")
        return make_list(items)

    # default: table
    rows = []
    for p in pubs_sorted:
        scholarly.fill(p)
        bib = p.get("bib", {})
        title = html.escape(bib.get("title", "Untitled"))
        year  = bib.get("pub_year") or bib.get("year") or "n.d."
        authors = format_authors(bib.get("author", ""))
        cites = p.get("num_citations", 0) or 0
        url = coalesce_pub_url(p)
        rows.append(f"| [**{title}**]({url}) | {authors} | {year} | {cites} |")
    return make_table(rows)

def main():
    user_id = SCHOLAR_USER or extract_user_from_url(SCHOLAR_URL)
    if not user_id:
        print("❌ Set SCHOLAR_USER_ID or SCHOLAR_PROFILE_URL env.")
        sys.exit(1)

    author = get_author(user_id)
    if not author:
        print("❌ Failed to load author.")
        sys.exit(1)

    block_md = build_block(author, MAX_ITEMS, OUTPUT_STYLE)
    with open(README_PATH, "r", encoding="utf-8") as f:
        md = f.read()

    if START not in md or END not in md:
        print(f"❌ Place {START} ... {END} markers in README.md")
        sys.exit(1)

    new = re.sub(
        rf"{re.escape(START)}[\s\S]*?{re.escape(END)}",
        f"{START}\n{block_md}\n{END}",
        md,
    )

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(new)
    print("✅ README updated.")

if __name__ == "__main__":
    main()
