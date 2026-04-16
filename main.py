import io
import math
import os
import re
import time
import unicodedata
from collections import Counter
from datetime import date, datetime, timezone
from html import unescape
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import feedparser
import requests
import streamlit as st
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from docx import Document

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None


APP_TITLE = "Nutreco Iberia | Radar sectorial"
USER_AGENT = "Mozilla/5.0 (compatible; NutrecoRadar/5.0; +https://streamlit.io)"
REQUEST_TIMEOUT = 25
DEFAULT_MAX_RESULTS = 12
MAX_CONTEXT_ITEMS = 8

CATEGORY_LABELS = {
    "market": "Mercado",
    "science": "Científico-técnico",
    "regulation": "Legislación y regulación",
}

DEFAULT_COMPANY_CONTEXT = """Contexto y criterios para las recomendaciones:
- Empresa: Nutreco Iberia (alimentación animal y soluciones técnicas).
- Priorizar acciones con valor técnico-comercial, soporte a ventas, vigilancia regulatoria y generación de contenido.
- Proponer medidas accionables, realistas y priorizadas.
- Diferenciar entre acciones inmediatas, a 30-90 días y de seguimiento.
- Evitar afirmaciones no sustentadas por las fuentes recuperadas.
"""

LEGAL_ANCHORS = [
    "reglamento", "regulation", "real decreto", "ley", "orden", "resolución", "decision", "directive",
    "directiva", "regulatory", "normativa", "boe", "eur-lex", "efsa", "ministerio", "animal health law",
    "sanidad animal", "bienestar animal", "trazabilidad", "identificación", "movement", "movimientos",
]

MARKET_ANCHORS = [
    "precio", "precios", "cotización", "cotizaciones", "mercado", "markets", "market", "boletín",
    "boletin", "trade", "consumo", "exportación", "exportacion", "importación", "importacion",
    "outlook", "coste", "costes", "margen", "margins", "feed cost", "raw materials", "piensos",
]

OFFICIAL_REGULATORY_DOMAINS = {
    "boe.es", "www.boe.es", "eur-lex.europa.eu", "europa.eu", "mapa.gob.es", "www.mapa.gob.es",
    "aesan.gob.es", "www.aesan.gob.es", "miteco.gob.es", "www.miteco.gob.es", "sanidad.gob.es",
    "www.sanidad.gob.es", "efsa.europa.eu", "www.efsa.europa.eu",
}

OFFICIAL_MARKET_DOMAINS = {
    "mapa.gob.es", "www.mapa.gob.es", "gob.es", "www.gob.es",
}

MARKET_MEDIA_DOMAINS = {
    "efeagro.com", "www.efeagro.com", "agrodigital.com", "www.agrodigital.com",
    "interempresas.net", "www.interempresas.net", "avicultura.com", "www.avicultura.com",
    "porcino.info", "www.porcino.info", "vacapinta.com", "www.vacapinta.com",
}

SPECIES_OPTIONS: Dict[str, Dict[str, List[str]]] = {
    "Avicultura de puesta": {
        "aliases": ["avicultura de puesta", "gallinas ponedoras", "huevos", "layers", "laying hens", "egg sector"],
        "market": ["precio huevo", "mercado del huevo", "costes de producción", "consumo", "clasificación y comercialización"],
        "science": ["nutrition", "shell quality", "salmonella", "welfare", "persistencia de puesta"],
        "regulation": ["gallinas ponedoras", "salmonella", "bioseguridad", "bienestar animal", "etiquetado del huevo"],
    },
    "Avicultura de carne": {
        "aliases": ["avicultura de carne", "pollos de engorde", "broilers", "broiler chickens", "pollo", "chicken meat sector"],
        "market": ["precio pollo", "mercado avícola", "costes de producción", "consumo", "exportación"],
        "science": ["nutrition", "gut health", "coccidiosis", "necrotic enteritis", "performance"],
        "regulation": ["pollos de engorde", "bioseguridad", "influenza aviar", "bienestar animal", "residuos"],
    },
    "Porcino": {
        "aliases": ["porcino", "cerdo", "swine", "pig", "pigs", "hog sector"],
        "market": ["precio cerdo", "mercado porcino", "costes de alimentación", "exportación", "mataderos"],
        "science": ["nutrition", "gut health", "weaning", "reproduction", "biosecurity"],
        "regulation": ["peste porcina africana", "African swine fever", "bioseguridad", "bienestar animal", "emisiones"],
    },
    "Vacuno de leche": {
        "aliases": ["vacuno de leche", "vacas de leche", "sector lácteo", "dairy cattle", "dairy cows", "milk sector"],
        "market": ["precio leche", "mercado lácteo", "costes de alimentación", "márgenes", "recogida de leche"],
        "science": ["nutrition", "rumen", "fertility", "mastitis", "transition cow", "methane"],
        "regulation": ["calidad de leche", "bienestar animal", "emisiones", "sanidad animal", "sostenibilidad"],
    },
    "Vacuno de carne": {
        "aliases": ["vacuno de carne", "beef cattle", "beef sector", "cebaderos", "fattening cattle"],
        "market": ["precio vacuno", "mercado vacuno", "costes de alimentación", "exportación", "canales"],
        "science": ["nutrition", "average daily gain", "respiratory disease", "welfare", "methane"],
        "regulation": ["bienestar animal", "transporte", "trazabilidad", "emisiones", "antibióticos"],
    },
    "Ovino": {
        "aliases": ["ovino", "cordero", "sheep", "ovine", "lamb sector", "ovino de leche"],
        "market": ["precio cordero", "mercado ovino", "leche ovina", "costes de alimentación", "exportación"],
        "science": ["nutrition", "parasites", "reproduction", "rumen", "milk quality"],
        "regulation": ["lengua azul", "bluetongue", "bienestar animal", "movimientos", "trazabilidad"],
    },
    "Caprino": {
        "aliases": ["caprino", "goat", "goats", "goat milk", "caprine sector"],
        "market": ["precio leche de cabra", "mercado caprino", "queso de cabra", "costes de alimentación"],
        "science": ["nutrition", "mastitis", "parasites", "reproduction", "kid growth"],
        "regulation": ["bienestar animal", "movimientos", "trazabilidad", "sanidad animal", "higiene"],
    },
    "Cunicultura": {
        "aliases": ["cunicultura", "conejos", "conejo", "rabbit production", "rabbit sector"],
        "market": ["precio conejo", "mercado cunícola", "costes de alimentación", "consumo"],
        "science": ["nutrition", "enteropathy", "digestive health", "welfare", "reproduction"],
        "regulation": ["bienestar animal", "bioseguridad", "antimicrobianos", "medicación veterinaria"],
    },
}

TERM_SYNONYMS: Dict[str, List[str]] = {
    "peste porcina africana": ["African swine fever", "ASF", "ASFV", "jabalí", "wild boar"],
    "ppa": ["peste porcina africana", "African swine fever", "ASF", "ASFV"],
    "influenza aviar": ["avian influenza", "bird flu", "HPAI", "H5N1"],
    "ia": ["influenza aviar", "avian influenza", "HPAI", "H5N1"],
    "lengua azul": ["bluetongue", "BTV", "orbivirus"],
    "mastitis": ["mamitis", "udder health", "intramammary infection"],
    "mamitis": ["mastitis", "udder health", "intramammary infection"],
    "metano": ["methane", "enteric methane", "GHG", "huella de carbono"],
    "bienestar animal": ["animal welfare", "welfare"],
    "bienestar": ["animal welfare", "welfare"],
    "bioseguridad": ["biosecurity", "farm biosecurity", "disease prevention"],
    "trazabilidad": ["traceability", "identification", "animal movements"],
    "movimientos": ["movimientos animales", "animal movements", "transport", "movement restrictions"],
    "sanidad animal": ["animal health", "Animal Health Law", "disease control"],
    "piensos": ["feed", "compound feed", "feed costs", "raw materials"],
    "costes de alimentación": ["feed costs", "feed cost", "raw materials", "soybean meal", "corn"],
    "precio leche": ["milk price", "farmgate milk price", "dairy prices"],
    "precio huevo": ["egg price", "egg prices", "egg market"],
    "precio pollo": ["broiler price", "chicken price", "poultry prices"],
    "precio cerdo": ["pig price", "hog price", "swine prices"],
    "precio cordero": ["lamb price", "sheep prices"],
    "normativa": ["regulation", "legislation", "real decreto", "reglamento"],
    "regulación": ["regulation", "legislation", "real decreto", "reglamento"],
}

WORD_TRANSLATIONS = {
    "nutricion": "nutrition",
    "sanidad": "health",
    "bienestar": "welfare",
    "mercado": "market",
    "precio": "price",
    "precios": "prices",
    "coste": "cost",
    "costes": "costs",
    "emisiones": "emissions",
    "sostenibilidad": "sustainability",
    "legislacion": "legislation",
    "regulacion": "regulation",
    "normativa": "regulation",
    "leche": "milk",
    "carne": "meat",
    "huevo": "egg",
    "huevos": "eggs",
    "pollo": "chicken",
    "cerdo": "pig",
    "porcino": "swine",
    "ovino": "sheep",
    "caprino": "goat",
    "vacuno": "cattle",
    "conejo": "rabbit",
}

STOPWORDS = {
    "de", "la", "el", "los", "las", "y", "o", "en", "para", "por", "con", "del", "al", "un", "una",
    "que", "sobre", "from", "the", "and", "for", "entre", "como", "más", "menos", "this", "that",
    "market", "mercado", "regulation", "science", "technical", "legislation", "animal", "production",
    "ministerio", "agricultura", "españa", "espana",
}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s\-/]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _strip_html(text: str) -> str:
    return BeautifulSoup(text or "", "html.parser").get_text(" ", strip=True)


def _truncate(text: str, max_len: int = 420) -> str:
    text = text or ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _request(url: str, *, params: Optional[dict] = None, expect: str = "text"):
    last_error: Optional[Exception] = None
    for attempt in range(2):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json, application/xml, text/xml, text/html, */*",
                },
            )
            response.raise_for_status()
            if expect == "json":
                return response.json()
            if expect == "content":
                return response.content
            return response.text
        except Exception as exc:  # pragma: no cover
            last_error = exc
            if attempt == 0:
                time.sleep(0.7)
    raise RuntimeError(f"Error al consultar la fuente externa: {last_error}")


def _ensure_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return _ensure_naive_utc(date_parser.parse(str(value)))
    except Exception:
        return None


def _date_in_range(value: Optional[datetime], start: date, end: date) -> bool:
    if value is None:
        return True
    return start <= value.date() <= end


def _safe_iso(value: Optional[datetime]) -> str:
    return value.isoformat() if value else ""


def _clean_url(url: str, base_url: str = "") -> str:
    if not url:
        return ""
    return urljoin(base_url, url.strip())


def _canonical_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    return f"{parsed.netloc.lower()}{parsed.path.rstrip('/').lower()}"


def _domain(url: str) -> str:
    return urlparse(url or "").netloc.lower()


def _extract_ddg_url(raw_url: str) -> str:
    href = (raw_url or "").strip()
    if not href:
        return ""
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/l/?") or href.startswith("https://duckduckgo.com/l/?"):
        parsed = urlparse(href)
        query = parse_qs(parsed.query)
        uddg = query.get("uddg", [""])[0]
        return unquote(uddg) if uddg else ""
    return href


def _record_key(item: dict) -> Tuple[str, str]:
    doi = _normalize(item.get("doi", ""))
    if doi:
        return ("doi", doi)
    url = _canonical_url(item.get("url", ""))
    if url:
        return ("url", url)
    return ("title", _normalize(item.get("title", "")))


def _dedupe(records: List[dict]) -> List[dict]:
    seen = set()
    out: List[dict] = []
    for item in records:
        key = _record_key(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _unique_keep_order(items: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        item = re.sub(r"\s+", " ", (item or "").strip())
        if not item:
            continue
        key = _normalize(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _keywords_from_text(text: str, top_k: int = 8) -> List[str]:
    words = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñÜü0-9\-]{4,}", text.lower())
    counts = Counter(w for w in words if _normalize(w) not in STOPWORDS)
    return [w for w, _ in counts.most_common(top_k)]


def parse_user_phrases(text: str) -> List[str]:
    parts = re.split(r"[\n,;|]+", text or "")
    return _unique_keep_order([re.sub(r"\s+", " ", p).strip(" .") for p in parts if p.strip()])


def _maybe_translate_phrase(term: str) -> List[str]:
    normalized = _normalize(term)
    words = normalized.split()
    if not words:
        return []
    translated = [WORD_TRANSLATIONS.get(word, word) for word in words]
    if translated == words:
        return []
    candidate = " ".join(translated)
    return [candidate] if candidate and candidate != normalized else []


def expand_phrase(term: str) -> List[str]:
    normalized = _normalize(term)
    out = [term]
    if normalized in TERM_SYNONYMS:
        out.extend(TERM_SYNONYMS[normalized])
    out.extend(_maybe_translate_phrase(term))

    for token in normalized.split():
        if token in TERM_SYNONYMS:
            out.extend(TERM_SYNONYMS[token])

    for key, values in TERM_SYNONYMS.items():
        if normalized in {_normalize(v) for v in values}:
            out.append(key)
            out.extend(values)

    return _unique_keep_order(out)


def build_keyword_meta(species: str, user_keywords: str) -> dict:
    profile = SPECIES_OPTIONS[species]
    user_phrases = parse_user_phrases(user_keywords)

    expanded_terms: List[str] = []
    for phrase in user_phrases:
        expanded_terms.extend(expand_phrase(phrase))
    expanded_terms = _unique_keep_order(expanded_terms)

    if not expanded_terms:
        expanded_terms = _unique_keep_order(profile["market"][:2] + profile["science"][:2])

    species_terms = _unique_keep_order(profile["aliases"])
    market_terms = _unique_keep_order(expanded_terms + profile["market"] + MARKET_ANCHORS)
    science_terms = _unique_keep_order(expanded_terms + profile["science"])
    regulation_terms = _unique_keep_order(expanded_terms + profile["regulation"] + LEGAL_ANCHORS)

    return {
        "species_terms": species_terms,
        "user_phrases": user_phrases,
        "expanded_terms": expanded_terms,
        "market_terms": market_terms,
        "science_terms": science_terms,
        "regulation_terms": regulation_terms,
    }


def _match_count(text: str, terms: Sequence[str]) -> int:
    haystack = _normalize(text)
    hits = 0
    for term in terms:
        needle = _normalize(term)
        if needle and needle in haystack:
            hits += 1
    return hits


def _has_any(text: str, terms: Sequence[str]) -> bool:
    return _match_count(text, terms) > 0


def _format_result(item: dict, category: str) -> dict:
    current = dict(item)
    current["category"] = CATEGORY_LABELS[category]
    return current


def _score_recency(published: Optional[datetime]) -> float:
    if not published:
        return 0.0
    age_days = max((_ensure_naive_utc(datetime.utcnow()) - published).days, 0)
    if age_days <= 30:
        return 1.0
    if age_days <= 90:
        return 0.6
    if age_days <= 365:
        return 0.2
    return 0.0


# -------------------------
# External sources
# -------------------------

@st.cache_data(show_spinner=False, ttl=3600)
def search_google_news(query: str, start_date: date, end_date: date, max_results: int = 10) -> List[dict]:
    content = _request(
        "https://news.google.com/rss/search",
        params={"q": query, "hl": "es", "gl": "ES", "ceid": "ES:es"},
        expect="content",
    )
    feed = feedparser.parse(content)
    records: List[dict] = []
    for entry in feed.entries:
        published = _parse_date(entry.get("published") or entry.get("pubDate"))
        if not _date_in_range(published, start_date, end_date):
            continue
        source = "Google News"
        if isinstance(entry.get("source"), dict):
            source = entry.get("source", {}).get("title", source)
        records.append(
            {
                "title": _strip_html(entry.get("title", "Sin título")),
                "snippet": _truncate(_strip_html(entry.get("summary", ""))),
                "url": _clean_url(entry.get("link", "")),
                "source": source,
                "published": _safe_iso(published),
                "source_db": "Google News",
                "query_used": query,
            }
        )
        if len(records) >= max_results:
            break
    return _dedupe(records)


@st.cache_data(show_spinner=False, ttl=3600)
def search_duckduckgo_html(query: str, max_results: int = 10) -> List[dict]:
    html = _request("https://html.duckduckgo.com/html/", params={"q": query}, expect="text")
    soup = BeautifulSoup(html, "html.parser")
    records: List[dict] = []
    for result in soup.select(".result"):
        link_tag = result.select_one("a.result__a") or result.select_one("a[href]")
        if not link_tag:
            continue
        url = _extract_ddg_url(link_tag.get("href", ""))
        title = _strip_html(link_tag.get_text(" ", strip=True))
        snippet_tag = result.select_one(".result__snippet") or result.select_one(".result__extras__url")
        snippet = _strip_html(snippet_tag.get_text(" ", strip=True)) if snippet_tag else ""
        if not url or not title:
            continue
        records.append(
            {
                "title": title,
                "snippet": _truncate(unescape(snippet)),
                "url": url,
                "source": _domain(url) or "DuckDuckGo",
                "published": "",
                "source_db": "DuckDuckGo",
                "query_used": query,
            }
        )
        if len(records) >= max_results:
            break
    return _dedupe(records)


@st.cache_data(show_spinner=False, ttl=3600)
def search_gdelt_articles(query: str, start_date: date, end_date: date, max_results: int = 15) -> List[dict]:
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": max_results,
        "sort": "datedesc",
        "startdatetime": start_date.strftime("%Y%m%d000000"),
        "enddatetime": end_date.strftime("%Y%m%d235959"),
    }
    data = _request("https://api.gdeltproject.org/api/v2/doc/doc", params=params, expect="json")
    articles = data.get("articles", []) or data.get("artlist", []) or []
    records: List[dict] = []
    for item in articles:
        published = _parse_date(item.get("seendate") or item.get("date"))
        if not _date_in_range(published, start_date, end_date):
            continue
        url = item.get("url", "")
        records.append(
            {
                "title": _strip_html(item.get("title", "Sin título")),
                "snippet": _truncate(item.get("snippet") or item.get("domain") or ""),
                "url": url,
                "source": item.get("domain") or _domain(url) or "GDELT",
                "published": _safe_iso(published),
                "source_db": "GDELT",
                "query_used": query,
            }
        )
    return _dedupe(records)


@st.cache_data(show_spinner=False, ttl=3600)
def search_mapa_press_rss(start_date: date, end_date: date, max_results: int = 20) -> List[dict]:
    try:
        content = _request("https://www.mapa.gob.es/es/prensa/noticiasrss", expect="content")
    except Exception:
        return []
    feed = feedparser.parse(content)
    records: List[dict] = []
    for entry in feed.entries:
        published = _parse_date(entry.get("published") or entry.get("updated") or entry.get("pubDate"))
        if not _date_in_range(published, start_date, end_date):
            continue
        records.append(
            {
                "title": _strip_html(entry.get("title", "Sin título")),
                "snippet": _truncate(_strip_html(entry.get("summary", ""))),
                "url": _clean_url(entry.get("link", "")),
                "source": "MAPA",
                "published": _safe_iso(published),
                "source_db": "MAPA RSS",
                "query_used": "MAPA RSS",
            }
        )
        if len(records) >= max_results:
            break
    return _dedupe(records)


@st.cache_data(show_spinner=False, ttl=7200)
def search_openalex(query: str, start_date: date, end_date: date, max_results: int = 12) -> List[dict]:
    filters = f"from_publication_date:{start_date.isoformat()},to_publication_date:{end_date.isoformat()}"
    data = _request(
        "https://api.openalex.org/works",
        params={"search": query, "filter": filters, "per-page": max_results, "sort": "relevance_score:desc"},
        expect="json",
    )
    records: List[dict] = []
    for item in data.get("results", []):
        title = _strip_html(item.get("title", "Sin título"))
        abstract = ""
        inverted = item.get("abstract_inverted_index") or {}
        if inverted:
            words = sorted(((idx, token) for token, idxs in inverted.items() for idx in idxs), key=lambda x: x[0])
            abstract = " ".join(token for _, token in words)
        doi = item.get("doi") or ""
        published = _parse_date(item.get("publication_date") or item.get("publication_year"))
        records.append(
            {
                "title": title,
                "snippet": _truncate(abstract or ((item.get("primary_location") or {}).get("source") or {}).get("display_name", "")),
                "url": doi or ((item.get("primary_location") or {}).get("landing_page_url") or ""),
                "source": ((item.get("primary_location") or {}).get("source") or {}).get("display_name", "OpenAlex"),
                "journal": ((item.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
                "published": _safe_iso(published),
                "authors": ", ".join(a.get("author", {}).get("display_name", "") for a in item.get("authorships", [])[:6]),
                "doi": doi,
                "source_db": "OpenAlex",
                "cited_by_count": item.get("cited_by_count", 0),
                "query_used": query,
            }
        )
    return _dedupe(records)


@st.cache_data(show_spinner=False, ttl=7200)
def search_europe_pmc(query: str, start_date: date, end_date: date, max_results: int = 12) -> List[dict]:
    epmc_query = f'({query}) AND FIRST_PDATE:[{start_date.isoformat()} TO {end_date.isoformat()}]'
    data = _request(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": epmc_query, "format": "json", "pageSize": max_results, "sort": "FIRST_PDATE_D"},
        expect="json",
    )
    records: List[dict] = []
    for item in data.get("resultList", {}).get("result", []):
        published = _parse_date(item.get("firstPublicationDate") or item.get("pubYear"))
        doi = item.get("doi") or ""
        url = doi and f"https://doi.org/{doi}" or ""
        if not url and item.get("pmid"):
            url = f"https://europepmc.org/article/MED/{item['pmid']}"
        if not url and item.get("pmcid"):
            url = f"https://europepmc.org/article/PMC/{item['pmcid']}"
        records.append(
            {
                "title": _strip_html(item.get("title", "Sin título")),
                "snippet": _truncate(_strip_html(item.get("abstractText", "")) or item.get("journalTitle", "")),
                "url": url,
                "source": item.get("journalTitle", "Europe PMC"),
                "journal": item.get("journalTitle", ""),
                "published": _safe_iso(published),
                "authors": item.get("authorString", ""),
                "doi": doi,
                "source_db": "Europe PMC",
                "cited_by_count": 0,
                "query_used": query,
            }
        )
    return _dedupe(records)


# -------------------------
# Query building
# -------------------------


def _q(term: str) -> str:
    term = re.sub(r'["“”]', "", (term or "").strip())
    if not term:
        return ""
    if " " in term or "-" in term:
        return f'"{term}"'
    return term


def build_market_queries(species: str, meta: dict) -> List[str]:
    species_main = SPECIES_OPTIONS[species]["aliases"][0]
    topic_terms = meta["expanded_terms"][:4]
    queries = [
        f'{_q(species_main)} noticias',
        f'{_q(species_main)} precios mercado',
        f'site:mapa.gob.es {_q(species_main)} precios',
        f'site:mapa.gob.es {_q(species_main)} boletín precios',
        f'site:mapa.gob.es {_q(species_main)} mercado ganadero',
        f'site:gob.es {_q(species_main)} ministerio noticias',
    ]
    for term in topic_terms[:3]:
        queries.extend(
            [
                f'{_q(species_main)} {_q(term)} noticias',
                f'{_q(species_main)} {_q(term)} mercado',
                f'site:mapa.gob.es {_q(species_main)} {_q(term)}',
                f'site:gob.es {_q(species_main)} {_q(term)}',
            ]
        )
    return _unique_keep_order(queries)[:10]


def build_regulation_queries(species: str, meta: dict) -> List[str]:
    species_main = SPECIES_OPTIONS[species]["aliases"][0]
    topic_terms = meta["expanded_terms"][:4]
    queries = [
        f'site:boe.es {_q(species_main)} normativa',
        f'site:eur-lex.europa.eu {_q(species_main)} regulation',
        f'site:mapa.gob.es {_q(species_main)} normativa',
    ]
    for term in topic_terms[:3]:
        queries.extend(
            [
                f'site:boe.es {_q(species_main)} {_q(term)} (reglamento OR "real decreto" OR orden OR resolución)',
                f'site:eur-lex.europa.eu {_q(species_main)} {_q(term)} regulation',
                f'site:mapa.gob.es {_q(species_main)} {_q(term)} normativa',
                f'site:efsa.europa.eu {_q(species_main)} {_q(term)}',
            ]
        )
    return _unique_keep_order(queries)[:12]


def build_science_queries(species: str, meta: dict) -> List[str]:
    profile = SPECIES_OPTIONS[species]
    species_en = next((t for t in profile["aliases"] if t.isascii() and " " in t or t in {"swine", "pig", "sheep", "goat"}), profile["aliases"][0])
    topic_terms = meta["expanded_terms"][:4]
    if not topic_terms:
        topic_terms = profile["science"][:3]
    queries = [f'{species_en} {term}' for term in topic_terms[:3]]
    queries.extend([f'{profile["aliases"][0]} {term}' for term in topic_terms[:2]])
    return _unique_keep_order(queries)[:6]


# -------------------------
# Relevance and ranking
# -------------------------


def _topic_terms_for_strict_filter(meta: dict) -> List[str]:
    return meta["user_phrases"] or meta["expanded_terms"][:4]


def is_market_relevant(item: dict, meta: dict) -> bool:
    text = " ".join(filter(None, [item.get("title", ""), item.get("snippet", ""), item.get("source", "")]))
    species_hits = _match_count(text, meta["species_terms"])
    topic_terms = _topic_terms_for_strict_filter(meta)
    topic_hits = _match_count(text, topic_terms)
    market_hits = _match_count(text, MARKET_ANCHORS + meta["market_terms"])
    domain = _domain(item.get("url", ""))

    if topic_terms:
        if topic_hits == 0 and not (species_hits > 0 and market_hits > 1):
            return False
    if species_hits == 0 and domain not in OFFICIAL_MARKET_DOMAINS and topic_hits == 0:
        return False
    return market_hits > 0 or domain in OFFICIAL_MARKET_DOMAINS or domain in MARKET_MEDIA_DOMAINS


def is_regulatory_relevant(item: dict, meta: dict) -> bool:
    text = " ".join(filter(None, [item.get("title", ""), item.get("snippet", ""), item.get("source", ""), item.get("url", "")]))
    species_hits = _match_count(text, meta["species_terms"])
    topic_terms = _topic_terms_for_strict_filter(meta)
    topic_hits = _match_count(text, topic_terms)
    legal_hits = _match_count(text, LEGAL_ANCHORS)
    domain = _domain(item.get("url", ""))
    is_official = domain in OFFICIAL_REGULATORY_DOMAINS

    if not is_official:
        return False
    if legal_hits == 0 and domain not in {"boe.es", "www.boe.es", "eur-lex.europa.eu"}:
        return False
    if topic_terms:
        if topic_hits == 0:
            return False
        if species_hits == 0 and topic_hits < 2:
            return False
    else:
        if species_hits == 0:
            return False
    return True


def score_market(item: dict, meta: dict) -> float:
    text = " ".join(filter(None, [item.get("title", ""), item.get("snippet", ""), item.get("source", "")]))
    species_hits = _match_count(text, meta["species_terms"])
    topic_hits = _match_count(text, _topic_terms_for_strict_filter(meta))
    market_hits = _match_count(text, MARKET_ANCHORS + meta["market_terms"])
    domain = _domain(item.get("url", ""))
    score = species_hits * 1.4 + topic_hits * 2.0 + market_hits * 0.6 + _score_recency(_parse_date(item.get("published")))
    if domain in OFFICIAL_MARKET_DOMAINS:
        score += 1.1
    if domain in MARKET_MEDIA_DOMAINS:
        score += 0.6
    if item.get("source_db") == "MAPA RSS":
        score += 0.8
    if item.get("source_db") == "Google News":
        score += 0.3
    if item.get("source_db") == "GDELT":
        score += 0.4
    return score


def score_regulation(item: dict, meta: dict) -> float:
    text = " ".join(filter(None, [item.get("title", ""), item.get("snippet", ""), item.get("source", "")]))
    species_hits = _match_count(text, meta["species_terms"])
    topic_hits = _match_count(text, _topic_terms_for_strict_filter(meta))
    legal_hits = _match_count(text, LEGAL_ANCHORS)
    domain = _domain(item.get("url", ""))
    score = species_hits * 1.4 + topic_hits * 2.6 + legal_hits * 1.3 + _score_recency(_parse_date(item.get("published")))
    if domain in {"boe.es", "www.boe.es"}:
        score += 2.0
    elif domain == "eur-lex.europa.eu":
        score += 1.8
    elif domain in OFFICIAL_REGULATORY_DOMAINS:
        score += 1.0
    return score


def score_science(item: dict, meta: dict) -> float:
    text = " ".join(filter(None, [item.get("title", ""), item.get("snippet", ""), item.get("authors", ""), item.get("journal", "")]))
    species_hits = _match_count(text, meta["species_terms"])
    topic_hits = _match_count(text, meta["expanded_terms"])
    score = species_hits * 1.0 + topic_hits * 2.2 + _score_recency(_parse_date(item.get("published")))
    cited_by = item.get("cited_by_count") or 0
    if cited_by:
        score += min(math.log1p(cited_by), 3.0) * 0.35
    if item.get("source_db") == "Europe PMC":
        score += 0.6
    if item.get("source_db") == "OpenAlex":
        score += 0.4
    return score


# -------------------------
# Category searches
# -------------------------


def search_market_sources(species: str, meta: dict, start_date: date, end_date: date, max_results: int = DEFAULT_MAX_RESULTS) -> Tuple[List[dict], List[str]]:
    queries = build_market_queries(species, meta)
    records: List[dict] = []

    try:
        rss_items = search_mapa_press_rss(start_date, end_date, max_results=25)
        records.extend(rss_items)
    except Exception:
        pass

    for query in queries[:4]:
        try:
            records.extend(search_google_news(query, start_date, end_date, max_results=8))
        except Exception:
            continue

    for query in queries[:4]:
        try:
            records.extend(search_gdelt_articles(query, start_date, end_date, max_results=8))
        except Exception:
            continue

    for query in queries[:6]:
        try:
            records.extend(search_duckduckgo_html(query, max_results=8))
        except Exception:
            continue

    filtered = [r for r in _dedupe(records) if is_market_relevant(r, meta)]
    ranked = sorted(filtered, key=lambda item: (score_market(item, meta), item.get("published", "")), reverse=True)
    return [_format_result(r, "market") for r in ranked[:max_results]], queries


def search_regulation_sources(species: str, meta: dict, start_date: date, end_date: date, max_results: int = DEFAULT_MAX_RESULTS) -> Tuple[List[dict], List[str]]:
    queries = build_regulation_queries(species, meta)
    records: List[dict] = []

    for query in queries:
        try:
            records.extend(search_duckduckgo_html(query, max_results=8))
        except Exception:
            continue

    # Noticias oficiales muy recientes a veces comunican cambios regulatorios.
    for query in queries[:3]:
        try:
            records.extend(search_google_news(query, start_date, end_date, max_results=5))
        except Exception:
            continue

    filtered = [r for r in _dedupe(records) if is_regulatory_relevant(r, meta)]
    ranked = sorted(filtered, key=lambda item: (score_regulation(item, meta), item.get("published", "")), reverse=True)
    return [_format_result(r, "regulation") for r in ranked[:max_results]], queries


def search_science_sources(species: str, meta: dict, start_date: date, end_date: date, max_results: int = DEFAULT_MAX_RESULTS) -> Tuple[List[dict], List[str]]:
    queries = build_science_queries(species, meta)
    records: List[dict] = []
    for query in queries:
        try:
            records.extend(search_openalex(query, start_date, end_date, max_results=8))
        except Exception:
            pass
        try:
            records.extend(search_europe_pmc(query, start_date, end_date, max_results=8))
        except Exception:
            pass

    ranked = sorted(_dedupe(records), key=lambda item: (score_science(item, meta), item.get("published", "")), reverse=True)
    return [_format_result(r, "science") for r in ranked[:max_results]], queries


def flatten_results(results: Dict[str, List[dict]]) -> List[dict]:
    out: List[dict] = []
    for category in ["market", "science", "regulation"]:
        out.extend(results.get(category, []))
    return out


def run_search(species: str, user_keywords: str, start_date: date, end_date: date, max_results: int) -> Tuple[Dict[str, List[dict]], Dict[str, List[str]]]:
    meta = build_keyword_meta(species, user_keywords)
    market, market_queries = search_market_sources(species, meta, start_date, end_date, max_results=max_results)
    science, science_queries = search_science_sources(species, meta, start_date, end_date, max_results=max_results)
    regulation, regulation_queries = search_regulation_sources(species, meta, start_date, end_date, max_results=max_results)
    return (
        {"market": market, "science": science, "regulation": regulation},
        {"market": market_queries, "science": science_queries, "regulation": regulation_queries},
    )


# -------------------------
# Briefing, chat, export
# -------------------------


def llm_is_available() -> bool:
    return bool(OpenAI and os.getenv("OPENAI_API_KEY"))


def call_openai(system_prompt: str, user_prompt: str) -> str:
    if not llm_is_available():
        raise RuntimeError("No hay configuración de OpenAI disponible.")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    response = client.responses.create(model=model, instructions=system_prompt, input=user_prompt)
    output_text = getattr(response, "output_text", "")
    return (output_text or "").strip()


def corpus_text(results: Dict[str, List[dict]], per_category: int = 6) -> str:
    blocks = []
    for category in ["market", "science", "regulation"]:
        blocks.append(f"[{CATEGORY_LABELS[category]}]")
        for item in results.get(category, [])[:per_category]:
            blocks.append(
                f"- {item.get('title')} | {item.get('source')} | {item.get('published', '')[:10]} | {item.get('snippet', '')} | {item.get('url', '')}"
            )
    return "\n".join(blocks)


def bibliography_entries(results: Dict[str, List[dict]]) -> List[str]:
    entries = []
    for item in flatten_results(results):
        published = item.get("published", "")[:10] or "s/f"
        url = item.get("url", "")
        if item.get("category") == CATEGORY_LABELS["science"]:
            entries.append(
                f"{item.get('authors', 'Autoría no disponible')}. ({published}). {item.get('title')}. {item.get('journal') or item.get('source', 'Fuente científica')}. {item.get('doi') or url}"
            )
        else:
            entries.append(f"{item.get('source', 'Fuente no indicada')}. ({published}). {item.get('title')}. {url}")
    return entries


def extractive_brief(species: str, user_keywords: str, results: Dict[str, List[dict]], company_context: str, chat_history: List[dict]) -> str:
    flat = flatten_results(results)
    if not flat:
        return "No se han recuperado resultados suficientes para elaborar el briefing."

    meta = build_keyword_meta(species, user_keywords)
    corpus = " ".join(filter(None, [item.get("title", "") + " " + item.get("snippet", "") for item in flat]))
    themes = _keywords_from_text(corpus, top_k=12)

    market_items = results.get("market", [])[:4]
    science_items = results.get("science", [])[:4]
    reg_items = results.get("regulation", [])[:4]

    cross_summary = []
    if market_items:
        cross_summary.append(f"mercado: {len(results.get('market', []))} señales recuperadas")
    if science_items:
        cross_summary.append(f"ciencia: {len(results.get('science', []))} publicaciones")
    if reg_items:
        cross_summary.append(f"regulación: {len(results.get('regulation', []))} referencias oficiales")

    lines = [
        f"# Briefing radar | {species}",
        "",
        "## Resumen ejecutivo",
        f"Búsqueda enfocada en **{user_keywords or species}** para **{species}**.",
        f"Cobertura recuperada: {', '.join(cross_summary) if cross_summary else 'sin cobertura suficiente'}.",
        f"Tema(s) dominantes detectados en el conjunto de resultados: {', '.join(themes[:8]) if themes else 'sin patrón claro'}.",
        "",
        "## Síntesis integrada del radar",
        f"La búsqueda conjunta sugiere que las señales más útiles para seguimiento combinan los términos de especie ({', '.join(meta['species_terms'][:3])}) con los focos temáticos ({', '.join(meta['expanded_terms'][:5])}). "
        f"En mercado predominan noticias de prensa y publicaciones institucionales; en ciencia, artículos de revisión y trabajos recientes; en regulación, documentos oficiales filtrados de forma estricta para que incluyan tanto el tema como la especie o un equivalente directo.",
        "",
        "## Radar de mercado",
    ]

    if market_items:
        for item in market_items:
            lines.append(f"- **{item['title']}** ({item.get('source', 'Fuente')}, {item.get('published', 's/f')[:10]}). {item.get('snippet', '')}")
    else:
        lines.append("- No se han encontrado resultados de mercado suficientemente relevantes con la combinación actual de filtros.")

    lines.extend(["", "## Radar científico-técnico"])
    if science_items:
        for item in science_items:
            lines.append(f"- **{item['title']}** ({item.get('journal') or item.get('source', 'Fuente científica')}, {item.get('published', 's/f')[:10]}). {item.get('snippet', '')}")
    else:
        lines.append("- No se han encontrado publicaciones suficientes con la combinación actual de filtros.")

    lines.extend(["", "## Radar regulatorio"])
    if reg_items:
        for item in reg_items:
            lines.append(f"- **{item['title']}** ({item.get('source', 'Fuente oficial')}, {item.get('published', 's/f')[:10]}). {item.get('snippet', '')}")
    else:
        lines.append("- No se han encontrado referencias regulatorias oficiales que cumplan a la vez el filtro temático y de especie.")

    lines.extend([
        "",
        "## Recomendaciones preliminares para Nutreco Iberia",
        "- Priorizar un seguimiento periódico de los temas con presencia simultánea en mercado, ciencia y regulación.",
        "- Convertir los hallazgos con mejor respaldo en argumentarios técnico-comerciales y alertas internas.",
        "- Validar con fuente primaria cualquier implicación legal o claim técnico antes de su uso externo.",
        "- Mantener vigilancia específica sobre precios, comunicados ministeriales y cambios normativos directamente vinculados con la especie y el tema buscado.",
    ])

    if chat_history:
        lines.extend(["", "## Aclaraciones del chat previas al informe"])
        for turn in chat_history[-6:]:
            role = "Usuario" if turn["role"] == "user" else "App"
            lines.append(f"- **{role}:** {turn['content']}")

    lines.extend(["", "## Contexto corporativo utilizado", company_context.strip()])
    return "\n".join(lines)


def generate_brief(species: str, user_keywords: str, results: Dict[str, List[dict]], company_context: str, chat_history: List[dict]) -> str:
    if not llm_is_available():
        return extractive_brief(species, user_keywords, results, company_context, chat_history)

    system_prompt = (
        "Eres un analista senior de inteligencia sectorial y asuntos regulatorios para nutrición animal. "
        "Usa solo el corpus proporcionado y marca como tentativa cualquier inferencia no cerrada."
    )
    history = "\n".join([f"{m['role']}: {m['content']}" for m in chat_history[-8:]]) if chat_history else "Sin aclaraciones adicionales."
    user_prompt = f"""
Especie/segmento: {species}
Palabras clave: {user_keywords or '(sin palabras clave adicionales)'}

Contexto corporativo:
{company_context}

Historial del chat:
{history}

Corpus de resultados:
{corpus_text(results)}

Genera un briefing con esta estructura:
1. Resumen ejecutivo.
2. Síntesis integrada del radar (mercado + ciencia + regulación).
3. Señales de mercado.
4. Hallazgos científico-técnicos.
5. Implicaciones regulatorias.
6. Recomendaciones priorizadas para Nutreco Iberia.
7. Riesgos, vacíos y preguntas abiertas.

No inventes fuentes ni bibliografía final.
"""
    return call_openai(system_prompt, user_prompt)


def answer_chat(question: str, species: str, user_keywords: str, results: Dict[str, List[dict]], company_context: str, chat_history: List[dict]) -> str:
    if not question.strip():
        return ""
    if llm_is_available():
        system_prompt = "Responde como analista sectorial usando solo el corpus proporcionado. Si falta evidencia, dilo explícitamente."
        history = "\n".join([f"{m['role']}: {m['content']}" for m in chat_history[-8:]]) if chat_history else ""
        user_prompt = f"""
Contexto corporativo:
{company_context}

Especie/segmento: {species}
Palabras clave: {user_keywords or '(sin palabras clave adicionales)'}

Historial:
{history}

Corpus:
{corpus_text(results)}

Pregunta:
{question}
"""
        return call_openai(system_prompt, user_prompt)

    tokens = set(_keywords_from_text(question, top_k=10))
    candidates = []
    for item in flatten_results(results):
        haystack = _normalize(item.get("title", "") + " " + item.get("snippet", ""))
        score = sum(1 for token in tokens if _normalize(token) in haystack)
        if score > 0:
            candidates.append((score, item))
    candidates.sort(key=lambda x: x[0], reverse=True)

    if not candidates:
        return "No encuentro evidencia suficiente en los resultados actuales para responder con precisión. Prueba a ampliar fechas o reformular las palabras clave."

    lines = ["He localizado la siguiente evidencia relevante en los resultados recuperados:"]
    for _, item in candidates[:4]:
        lines.append(f"- {item.get('title')} ({item.get('source', 'Fuente')}, {item.get('published', 's/f')[:10]}): {item.get('snippet', '')}")
    lines.append("Conclusión provisional: valida este punto con la fuente primaria antes de cerrar el informe.")
    return "\n".join(lines)


def build_docx_bytes(
    species: str,
    user_keywords: str,
    start_date: date,
    end_date: date,
    company_context: str,
    brief_text: str,
    results: Dict[str, List[dict]],
) -> bytes:
    doc = Document()
    doc.add_heading(f"Radar sectorial | {species}", level=0)
    doc.add_paragraph(f"Fecha de generación: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    doc.add_paragraph(f"Intervalo analizado: {start_date.isoformat()} a {end_date.isoformat()}")
    doc.add_paragraph(f"Palabras clave: {user_keywords or 'Sin palabras clave adicionales'}")

    doc.add_heading("Briefing", level=1)
    for paragraph in brief_text.split("\n"):
        clean = paragraph.strip()
        if not clean:
            doc.add_paragraph("")
            continue
        if clean.startswith("# "):
            doc.add_heading(clean.replace("# ", ""), level=1)
        elif clean.startswith("## "):
            doc.add_heading(clean.replace("## ", ""), level=2)
        elif clean.startswith("- "):
            doc.add_paragraph(clean[2:], style="List Bullet")
        else:
            doc.add_paragraph(clean)

    doc.add_heading("Contexto corporativo aplicado", level=1)
    doc.add_paragraph(company_context.strip())

    doc.add_heading("Fuentes recuperadas", level=1)
    for category in ["market", "science", "regulation"]:
        doc.add_heading(CATEGORY_LABELS[category], level=2)
        items = results.get(category, [])
        if not items:
            doc.add_paragraph("Sin resultados.")
            continue
        for item in items:
            p = doc.add_paragraph(style="List Bullet")
            p.add_run(item.get("title", "Sin título")).bold = True
            p.add_run(f" | {item.get('source', 'Fuente')} | {item.get('published', '')[:10]}\n")
            p.add_run(item.get("snippet", ""))
            if item.get("url"):
                p.add_run(f"\n{item['url']}")

    doc.add_heading("Referencias bibliográficas / documentales", level=1)
    for entry in bibliography_entries(results):
        doc.add_paragraph(entry, style="List Number")

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


# -------------------------
# UI rendering
# -------------------------


def render_result_block(items: List[dict], empty_text: str):
    if not items:
        st.info(empty_text)
        return
    for item in items:
        title = item.get("title", "Sin título")
        url = item.get("url", "")
        source = item.get("source", "Fuente")
        published = item.get("published", "")[:10] or "s/f"
        snippet = item.get("snippet", "")
        header = f"**{title}**"
        if url:
            header += f"  \\n[Enlace a la fuente]({url})"
        st.markdown(header)
        st.caption(f"{source} · {published} · {item.get('source_db', '')}")
        if snippet:
            st.write(snippet)
        st.divider()


def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)
    st.write(
        "Radar sectorial para reunir señales de mercado, publicaciones científico-técnicas y referencias regulatorias por especie, fechas y palabras clave."
    )

    if "results" not in st.session_state:
        st.session_state.results = {"market": [], "science": [], "regulation": []}
    if "queries" not in st.session_state:
        st.session_state.queries = {"market": [], "science": [], "regulation": []}
    if "brief_text" not in st.session_state:
        st.session_state.brief_text = ""
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    with st.sidebar:
        st.header("Filtros")
        species = st.selectbox("Especie / segmento", list(SPECIES_OPTIONS.keys()))
        default_start = date.today().replace(month=1, day=1)
        start_date = st.date_input("Fecha inicial", value=default_start)
        end_date = st.date_input("Fecha final", value=date.today())
        user_keywords = st.text_area(
            "Palabras clave",
            placeholder="Ej.: peste porcina africana; exportación; precio cerdo",
            help="Puedes separar términos con coma, punto y coma o salto de línea.",
        )
        max_results = st.slider("Máximo de resultados por bloque", min_value=5, max_value=20, value=12, step=1)
        company_context = st.text_area("Contexto corporativo", value=DEFAULT_COMPANY_CONTEXT, height=160)
        search_button = st.button("Buscar y actualizar radar", type="primary")
        generate_button = st.button("Generar briefing")

        meta_preview = build_keyword_meta(species, user_keywords)
        with st.expander("Vista previa de expansión de palabras clave"):
            st.write("**Frases del usuario:**", meta_preview["user_phrases"] or ["(ninguna)"])
            st.write("**Términos ampliados:**", meta_preview["expanded_terms"][:12])

    if start_date > end_date:
        st.error("La fecha inicial no puede ser posterior a la fecha final.")
        st.stop()

    if search_button:
        with st.spinner("Recopilando información..."):
            try:
                results, queries = run_search(species, user_keywords, start_date, end_date, max_results)
                st.session_state.results = results
                st.session_state.queries = queries
                st.session_state.brief_text = ""
                st.session_state.chat_history = []
            except Exception as exc:
                st.error(f"No se pudo completar la búsqueda: {exc}")

    results = st.session_state.results
    queries = st.session_state.queries

    tabs = st.tabs(["Mercado", "Científico-técnico", "Legislación", "Chat", "Briefing", "Depuración"])
    tab_market, tab_science, tab_regulation, tab_chat, tab_brief, tab_debug = tabs

    with tab_market:
        render_result_block(results.get("market", []), "No se han encontrado resultados de mercado suficientemente relevantes.")

    with tab_science:
        render_result_block(results.get("science", []), "No se han encontrado publicaciones científico-técnicas.")
        if user_keywords or species:
            scholar_query = quote_plus(f"{species} {user_keywords}".strip())
            st.markdown(f"Acceso externo complementario: [Google Scholar](https://scholar.google.com/scholar?q={scholar_query})")

    with tab_regulation:
        render_result_block(results.get("regulation", []), "No se han encontrado referencias regulatorias oficiales que cumplan los filtros.")
        st.caption("La búsqueda regulatoria aplica un filtro estricto: dominio oficial + coincidencia temática + anclaje legal.")

    with tab_chat:
        st.write("Usa este chat para afinar el enfoque antes de generar el informe final.")
        for message in st.session_state.chat_history:
            with st.chat_message("assistant" if message["role"] == "assistant" else "user"):
                st.markdown(message["content"])

        question = st.chat_input("Haz una pregunta sobre los resultados recuperados")
        if question:
            st.session_state.chat_history.append({"role": "user", "content": question})
            with st.chat_message("user"):
                st.markdown(question)
            with st.chat_message("assistant"):
                with st.spinner("Analizando contexto..."):
                    answer = answer_chat(question, species, user_keywords, results, company_context, st.session_state.chat_history)
                    st.markdown(answer)
            st.session_state.chat_history.append({"role": "assistant", "content": answer})

    with tab_brief:
        if generate_button:
            with st.spinner("Generando briefing..."):
                try:
                    st.session_state.brief_text = generate_brief(
                        species,
                        user_keywords,
                        results,
                        company_context,
                        st.session_state.chat_history,
                    )
                except Exception as exc:
                    st.error(f"No se pudo generar el briefing: {exc}")

        if st.session_state.brief_text:
            st.markdown(st.session_state.brief_text)
            docx_bytes = build_docx_bytes(
                species,
                user_keywords,
                start_date,
                end_date,
                company_context,
                st.session_state.brief_text,
                results,
            )
            st.download_button(
                label="Descargar informe Word (.docx)",
                data=docx_bytes,
                file_name=f"radar_{species.lower().replace(' ', '_')}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            with st.expander("Referencias bibliográficas / documentales"):
                for entry in bibliography_entries(results):
                    st.markdown(f"- {entry}")
        else:
            st.info("Ejecuta la búsqueda y después genera el briefing.")

    with tab_debug:
        st.subheader("Consultas lanzadas")
        st.write("**Mercado**")
        for q in queries.get("market", []):
            st.code(q)
        st.write("**Científico-técnico**")
        for q in queries.get("science", []):
            st.code(q)
        st.write("**Legislación**")
        for q in queries.get("regulation", []):
            st.code(q)

    st.divider()
    st.caption(
        "Aviso: esta herramienta no sustituye la revisión técnica, regulatoria ni jurídica. "
        "Antes de usar conclusiones en documentos externos o claims comerciales, valida cada punto con la fuente primaria."
    )


if __name__ == "__main__":
    main()
