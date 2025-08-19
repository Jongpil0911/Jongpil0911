# # scripts/update_scholar.py
# import os, re, sys, html, time
# from datetime import datetime
# from scholarly import scholarly

# README_PATH   = os.getenv("README_PATH", "README.md")
# SCHOLAR_URL   = os.getenv("SCHOLAR_PROFILE_URL", "").strip()
# SCHOLAR_USER  = os.getenv("SCHOLAR_USER_ID", "").strip()
# MAX_ITEMS     = int(os.getenv("SCHOLAR_MAX_ITEMS", "6"))
# OUTPUT_STYLE  = os.getenv("SCHOLAR_OUTPUT_STYLE", "table").lower()  # "table" or "list"

# START = "<!-- SCHOLAR:START -->"
# END   = "<!-- SCHOLAR:END -->"

# def extract_user_from_url(url: str) -> str:
#     m = re.search(r"[?&]user=([A-Za-z0-9_-]+)", url)
#     return m.group(1) if m else ""

# def get_author(user_id: str, retry=2, delay=2):
#     last_err = None
#     for _ in range(retry + 1):
#         try:
#             author = scholarly.search_author_id(user_id)
#             return scholarly.fill(author, sections=["publications"])
#         except Exception as e:
#             last_err = e
#             time.sleep(delay)
#     print(f"[warn] author fetch failed: {last_err}")
#     return None

# def coalesce_pub_url(pub: dict) -> str:
#     url = pub.get("pub_url")
#     if url:
#         return url
#     title = pub.get("bib", {}).get("title", "")
#     q = re.sub(r"\s+", "+", title.strip())
#     return f"https://scholar.google.com/scholar?q={q}"

# def sort_key(p):
#     bib = p.get("bib", {})
#     year = bib.get("pub_year") or bib.get("year") or -1
#     try:
#         year = int(year)
#     except Exception:
#         year = -1
#     cites = p.get("num_citations", 0) or 0
#     return (year, cites)

# def format_authors(bib_author_field: str) -> str:
#     if not bib_author_field:
#         return ""
#     authors = [author.strip() for author in bib_author_field.split("and")]
#     if len(authors) == 1:
#         return html.escape(authors[0]).replace(" ", "&nbsp;")
#     return f"{html.escape(authors[0]).replace(' ', '&nbsp;')}&nbsp;et&nbsp;al."

# def make_table(rows: list) -> str:
#     header = "| Title | Authors | Year | Citations |\n|:---:|:---:|:---:|:---:|"
#     return header + "\n" + "\n".join(rows) if rows else "_No publications found_"

# def make_list(rows: list) -> str:
#     return "\n".join(f"- {r}" for r in rows) if rows else "_No publications found_"

# def build_block(author: dict, max_items: int = 6, output_style: str = "table") -> str:
#     pubs = author.get("publications", [])
#     pubs_sorted = sorted(pubs, key=sort_key, reverse=True)[:max_items]

#     if output_style == "list":
#         items = []
#         for p in pubs_sorted:
#             bib = p.get("bib", {})
#             title = html.escape(bib.get("title", "Untitled"))
#             year  = bib.get("pub_year") or bib.get("year") or "n.d."
#             authors = format_authors(bib.get("author", ""))
#             cites = p.get("num_citations", 0) or 0
#             url = coalesce_pub_url(p)
#             # "Title(🔗) + Author(First author et al.) + Year + Citations"
#             items.append(f"[**{title}**]({url}) • {authors} • {year} • Citations: {cites}")
#         return make_list(items)

#     # default: table
#     rows = []
#     for p in pubs_sorted:
#         scholarly.fill(p)
#         bib = p.get("bib", {})
#         title = html.escape(bib.get("title", "Untitled"))
#         year  = bib.get("pub_year") or bib.get("year") or "n.d."
#         authors = format_authors(bib.get("author", ""))
#         cites = p.get("num_citations", 0) or 0
#         url = coalesce_pub_url(p)
#         rows.append(f"| <div align='left'>[**{title}**]({url})</div> | {authors} | {year} | {cites} |")
#     return make_table(rows)

# def main():
#     user_id = SCHOLAR_USER or extract_user_from_url(SCHOLAR_URL)
#     if not user_id:
#         print("❌ Set SCHOLAR_USER_ID or SCHOLAR_PROFILE_URL env.")
#         sys.exit(1)

#     author = get_author(user_id)
#     if not author:
#         print("❌ Failed to load author.")
#         sys.exit(1)

#     block_md = build_block(author, MAX_ITEMS, OUTPUT_STYLE)
#     with open(README_PATH, "r", encoding="utf-8") as f:
#         md = f.read()

#     if START not in md or END not in md:
#         print(f"❌ Place {START} ... {END} markers in README.md")
#         sys.exit(1)

#     new = re.sub(
#         rf"{re.escape(START)}[\s\S]*?{re.escape(END)}",
#         f"{START}\n{block_md}\n{END}",
#         md,
#     )

#     with open(README_PATH, "w", encoding="utf-8") as f:
#         f.write(new)
#     print("✅ README updated.")

# if __name__ == "__main__":
#     main()




# scripts/update_scholar.py
import os, re, sys, html, time, concurrent.futures as cf

README_PATH   = os.getenv("README_PATH", "README.md")
SCHOLAR_URL   = os.getenv("SCHOLAR_PROFILE_URL", "").strip()
SCHOLAR_USER  = os.getenv("SCHOLAR_USER_ID", "").strip()
MAX_ITEMS     = int(os.getenv("SCHOLAR_MAX_ITEMS", "6"))
OUTPUT_STYLE  = os.getenv("SCHOLAR_OUTPUT_STYLE", "table").lower()  # "table" or "list"
ALLOW_SERPAPI_FALLBACK = os.getenv("ALLOW_SERPAPI_FALLBACK", "false").lower() == "true"

# 타임아웃(초) 환경변수로 조정 가능
AUTHOR_TIMEOUT = int(os.getenv("SCHOLAR_AUTHOR_TIMEOUT", "12"))
PUB_TIMEOUT    = int(os.getenv("SCHOLAR_PUB_TIMEOUT", "4"))

START = "<!-- SCHOLAR:START -->"
END   = "<!-- SCHOLAR:END -->"

# 헤더: Title만 왼쪽(:---), 나머지 가운데(:---:)
HEADER = "| Title | Authors | Year | Citations |\n|:---|:---:|:---:|:---:|"

def extract_user_from_url(url: str) -> str:
    m = re.search(r"[?&]user=([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else ""

def coalesce_pub_url_by_title(title: str) -> str:
    q = re.sub(r"\s+", "+", (title or "").strip())
    return f"https://scholar.google.com/scholar?q={q}"

def format_authors(bib_author_field: str) -> str:
    """첫 저자만 + 줄바꿈 방지(&nbsp;)"""
    if not bib_author_field:
        return ""
    parts = [p.strip() for p in bib_author_field.split(",")]
    if len(parts) >= 2:
        first_author = f"{parts[1]} {parts[0]}"  # 이름 성
    else:
        first_author = parts[0]
    first_author = html.escape(first_author)
    return f"{first_author}&nbsp;et&nbsp;al."

def sort_key_generic(year, cites):
    try:
        y = int(year)
    except Exception:
        y = -1
    try:
        c = int(cites or 0)
    except Exception:
        c = 0
    return (y, c)

def make_table(rows):
    return HEADER + "\n" + "\n".join(rows) if rows else "_No publications found_"

def make_list(items):
    return "\n".join(f"- {it}" for it in items) if items else "_No publications found_"

def render_items(items, output_style):
    if output_style == "list":
        lines = []
        for it in items:
            lines.append(f"[**{it['title']}**]({it['url']}) • {it['authors']} • {it['year']} • Citations: {it['cites']}")
        return make_list(lines)
    rows = [f"| <div align='left'>[**{it['title']}**]({it['url']})</div> | {it['authors']} | {it['year']} | {it['cites']} |"
            for it in items]
    return make_table(rows)

# ---------- scholarly with timeouts ----------
def try_scholarly(user_id: str, max_items: int):
    try:
        from scholarly import scholarly
    except Exception as e:
        print(f"[info] scholarly import failed: {e}")
        return None

    def _search_and_fill_author(uid):
        author = scholarly.search_author_id(uid)
        return scholarly.fill(author, sections=["publications"])

    # 저자 단위 타임아웃
    with cf.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_search_and_fill_author, user_id)
        try:
            author = fut.result(timeout=AUTHOR_TIMEOUT)
        except Exception as e:
            print(f"[warn] scholarly author timeout/fail: {e}")
            return None

    pubs = author.get("publications", [])
    if not pubs:
        return None

    # 과도한 상세조회 방지: 상위 N*3개만 샘플링
    slice_cnt = min(len(pubs), max_items * 3)
    pubs = pubs[:slice_cnt]

    items = []

    def _fill_one(p):
        try:
            return scholarly.fill(p)
        except Exception:
            return None

    # 각 논문 fill 타임아웃 적용 병렬 처리
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        futures = [ex.submit(_fill_one, p) for p in pubs]
        for fut in cf.as_completed(futures, timeout=max(10, PUB_TIMEOUT * slice_cnt)):
            try:
                p2 = fut.result(timeout=0)  # 이미 as_completed
            except Exception:
                p2 = None
            if not p2:
                continue
            bib = p2.get("bib", {})
            title = html.escape(bib.get("title", "Untitled"))
            year  = bib.get("pub_year") or bib.get("year") or "n.d."
            authors = format_authors(bib.get("author", ""))
            cites = p2.get("num_citations", 0) or 0
            url = p2.get("pub_url") or coalesce_pub_url_by_title(bib.get("title", ""))
            items.append({"title": title, "year": year, "authors": authors, "cites": cites, "url": url})
            if len(items) >= max_items * 2:  # 충분히 모였으면 조기 종료
                break

    if not items:
        return None

    items.sort(key=lambda x: sort_key_generic(x["year"], x["cites"]), reverse=True)
    return items[:max_items]

# ---------- SerpAPI fallback (Google Scholar Author 엔진) ----------
def try_serpapi(user_id: str, max_items: int):
    if not ALLOW_SERPAPI_FALLBACK:
        print("[info] SerpAPI fallback disabled.")
        return None

    key = os.getenv("SERPAPI_KEY", "").strip()
    if not key:
        print("[info] SERPAPI_KEY not set; skipping SerpAPI fallback.")
        return None

    try:
        from serpapi import GoogleSearch
    except Exception as e:
        print(f"[info] serpapi import failed: {e}")
        return None

    try:
        params = {
            "engine": "google_scholar_author",  # Scholar만 조회
            "author_id": user_id,
            "api_key": key,
            "hl": "en",
            "num": "100",
        }
        data = GoogleSearch(params).get_dict()
        articles = data.get("articles", []) or []

        items = []
        for a in articles:
            title = html.escape(a.get("title", "Untitled"))
            link  = a.get("link") or coalesce_pub_url_by_title(a.get("title", ""))
            year  = a.get("year") or "n.d."

            authors_raw = a.get("authors")
            if isinstance(authors_raw, list) and authors_raw:
                authors_str = ", ".join([str(x) for x in authors_raw])
            else:
                authors_str = str(authors_raw or "")
            authors = format_authors(authors_str)

            cites = 0
            if isinstance(a.get("cited_by"), dict):
                cites = a["cited_by"].get("value", 0) or 0

            items.append({"title": title, "year": year, "authors": authors, "cites": cites, "url": link})

        items.sort(key=lambda x: sort_key_generic(x["year"], x["cites"]), reverse=True)
        return items[:max_items]
    except Exception as e:
        print(f"[warn] SerpAPI fetch failed: {e}")
        return None

def build_block(user_id: str):
    items = try_scholarly(user_id, MAX_ITEMS)
    if not items:
        print("[info] Falling back to SerpAPI…")
        items = try_serpapi(user_id, MAX_ITEMS)
    if not items:
        return "_No publications found_"
    return render_items(items, OUTPUT_STYLE)

def main():
    user_id = SCHOLAR_USER or extract_user_from_url(SCHOLAR_URL)
    if not user_id:
        print("❌ Set SCHOLAR_USER_ID or SCHOLAR_PROFILE_URL env.")
        sys.exit(1)

    block_md = build_block(user_id)

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
    if new != md:
        with open(README_PATH, "w", encoding="utf-8") as f:
            f.write(new)
        print("✅ README updated.")
    else:
        print("ℹ️ No changes.")

if __name__ == "__main__":
    main()
