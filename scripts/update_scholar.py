# scripts/update_scholar.py
import os, re, sys, html, time, concurrent.futures as cf

# ---- 기본 설정 (로컬 테스트용 기본값 포함) ----
SCHOLAR_URL  = os.getenv("SCHOLAR_PROFILE_URL", "https://scholar.google.com/citations?user=O-3pYeQAAAAJ&hl=en").strip()
SCHOLAR_USER = os.getenv("SCHOLAR_USER_ID", "O-3pYeQAAAAJ").strip()

README_PATH  = os.getenv("README_PATH", "README.md")
MAX_ITEMS    = int(os.getenv("SCHOLAR_MAX_ITEMS", "5"))
OUTPUT_STYLE = os.getenv("SCHOLAR_OUTPUT_STYLE", "table").lower()        # "table" or "list"
ALLOW_SERPAPI_FALLBACK = os.getenv("ALLOW_SERPAPI_FALLBACK", "false").lower() == "true"

AUTHOR_TIMEOUT = int(os.getenv("SCHOLAR_AUTHOR_TIMEOUT", "12"))
PUB_TIMEOUT    = int(os.getenv("SCHOLAR_PUB_TIMEOUT", "4"))

START = "<!-- SCHOLAR:START -->"
END   = "<!-- SCHOLAR:END -->"

# 5열(Title / Authors / Year / Publisher / Citations) 고정
HEADER = "| Title | Authors | Year | Publisher | Citations |\n|:---:|:---:|:---:|:---:|:---:|"

# ---- 유틸 ----
def extract_user_from_url(url: str) -> str:
    m = re.search(r"[?&]user=([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else ""

def coalesce_pub_url_by_title(title: str) -> str:
    q = re.sub(r"\s+", "+", (title or "").strip())
    return f"https://scholar.google.com/scholar?q={q}"

def format_authors(bib_author_field: str) -> str:
    """
    첫 저자만 + 'et al.' , 줄바꿈 방지.
    Scholar는 'A and B and C' 또는 'A, B, C' 둘 다 가능 → 모두 처리
    """
    if not bib_author_field:
        return ""
    parts = [p.strip() for p in re.split(r'\s*(?:,| and )\s*', bib_author_field) if p.strip()]
    if not parts:
        return ""
    first = html.escape(parts[0]).replace(" ", "&nbsp;")  # 공백 비분리
    return f"<span style='white-space:nowrap;'>{first}&nbsp;et&nbsp;al.</span>" if len(parts) > 1 \
           else f"<span style='white-space:nowrap;'>{first}</span>"
           
def normalize_publisher(raw: str) -> str:
    """원문 venue/journal/publisher 문자열을 IEEE/SPIE/Optica 중 하나로 정규화."""
    s = (raw or "").lower()
    print(raw)

    # IEEE 계열 키워드
    ieee_keys = [
        "ieee", "trans.", "transactions on", "journal of ieee",
        "ieee access", "access"
    ]

    # SPIE 계열 키워드
    spie_keys = [
        "spie", "proc. spie", "proceedings of spie"
    ]

    # Optica(구 OSA) 계열 키워드
    optica_keys = [
        "optica", "osa", "optics express", "optics letters",
        "applied optics", "biomedical optics", "boe", "ol", "oe"
    ]
    
    # MDPI 계열 
    mdpi_keys = [
        "mdpi", "sensors", "applied sciences", "remote sensing",
        "micromachines", "electronics", "symmetry", "materials",
        "energies", "coatings"
    ]
    
    if any(k in s for k in ieee_keys):
        return "IEEE"
    if any(k in s for k in spie_keys):
        return "SPIE"
    if any(k in s for k in optica_keys):
        return "Optica"
    if any(k in s for k in mdpi_keys):
        return "MDPI"
    return "-"  # 세 분류에 안 걸리면 대시로

def sort_key_generic(year, cites):
    try: y = int(year)
    except: y = -1
    try: c = int(cites or 0)
    except: c = 0
    # 최신연도 ↓, 같은 연도면 인용수 ↓
    return (y, c)

def make_table(rows):
    return HEADER + "\n" + "\n".join(rows) if rows else "_No publications found_"

def make_list(items):
    return "\n".join(f"- {it}" for it in items) if items else "_No publications found_"

def render_items(items, output_style):
    if output_style == "list":
        lines = []
        for it in items:
            lines.append(
                f"[**{it['title']}**]({it['url']}) • {it['authors']} • {it['year']} • {it.get('publisher','-')} • Citations: {it['cites']}"
            )
        return make_list(lines)

    # table: Title은 줄바꿈 허용, Authors는 줄바꿈 금지
    rows = [
        f"| <div align='left' style='white-space:normal;'>[**{it['title']}**]({it['url']})</div> "
        f"| {it['authors']} "
        f"| {it['year']} "
        f"| {html.escape(it.get('publisher','-'))} "
        f"| {it['cites']} |"
        for it in items
    ]
    return make_table(rows)

# ---- scholarly 경로 ----
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

    # 과도한 상세조회 방지: 상위 N*3개만
    slice_cnt = min(len(pubs), max_items * 3)
    pubs = pubs[:slice_cnt]

    items = []

    def _fill_one(p):
        try:
            return scholarly.fill(p)
        except Exception:
            return None

    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        futures = [ex.submit(_fill_one, p) for p in pubs]
        for fut in cf.as_completed(futures, timeout=max(10, PUB_TIMEOUT * slice_cnt)):
            try:
                p2 = fut.result(timeout=0)
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

            # 🔸 publisher/venue 추출 (가능한 필드 우선순위)
            # publisher = bib.get("venue") or bib.get("journal") or bib.get("publisher") or ""
            raw_pub   = " ".join(filter(None, [bib.get("venue",""), bib.get("journal",""), bib.get("publisher","")])).strip()
            publisher = normalize_publisher(raw_pub)

            items.append({
                "title": title, "url": url, "authors": authors,
                "year": year, "cites": cites, "publisher": publisher
            })
            if len(items) >= max_items * 2:
                break

    if not items:
        return None

    items.sort(key=lambda x: sort_key_generic(x["year"], x["cites"]), reverse=True)
    return items[:max_items]

# ---- SerpAPI 백업 경로 ----
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
            "engine": "google_scholar_author",
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

            # serpapi 응답에선 venue/journal이 없을 수 있음 → '-'
            # publisher = a.get("publication") or a.get("journal") or "-"
            raw_pub   = " ".join(filter(None, [a.get("publication",""), a.get("journal","")])).strip()
            publisher = normalize_publisher(raw_pub)
            
            items.append({
                "title": title, "url": link, "authors": authors,
                "year": year, "cites": cites, "publisher": publisher
            })

        items.sort(key=lambda x: sort_key_generic(x["year"], x["cites"]), reverse=True)
        return items[:max_items]
    except Exception as e:
        print(f"[warn] SerpAPI fetch failed: {e}")
        return None

# ---- 빌드/갱신 ----
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