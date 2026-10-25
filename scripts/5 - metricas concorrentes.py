# -*- coding: utf-8 -*-
"""Metricas de canais dos top concorrentes Alto.

Fluxo MVP:
1. Le o XLSX nacional de concorrentes ja gerado
2. Pega top 5 concorrentes com similaridade Alto
3. Reaproveita SEO/Trafego do XLSX nacional
4. Busca Meta Ads via ScrapingBee + GraphQL da Ad Library
5. Busca Google Ads na Transparency por dominio (region=anywhere)
6. Busca LinkedIn Ads via ScrapingBee (accountOwner na Ad Library)
7. Extrai links sociais da homepage e tenta ler seguidores
8. Gera XLSX + HTML com aba "Metricas Canais"

Uso:
    python "5 - metricas concorrentes.py" chatguru
    python "5 - metricas concorrentes.py" chatguru google_ads
    python "5 - metricas concorrentes.py" chatguru seo
    python "5 - metricas concorrentes.py" chatguru brand
    python "5 - metricas concorrentes.py" chatguru full
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

try:
    from market import (
        LOCATION_CODE as LOCATION_BRAZIL,
        SEMRUSH_DB,
        LANGUAGE_CODE as _MKT_LANG,
        SCRAPINGBEE_COUNTRY,
        META_COUNTRY,
        ACCEPT_LANGUAGE,
    )
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from market import (
        LOCATION_CODE as LOCATION_BRAZIL,
        SEMRUSH_DB,
        LANGUAGE_CODE as _MKT_LANG,
        SCRAPINGBEE_COUNTRY,
        META_COUNTRY,
        ACCEPT_LANGUAGE,
    )

from urllib.parse import quote_plus, unquote, urlparse

import openpyxl
import requests
from bs4 import BeautifulSoup
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

FINAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(FINAL_DIR))

from workspace_paths import (  # noqa: E402
    CONC_DIR,
    MVP_DIR,
    OUT_CONCORRENTES,
    OUT_METRICAS,
    setup_workspace,
)

for p in (MVP_DIR, CONC_DIR, FINAL_DIR):
    if p and p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))
if str(FINAL_DIR) in sys.path:
    sys.path.remove(str(FINAL_DIR))
sys.path.insert(0, str(FINAL_DIR))

setup_workspace()

from find_concorrentes import (  # noqa: E402
    find_client_xlsx,
    read_briefing_from_xlsx,
    normalize_domain,
)
from gerar_html_concorrentes import generate_html_from_xlsx  # noqa: E402

NATIONAL_DIR = OUT_CONCORRENTES
OUTPUT_DIR = OUT_METRICAS
TOP_COMPETITORS = 10
HEADERS = {"User-Agent": "Mozilla/5.0"}
SCRAPINGBEE_API_KEY = os.environ.get("SCRAPINGBEE_API_KEY", "").strip()
SCRAPINGBEE_URL = "https://app.scrapingbee.com/api/v1/"
META_DOC_ID_TYPEAHEAD = "9755915494515334"
META_DOC_ID_ADS_COUNT = "25863916039859122"
LINKEDIN_AD_LIBRARY_BASE = "https://www.linkedin.com/ad-library/search"

HEAD_FONT = Font(bold=True, color="FFFFFF")
HEAD_FILL = PatternFill(start_color="0F766E", end_color="0F766E", fill_type="solid")
THIN = Side(style="thin", color="CBD5E1")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
FILL_SIM = {
    "Alto": PatternFill(start_color="D1FAE5", end_color="D1FAE5", fill_type="solid"),
    "Medio": PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid"),
    "Baixo": PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid"),
}
FILL_PERFIL = {
    "Especialista": PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid"),
    "Generalista": PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid"),
}


def slugify_client(client_input: str) -> str:
    raw = client_input.strip().lower()
    raw = raw.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]
    return re.sub(r"[^a-z0-9]+", "", raw.split(".")[0])


def fold(value: str) -> str:
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = s.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", s).strip().lower()


def compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", fold(value))


def ascii_text(value: str) -> str:
    return unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")


def domain_token(domain: str) -> str:
    d = normalize_domain(domain)
    d = d.replace(".com.br", "").replace(".com", "").replace(".br", "")
    d = d.replace(".net", "").replace(".org", "").replace(".io", "").replace(".ai", "")
    return compact(d)


def root_url(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = parsed.netloc or parsed.path
    return f"{parsed.scheme or 'https'}://{host}/" if host else raw


def extract_website_name(url: str) -> str:
    parsed = urlparse(root_url(url))
    host = parsed.netloc or parsed.path
    if host.startswith("www."):
        host = host[4:]
    return host.split(".")[0].strip().lower()


def normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def social_search_label(site_url: str, company_name: str = "") -> str:
    if company_name:
        return company_name.strip()
    host = urlparse(root_url(site_url)).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.endswith(".com.br"):
        host = host[:-7]
    elif host.endswith(".com"):
        host = host[:-4]
    return re.sub(r"[^a-z0-9]+", " ", host).strip()


def _extract_google_result_urls(html_text: str) -> list[str]:
    urls = []
    seen = set()
    for raw in re.findall(r'href="/url\\?q=([^"&]+)[^"]*"', html_text or ""):
        url = unquote(raw)
        dom = normalize_domain(url)
        if not dom or dom.endswith("google.com") or dom.endswith("google.com.br"):
            continue
        if url not in seen:
            seen.add(url)
            urls.append(url)
    for raw in re.findall(r'https?://[^\\s"<>]+', html_text or ""):
        if "google." in raw:
            continue
        clean = raw.rstrip(').,\'"')
        dom = normalize_domain(clean)
        if not dom:
            continue
        if clean not in seen:
            seen.add(clean)
            urls.append(clean)
    return urls


def company_query_for_competitor(comp: dict) -> str:
    """Nome legivel para LinkedIn/Meta: title > company > dominio."""
    for key in ("company", "name", "title"):
        title = re.split(r"[|\-–—:·•/]", str(comp.get(key, "") or ""))[0].strip()
        title = re.sub(r"\s+", " ", title)
        if len(title.split()) > 6:
            title = " ".join(title.split()[:4])
        title_fold = compact(title)
        if title and len(title_fold) >= 3 and not title.lower().startswith("http"):
            return title
    token = domain_token(comp.get("domain", ""))
    return token or comp.get("domain", "")


def parse_int(value) -> int | None:
    if value in (None, "", "—", "-", "Nao consultado"):
        return None
    raw = str(value).strip().replace(".", "").replace(",", "")
    m = re.search(r"\d+", raw)
    if not m:
        return None
    try:
        return int(m.group(0))
    except ValueError:
        return None


def parse_human_number(value: str) -> int | None:
    s = str(value or "").strip().lower().replace("\xa0", " ").replace(" ", "")
    if not s:
        return None
    s = (
        s.replace("thousand", "k")
        .replace("million", "m")
        .replace("billion", "b")
    )
    m = re.search(r"(\d+(?:[.,]\d+)?)(mil|mi|k|m|b)?", s)
    if not m:
        return parse_int(value)
    raw_num = m.group(1)
    suf = m.group(2) or ""
    if not suf:
        digits = re.sub(r"\D+", "", raw_num)
        return int(digits) if digits else None
    # 80.8K is 80.8 × 1000, not 808 × 1000 (dot is decimal when a suffix is present)
    if "," in raw_num and "." in raw_num:
        if raw_num.rfind(",") > raw_num.rfind("."):
            num = float(raw_num.replace(".", "").replace(",", "."))
        else:
            num = float(raw_num.replace(",", ""))
    elif "," in raw_num:
        num = float(raw_num.replace(",", "."))
    else:
        num = float(raw_num)
    mult = 1
    if suf in ("k", "mil"):
        mult = 1_000
    elif suf in ("m", "mi"):
        mult = 1_000_000
    elif suf == "b":
        mult = 1_000_000_000
    return int(num * mult)


def load_sheet_rows(xlsx_path: Path, sheet_name: str) -> list[list[str]]:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    if sheet_name not in wb.sheetnames:
        wb.close()
        return []
    ws = wb[sheet_name]
    rows = []
    for row in ws.iter_rows(values_only=True):
        vals = []
        for cell in row:
            if cell is None:
                vals.append("")
            elif isinstance(cell, float) and cell == int(cell):
                vals.append(str(int(cell)))
            else:
                vals.append(str(cell).strip())
        rows.append(vals)
    wb.close()
    return rows


def find_national_xlsx(client_slug: str) -> Path:
    folder = NATIONAL_DIR / client_slug
    patterns = (
        f"concorrentes-all-{client_slug}-nacional.xlsx",
        f"concorrentes-all-{client_slug}*.xlsx",
    )
    for pattern in patterns:
        files = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            return files[0]
    raise FileNotFoundError(f"XLSX nacional nao encontrado em {folder}")


def load_top_alto_competitors(xlsx_path: Path, limit: int = TOP_COMPETITORS) -> list[dict]:
    rows = load_sheet_rows(xlsx_path, "Concorrentes Unificado")
    if not rows:
        return []
    headers = rows[0]
    idx = {h: i for i, h in enumerate(headers)}

    def cell(row: list[str], name: str) -> str:
        i = idx.get(name)
        return row[i] if i is not None and i < len(row) else ""

    altos: list[dict] = []
    medios: list[dict] = []
    user_added: list[dict] = []
    for row in rows[1:]:
        if not any(row):
            continue
        sim = (cell(row, "Similaridade") or "").strip()
        sim_norm = sim.lower().replace("é", "e")
        item = {
            "domain": normalize_domain(cell(row, "Dominio")),
            "url": cell(row, "URL"),
            "title": cell(row, "Titulo"),
            "similaridade": sim,
            "perfil": cell(row, "Perfil"),
            "fonte": cell(row, "Fonte"),
            "nicho": cell(row, "Nicho (LLM)"),
        }
        if not item["domain"]:
            continue
        fonte_l = (item["fonte"] or "").strip().lower()
        # Concorrentes do usuario (enrich) entram sempre, mesmo alem do top N
        if "usuario" in fonte_l or "user" in fonte_l:
            user_added.append(item)
            continue
        if sim_norm == "alto":
            altos.append(item)
        elif sim_norm == "medio":
            medios.append(item)

    out = altos[:limit]
    # Se faltam Altos, completa com Medio ate o limite (minimo util: 10)
    if len(out) < limit and medios:
        seen = {c["domain"] for c in out}
        for m in medios:
            if len(out) >= limit:
                break
            if m["domain"] in seen:
                continue
            out.append(m)
            seen.add(m["domain"])

    seen = {c["domain"] for c in out}
    for u in user_added:
        if u["domain"] in seen:
            continue
        out.append(u)
        seen.add(u["domain"])
    return out


def load_traffic_map(xlsx_path: Path) -> dict[str, dict]:
    rows = load_sheet_rows(xlsx_path, "Trafego SEO Marca")
    if len(rows) < 4:
        return {}
    headers = rows[2]
    idx = {h: i for i, h in enumerate(headers)}
    cur_seo = next((h for h in headers if h.startswith("SEO ")), "")
    cur_brand = next((h for h in headers if h.startswith("Marca ")), "")
    cur_total = next((h for h in headers if h.startswith("Total ")), "")
    out: dict[str, dict] = {}
    for row in rows[3:]:
        if not any(row):
            continue
        dom = normalize_domain(row[idx.get("Dominio", 1)])
        out[dom] = {
            "tipo": row[idx.get("Tipo", 0)],
            "perfil": row[idx.get("Perfil", 2)],
            "seo_atual": parse_int(row[idx.get(cur_seo, -1)]) if cur_seo in idx else None,
            "marca_atual": parse_int(row[idx.get(cur_brand, -1)]) if cur_brand in idx else None,
            "total_atual": parse_int(row[idx.get(cur_total, -1)]) if cur_total in idx else None,
            "cresc_seo_1a": row[idx.get("Cresc SEO 1a (%)", -1)] if "Cresc SEO 1a (%)" in idx else "",
            "cresc_seo_2a": row[idx.get("Cresc SEO 2a (%)", -1)] if "Cresc SEO 2a (%)" in idx else "",
            "cresc_seo_3a": row[idx.get("Cresc SEO 3a (%)", -1)] if "Cresc SEO 3a (%)" in idx else "",
            "cresc_marca_1a": row[idx.get("Cresc Marca 1a (%)", -1)] if "Cresc Marca 1a (%)" in idx else "",
            "cresc_marca_2a": row[idx.get("Cresc Marca 2a (%)", -1)] if "Cresc Marca 2a (%)" in idx else "",
            "cresc_marca_3a": row[idx.get("Cresc Marca 3a (%)", -1)] if "Cresc Marca 3a (%)" in idx else "",
        }
    return out


def build_client_entity(briefing: dict, traffic_map: dict[str, dict]) -> dict:
    dom = normalize_domain(briefing.get("url", ""))
    traffic = traffic_map.get(dom, {})
    title = (
        (briefing.get("cliente") or briefing.get("client") or briefing.get("empresa") or "")
        or (briefing.get("nicho_principal") and extract_website_name(briefing.get("url", "")))
        or extract_website_name(briefing.get("url", ""))
        or dom
    )
    return {
        "domain": dom,
        "url": root_url(briefing.get("url", "")),
        "title": str(title).strip() or dom,
        "company": str(title).strip() or dom,
        "similaridade": "Cliente",
        "perfil": traffic.get("perfil") or "—",
        "fonte": "Cliente",
        "nicho": briefing.get("nicho_principal") or briefing.get("nicho") or "",
    }


def _parse_meta_graphql_response(raw: str) -> dict | None:
    """Facebook GraphQL via ScrapingBee às vezes devolve 1+ linhas JSON."""
    text = (raw or "").strip()
    if not text:
        return None
    candidates = [text]
    # resposta multi-linha (comum no Ad Library)
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    if len(parts) > 1:
        candidates = [parts[1], parts[0]] + parts[2:]
    for chunk in candidates:
        for attempt in (chunk, chunk.replace('\\"', '"'), chunk.replace('\\"', "")):
            try:
                data = json.loads(attempt)
                if isinstance(data, dict):
                    return data
            except Exception:
                continue
    return None


def _meta_brand_query_variants(brand: str, domain: str = "", company_query: str = "") -> list[str]:
    """Search terms for Ad Library typeahead (order matters less — we score pages)."""
    brand = (brand or "").strip()
    domain = normalize_domain(domain or "")
    out: list[str] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        t = re.sub(r"\s+", " ", (term or "").strip())
        if not t:
            return
        key = t.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(t)

    _add(company_query)
    # aiapply -> "ai apply" (common compound brands)
    b = re.sub(r"[^a-z0-9]+", "", brand.lower())
    if b:
        _add(brand)
        m = re.match(r"^(ai)([a-z]{3,})$", b)
        if m:
            _add(f"{m.group(1)} {m.group(2)}")
        m = re.match(r"^([a-z]{3,})(ai)$", b)
        if m:
            _add(f"{m.group(1)} {m.group(2)}")
        # Camel-ish: jobRight already handled; try spaced token from domain host label
        spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", brand).strip()
        _add(spaced)
    if domain:
        _add(domain)
        _add(domain.split(".")[0])
    return out[:5]


def _score_meta_page(page: dict, *, brand: str, domain: str) -> float:
    """Higher = better match for this brand/domain (avoid random typeahead #1)."""
    if not page or page.get("page_is_deleted"):
        return -1e9
    brand_tok = normalize_token(brand)
    domain_full = normalize_domain(domain)
    domain_tok = normalize_token(extract_website_name(domain_full or brand))
    name_tok = normalize_token(page.get("name") or "")
    ig = str(page.get("ig_username") or "").strip().lower().lstrip("@")
    alias = str(page.get("page_alias") or "").strip().lower()
    ig_dom = normalize_domain(ig) if ig and "." in ig else ig
    alias_dom = normalize_domain(alias) if alias and "." in alias else alias

    score = 0.0
    # Strongest: IG handle / page alias equals the website domain
    if domain_full and ig_dom == domain_full:
        score += 120
    elif domain_tok and ig and normalize_token(ig) == domain_tok:
        score += 90
    if domain_full and alias_dom == domain_full:
        score += 100
    elif domain_tok and alias and normalize_token(alias) == domain_tok:
        score += 70

    if brand_tok and name_tok:
        if name_tok == brand_tok or name_tok == domain_tok:
            score += 55
        elif brand_tok in name_tok or name_tok in brand_tok:
            score += 35
        elif domain_tok and (domain_tok in name_tok or name_tok in domain_tok):
            score += 30
        else:
            # soft penalty for unrelated names (Aiapplyd vs aiapply)
            if len(name_tok) >= 4 and brand_tok and not (
                name_tok.startswith(brand_tok[:4]) or brand_tok.startswith(name_tok[:4])
            ):
                score -= 25

    likes = int(page.get("likes") or 0)
    ig_f = int(page.get("ig_followers") or 0)
    # Soft popularity boost; prefer real pages over 7-like stubs
    score += min(40.0, (likes ** 0.5) * 0.15 + (ig_f ** 0.5) * 0.08)
    if likes < 50 and ig_f < 200:
        score -= 30
    if str(page.get("verification") or "").upper() in ("VERIFIED", "BLUE_VERIFIED"):
        score += 10
    return score


def _meta_typeahead_pages(query: str) -> tuple[list[dict], int]:
    """Return Ad Library typeahead page_results for a query."""
    if not query:
        return [], 0
    params = {
        "api_key": SCRAPINGBEE_API_KEY,
        "url": "https://www.facebook.com/api/graphql/",
        "country_code": SCRAPINGBEE_COUNTRY,
    }
    data = {
        "variables": json.dumps({
            "queryString": query,
            "isMobile": False,
            "country": META_COUNTRY,
            "adType": "ALL",
        }, separators=(",", ":")),
        "doc_id": META_DOC_ID_TYPEAHEAD,
    }
    data_legacy = {
        "variables": (
            '{"queryString":"'
            + query.replace('"', "")
            + '","isMobile":false,"country":"'
            + META_COUNTRY
            + '","adType":"ALL"}'
        ),
        "doc_id": META_DOC_ID_TYPEAHEAD,
    }
    credits = 0
    for payload in (data_legacy, data):
        try:
            r = requests.post(SCRAPINGBEE_URL, params=params, data=payload, timeout=60)
            credits += int(r.headers.get("Spb-cost", 1) or 1)
            if r.status_code == 401:
                raise RuntimeError("ScrapingBee sem creditos (401) no Meta typeahead")
            r.raise_for_status()
            js = _parse_meta_graphql_response(r.text)
            if not js:
                continue
            pages = (
                ((js.get("data") or {}).get("ad_library_main") or {})
                .get("typeahead_suggestions", {})
                .get("page_results")
                or []
            )
            if pages:
                return list(pages), credits
        except RuntimeError:
            raise
        except Exception:
            continue
    return [], credits


def _meta_page_id_via_scrapingbee(query: str) -> tuple[str | None, int]:
    """Back-compat: best-effort first page for a single query (no brand scoring)."""
    pages, credits = _meta_typeahead_pages(query)
    if pages and pages[0].get("page_id"):
        return str(pages[0]["page_id"]), credits
    return None, credits


def _meta_ads_count_via_scrapingbee(page_id: str) -> tuple[int | None, int]:
    """Conta anuncios ACTIVE da pagina na Ad Library (US)."""
    params = {
        "api_key": SCRAPINGBEE_API_KEY,
        "url": "https://www.facebook.com/api/graphql/",
        "country_code": SCRAPINGBEE_COUNTRY,
        "premium_proxy": "true",
        "render_js": "false",
    }
    # country=ALL matches Ad Library links we expose (global active ads, not US-only)
    variables = (
        '{"activeStatus":"ACTIVE","adType":"ALL","audienceTimeframe":"LAST_7_DAYS",'
        '"bylines":[],"contentLanguages":[],"countries":["ALL"],"country":"ALL",'
        '"deeplinkAdID":null,"excludedIDs":[],"fetchPageInfo":true,"fetchSharedDisclaimers":true,'
        '"hasDeeplinkAdID":false,"isAboutTab":false,"isAudienceTab":false,"isLandingPage":false,'
        '"isTargetedCountry":false,"location":null,"mediaType":"ALL","multiCountryFilterMode":null,'
        '"pageIDs":[],"potentialReachInput":[],"publisherPlatforms":[],"queryString":"","regions":[],'
        '"searchType":"PAGE","shouldFetchCount":true,'
        '"sortData":{"mode":"SORT_BY_TOTAL_IMPRESSIONS","direction":"DESCENDING"},'
        '"source":null,"startDate":null,"viewAllPageID":"' + page_id + '"}'
    )
    data = {"variables": variables, "doc_id": META_DOC_ID_ADS_COUNT}
    credits = 0
    for attempt in range(2):
        try:
            r = requests.post(SCRAPINGBEE_URL, params=params, data=data, timeout=45)
            credits += int(r.headers.get("Spb-cost", 1) or 1)
            if r.status_code == 401:
                raise RuntimeError("ScrapingBee sem creditos (401) no Meta ads count")
            r.raise_for_status()
            js = _parse_meta_graphql_response(r.text)
            if not js:
                time.sleep(1.5 + attempt)
                continue
            if js.get("errors"):
                time.sleep(2 + attempt)
                continue
            count = (
                ((js.get("data") or {}).get("ad_library_main") or {})
                .get("search_results_connection", {})
                .get("count")
            )
            if count is None:
                return 0, credits
            return int(count), credits
        except RuntimeError:
            raise
        except Exception:
            time.sleep(1.5 + attempt)
    return None, credits


def _meta_keyword_library_url(query: str) -> str:
    q = quote_plus((query or "").strip())
    return (
        "https://www.facebook.com/ads/library/"
        f"?active_status=active&ad_type=all&country=ALL&is_targeted_country=false"
        f"&media_type=all&q={q}&search_type=keyword_unordered"
    )


def _meta_name_needles(brand: str, company_query: str = "", domain: str = "") -> list[str]:
    """Names to Ctrl+F on the Ad Library keyword results page (longest first)."""
    needles: list[str] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        t = re.sub(r"\s+", " ", (term or "").strip())
        if len(t) < 2:
            return
        key = t.lower()
        if key in seen:
            return
        seen.add(key)
        needles.append(t)

    _add(company_query)
    _add(brand)
    if domain:
        host = normalize_domain(domain)
        _add(host.split(".")[0] if host else "")
    # Prefer longer needles so "AI Apply" beats "AI"
    needles.sort(key=lambda s: (-len(s), s.lower()))
    return needles[:4]


def _count_name_occurrences(html: str, needle: str) -> int:
    """Case-insensitive substring count (browser Ctrl+F style)."""
    if not html or not needle:
        return 0
    # Drop scripts/styles noise so we approximate visible text better
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    return len(re.findall(re.escape(needle), text, flags=re.IGNORECASE))


def _meta_keyword_total_via_graphql(query: str) -> tuple[int | None, int]:
    """Unofficial total ACTIVE results for keyword search (Ad Library count)."""
    q = (query or "").replace("\\", " ").replace('"', "").strip()
    if not q:
        return None, 0
    params = {
        "api_key": SCRAPINGBEE_API_KEY,
        "url": "https://www.facebook.com/api/graphql/",
        "country_code": SCRAPINGBEE_COUNTRY,
        "premium_proxy": "true",
        "render_js": "false",
    }
    variables = (
        '{"activeStatus":"ACTIVE","adType":"ALL","audienceTimeframe":"LAST_7_DAYS",'
        '"bylines":[],"contentLanguages":[],"countries":["ALL"],"country":"ALL",'
        '"deeplinkAdID":null,"excludedIDs":[],"fetchPageInfo":true,"fetchSharedDisclaimers":true,'
        '"hasDeeplinkAdID":false,"isAboutTab":false,"isAudienceTab":false,"isLandingPage":false,'
        '"isTargetedCountry":false,"location":null,"mediaType":"ALL","multiCountryFilterMode":null,'
        '"pageIDs":[],"potentialReachInput":[],"publisherPlatforms":[],'
        f'"queryString":"{q}","regions":[],'
        '"searchType":"KEYWORD_UNORDERED","shouldFetchCount":true,'
        '"sortData":{"mode":"SORT_BY_TOTAL_IMPRESSIONS","direction":"DESCENDING"},'
        '"source":null,"startDate":null,"viewAllPageID":null}'
    )
    data = {"variables": variables, "doc_id": META_DOC_ID_ADS_COUNT}
    credits = 0
    for attempt in range(2):
        try:
            r = requests.post(SCRAPINGBEE_URL, params=params, data=data, timeout=45)
            credits += int(r.headers.get("Spb-cost", 1) or 1)
            if r.status_code == 401:
                raise RuntimeError("ScrapingBee sem creditos (401) no Meta keyword total")
            r.raise_for_status()
            js = _parse_meta_graphql_response(r.text)
            if not js:
                time.sleep(1.2 + attempt)
                continue
            count = (
                ((js.get("data") or {}).get("ad_library_main") or {})
                .get("search_results_connection", {})
                .get("count")
            )
            # Meta often returns soft GraphQL errors but still includes count
            if count is not None:
                return int(count), credits
            if js.get("errors"):
                time.sleep(1.2 + attempt)
                continue
            return 0, credits
        except RuntimeError:
            raise
        except Exception:
            time.sleep(1.2 + attempt)
    return None, credits


def _meta_keyword_name_count_via_scrapingbee(
    query: str,
    needles: list[str],
) -> tuple[int | None, int | None, int, str]:
    """
    Open Ad Library keyword search and count how many times the company name
    appears in visible text (browser Ctrl+F on innerText after scroll).
    Returns (ctrl_f_count, page_total_hint, credits, library_url).
    """
    if not query or not needles:
        return None, None, 0, ""
    library_url = _meta_keyword_library_url(query)
    js_needles = json.dumps(needles)
    evaluate_js = (
        "(() => {"
        f" const needles = {js_needles};"
        " const sleep = (ms) => new Promise((r) => setTimeout(r, ms));"
        " const countOcc = (text, needle) => {"
        "   if (!needle) return 0;"
        "   const t = String(text).toLowerCase();"
        "   const n = String(needle).toLowerCase();"
        "   let c = 0, i = 0;"
        "   while ((i = t.indexOf(n, i)) !== -1) { c += 1; i += Math.max(n.length, 1); }"
        "   return c;"
        " };"
        " const parseTotal = (text) => {"
        "   const m = String(text).match(/([\\d,.\\s]+)\\s*\\+?\\s*results?/i);"
        "   if (!m) return null;"
        "   const n = parseInt(String(m[1]).replace(/[^\\d]/g, ''), 10);"
        "   return Number.isFinite(n) ? n : null;"
        " };"
        " return (async () => {"
        "   let lastH = 0, stable = 0;"
        "   for (let i = 0; i < 30; i++) {"
        "     window.scrollBy(0, 3000);"
        "     await sleep(850);"
        "     const h = document.body ? document.body.scrollHeight : 0;"
        "     if (h <= lastH) { stable += 1; if (stable >= 5) break; }"
        "     else { stable = 0; lastH = h; }"
        "   }"
        "   const text = (document.body && (document.body.innerText || document.body.textContent)) || '';"
        "   let best = {needle: needles[0] || '', count: 0, total: parseTotal(text)};"
        "   for (const n of needles) {"
        "     const c = countOcc(text, n);"
        "     if (c > best.count) best = {needle: n, count: c, total: best.total};"
        "   }"
        "   return best;"
        " })();"
        "})()"
    )
    js_scenario = json.dumps({
        "instructions": [
            {"wait": 4000},
            {"evaluate": evaluate_js},
        ]
    })
    params = {
        "api_key": SCRAPINGBEE_API_KEY,
        "url": library_url,
        "country_code": SCRAPINGBEE_COUNTRY,
        "premium_proxy": "true",
        "render_js": "true",
        "js_scenario": js_scenario,
        "block_resources": "false",
        "json_response": "true",
        "timeout": "120000",
    }
    credits = 0
    try:
        r = requests.get(SCRAPINGBEE_URL, params=params, timeout=150)
        credits += int(r.headers.get("Spb-cost", 5) or 5)
        if r.status_code == 401:
            raise RuntimeError("ScrapingBee sem creditos (401) no Meta keyword search")
        r.raise_for_status()
        payload = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if not payload:
            # unexpected plain HTML fallback
            html = r.text or ""
            best_n = max((_count_name_occurrences(html, n) for n in needles), default=0)
            print(f"[META/SB] keyword '{query}' ctrl+f(html)={best_n}", flush=True)
            return best_n, None, credits, library_url
    except RuntimeError:
        raise
    except Exception as e:
        print(f"[META/SB] keyword fetch falhou ({query}): {e}", flush=True)
        return None, None, credits, library_url

    # ScrapingBee json_response: evaluate result lives in js_scenario_report / evaluate_results
    best_n = 0
    best_needle = needles[0]
    page_total: int | None = None
    report = payload.get("js_scenario_report") or {}
    evals = report.get("evaluate") or report.get("evaluate_results") or payload.get("evaluate_results") or []
    if isinstance(evals, list):
        for item in evals:
            val = item.get("result") if isinstance(item, dict) else item
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except Exception:
                    pass
            if isinstance(val, dict) and "count" in val:
                best_n = int(val.get("count") or 0)
                best_needle = str(val.get("needle") or best_needle)
                if isinstance(val.get("total"), (int, float)):
                    page_total = int(val["total"])
                break
            if isinstance(val, (int, float)):
                best_n = int(val)
                break
    if best_n <= 0:
        # Fallback: count in returned body HTML
        body = payload.get("body") or ""
        for needle in needles:
            n = _count_name_occurrences(body, needle)
            if n > best_n:
                best_n = n
                best_needle = needle

    print(
        f"[META/SB] keyword '{query}' needle='{best_needle}' "
        f"ctrl+f={best_n} page_total={page_total}",
        flush=True,
    )
    return best_n, page_total, credits, library_url


def _fmt_meta_dual(ctrl_f: int | None, total: int | None) -> str:
    """Display official/unofficial as 63/1234 (Ctrl+F / total results)."""
    if ctrl_f is None and total is None:
        return ""
    left = "—" if ctrl_f is None else str(int(ctrl_f))
    right = "—" if total is None else str(int(total))
    return f"{left}/{right}"


def _parse_meta_dual(val: Any) -> tuple[int | None, int | None]:
    """Parse '63/1234' or plain int from XLSX Meta Ads cell."""
    if val is None or val == "" or val == "—":
        return None, None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return int(val), None
    s = str(val).strip().replace(" ", "")
    if "/" in s:
        left, right = s.split("/", 1)
        def _n(x: str) -> int | None:
            x = x.replace(".", "").replace(",", "")
            if not x or x in ("—", "-", "n/d", "None"):
                return None
            try:
                return int(float(x))
            except Exception:
                return None
        return _n(left), _n(right)
    try:
        return int(float(re.sub(r"[^\d.]", "", s))), None
    except Exception:
        return None, None


_IG_EXCLUDED = {
    "p", "reel", "reels", "stories", "explore", "accounts", "rsrc.php",
    "static", "developer", "about", "privacy", "terms", "legal", "directory",
}


def _ig_handle_from_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.netloc or "").lower()
    if "instagram.com" in host:
        parts = [p for p in parsed.path.split("/") if p]
        handle = (parts[0] if parts else "").strip("@")
    else:
        handle = raw.lstrip("@").split("/")[0]
    handle = handle.split("?")[0].strip()
    return handle.lower()


def _ig_handle_usable(handle: str) -> bool:
    h = (handle or "").strip().lstrip("@").lower()
    if not h or h.isdigit() or h in _IG_EXCLUDED:
        return False
    return bool(re.fullmatch(r"[a-z0-9._]{2,30}", h))


def _instagram_from_html(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    hrefs: list[str] = []
    for a in soup.find_all("a", href=True):
        hrefs.append(a.get("href", "") or "")
    for tag in soup.find_all(["link", "meta"]):
        for attr in ("href", "content"):
            val = tag.get(attr) or ""
            if "instagram.com" in val.lower():
                hrefs.append(val)
    for href in hrefs:
        if "instagram.com" not in href.lower():
            continue
        url = normalize_instagram_url(href)
        if _ig_handle_usable(_ig_handle_from_url(url)):
            return url
    for match in re.findall(r"instagram\.com/([A-Za-z0-9._]+)", html, flags=re.I):
        if _ig_handle_usable(match):
            return f"https://www.instagram.com/{match}/"
    return ""


def _instagram_from_website(url: str) -> str:
    if not url:
        return ""
    html = fetch_url_text(root_url(url), allow_proxy=True)
    return _instagram_from_html(html)


def _resolve_company_instagram(comp: dict) -> tuple[str, str]:
    """Website first, then cached handle, then Google. Returns (url, source)."""
    base_url = comp.get("url") or comp.get("domain") or ""
    name = company_query_for_competitor(comp) or extract_website_name(base_url)
    found = _instagram_from_website(base_url)
    if found:
        print(f"[META/IG] website -> {found}", flush=True)
        return found, "website"
    cached = str(comp.get("instagram_url") or "").strip()
    if _ig_handle_usable(_ig_handle_from_url(cached)):
        url = normalize_instagram_url(cached)
        print(f"[META/IG] cache -> {url}", flush=True)
        return url, "cache"
    searched = search_instagram_profile(name, base_url) if (name or base_url) else ""
    if (
        searched
        and _ig_handle_usable(_ig_handle_from_url(searched))
        and instagram_matches_brand(searched, name, base_url)
    ):
        print(f"[META/IG] google -> {searched}", flush=True)
        return searched, "google"
    print("[META/IG] not found", flush=True)
    return "", ""


def _meta_page_library_url(page_id: str) -> str:
    return (
        "https://www.facebook.com/ads/library/"
        "?active_status=active&ad_type=all&country=ALL"
        "&is_targeted_country=false&media_type=all"
        f"&search_type=page&view_all_page_id={page_id}"
    )


def _meta_page_for_instagram(handle: str, extra_queries: list[str]) -> tuple[dict | None, int]:
    """Typeahead for the IG handle; keep only pages whose ig_username matches."""
    handle_n = normalize_token(handle)
    if not handle_n:
        return None, 0
    queries: list[str] = []
    seen_q: set[str] = set()
    for q in (handle, f"@{handle}", handle.replace("_", " "), handle.replace(".", ""), *extra_queries):
        t = re.sub(r"\s+", " ", (q or "").strip())
        key = t.lower()
        if not t or key in seen_q:
            continue
        seen_q.add(key)
        queries.append(t)
    credits = 0
    best: dict | None = None
    best_score = -1e9
    seen_ids: set[str] = set()
    for q in queries[:6]:
        pages, used = _meta_typeahead_pages(q)
        credits += used
        for page in pages:
            ig = str(page.get("ig_username") or "").strip().lower().lstrip("@")
            if normalize_token(ig) != handle_n:
                continue
            pid = str(page.get("page_id") or "")
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)
            score = _score_meta_page(page, brand=handle, domain="")
            if score > best_score:
                best, best_score = page, score
        if best:
            break
    return best, credits


def _lookup_meta_keyword_fallback(comp: dict) -> dict:
    """Current keyword Ctrl+F method — only when Instagram was not found."""
    brand = extract_website_name(comp.get("url") or comp.get("domain", ""))
    base_url = comp.get("url") or comp.get("domain", "")
    domain = normalize_domain(base_url or comp.get("domain", ""))
    company_query = company_query_for_competitor(comp)
    search_terms = _meta_brand_query_variants(brand, domain=domain, company_query=company_query)
    if not search_terms:
        search_terms = [brand or domain or ""]
    query = next((t for t in search_terms if t), brand or domain)
    needles = _meta_name_needles(brand, company_query=company_query, domain=domain)
    if query and query not in needles:
        needles = [query] + needles
    credits = 0
    ctrl_f: int | None = None
    total: int | None = None
    library_url = _meta_keyword_library_url(query)
    try:
        total, used_t = _meta_keyword_total_via_graphql(query)
        credits += used_t
    except Exception as e:
        print(f"[META/SB] keyword total falhou ({query}): {e}", flush=True)
    try:
        ctrl_f, page_total, used, library_url = _meta_keyword_name_count_via_scrapingbee(
            query, needles
        )
        credits += used
        if total is None and page_total is not None:
            total = page_total
    except Exception as e:
        print(f"[META/SB] keyword count falhou ({query}): {e}", flush=True)
    dual = _fmt_meta_dual(ctrl_f, total)
    print(f"[META/SB] keyword '{query}' -> {dual} (unverified fallback)", flush=True)
    return {
        "meta_ads": ctrl_f,
        "meta_ads_total": total,
        "meta_ads_fmt": dual,
        "meta_url": library_url,
        "page_id": "",
        "page_name": query,
        "instagram_url": "",
        "ig_handle": "",
        "confirmed": False,
        "method": "keyword_name_count",
        "spb_credits": credits,
    }


def lookup_meta_ads(comp: dict) -> dict:
    """Resolve Instagram, verify it on Ad Library, else fall back to keyword search."""
    ig_url, ig_source = _resolve_company_instagram(comp)
    handle = _ig_handle_from_url(ig_url)
    credits = 0
    if handle and _ig_handle_usable(handle):
        extra = _meta_brand_query_variants(
            extract_website_name(comp.get("url") or comp.get("domain", "")),
            domain=normalize_domain(comp.get("url") or comp.get("domain", "")),
            company_query=company_query_for_competitor(comp),
        )
        page, used = _meta_page_for_instagram(handle, extra)
        credits += used
        if page and page.get("page_id"):
            page_id = str(page["page_id"])
            count, used_c = _meta_ads_count_via_scrapingbee(page_id)
            credits += used_c
            ads = 0 if count is None else int(count)
            print(
                f"[META/SB] IG @{handle} ({ig_source}) verified page={page.get('name')} "
                f"id={page_id} ads={ads}",
                flush=True,
            )
            return {
                "meta_ads": ads,
                "meta_ads_total": ads,
                "meta_ads_fmt": str(ads),
                "meta_url": _meta_page_library_url(page_id),
                "page_id": page_id,
                "page_name": str(page.get("name") or handle),
                "instagram_url": f"https://www.instagram.com/{handle}/",
                "ig_handle": handle,
                "confirmed": True,
                "method": f"instagram_{ig_source}",
                "spb_credits": credits,
            }
        print(
            f"[META/SB] IG @{handle} ({ig_source}) not verified on Ad Library — keyword fallback",
            flush=True,
        )
        result = _lookup_meta_keyword_fallback(comp)
        result["instagram_url"] = f"https://www.instagram.com/{handle}/"
        result["ig_handle"] = handle
        result["spb_credits"] = int(result.get("spb_credits") or 0) + credits
        return result
    result = _lookup_meta_keyword_fallback(comp)
    result["spb_credits"] = int(result.get("spb_credits") or 0) + credits
    return result


def load_meta_map(competitors: list[dict]) -> dict[str, dict]:
    out = {}
    n = len(competitors)
    total_credits = 0
    for i, comp in enumerate(competitors, 1):
        t0 = time.time()
        dom = comp.get("domain", "?")
        print(f"[META/SB] ({i}/{n}) {dom} ...", flush=True)
        try:
            result = lookup_meta_ads(comp)
        except Exception as e:
            print(f"[META/SB] ({i}/{n}) {dom} ERRO: {e}", flush=True)
            result = {"meta_ads": None, "meta_ads_total": None, "meta_url": "", "spb_credits": 0}
        out[comp["domain"]] = result
        total_credits += int(result.get("spb_credits") or 0)
        dual = result.get("meta_ads_fmt") or _fmt_meta_dual(
            result.get("meta_ads"), result.get("meta_ads_total")
        )
        print(
            f"[META/SB] ({i}/{n}) {dom} -> {dual or '—'}  "
            f"q={result.get('page_name') or '—'}  "
            f"ig=@{result.get('ig_handle') or '—'}  "
            f"confirmed={bool(result.get('confirmed'))}  "
            f"credits={result.get('spb_credits', 0)}  ({time.time() - t0:.1f}s)",
            flush=True,
        )
    print(f"[META/SB] Total credits ScrapingBee: {total_credits}", flush=True)
    return out


def lookup_google_ads(company_name: str) -> dict:
    vendor = FINAL_DIR / "vendor"
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    from google_ads_library import lookup_google_ads as _lookup_domain

    domain = normalize_domain(company_name)
    if not domain:
        domain = normalize_domain(root_url(company_name))
    return _lookup_domain(domain or company_name)


def load_google_ads_map(competitors: list[dict]) -> dict[str, dict]:
    out = {}
    n = len(competitors)
    for i, comp in enumerate(competitors, 1):
        t0 = time.time()
        print(f"[GOOGLE] ({i}/{n}) {comp.get('domain', '?')} ...", flush=True)
        out[comp["domain"]] = lookup_google_ads(comp.get("url") or comp.get("domain", ""))
        print(
            f"[GOOGLE] ({i}/{n}) {comp.get('domain', '?')} -> "
            f"{out[comp['domain']].get('google_ads')} ads  ({time.time() - t0:.1f}s)",
            flush=True,
        )
    return out


def normalize_instagram_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    excluded = {"p", "reel", "reels", "stories", "explore", "accounts", "rsrc.php", "static", "developer", "about", "privacy", "terms"}
    if parts and parts[0].lower() not in excluded:
        return f"https://www.instagram.com/{parts[0].strip('@')}/"
    text = fetch_url_text(url, allow_proxy=True)
    soup = BeautifulSoup(text, "html.parser")
    for meta in soup.find_all("meta"):
        content = meta.get("content", "") or ""
        m = re.search(r"\(@([a-zA-Z0-9_\.]+)\)", content)
        if m and m.group(1).lower() not in excluded:
            return f"https://www.instagram.com/{m.group(1)}/"
    for match in re.findall(r'instagram\.com/([a-zA-Z0-9_\.]+)', text, flags=re.IGNORECASE):
        handle = match.strip("/").split("?")[0]
        if handle and handle.lower() not in excluded:
            return f"https://www.instagram.com/{handle}/"
    return url


def search_instagram_profile(company_name: str, site_url: str = "") -> str:
    query_base = social_search_label(site_url) if site_url else social_search_label("", company_name)
    if not query_base:
        return ""
    params = {"search": f"{query_base} instagram", "country_code": SCRAPINGBEE_COUNTRY}
    headers = {
        "Authorization": f"Bearer {SCRAPINGBEE_API_KEY}",
        "Spb-Accept-Language": ACCEPT_LANGUAGE,
        "User-Agent": "Mozilla/5.0",
    }
    try:
        r = requests.get("https://app.scrapingbee.com/api/v1/google", params=params, headers=headers, timeout=60)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return ""
    for key in ("organic_results", "results", "items"):
        items = data.get(key)
        if not isinstance(items, list) or not items:
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            url = (item.get("url") or item.get("link") or "").strip()
            if "instagram.com" in url.lower():
                return normalize_instagram_url(url)
    return ""


def _social_handle_from_url(platform: str, url: str) -> str:
    parts = [p for p in urlparse(url or "").path.split("/") if p]
    if not parts:
        return ""
    if platform == "youtube" and parts[0] in {"channel", "c", "user", "@"} and len(parts) >= 2:
        return parts[1].lstrip("@")
    return parts[0].lstrip("@")


def social_handle_matches_brand(handle: str, company_name: str, site_url: str = "") -> bool:
    """Handle must contain the brand/domain token. Short prefixes ('trend' vs TrendTrack) do not count."""
    vendor = Path(__file__).resolve().parent / "vendor"
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    try:
        from tiktok_brand_filter import handle_matches_brand
        return handle_matches_brand(handle, company_name, extract_website_name(site_url) or site_url)
    except Exception:
        handle_n = normalize_token(handle)
        company_token = normalize_token(company_name)
        domain_token = normalize_token(extract_website_name(site_url))
        if not handle_n or len(handle_n) < 3:
            return False
        for tok in (company_token, domain_token):
            if tok and len(tok) >= 3 and (handle_n == tok or tok in handle_n):
                return True
        return False


def social_url_matches_brand(platform: str, url: str, company_name: str, site_url: str = "") -> bool:
    handle = _social_handle_from_url(platform, url)
    return social_handle_matches_brand(handle, company_name, site_url)


def _social_handle_is_impersonator(handle: str) -> bool:
    vendor = Path(__file__).resolve().parent / "vendor"
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    try:
        from tiktok_brand_filter import handle_is_impersonator
        return handle_is_impersonator(handle)
    except Exception:
        return bool(re.search(r"(?:0fficial|offici4l|off1cial|0ficial)", handle or "", re.I))


def instagram_matches_brand(instagram_url: str, company_name: str, site_url: str = "") -> bool:
    if not instagram_url:
        return False
    return social_url_matches_brand("instagram", instagram_url, company_name, site_url)


def normalize_youtube_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return url
    if parts[0] in {"channel", "c", "user", "@"} and len(parts) >= 2:
        return f"{parsed.scheme or 'https'}://{parsed.netloc}/{parts[0]}/{parts[1]}/"
    return f"{parsed.scheme or 'https'}://{parsed.netloc}/{parts[0]}/"


def youtube_handle_from_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return ""
    first = parts[0].strip()
    if first.startswith("@"):
        return first.lower()
    return ""


def normalize_tiktok_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if parts and parts[0].startswith("@"):
        return f"{parsed.scheme or 'https'}://{parsed.netloc}/{parts[0]}/"
    return url


def _extract_llm_json(text: str) -> dict:
    raw = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if m:
        raw = m.group(1).strip()
    raw = re.sub(r"^[^{\[]*", "", raw)
    raw = re.sub(r"[^}\]]*$", "", raw)
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def _validate_social_url(platform: str, url: str) -> str:
    """Keep profile/channel URLs only — drop videos, posts, and search pages."""
    raw = (url or "").strip()
    if not raw:
        return ""
    if raw.startswith("@") and " " not in raw:
        handle = raw
        if platform == "youtube":
            raw = f"https://www.youtube.com/{handle}"
        elif platform == "tiktok":
            raw = f"https://www.tiktok.com/{handle}"
        elif platform == "instagram":
            raw = f"https://www.instagram.com/{handle.lstrip('@')}/"
    low = raw.lower()
    if platform == "youtube":
        if "youtube.com" not in low and "youtu.be" not in low:
            return ""
        if "/watch" in low or "youtu.be/" in low or "/shorts/" in low or "/playlist" in low:
            return ""
        return normalize_youtube_url(raw)
    if platform == "instagram":
        if "instagram.com" not in low:
            return ""
        return normalize_instagram_url(raw)
    if platform == "tiktok":
        if "tiktok.com" not in low:
            return ""
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        if not parts or not parts[0].startswith("@") or any(p.lower() == "video" for p in parts):
            return ""
        return normalize_tiktok_url(raw)
    return ""


def _llm_official_socials(company: str, site_url: str, domain: str) -> dict[str, str]:
    """Ask Gemini (OpenRouter) for official YT / IG / TikTok accounts."""
    empty = {"youtube": "", "instagram": "", "tiktok": ""}
    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key or not (company or domain):
        return empty
    model = (os.environ.get("OPENROUTER_MODEL") or "google/gemini-2.5-flash").strip()
    prompt = (
        "Find the official social-media accounts for this company.\n\n"
        f"Company: {company or domain}\n"
        f"Website: {site_url or domain}\n"
        f"Domain: {domain}\n\n"
        "Return JSON only, no markdown:\n"
        '{"youtube":"https://www.youtube.com/@handle","instagram":"https://www.instagram.com/handle/",'
        '"tiktok":"https://www.tiktok.com/@handle"}\n\n'
        "Rules:\n"
        "- Only the company's own official account, never a fan page, article, or a single video/post.\n"
        "- Use an empty string when you are not sure of the exact handle. Do not guess a similar handle "
        "(underscores, extra words, or a close spelling).\n"
        "- Prefer the handle that matches the brand name on the official website.\n"
    )
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 400,
                "temperature": 0.1,
            },
            timeout=45,
        )
        r.raise_for_status()
        raw = (((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        data = _extract_llm_json(raw)
    except Exception as e:
        print(f"[SOCIAL] gemini failed: {e}", flush=True)
        return empty
    out = dict(empty)
    for key_name in out:
        out[key_name] = str(data.get(key_name) or "").strip()
    return out


def search_social_profile_google(platform: str, company_name: str, site_url: str = "") -> str:
    """Page-1 Google for the official profile (TinyFish → ScrapingBee → DataForSEO)."""
    label = (company_name or social_search_label(site_url) or "").strip()
    if not label:
        return ""
    vendor = Path(__file__).resolve().parent / "vendor"
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    try:
        from google_serp import google_serp
    except Exception as e:
        print(f"[SOCIAL] google_serp import failed: {e}", flush=True)
        return ""
    market = (os.environ.get("SPY_MARKET") or "us").strip().lower()
    domain = {"youtube": "youtube.com", "instagram": "instagram.com", "tiktok": "tiktok.com"}.get(platform, "")
    queries = [f"{label} official {platform}", f"{label} {platform}"]
    for query in queries:
        try:
            res = google_serp(query, market=market, include_domains=domain or None)
        except Exception as e:
            print(f"[SOCIAL] google '{query}' failed: {e}", flush=True)
            continue
        for item in res.get("items") or []:
            url = _validate_social_url(platform, str(item.get("url") or ""))
            if not url:
                continue
            handle = _social_handle_from_url(platform, url)
            if _social_handle_is_impersonator(handle):
                print(f"[SOCIAL] google skip impersonator {url}", flush=True)
                continue
            if social_url_matches_brand(platform, url, label, site_url):
                return url
        src = res.get("source") or "?"
        print(f"[SOCIAL] google '{query}' src={src} no brand-handle match", flush=True)
    return ""


def social_links_from_homepage(url: str, company_name: str = "") -> dict[str, str]:
    """Scrape homepage <a href> only — Google fallback lives in discover_official_socials."""
    out = {"instagram": "", "youtube": "", "tiktok": ""}
    if not url:
        return out
    html = fetch_url_text(root_url(url), allow_proxy=True)
    if not html:
        return out
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        low = href.lower()
        if not out["instagram"] and "instagram.com" in low:
            out["instagram"] = normalize_instagram_url(href)
        elif not out["youtube"] and ("youtube.com" in low or "youtu.be" in low):
            out["youtube"] = normalize_youtube_url(href)
        elif not out["tiktok"] and "tiktok.com" in low:
            out["tiktok"] = normalize_tiktok_url(href)
    return out


def _social_url_key(platform: str, url: str) -> str:
    return (_validate_social_url(platform, url) or "").lower().rstrip("/")


def _followers_for_platform(platform: str, url: str) -> int | None:
    if platform == "instagram":
        return parse_instagram_followers(url)
    if platform == "youtube":
        return parse_youtube_followers(url)
    if platform == "tiktok":
        return parse_tiktok_followers(url)
    return None


def discover_official_socials(
    company_name: str, site_url: str, domain: str = "",
) -> tuple[dict[str, str], dict[str, int | None]]:
    """Official YT / IG / TikTok: gather Gemini + website + Google, then keep the biggest profile."""
    label = (company_name or social_search_label(site_url) or domain or "").strip()
    out = {"instagram": "", "youtube": "", "tiktok": ""}
    src = {k: "" for k in out}
    counts: dict[str, int | None] = {}
    candidates: dict[str, list[tuple[str, str]]] = {k: [] for k in out}

    def _add(platform: str, url: str, source: str) -> None:
        clean = _validate_social_url(platform, url)
        if not clean:
            return
        handle = _social_handle_from_url(platform, clean)
        if _social_handle_is_impersonator(handle) and source != "website":
            print(f"[SOCIAL] drop {platform} {clean} src={source} (impersonator)", flush=True)
            return
        if source != "website" and not social_url_matches_brand(platform, clean, label, site_url):
            print(f"[SOCIAL] drop {platform} {clean} src={source} (handle≠brand)", flush=True)
            return
        key = _social_url_key(platform, clean)
        if any(_social_url_key(platform, existing) == key for existing, _ in candidates[platform]):
            return
        candidates[platform].append((clean, source))

    llm = _llm_official_socials(label, site_url, domain)
    for key_name in out:
        _add(key_name, llm.get(key_name) or "", "gemini")
    print(
        f"[SOCIAL] gemini {label}: yt={llm.get('youtube') or '—'} "
        f"ig={llm.get('instagram') or '—'} tt={llm.get('tiktok') or '—'}",
        flush=True,
    )

    if site_url:
        web = social_links_from_homepage(site_url, label)
        for key_name in out:
            _add(key_name, web.get(key_name) or "", "website")
        print(
            f"[SOCIAL] website {label}: yt={web.get('youtube') or '—'} "
            f"ig={web.get('instagram') or '—'} tt={web.get('tiktok') or '—'}",
            flush=True,
        )

    def _best_of(platform: str, cands: list[tuple[str, str]]) -> tuple[str, str, int | None]:
        if not cands:
            return "", "", None
        # Homepage link wins even if a Gemini/Google lookalike has more followers.
        website = [(u, s) for u, s in cands if s == "website"]
        pool = website or cands
        best_url, best_src, best_n = pool[0][0], pool[0][1], -1
        best_count: int | None = None
        for url, source in pool:
            n = _followers_for_platform(platform, url)
            n_i = -1 if n is None else int(n)
            print(f"[SOCIAL] candidate {platform} {url} src={source} followers={n}", flush=True)
            if n_i > best_n:
                best_url, best_src, best_n, best_count = url, source, n_i, n
        return best_url, best_src, best_count

    # Google when a platform is empty *or* the best Gemini/website pick looks like a stub.
    _WEAK_FOLLOWERS = 200
    for key_name in out:
        url, source, n = _best_of(key_name, candidates[key_name])
        weak = (not url) or n is None or int(n) < _WEAK_FOLLOWERS
        if weak:
            before = {_social_url_key(key_name, u) for u, _ in candidates[key_name]}
            _add(key_name, search_social_profile_google(key_name, label, site_url), "google")
            added = any(
                _social_url_key(key_name, u) not in before for u, _ in candidates[key_name]
            )
            if added or not url:
                url, source, n = _best_of(key_name, candidates[key_name])
        if not url:
            continue
        out[key_name] = url
        src[key_name] = source
        if n is not None:
            counts[key_name] = n

    print(f"[SOCIAL] official {label} sources={src}", flush=True)
    return out, counts


def _fetch_via_scrapingbee(
    url: str,
    render_js: bool = False,
    *,
    wait: str | None = None,
    premium_proxy: bool = False,
    country_code: str = "",
) -> str:
    if not SCRAPINGBEE_API_KEY:
        raise RuntimeError("SCRAPINGBEE_API_KEY ausente")
    params = {
        "api_key": SCRAPINGBEE_API_KEY,
        "url": url,
        "render_js": "true" if render_js else "false",
    }
    if wait:
        params["wait"] = wait
    if premium_proxy:
        params["premium_proxy"] = "true"
    if country_code:
        params["country_code"] = country_code.lower()[:2]
    r = requests.get("https://app.scrapingbee.com/api/v1/", params=params, timeout=90)
    r.raise_for_status()
    return r.text


def fetch_url_text(
    url: str,
    allow_proxy: bool = False,
    prefer_proxy: bool = False,
    render_js: bool = False,
) -> str:
    if not url:
        return ""
    if allow_proxy and prefer_proxy:
        try:
            return _fetch_via_scrapingbee(url, render_js=render_js)
        except Exception:
            pass
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return r.text
    except Exception:
        if not allow_proxy:
            return ""
    try:
        return _fetch_via_scrapingbee(url, render_js=render_js)
    except Exception:
        return ""


def parse_instagram_followers(url: str) -> int | None:
    # Instagram bloqueia IP direto e exige JS — ScrapingBee com render_js
    text = fetch_url_text(url, allow_proxy=True, prefer_proxy=True, render_js=True)
    if not text:
        text = fetch_url_text(url, allow_proxy=True, prefer_proxy=True, render_js=False)
    if not text:
        text = fetch_url_text(url, allow_proxy=True, prefer_proxy=False)
    if not text:
        return None
    soup = BeautifulSoup(text, "html.parser")
    for meta in soup.find_all("meta"):
        content = ascii_text(meta.get("content", "") or "")
        for pattern in (r'([0-9][0-9.,]*)\s+Followers', r'([0-9][0-9.,]*)\s+seguidores'):
            m = re.search(pattern, content, flags=re.IGNORECASE)
            if m:
                n = parse_human_number(m.group(1))
                if n is not None:
                    return n
    patterns = [
        r'"edge_followed_by"\s*:\s*\{"count"\s*:\s*(\d+)\}',
        r'content="([^"]*followers[^"]*)"',
        r'content="([^"]*seguidores[^"]*)"',
        r'([\d.,kmb]+)\s+Followers',
        r'([\d.,kmb]+)\s+seguidores',
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            return parse_human_number(m.group(1))
    return None


def _yt_subscriber_text_to_int(text: str) -> int | None:
    blob = ascii_text(text or "")
    if not blob:
        return None
    m = re.search(
        r"([\d][\d.,]*)\s*(k|m|b|mil|thousand|million|billion)?\s*"
        r"(subscribers?|inscrit[oa]s?)",
        blob,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    token = m.group(1)
    suf = (m.group(2) or "").lower()
    if suf == "thousand":
        suf = "k"
    elif suf == "million":
        suf = "m"
    elif suf == "billion":
        suf = "b"
    return parse_human_number(token + suf)


def _yt_subscribers_from_header_html(html: str) -> int | None:
    """Read the channel header / About block only — never the first video-card count."""
    if not html:
        return None
    scoped = [
        re.compile(
            r'"aboutChannelViewModel"\s*:\s*\{.{0,8000}?"subscriberCountText"\s*:\s*"([^"]+)"',
            re.S,
        ),
        re.compile(
            r'"c4TabbedHeaderRenderer"\s*:\s*\{.{0,16000}?"subscriberCountText"'
            r'.{0,800}?"simpleText"\s*:\s*"([^"]+)"',
            re.S,
        ),
        re.compile(
            r'"c4TabbedHeaderRenderer"\s*:\s*\{.{0,16000}?"subscriberCountText"'
            r'.{0,1000}?"label"\s*:\s*"([^"]+)"',
            re.S,
        ),
        re.compile(
            r'"pageHeaderViewModel".{0,24000}?"content"\s*:\s*"([^"]*(?:subscribers|inscrit)[^"]*)"',
            re.S | re.I,
        ),
    ]
    for pat in scoped:
        m = pat.search(html)
        if not m:
            continue
        n = _yt_subscriber_text_to_int(m.group(1))
        if n is not None:
            return n
    return None


def _yt_subscribers_near_handle(html: str, handle: str) -> int | None:
    if not html or not handle:
        return None
    text = ascii_text(html)
    low = text.lower()
    needle = handle.lower()
    idx = low.find(needle)
    if idx < 0:
        return None
    chunk = text[idx:idx + 500]
    return _yt_subscriber_text_to_int(chunk)


def _youtube_subscribers_from_google(url: str) -> int | None:
    handle = youtube_handle_from_url(url)
    label = (handle or url or "").strip()
    if not label:
        return None
    vendor = Path(__file__).resolve().parent / "vendor"
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    try:
        from google_serp import google_serp
    except Exception as e:
        print(f"[SOCIAL] youtube google fallback import failed: {e}", flush=True)
        return None
    market = (os.environ.get("SPY_MARKET") or "us").strip().lower()
    res = google_serp(label, market=market, include_domains="youtube.com")
    handle_l = (handle or "").lower().lstrip("@")
    for it in res.get("items") or []:
        u = str(it.get("url") or "").lower()
        blob = " ".join(
            str(it.get(k) or "")
            for k in ("title", "snippet", "extra", "extended_snippet", "pre_snippet")
        )
        if handle_l and handle_l not in u and handle_l not in blob.lower():
            continue
        if "youtube.com" not in u and "youtube.com" not in blob.lower():
            continue
        n = _yt_subscriber_text_to_int(blob)
        if n is not None:
            return n
    return None


def parse_youtube_followers(url: str) -> int | None:
    """Official channel subscribers from the header / About JSON, then Google."""
    if not url:
        return None
    base = normalize_youtube_url(url).rstrip("/")
    pages = []
    if base:
        pages.append(base + "/about")
        if base not in pages:
            pages.append(base)
    if url.rstrip("/") not in pages:
        pages.append(url)
    for page in pages:
        text = ""
        try:
            text = _fetch_via_scrapingbee(
                page,
                render_js=True,
                wait="3000",
                premium_proxy=True,
                country_code="us",
            )
        except Exception:
            text = fetch_url_text(page, allow_proxy=True, prefer_proxy=True, render_js=True)
        if not text:
            continue
        n = _yt_subscribers_from_header_html(text)
        if n is not None:
            print(f"[SOCIAL] youtube {page} src=header subscribers={n}", flush=True)
            return n
        n = _yt_subscribers_near_handle(text, youtube_handle_from_url(url))
        if n is not None:
            print(f"[SOCIAL] youtube {page} src=handle subscribers={n}", flush=True)
            return n
    n = _youtube_subscribers_from_google(url)
    if n is not None:
        print(f"[SOCIAL] youtube {url} src=google subscribers={n}", flush=True)
        return n
    print(f"[SOCIAL] youtube {url} subscribers=None", flush=True)
    return None


def parse_tiktok_followers(url: str) -> int | None:
    # TikTok tambem bloqueia IP direto — ScrapingBee com JS
    text = fetch_url_text(url, allow_proxy=True, prefer_proxy=True, render_js=True)
    if not text:
        text = fetch_url_text(url, allow_proxy=True, prefer_proxy=True, render_js=False)
    if not text:
        text = fetch_url_text(url, allow_proxy=True, prefer_proxy=False)
    if not text:
        return None
    text_ascii = ascii_text(text)
    soup = BeautifulSoup(text, "html.parser")
    for meta in soup.find_all("meta"):
        content = ascii_text(meta.get("content", "") or "")
        for pattern in (
            r'([0-9][0-9.,]*)\s*mil\s+seguidores',
            r'([0-9][0-9.,]*)\s+Followers',
            r'([0-9][0-9.,]*)\s+seguidores',
        ):
            m = re.search(pattern, content, flags=re.IGNORECASE)
            if m:
                token = m.group(1) + ("mil" if "mil" in pattern else "")
                n = parse_human_number(token)
                if n is not None:
                    return n
    patterns = [
        r'"followerCount"\s*:\s*(\d+)',
        r'"fans"\s*:\s*(\d+)',
        r'([\d.,]+mil)\s+seguidores',
        r'([\d.,kmb]+)\s+Followers',
        r'([\d.,kmb]+)\s+seguidores',
    ]
    for pattern in patterns:
        m = re.search(pattern, text_ascii, flags=re.IGNORECASE)
        if m:
            return parse_human_number(m.group(1))
    return None


def linkedin_account_owner_url(name: str) -> str:
    try:
        from linkedin_library_us import account_owner_url
        return account_owner_url(name)
    except Exception:
        return f"{LINKEDIN_AD_LIBRARY_BASE}?accountOwner={quote_plus(name.strip())}&countries={META_COUNTRY}"


def parse_linkedin_result_count(text: str) -> int | None:
    """Extrai total do h1 PT/EN/FR da LinkedIn Ad Library."""
    try:
        from linkedin_library_us import parse_result_count
        return parse_result_count(text)
    except Exception:
        pass
    if not text:
        return None
    t = (text or "").replace("\xa0", " ").replace("&nbsp;", " ")
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if re.search(r"(nenhum resultado|no results|aucun r[eé]sultat)", t, flags=re.IGNORECASE):
        return 0
    m = re.search(
        r"([\d.,\s]+)\s+(?:an[uú]ncios?|ads?|publicit[eé]s?)\s+(?:correspond|match)",
        t,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    raw = re.sub(r"[^\d]", "", m.group(1))
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def lookup_linkedin_ads(query: str) -> dict:
    """LinkedIn Ads: keyword search + Ctrl+F name + H1 total (ScrapingBee)."""
    q = (query or "").strip()
    if not q:
        return {
            "linkedin_ads": None,
            "linkedin_payer": "",
            "linkedin_search_url": "",
            "spb_credits": 0,
        }
    vendor = Path(__file__).resolve().parent / "vendor"
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    from linkedin_library_us import lookup_company_via_payer_flow

    return lookup_company_via_payer_flow(q)


def load_linkedin_map(competitors: list[dict]) -> dict[str, dict]:
    if not competitors:
        return {}
    out = {}
    n = len(competitors)
    total_credits = 0
    for i, comp in enumerate(competitors, 1):
        query = company_query_for_competitor(comp)
        t0 = time.time()
        print(f"[LINKEDIN] ({i}/{n}) {comp.get('domain', '?')} query='{query}' ...", flush=True)
        result = lookup_linkedin_ads(query)
        out[comp["domain"]] = result
        total_credits += int(result.get("spb_credits") or 0)
        print(
            f"[LINKEDIN] ({i}/{n}) {comp.get('domain', '?')} -> "
            f"{result.get('linkedin_ads')} ads  found={result.get('name_found')}  "
            f"({time.time() - t0:.1f}s)",
            flush=True,
        )
    print(f"[LINKEDIN] Total creditos ScrapingBee: {total_credits}", flush=True)
    return out


def build_metric_rows(
    competitors: list[dict],
    traffic_map: dict[str, dict],
    meta_map: dict[str, dict],
    google_ads_map: dict[str, dict],
    linkedin_map: dict[str, dict],
    collect_social: bool = True,
) -> list[dict]:
    rows = []
    n = len(competitors)
    for i, comp in enumerate(competitors, 1):
        t0 = time.time()
        dom = comp["domain"]
        base_url = comp.get("url") or comp.get("domain", "")
        if collect_social:
            print(f"[SOCIAL] ({i}/{n}) {dom} ...", flush=True)
            social_name = (
                comp.get("company")
                or comp.get("title")
                or social_search_label(base_url)
                or dom
            )
            socials, pre_counts = discover_official_socials(str(social_name), base_url, dom)
            t_links = time.time()
            instagram_followers = pre_counts.get("instagram")
            youtube_followers = pre_counts.get("youtube")
            tiktok_followers = pre_counts.get("tiktok")
            if instagram_followers is None and socials["instagram"]:
                instagram_followers = parse_instagram_followers(socials["instagram"])
            if youtube_followers is None and socials["youtube"]:
                youtube_followers = parse_youtube_followers(socials["youtube"])
            if tiktok_followers is None and socials["tiktok"]:
                tiktok_followers = parse_tiktok_followers(socials["tiktok"])
            print(
                f"[SOCIAL] ({i}/{n}) {dom} links={time.time() - t0:.1f}s "
                f"followers_extra={time.time() - t_links:.1f}s total={time.time() - t0:.1f}s "
                f"ig={instagram_followers} yt={youtube_followers} tt={tiktok_followers}",
                flush=True,
            )
        else:
            socials = {"instagram": "", "youtube": "", "tiktok": ""}
            instagram_followers = youtube_followers = tiktok_followers = None
        traffic = traffic_map.get(dom, {})
        meta = meta_map.get(dom, {})
        google = google_ads_map.get(dom, {})
        linkedin = linkedin_map.get(dom, {})
        rows.append({
            "domain": dom,
            "url": comp.get("url", ""),
            "similaridade": comp.get("similaridade", "Alto"),
            "perfil": comp.get("perfil", "—"),
            "fonte": comp.get("fonte", ""),
            "seo_atual": traffic.get("seo_atual"),
            "marca_atual": traffic.get("marca_atual"),
            "meta_ads": meta.get("meta_ads"),
            "meta_ads_total": meta.get("meta_ads_total"),
            "meta_ads_fmt": meta.get("meta_ads_fmt")
            or _fmt_meta_dual(meta.get("meta_ads"), meta.get("meta_ads_total")),
            "meta_ads_url": meta.get("meta_url", ""),
            "meta_confirmed": bool(meta.get("confirmed")),
            "meta_ig": meta.get("ig_handle") or "",
            "meta_page_id": meta.get("page_id") or "",
            "meta_method": meta.get("method") or "",
            "google_ads": google.get("google_ads"),
            "google_ads_url": google.get("google_ads_url", ""),
            "linkedin_ads": linkedin.get("linkedin_ads"),
            "linkedin_ads_total": linkedin.get("linkedin_ads_total"),
            "linkedin_ads_ctrl": linkedin.get("linkedin_ads_ctrl"),
            "linkedin_ads_fmt": linkedin.get("linkedin_ads_fmt")
            or (
                str(int(linkedin["linkedin_ads_ctrl"]))
                if linkedin.get("linkedin_ads_ctrl") is not None
                else ""
            ),
            "linkedin_ads_url": linkedin.get("linkedin_search_url", ""),
            "instagram_url": socials["instagram"] or meta.get("instagram_url") or "",
            "youtube_url": socials["youtube"],
            "tiktok_url": socials["tiktok"],
            "instagram_followers": instagram_followers,
            "youtube_followers": youtube_followers,
            "tiktok_followers": tiktok_followers,
        })
    return rows


@contextmanager
def _xlsx_write_lock(path: Path, timeout: float = 180.0) -> Iterator[None]:
    """Exclusive mkdir lock so parallel channel modes cannot clobber the workbook."""
    lock_dir = Path(str(path) + ".lockdir")
    lock_dir.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    while True:
        try:
            if lock_dir.exists():
                age = time.time() - lock_dir.stat().st_mtime
                if age > 600:
                    try:
                        lock_dir.rmdir()
                    except OSError:
                        pass
            lock_dir.mkdir()
            break
        except FileExistsError:
            if time.time() - t0 > timeout:
                raise TimeoutError(f"XLSX lock timeout after {timeout:.0f}s: {path.name}")
            time.sleep(0.15)
    try:
        yield
    finally:
        try:
            lock_dir.rmdir()
        except OSError:
            pass


def _seed_keep_maps(
    latest: dict[str, dict],
    meta_map: dict[str, dict],
    google_ads_map: dict[str, dict],
    linkedin_map: dict[str, dict],
    *,
    keep_meta: bool,
    keep_google: bool,
    keep_linkedin: bool,
) -> None:
    """Fill other-channel maps from the latest on-disk workbook (setdefault keeps fresh collects)."""
    for dom, prev in latest.items():
        if keep_meta:
            meta_map.setdefault(dom, {"meta_ads": prev.get("meta_ads"), "meta_url": prev.get("meta_url", "")})
        if keep_google:
            google_ads_map.setdefault(
                dom,
                {"google_ads": prev.get("google_ads"), "google_ads_url": prev.get("google_ads_url", "")},
            )
        if keep_linkedin:
            linkedin_map.setdefault(
                dom,
                {
                    "linkedin_ads": prev.get("linkedin_ads"),
                    "linkedin_search_url": prev.get("linkedin_search_url", ""),
                },
            )


def load_existing_channel_map(xlsx_path: Path) -> dict[str, dict]:
    """Reaproveita Google/Meta/LinkedIn ja gravados em metricas anteriores."""
    if not xlsx_path or not Path(xlsx_path).exists():
        return {}
    rows: list = []
    last_err: Optional[Exception] = None
    for attempt in range(5):
        try:
            rows = load_sheet_rows(xlsx_path, "Metricas Canais")
            last_err = None
            break
        except Exception as exc:
            last_err = exc
            time.sleep(0.2)
    if last_err is not None:
        print(f"[METRICAS] warn: could not re-read {Path(xlsx_path).name}: {last_err}", flush=True)
        return {}
    if not rows:
        return {}
    headers = rows[0]
    idx = {str(h).strip(): i for i, h in enumerate(headers)}
    out: dict[str, dict] = {}
    for row in rows[1:]:
        if not any(row):
            continue
        i_dom = idx.get("Dominio")
        if i_dom is None or i_dom >= len(row):
            continue
        dom = normalize_domain(row[i_dom] or "")
        if not dom:
            continue

        def col(*names):
            for name in names:
                j = idx.get(name)
                if j is not None and j < len(row):
                    return row[j]
            return None

        meta_ctrl, meta_total = _parse_meta_dual(col("Meta Ads"))
        out[dom] = {
            "google_ads": col("Google Ads"),
            "google_ads_url": col("Google Ads URL") or "",
            "meta_ads": meta_ctrl,
            "meta_ads_total": meta_total,
            "meta_ads_fmt": _fmt_meta_dual(meta_ctrl, meta_total) if (meta_ctrl is not None or meta_total is not None) else "",
            "meta_url": col("Meta Ads URL") or "",
            "confirmed": str(col("Meta Confirmado") or "").strip().lower() in ("sim", "yes", "true", "1"),
            "ig_handle": col("Meta IG") or "",
            "page_id": col("Meta Page ID") or "",
            "method": col("Meta Method") or "",
            "linkedin_ads": col("Linkedin Ads", "LinkedIn Ads"),
            "linkedin_ads_fmt": col("Linkedin Ads", "LinkedIn Ads") or "",
            "linkedin_search_url": col("Linkedin Ads URL", "LinkedIn Ads URL") or "",
            "instagram_url": col("Instagram URL") or "",
            "youtube_url": col("YouTube URL", "Youtube URL") or "",
            "tiktok_url": col("TikTok URL", "Tiktok URL") or "",
            "instagram_followers": col("Instagram Seguidores", "Instagram Followers", "Instagram"),
            "youtube_followers": col("Youtube Seguidores", "YouTube Seguidores", "YouTube Followers", "Youtube Followers", "YouTube"),
            "tiktok_followers": col("Tiktok Seguidores", "TikTok Followers", "Tiktok Followers"),
        }
    return out


def _merge_preserved_channels(
    metric_rows: list[dict],
    existing_maps: dict[str, dict],
    *,
    keep_meta: bool = False,
    keep_google: bool = False,
    keep_linkedin: bool = False,
    keep_social: bool = False,
) -> None:
    """Preserva canais ja coletados quando o modo atual nao os recalcula."""
    for row in metric_rows:
        prev = existing_maps.get(row.get("domain") or "", {})
        if not prev:
            continue
        if keep_meta and row.get("meta_ads") is None:
            row["meta_ads"] = prev.get("meta_ads")
            row["meta_ads_total"] = prev.get("meta_ads_total")
            row["meta_ads_fmt"] = prev.get("meta_ads_fmt") or _fmt_meta_dual(
                prev.get("meta_ads"), prev.get("meta_ads_total")
            )
            row["meta_ads_url"] = prev.get("meta_url") or row.get("meta_ads_url") or ""
            row["meta_confirmed"] = bool(prev.get("confirmed"))
            row["meta_ig"] = prev.get("ig_handle") or row.get("meta_ig") or ""
            row["meta_page_id"] = prev.get("page_id") or row.get("meta_page_id") or ""
            row["meta_method"] = prev.get("method") or row.get("meta_method") or ""
        if keep_google and row.get("google_ads") is None:
            row["google_ads"] = prev.get("google_ads")
            row["google_ads_url"] = prev.get("google_ads_url") or row.get("google_ads_url") or ""
        if keep_linkedin and row.get("linkedin_ads") is None:
            row["linkedin_ads"] = prev.get("linkedin_ads")
            row["linkedin_ads_url"] = prev.get("linkedin_search_url") or row.get("linkedin_ads_url") or ""
        if keep_social:
            for prefix in ("instagram", "youtube", "tiktok"):
                url_k = f"{prefix}_url"
                fol_k = f"{prefix}_followers"
                if not row.get(url_k) and prev.get(url_k):
                    row[url_k] = prev.get(url_k) or ""
                if row.get(fol_k) in (None, "", "—") and prev.get(fol_k) not in (None, "", "—"):
                    row[fol_k] = prev.get(fol_k)


def filtered_sheet(rows: list[list[str]], keep_domains: set[str], include_client: bool = False) -> list[list[str]]:
    if not rows:
        return []
    out = rows[:3]
    for row in rows[3:]:
        if not any(row):
            continue
        dom = normalize_domain(row[1] if len(row) > 1 else "")
        role = fold(row[0] if row else "")
        if dom in keep_domains or (include_client and role.startswith("cliente")):
            out.append(row)
    return out


def write_rows_sheet(wb: Workbook, sheet_name: str, rows: list[list[str]]) -> None:
    if not rows:
        return
    ws = wb.create_sheet(sheet_name)
    for row in rows:
        ws.append(row)
    for row_idx, row in enumerate(ws.iter_rows(), 1):
        for cell in row:
            cell.border = BORDER
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        if row_idx in (1, 3):
            for cell in row:
                if cell.value not in (None, ""):
                    cell.font = HEAD_FONT if row_idx == 3 else Font(bold=True, size=12, color="0F172A")
                    if row_idx == 3:
                        cell.fill = HEAD_FILL


def write_metrics_xlsx(
    out_path: Path,
    client_input: str,
    briefing: dict,
    competitors: list[dict],
    metric_rows: list[dict],
    traffic_rows: list[list[str]],
    growth_rows: list[list[str]],
    national_xlsx: Path,
) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumo"
    ws.append(["Metricas Concorrentes"])
    ws.merge_cells("A1:B1")
    ws["A1"].font = Font(bold=True, size=14, color="0F172A")
    ws.append([])
    ws.append(["Cliente (input)", client_input])
    ws.append(["URL cliente", briefing.get("url", "")])
    ws.append(["Nicho principal", briefing.get("nicho_principal", "")])
    ws.append(["Escopo", briefing.get("escopo", "")])
    ws.append(["Top concorrentes", str(len(competitors))])
    ws.append(["Fonte nacional", str(national_xlsx)])
    ws.append(["Meta Ads", "Keyword search: Ctrl+F name hits (official) / total results (unofficial)"])
    ws.append(["Google Ads", "Transparency domain search, region=anywhere"])
    ws.append(["LinkedIn Ads", "Keyword search: Ctrl+F name hits / H1 ads total (ScrapingBee)"])
    ws.append(["Data", datetime.now().strftime("%d/%m/%Y %H:%M")])
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 90

    ws_u = wb.create_sheet("Concorrentes Unificado")
    headers_u = ["#", "Dominio", "Similaridade", "Perfil", "Fonte", "Nicho (LLM)", "URL", "Titulo"]
    ws_u.append(headers_u)
    for c in ws_u[1]:
        c.font = HEAD_FONT
        c.fill = HEAD_FILL
        c.border = BORDER
    for i, comp in enumerate(competitors, 1):
        ws_u.append([i, comp.get("domain", ""), comp.get("similaridade", ""), comp.get("perfil", ""), comp.get("fonte", ""), comp.get("nicho", ""), comp.get("url", ""), comp.get("title", "")])
        last = ws_u.max_row
        ws_u.cell(row=last, column=3).fill = FILL_SIM.get(comp.get("similaridade", ""), PatternFill(fill_type=None))
        ws_u.cell(row=last, column=4).fill = FILL_PERFIL.get(comp.get("perfil", ""), PatternFill(fill_type=None))
        for cell in ws_u[last]:
            cell.border = BORDER
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    ws_m = wb.create_sheet("Metricas Canais")
    headers_m = [
        "#", "Dominio", "Similaridade", "Perfil", "Fonte",
        "SEO Atual", "Marca Atual", "Meta Ads", "Google Ads", "Linkedin Ads",
        "Meta Ads URL", "Meta Confirmado", "Meta IG", "Meta Page ID", "Meta Method",
        "Google Ads URL", "Linkedin Ads URL",
        "Instagram Seguidores", "Youtube Seguidores", "Tiktok Seguidores",
        "Instagram URL", "Youtube URL", "Tiktok URL", "URL",
    ]
    ws_m.append(headers_m)
    for c in ws_m[1]:
        c.font = HEAD_FONT
        c.fill = HEAD_FILL
        c.border = BORDER
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    for i, row in enumerate(metric_rows, 1):
        ws_m.append([
            i, row["domain"], row["similaridade"], row["perfil"], row["fonte"],
            row["seo_atual"], row["marca_atual"],
            (row.get("meta_ads_fmt") or _fmt_meta_dual(row.get("meta_ads"), row.get("meta_ads_total")) or row.get("meta_ads")),
            row["google_ads"],
            (row.get("linkedin_ads_fmt") or row.get("linkedin_ads_ctrl") or row.get("linkedin_ads") or 0),
            row["meta_ads_url"],
            "sim" if row.get("meta_confirmed") else "nao",
            row.get("meta_ig") or "",
            row.get("meta_page_id") or "",
            row.get("meta_method") or "",
            row["google_ads_url"], row["linkedin_ads_url"],
            row["instagram_followers"], row["youtube_followers"], row["tiktok_followers"],
            row["instagram_url"], row["youtube_url"], row["tiktok_url"], row["url"],
        ])
        last = ws_m.max_row
        ws_m.cell(row=last, column=3).fill = FILL_SIM.get(row["similaridade"], PatternFill(fill_type=None))
        ws_m.cell(row=last, column=4).fill = FILL_PERFIL.get(row["perfil"], PatternFill(fill_type=None))
        for metric_col, url_col in ((8, 11), (9, 16), (10, 17), (18, 21), (19, 22), (20, 23)):
            metric_cell = ws_m.cell(row=last, column=metric_col)
            url_value = ws_m.cell(row=last, column=url_col).value
            if url_value not in (None, "", "—") and metric_cell.value not in (None, "", "—"):
                metric_cell.hyperlink = str(url_value)
                metric_cell.style = "Hyperlink"
        for cell in ws_m[last]:
            cell.border = BORDER
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    widths = [4, 26, 13, 13, 14, 12, 12, 14, 10, 11, 34, 12, 18, 16, 20, 34, 34, 18, 18, 18, 34, 34, 34, 42]
    for i, w in enumerate(widths, 1):
        letter = chr(64 + i) if i <= 26 else "A" + chr(64 + i - 26)
        ws_m.column_dimensions[letter].width = w
    for col in ("K", "N", "O", "P", "Q", "U", "V", "W", "X"):
        ws_m.column_dimensions[col].hidden = True

    write_rows_sheet(wb, "Trafego SEO Marca", traffic_rows)
    write_rows_sheet(wb, "Crescimento", growth_rows)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    wb.save(tmp_path)
    for attempt in range(8):
        try:
            os.replace(tmp_path, out_path)
            break
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.2)
    return out_path


def main() -> None:
    if len(sys.argv) < 2:
        print('Uso: python "5 - metricas concorrentes.py" <cliente> [google_ads|seo|brand|meta|linkedin|social|full]')
        sys.exit(1)

    t_all = time.time()
    timings: list[tuple[str, float]] = []

    def mark(label: str, t0: float) -> None:
        dt = time.time() - t0
        timings.append((label, dt))
        print(f"[TIME-SUB] {label}: {dt:.1f}s", flush=True)

    client_input = sys.argv[1].strip()
    mode = (sys.argv[2].strip().lower() if len(sys.argv) >= 3 else "full")
    valid_modes = {"full", "google_ads", "seo", "brand", "meta", "linkedin", "social"}
    if mode not in valid_modes:
        print(f"ERRO: modo '{mode}' invalido. Opcoes: {', '.join(sorted(valid_modes))}")
        sys.exit(1)

    client_slug = slugify_client(client_input)
    print(f"\n=== Metricas Final 09: '{client_input}' | modo {mode} ===\n", flush=True)

    t0 = time.time()
    briefing_xlsx = find_client_xlsx(client_input)
    briefing = read_briefing_from_xlsx(briefing_xlsx)
    national_xlsx = find_national_xlsx(client_slug)
    traffic_map = load_traffic_map(national_xlsx)
    competitors = load_top_alto_competitors(national_xlsx, TOP_COMPETITORS)
    site_only = os.environ.get("SPY_SITE_ONLY", "").strip().lower() in ("1", "true", "yes")
    if not competitors and not site_only:
        raise RuntimeError("Nenhum concorrente Alto/Medio encontrado no XLSX nacional.")
    metric_entities = [build_client_entity(briefing, traffic_map)] + competitors
    mark(f"setup (briefing+top {len(competitors)} Alto)", t0)
    print(
        f"[METRICAS] Entidades: {len(metric_entities)} "
        f"(cliente + {len(competitors)} concorrentes"
        f"{'; site_only' if site_only else ''})",
        flush=True,
    )

    out_path = OUTPUT_DIR / client_slug / f"metricas-concorrentes-{client_slug}.xlsx"
    existing_maps = load_existing_channel_map(out_path) if out_path.exists() else {}
    for ent in metric_entities:
        prev = existing_maps.get(ent.get("domain") or "", {})
        if prev.get("instagram_url") and not ent.get("instagram_url"):
            ent["instagram_url"] = prev.get("instagram_url")

    meta_map: dict[str, dict] = {}
    google_ads_map: dict[str, dict] = {}
    linkedin_map: dict[str, dict] = {}
    collect_social = False
    keep_meta = keep_google = keep_linkedin = keep_social = False

    if mode == "full":
        t0 = time.time()
        print("[METRICAS] Subetapa Meta Ads Library (ScrapingBee GraphQL) ...", flush=True)
        meta_map = load_meta_map(metric_entities)
        mark("Meta Ads (ScrapingBee)", t0)

        t0 = time.time()
        print("[METRICAS] Subetapa Google Ads Transparency (ScrapingBee) ...", flush=True)
        google_ads_map = load_google_ads_map(metric_entities)
        mark("Google Ads (ScrapingBee)", t0)

        t0 = time.time()
        print("[METRICAS] Subetapa LinkedIn Ad Library (ScrapingBee) ...", flush=True)
        linkedin_map = load_linkedin_map(metric_entities)
        mark("LinkedIn Ads (ScrapingBee)", t0)
        collect_social = True

    elif mode == "google_ads":
        t0 = time.time()
        print("[METRICAS] Subetapa Google Ads Transparency (somente este canal) ...", flush=True)
        google_ads_map = load_google_ads_map(metric_entities)
        mark("Google Ads (ScrapingBee)", t0)
        keep_meta = keep_linkedin = keep_social = True

    elif mode == "meta":
        t0 = time.time()
        print("[METRICAS] Subetapa Meta Ads Library (somente este canal) ...", flush=True)
        meta_map = load_meta_map(metric_entities)
        mark("Meta Ads (ScrapingBee)", t0)
        keep_google = keep_linkedin = keep_social = True

    elif mode == "linkedin":
        t0 = time.time()
        print("[METRICAS] Subetapa LinkedIn Ads (somente este canal) ...", flush=True)
        linkedin_map = load_linkedin_map(metric_entities)
        mark("LinkedIn Ads (ScrapingBee)", t0)
        keep_meta = keep_google = keep_social = True

    elif mode == "social":
        t0 = time.time()
        print("[METRICAS] Subetapa Instagram + YouTube (sem TikTok) ...", flush=True)
        collect_social = True
        keep_meta = keep_google = keep_linkedin = True
        mark("setup social (ads rematched under lock)", t0)

    elif mode in ("seo", "brand"):
        print(
            f"[METRICAS] Modo {mode}: reaproveitando SEO/Marca do XLSX nacional (sem ScrapingBee).",
            flush=True,
        )
        keep_meta = keep_google = keep_linkedin = keep_social = True

    collected_rows = None
    if collect_social:
        t0 = time.time()
        print("[METRICAS] Subetapa redes sociais (homepage + followers, sem TikTok) ...", flush=True)
        collected_rows = build_metric_rows(
            metric_entities, traffic_map, meta_map, google_ads_map, linkedin_map, collect_social=True,
        )
        mark("Redes sociais (links+followers)", t0)

    keep_domains = {c["domain"] for c in competitors}
    traffic_rows = filtered_sheet(load_sheet_rows(national_xlsx, "Trafego SEO Marca"), keep_domains, include_client=True)
    growth_rows = filtered_sheet(load_sheet_rows(national_xlsx, "Crescimento"), keep_domains, include_client=True)

    t0 = time.time()
    with _xlsx_write_lock(out_path):
        latest = load_existing_channel_map(out_path) if out_path.exists() else {}
        print(
            f"[METRICAS] XLSX lock · re-read {len(latest)} domain(s) before merge+save ({mode})",
            flush=True,
        )
        _seed_keep_maps(
            latest,
            meta_map,
            google_ads_map,
            linkedin_map,
            keep_meta=keep_meta,
            keep_google=keep_google,
            keep_linkedin=keep_linkedin,
        )
        if collected_rows is not None:
            metric_rows = collected_rows
            _merge_preserved_channels(
                metric_rows,
                latest,
                keep_meta=keep_meta,
                keep_google=keep_google,
                keep_linkedin=keep_linkedin,
                keep_social=False,
            )
        else:
            metric_rows = build_metric_rows(
                metric_entities, traffic_map, meta_map, google_ads_map, linkedin_map, collect_social=False,
            )
            _merge_preserved_channels(
                metric_rows,
                latest,
                keep_meta=keep_meta,
                keep_google=keep_google,
                keep_linkedin=keep_linkedin,
                keep_social=keep_social,
            )
        saved = write_metrics_xlsx(
            out_path,
            client_input,
            briefing,
            competitors,
            metric_rows,
            traffic_rows,
            growth_rows,
            national_xlsx,
        )
    # HTML completo so no modo full (evita custo nas etapas separadas do chat)
    if mode == "full":
        html_path = generate_html_from_xlsx(saved)
        mark("Gravacao XLSX+HTML", t0)
        print(f"[OUT] HTML salvo: {html_path}")
    else:
        mark(f"Gravacao XLSX ({mode})", t0)

    print(f"[OUT] XLSX salvo: {saved}")
    print("\n[METRICAS] Resumo de subetapas:", flush=True)
    for label, dt in timings:
        print(f"  - {label}: {dt:.1f}s", flush=True)
    print(f"  - TOTAL: {time.time() - t_all:.1f}s", flush=True)


if __name__ == "__main__":
    main()
