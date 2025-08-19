# scripts/update_scholar.py
import os, re, sys, html
from scholarly import scholarly

README_PATH  = os.getenv("README_PATH", "README.md")

# 🔧 Secrets/환경변수에서 값 읽기
SCHOLAR_URL  = os.getenv("SCHOLAR_PROFILE_URL", "").strip()   # 전체 URL을 넣는 경우 (선택)
SCHOLAR_USER = os.getenv("SCHOLAR_USER_ID", "").strip()       # user ID만 넣는 경우 (권장)

MAX_ITEMS    = int(os.getenv("SCHOLAR_MAX_ITEMS", "5"))

START = "<!-- SCHOLAR:START -->"
END   = "<!-- SCHOLAR:END -->"

def extract_user_from_url(url: str) -> str:
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
    def year_of(p):
        y = p.get("bib", {}).get("pub_year") or p.get("bib", {}).get("year")
        try: return int(y)
        except: return -1

    pubs_sorted = sorted(pubs, key=year_of, reverse=True)[:max_items]
    rows = []
    for p in pubs_sorted:
        bib = p.get("bib", {})
        title   = html.escape(bib.get("title", "Untitled"))
        year    = bib.get("pub_year") or bib.get("year") or ""
        venue   = html.escape(bib.get("venue") or bib.get("journal") or bib.get("publisher") or "")
        authors = html.escape(bib.get("author", ""))
        url     = coalesce_pub_url(p)
        rows.append(f"| **{title}** | {authors} | {venue} | {year} | [link]({url}) |")

    header = "| Title | Authors | Venue | Year | Link |\n|---|---|---|---:|---|"
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

    new = re.sub(rf"{re.escape(START)}[\s\S]*?{re.escape(END)}",
                 f"{START}\n{table_md}\n{END}", md)

    if new != md:
        with open(README_PATH, "w", encoding="utf-8") as f:
            f.write(new)
        print("✅ README updated.")
    else:
        print("ℹ️ No changes.")

if __name__ == "__main__":
    main()
