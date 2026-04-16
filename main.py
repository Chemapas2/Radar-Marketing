import io
import math
import os
import re
import time
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote_plus, urljoin, urlparse

import feedparser
import pandas as pd
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
USER_AGENT = "Mozilla/5.0 (compatible; NutrecoRadar/4.0; +https://streamlit.io)"
REQUEST_TIMEOUT = 25
MAX_CONTEXT_ITEMS = 8
SCIENTIFIC_FETCH_FACTOR = 3
MAX_BOE_SCAN_DAYS = 120
MAX_MAPA_NEWS_PAGES = 3

SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

SPECIES_OPTIONS: Dict[str, Dict[str, List[str]]] = {
    "Avicultura de puesta": {
        "aliases": [
            "avicultura de puesta",
            "gallinas ponedoras",
            "huevos",
            "layers",
            "laying hens",
            "egg sector",
        ],
        "market_labels": ["avicultura", "sectores ganaderos", "piensos"],
        "legislation_pages": ["bienestar animal", "sanidad animal", "trazabilidad"],
        "market": ["precio huevo", "mercado del huevo", "egg price", "egg market", "costes", "consumo"],
        "science": ["nutrition", "shell quality", "salmonella", "welfare", "persistencia de puesta"],
        "regulation": ["bienestar", "gallinas ponedoras", "salmonella", "bioseguridad", "higiene"],
    },
    "Avicultura de carne": {
        "aliases": [
            "avicultura de carne",
            "pollos de engorde",
            "broilers",
            "broiler chickens",
            "pollo",
            "chicken meat sector",
        ],
        "market_labels": ["avicultura", "sectores ganaderos", "piensos"],
        "legislation_pages": ["bienestar animal", "sanidad animal", "trazabilidad"],
        "market": ["precio pollo", "mercado avícola", "broiler price", "poultry market", "costes", "consumo"],
        "science": ["nutrition", "gut health", "coccidiosis", "necrotic enteritis", "performance"],
        "regulation": ["bienestar", "pollos", "bioseguridad", "influenza aviar", "residuos"],
    },
    "Porcino": {
        "aliases": ["porcino", "cerdo", "swine", "pig", "pigs", "hog sector"],
        "market_labels": ["porcino", "sectores ganaderos", "piensos"],
        "legislation_pages": ["sector porcino", "bienestar animal", "sanidad animal", "trazabilidad"],
        "market": ["precio cerdo", "pig price", "hog price", "swine market", "exportación", "piensos"],
        "science": ["nutrition", "gut health", "weaning", "reproduction", "biosecurity"],
        "regulation": ["peste porcina africana", "African swine fever", "bienestar", "bioseguridad", "emisiones"],
    },
    "Vacuno de leche": {
        "aliases": ["vacuno de leche", "sector lácteo", "dairy cattle", "dairy cows", "milk sector"],
        "market_labels": ["vacuno de leche", "sectores ganaderos", "piensos"],
        "legislation_pages": ["sector vacuno de leche", "bienestar animal", "sanidad animal", "trazabilidad"],
        "market": ["precio leche", "milk price", "farmgate milk price", "dairy market", "márgenes", "piensos"],
        "science": ["nutrition", "rumen", "fertility", "mastitis", "transition cow", "methane"],
        "regulation": ["emisiones", "bienestar", "sanidad animal", "calidad de leche", "sostenibilidad"],
    },
    "Vacuno de carne": {
        "aliases": ["vacuno de carne", "beef cattle", "beef sector", "cebaderos", "fattening cattle"],
        "market_labels": ["vacuno de carne", "sectores ganaderos", "piensos"],
        "legislation_pages": ["sector vacuno de carne", "bienestar animal", "sanidad animal", "trazabilidad"],
        "market": ["precio vacuno", "beef price", "cattle price", "beef market", "exportación", "piensos"],
        "science": ["nutrition", "average daily gain", "respiratory disease", "welfare", "methane"],
        "regulation": ["transporte", "bienestar", "emisiones", "trazabilidad", "antibioticos"],
    },
    "Ovino": {
        "aliases": ["ovino", "cordero", "sheep", "ovine", "lamb sector", "ovine milk"],
        "market_labels": ["ovino", "ovino y caprino", "sectores ganaderos", "piensos"],
        "legislation_pages": ["sector ovino-caprino", "bienestar animal", "sanidad animal", "identificación y registro de ovinos y caprinos"],
        "market": ["precio cordero", "lamb price", "sheep market", "ovino de leche", "exportación", "piensos"],
        "science": ["nutrition", "parasites", "reproduction", "rumen", "milk quality"],
        "regulation": ["lengua azul", "bluetongue", "trazabilidad", "movimiento animal", "bienestar"],
    },
    "Caprino": {
        "aliases": ["caprino", "goat", "goats", "goat milk", "caprine sector"],
        "market_labels": ["caprino", "ovino y caprino", "sectores ganaderos", "piensos"],
        "legislation_pages": ["sector ovino-caprino", "bienestar animal", "sanidad animal", "identificación y registro de ovinos y caprinos"],
        "market": ["precio leche de cabra", "goat milk price", "goat market", "queso de cabra", "piensos"],
        "science": ["nutrition", "mastitis", "parasites", "reproduction", "kid growth"],
        "regulation": ["trazabilidad", "movimiento animal", "bienestar", "sanidad animal", "higiene"],
    },
    "Cunicultura": {
        "aliases": ["cunicultura", "cunícola", "rabbit production", "rabbit sector", "conejo"],
        "market_labels": ["cunicultura", "sectores ganaderos", "piensos"],
        "legislation_pages": ["bienestar animal", "sanidad animal", "trazabilidad"],
        "market": ["precio conejo", "rabbit market", "rabbit meat", "consumo", "piensos"],
        "science": ["nutrition", "enteropathy", "digestive health", "welfare", "reproduction"],
        "regulation": ["bienestar", "bioseguridad", "medicación", "antimicrobianos"],
    },
}

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

STOPWORDS = {
    "de", "la", "el", "los", "las", "y", "o", "en", "para", "por", "con", "del", "al", "un", "una",
    "que", "sobre", "from", "the", "and", "for", "this", "that", "entre", "como", "más", "menos", "its",
    "are", "was", "were", "has", "have", "had", "muy", "also", "been", "being", "will", "would", "market",
    "mercado", "regulation", "science", "technical", "legislation", "animal", "production", "study", "review",
    "using", "effect", "effects", "analysis", "research", "results", "paper", "news", "official", "latest",
    "report", "sector", "sectores", "ganadero", "ganadera", "ganaderos", "ganaderas", "ministerio", "madrid",
}

TERM_SYNONYMS: Dict[str, List[str]] = {
    "peste porcina africana": ["African swine fever", "ASF", "ASFV", "jabalí", "wild boar", "biosecurity"],
    "ppa": ["peste porcina africana", "African swine fever", "ASF", "ASFV"],
    "influenza aviar": ["avian influenza", "bird flu", "highly pathogenic avian influenza", "HPAI", "H5N1"],
    "ia": ["influenza aviar", "avian influenza", "HPAI", "H5N1"],
    "lengua azul": ["bluetongue", "BTV", "orbivirus"],
    "mamitis": ["mastitis", "udder health", "intramammary infection"],
    "mastitis": ["mamitis", "udder health", "intramammary infection"],
    "metano": ["methane", "enteric methane", "greenhouse gas", "GHG", "carbon footprint"],
    "huella de carbono": ["carbon footprint", "life cycle assessment", "LCA", "GHG"],
    "bienestar": ["welfare", "animal welfare"],
    "bienestar animal": ["animal welfare", "welfare assessment"],
    "bioseguridad": ["biosecurity", "disease prevention", "farm biosecurity"],
    "coccidiosis": ["Eimeria", "anticoccidial", "coccidiosis"],
    "salmonella": ["Salmonella", "food safety"],
    "ileitis": ["ileitis", "Lawsonia intracellularis"],
    "diarrea postdestete": ["post-weaning diarrhoea", "post-weaning diarrhea", "weaning", "E. coli"],
    "destete": ["weaning", "post-weaning", "nursery pigs"],
    "rumen": ["ruminal", "ruminal fermentation"],
    "fertilidad": ["fertility", "reproduction"],
    "reproduccion": ["reproduction", "fertility"],
    "digestibilidad": ["digestibility", "nutrient utilization"],
    "sanidad": ["health", "disease", "animal health"],
    "nutricion": ["nutrition", "feeding", "diet", "feed formulation"],
    "piensos": ["feed", "compound feed", "feed formulation", "feed prices", "feed cost"],
    "costes de alimentacion": ["feed cost", "feed costs", "raw materials", "commodity prices", "soybean meal", "corn"],
    "precio leche": ["milk price", "farmgate milk price", "dairy prices"],
    "precio huevo": ["egg price", "egg market", "egg prices"],
    "precio pollo": ["broiler price", "chicken price", "poultry market"],
    "precio cerdo": ["hog price", "pig price", "swine market"],
    "precio cordero": ["lamb price", "sheep market"],
    "emisiones": ["emissions", "ammonia", "GHG", "environmental impact"],
    "amoniaco": ["ammonia", "NH3", "emissions"],
    "resistencia antimicrobiana": ["antimicrobial resistance", "AMR", "antibiotic resistance"],
    "antibioticos": ["antibiotics", "antimicrobial", "AMR"],
    "calidad de cascara": ["shell quality", "eggshell quality"],
    "enteropatia": ["enteropathy", "digestive disorder"],
    "necrosis enterica": ["necrotic enteritis", "Clostridium perfringens"],
    "enteritis necrotica": ["necrotic enteritis", "Clostridium perfringens"],
    "sostenibilidad": ["sustainability", "environmental impact", "LCA"],
    "mercado": ["market", "prices", "price bulletin", "news", "outlook"],
    "precios": ["prices", "price", "boletín de precios", "price bulletin"],
    "regulacion": ["regulation", "legislation", "real decreto", "reglamento"],
    "normativa": ["legislation", "regulation", "real decreto", "norma"],
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
    "regulacion": "regulation",
    "normativa": "regulation",
    "legislacion": "legislation",
    "leche": "milk",
    "carne": "meat",
    "huevo": "egg",
    "huevos": "eggs",
    "pollo": "chicken",
    "pollos": "chickens",
    "conejo": "rabbit",
    "cordero": "lamb",
    "cerdo": "pig",
    "porcino": "swine",
    "ovino": "sheep",
    "caprino": "goat",
    "vacuno": "cattle",
}

MAPA_MARKET_URL = "https://www.mapa.gob.es/es/ganaderia/estadisticas/mercados_agricolas_ganaderos"
MAPA_PRESS_RSS_URL = "https://www.mapa.gob.es/es/prensa/noticiasrss"
MAPA_PRESS_LIST_URL = "https://www.mapa.gob.es/es/prensa/ultimas-noticias"
MAPA_LEGISLATION_URL = "https://www.mapa.gob.es/es/ganaderia/legislacion"
BOE_SUMARIO_URL = "https://www.boe.es/datosabiertos/api/boe/sumario/{datestr}"


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9áéíóúñü\s\-/]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _strip_html(text: str) -> str:
    return BeautifulSoup(text or "", "html.parser").get_text(" ", strip=True)


def _truncate(text: str, max_len: int = 420) -> str:
    text = text or ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _canonical_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/")
    return f"{parsed.netloc.lower()}{path.lower()}"


def _clean_url(url: str, base_url: str = "") -> str:
    if not url:
        return ""
    return urljoin(base_url, url.strip())


def _safe_phrase(term: str) -> str:
    term = re.sub(r'["“”]', "", (term or "").strip())
    if not term:
        return ""
    return f'"{term}"' if (" " in term or "-" in term) else term


def _date_in_range(value: Optional[datetime], start: date, end: date) -> bool:
    if value is None:
        return True
    current = value.date()
    return start <= current <= end


def _normalize_datetime(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return _normalize_datetime(date_parser.parse(value))
    except Exception:
        return _normalize_datetime(_parse_spanish_date(value))


def _parse_spanish_date(text: str) -> Optional[datetime]:
    text_norm = _normalize(text)
    match = re.search(r"(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})", text_norm)
    if match:
        day = int(match.group(1))
        month = SPANISH_MONTHS.get(match.group(2), 0)
        year = int(match.group(3))
        if month:
            return datetime(year, month, day)

    match = re.search(r"([a-záéíóúñ]+)\s+(\d{4})", text_norm)
    if match:
        month = SPANISH_MONTHS.get(match.group(1), 0)
        year = int(match.group(2))
        if month:
            return datetime(year, month, 1)

    match = re.search(r"semana\s+(\d{1,2})\s*/\s*(\d{4})", text_norm)
    if match:
        week = int(match.group(1))
        year = int(match.group(2))
        try:
            return datetime.fromisocalendar(year, week, 1)
        except Exception:
            return None

    match = re.search(r"(\d{4})", text_norm)
    if match:
        year = int(match.group(1))
        return datetime(year, 1, 1)
    return None


def _infer_date_from_title(title: str) -> Optional[datetime]:
    return _parse_spanish_date(title) or _parse_date(title)


def _request(url: str, *, params: Optional[dict] = None, expect: str = "json"):
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
            if expect == "text":
                return response.text
            return response.content
        except Exception as exc:  # pragma: no cover
            last_error = exc
            if attempt == 0:
                time.sleep(0.8)
    raise RuntimeError(f"Error al consultar la fuente externa: {last_error}")


def _unique_keep_order(items: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        value = re.sub(r"\s+", " ", (item or "").strip())
        if not value:
            continue
        key = _normalize(value)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _first_non_empty(record: dict, keys: Sequence[str]) -> str:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


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
    deduped = []
    for item in records:
        key = _record_key(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _keywords_from_text(text: str, top_k: int = 8) -> List[str]:
    words = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñÜü0-9\-]{4,}", text.lower())
    counts = Counter(w for w in words if w not in STOPWORDS)
    return [w for w, _ in counts.most_common(top_k)]


def parse_user_phrases(text: str) -> List[str]:
    if not text:
        return []
    raw_parts = re.split(r"[\n;,|]+", text)
    parts: List[str] = []
    for part in raw_parts:
        cleaned = re.sub(r"\s+", " ", part).strip(" .")
        if cleaned:
            parts.append(cleaned)
    return _unique_keep_order(parts)


def _maybe_translate_phrase(term: str) -> List[str]:
    normalized = _normalize(term)
    words = normalized.split()
    if not words:
        return []
    translated_words = [WORD_TRANSLATIONS.get(word, word) for word in words]
    if translated_words == words:
        return []
    candidate = " ".join(translated_words)
    return [candidate] if candidate and candidate != normalized else []


def expand_phrase(phrase: str) -> List[str]:
    normalized = _normalize(phrase)
    expansions = [phrase]
    if normalized in TERM_SYNONYMS:
        expansions.extend(TERM_SYNONYMS[normalized])
    expansions.extend(_maybe_translate_phrase(phrase))

    tokens = normalized.split()
    for token in tokens:
        if token in TERM_SYNONYMS:
            expansions.extend(TERM_SYNONYMS[token][:4])

    for key, values in TERM_SYNONYMS.items():
        normalized_values = {_normalize(v) for v in values}
        if normalized in normalized_values:
            expansions.append(key)
            expansions.extend(values[:4])

    return _unique_keep_order(expansions)


def expand_user_keywords(user_keywords: str, species: str) -> Dict[str, List[str]]:
    profile = SPECIES_OPTIONS[species]
    user_phrases = parse_user_phrases(user_keywords)
    expanded_terms: List[str] = []
    for phrase in user_phrases:
        expanded_terms.extend(expand_phrase(phrase))

    expanded_terms = _unique_keep_order(expanded_terms)
    if not expanded_terms:
        expanded_terms = _unique_keep_order(profile["market"][:2] + profile["science"][:2])

    return {
        "user_phrases": user_phrases,
        "expanded_terms": expanded_terms,
        "species_terms": _unique_keep_order(profile["aliases"]),
        "market_terms": _unique_keep_order(expanded_terms + profile["market"][:8]),
        "science_terms": _unique_keep_order(expanded_terms + profile["science"][:8]),
        "regulation_terms": _unique_keep_order(expanded_terms + profile["regulation"][:8]),
    }


def _score_text(text: str, primary_terms: Sequence[str], secondary_terms: Sequence[str], support_terms: Sequence[str]) -> float:
    haystack = _normalize(text)
    score = 0.0
    primary_hits = 0
    secondary_hits = 0

    for term in primary_terms:
        norm = _normalize(term)
        if norm and norm in haystack:
            score += 2.4 if " " in norm else 1.4
            primary_hits += 1

    for term in secondary_terms:
        norm = _normalize(term)
        if norm and norm in haystack:
            score += 3.0 if " " in norm else 1.7
            secondary_hits += 1

    for term in support_terms:
        norm = _normalize(term)
        if norm and norm in haystack:
            score += 0.5

    if secondary_terms and secondary_hits == 0:
        score -= 1.2
    if primary_terms and primary_hits == 0:
        score -= 0.6
    return score


def _sort_records(records: List[dict], primary_terms: Sequence[str], secondary_terms: Sequence[str], support_terms: Sequence[str]) -> List[dict]:
    scored: List[dict] = []
    for item in records:
        text = " ".join(
            filter(
                None,
                [
                    item.get("title", ""),
                    item.get("snippet", ""),
                    item.get("source", ""),
                    item.get("journal", ""),
                    item.get("authors", ""),
                ],
            )
        )
        enriched = dict(item)
        enriched["score"] = _score_text(text, primary_terms, secondary_terms, support_terms)
        if item.get("source_db") in {"MAPA - Mercados", "MAPA - Legislación", "MAPA - Noticias", "BOE"}:
            enriched["score"] += 0.4
        published = _parse_date(item.get("published"))
        if published:
            age_days = max((datetime.now() - published).days, 0)
            if age_days <= 30:
                enriched["score"] += 0.5
            elif age_days <= 180:
                enriched["score"] += 0.2
        scored.append(enriched)

    scored.sort(key=lambda x: (x.get("score", 0), x.get("published", "")), reverse=True)
    return scored


# -------------------------
# Market queries and sources
# -------------------------

def build_market_queries(species: str, keyword_meta: dict) -> List[str]:
    profile = SPECIES_OPTIONS[species]
    species_terms = profile["aliases"]
    spanish_species = species_terms[0]
    english_species = species_terms[3] if len(species_terms) > 3 else species_terms[-1]
    focus_terms = keyword_meta["expanded_terms"][:3] or profile["market"][:2]

    queries = [
        f"{spanish_species} mercado precios",
        f"{spanish_species} boletín precios",
        f"{spanish_species} ministerio agricultura",
    ]

    for term in focus_terms[:2]:
        queries.extend(
            [
                f"{spanish_species} {_safe_phrase(term)}",
                f"{spanish_species} {_safe_phrase(term)} precios mercado",
                f"{spanish_species} {_safe_phrase(term)} ministerio agricultura",
                f"{english_species} {_safe_phrase(term)} market prices",
            ]
        )

    return _unique_keep_order(queries)[:8]


@st.cache_data(show_spinner=False, ttl=3600)
def search_google_news(query: str, start_date: date, end_date: date, max_results: int = 12) -> List[dict]:
    url = "https://news.google.com/rss/search"
    params = {"q": query, "hl": "es", "gl": "ES", "ceid": "ES:es"}
    content = _request(url, params=params, expect="content")
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
                "published": published.isoformat() if published else "",
                "source_db": "Google News",
                "query_used": query,
            }
        )
        if len(records) >= max_results:
            break
    return _dedupe(records)


@st.cache_data(show_spinner=False, ttl=1800)
def search_gdelt_articles(query: str, max_results: int = 10) -> List[dict]:
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": max_results,
        "sort": "datedesc",
        "timespan": "72h",
    }
    data = _request("https://api.gdeltproject.org/api/v2/doc/doc", params=params, expect="json")
    articles = data.get("articles", []) or data.get("artlist", [])
    records: List[dict] = []
    for item in articles:
        published = _parse_date(item.get("seendate") or item.get("date"))
        records.append(
            {
                "title": _strip_html(item.get("title", "Sin título")),
                "snippet": _truncate(item.get("snippet", "") or item.get("domain", "")),
                "url": _clean_url(item.get("url", "")),
                "source": item.get("domain", "GDELT"),
                "published": published.isoformat() if published else "",
                "source_db": "GDELT",
                "query_used": query,
            }
        )
    return _dedupe(records)


@st.cache_data(show_spinner=False, ttl=3600)
def search_mapa_news_rss(max_items: int = 80) -> List[dict]:
    content = _request(MAPA_PRESS_RSS_URL, expect="content")
    feed = feedparser.parse(content)
    records: List[dict] = []
    for entry in feed.entries[:max_items]:
        published = _parse_date(entry.get("published") or entry.get("pubDate"))
        records.append(
            {
                "title": _strip_html(entry.get("title", "Sin título")),
                "snippet": _truncate(_strip_html(entry.get("summary", ""))),
                "url": _clean_url(entry.get("link", "")),
                "source": "MAPA",
                "published": published.isoformat() if published else "",
                "source_db": "MAPA - Noticias",
            }
        )
    return _dedupe(records)


@st.cache_data(show_spinner=False, ttl=3600)
def search_mapa_news_pages(page_count: int = MAX_MAPA_NEWS_PAGES) -> List[dict]:
    records: List[dict] = []
    for page in range(1, page_count + 1):
        html = _request(f"{MAPA_PRESS_LIST_URL}?m=50&p={page}", expect="text")
        soup = BeautifulSoup(html, "html.parser")
        page_text = soup.get_text("\n")
        items = []

        for anchor in soup.find_all("a", href=True):
            title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
            href = _clean_url(anchor.get("href", ""), MAPA_PRESS_LIST_URL)
            if not title or not href or "detalle_noticias" not in href:
                continue
            items.append((title, href))

        seen = set()
        for title, href in items:
            if href in seen:
                continue
            seen.add(href)
            snippet = ""
            context_node = None
            if anchor := soup.find("a", href=re.compile(re.escape(href.split("https://www.mapa.gob.es")[-1])) if href.startswith("https://www.mapa.gob.es") else False):
                context_node = anchor.parent
            if context_node:
                snippet = _truncate(re.sub(r"\s+", " ", context_node.get_text(" ", strip=True)))
            date_match = re.search(r"(\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4})", page_text, re.IGNORECASE)
            published = _parse_spanish_date(date_match.group(1)) if date_match else None
            records.append(
                {
                    "title": title,
                    "snippet": snippet,
                    "url": href,
                    "source": "MAPA",
                    "published": published.isoformat() if published else "",
                    "source_db": "MAPA - Noticias",
                }
            )
    return _dedupe(records)


@st.cache_data(show_spinner=False, ttl=3600)
def search_mapa_market_portal() -> List[dict]:
    html = _request(MAPA_MARKET_URL, expect="text")
    soup = BeautifulSoup(html, "html.parser")
    records: List[dict] = []

    for anchor in soup.find_all("a", href=True):
        title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        if not title or "+info" in _normalize(title) or title in {"", "()"}:
            continue
        href = _clean_url(anchor.get("href", ""), MAPA_MARKET_URL)
        if not href or "mapa.gob.es" not in href:
            continue
        context = re.sub(r"\s+", " ", anchor.parent.get_text(" ", strip=True))
        if not any(token in _normalize(context) for token in ["porcino", "vacuno", "ovino", "caprino", "avicultura", "cunicultura", "piensos", "sectores ganaderos"]):
            continue
        published = _infer_date_from_title(title)
        records.append(
            {
                "title": title,
                "snippet": _truncate(context or "Publicación oficial del MAPA sobre mercados y precios."),
                "url": href,
                "source": "MAPA - Mercados agrícolas y ganaderos",
                "published": published.isoformat() if published else "",
                "source_db": "MAPA - Mercados",
            }
        )
    return _dedupe(records)


def search_market_sources(species: str, keyword_meta: dict, start_date: date, end_date: date, max_results: int) -> Tuple[List[dict], List[str]]:
    queries = build_market_queries(species, keyword_meta)
    records: List[dict] = []

    for query in queries[:6]:
        try:
            records.extend(search_google_news(query, start_date, end_date, max_results=max_results))
        except Exception:
            continue

    if (date.today() - start_date).days <= 3:
        for query in queries[:3]:
            try:
                records.extend(search_gdelt_articles(query, max_results=max_results))
            except Exception:
                continue

    try:
        portal_items = search_mapa_market_portal()
        records.extend(
            item for item in portal_items
            if _date_in_range(_parse_date(item.get("published")), start_date, end_date)
        )
    except Exception:
        pass

    try:
        mapa_news = search_mapa_news_rss()
        records.extend(
            item for item in mapa_news
            if _date_in_range(_parse_date(item.get("published")), start_date, end_date)
        )
    except Exception:
        pass

    primary_terms = keyword_meta["species_terms"] + SPECIES_OPTIONS[species]["market_labels"]
    secondary_terms = keyword_meta["expanded_terms"][:8]
    support_terms = keyword_meta["market_terms"][:10] + ["precio", "mercado", "boletín", "coyuntura", "MAPA", "ministerio"]

    ranked = _sort_records(_dedupe(records), primary_terms, secondary_terms, support_terms)
    filtered = [item for item in ranked if item.get("score", 0) >= 0.6]

    if len(filtered) < max(4, max_results // 2):
        fallback = [
            item for item in ranked
            if item.get("source_db") == "MAPA - Mercados" and item.get("score", 0) >= 0.0
        ]
        filtered = _dedupe(filtered + fallback)

    return filtered[:max_results], queries


# ----------------------------
# Regulatory queries and data
# ----------------------------

def build_regulation_queries(species: str, keyword_meta: dict) -> List[str]:
    profile = SPECIES_OPTIONS[species]
    spanish_species = profile["aliases"][0]
    focus_terms = keyword_meta["expanded_terms"][:3] or profile["regulation"][:2]

    queries = [
        f"{spanish_species} normativa",
        f"{spanish_species} real decreto",
        f"{spanish_species} ministerio agricultura normativa",
    ]
    for term in focus_terms[:2]:
        queries.extend(
            [
                f"{spanish_species} {_safe_phrase(term)} normativa",
                f"{spanish_species} {_safe_phrase(term)} real decreto",
                f"{spanish_species} {_safe_phrase(term)} reglamento",
                f"{spanish_species} {_safe_phrase(term)} ministerio agricultura",
            ]
        )
    return _unique_keep_order(queries)[:8]


@st.cache_data(show_spinner=False, ttl=3600)
def search_boe_sumario_day(day: date) -> List[dict]:
    data = _request(BOE_SUMARIO_URL.format(datestr=day.strftime("%Y%m%d")), expect="json")
    found: List[dict] = []

    def walk(node):
        if isinstance(node, dict):
            title = _first_non_empty(node, ["titulo", "title", "tituloItem", "titulo_item", "descripcion"])
            url = _first_non_empty(node, ["urlHtml", "url_html", "url", "urlPDF", "urlPdf", "url_pdf"])
            identifier = _first_non_empty(node, ["identificador", "id"]) or ""
            if not url and identifier.startswith("BOE-"):
                url = f"https://www.boe.es/buscar/doc.php?id={identifier}"
            summary = _first_non_empty(node, ["texto", "descripcion", "sumario", "epigrafe", "departamento"])
            if title and url and "boe.es" in url:
                found.append(
                    {
                        "title": _strip_html(title),
                        "snippet": _truncate(_strip_html(summary) or "Documento publicado en el BOE."),
                        "url": _clean_url(url),
                        "source": "BOE",
                        "published": datetime.combine(day, datetime.min.time()).isoformat(),
                        "source_db": "BOE",
                        "identifier": identifier,
                    }
                )
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return _dedupe(found)


@st.cache_data(show_spinner=False, ttl=3600)
def search_mapa_legislation_pages(seed_terms: Tuple[str, ...], max_pages: int = 5) -> List[dict]:
    html = _request(MAPA_LEGISLATION_URL, expect="text")
    soup = BeautifulSoup(html, "html.parser")

    candidate_pages: List[Tuple[str, str]] = []
    seed_norm = [_normalize(term) for term in seed_terms if term]
    for anchor in soup.find_all("a", href=True):
        title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        href = _clean_url(anchor.get("href", ""), MAPA_LEGISLATION_URL)
        if not title or not href or "mapa.gob.es" not in href:
            continue
        title_norm = _normalize(title)
        if any(seed in title_norm for seed in seed_norm) or any(k in title_norm for k in ["bienestar animal", "sanidad animal", "trazabilidad", "porcino", "vacuno", "ovino", "caprino"]):
            candidate_pages.append((title, href))

    records: List[dict] = []
    used_urls = set()
    for page_title, page_url in candidate_pages[:max_pages]:
        if page_url in used_urls:
            continue
        used_urls.add(page_url)
        try:
            page_html = _request(page_url, expect="text")
        except Exception:
            continue
        page_soup = BeautifulSoup(page_html, "html.parser")
        for anchor in page_soup.find_all("a", href=True):
            title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
            if not title or len(title) < 12:
                continue
            href = _clean_url(anchor.get("href", ""), page_url)
            if not href or "mapa.gob.es" not in href and "boe.es" not in href and "eur-lex.europa.eu" not in href:
                continue
            title_norm = _normalize(title)
            if not any(token in title_norm for token in ["real decreto", "ley", "reglamento", "directiva", "orden", "decision", "codigo", "norma"]):
                continue
            published = _infer_date_from_title(title)
            records.append(
                {
                    "title": title,
                    "snippet": _truncate(f"{page_title}. Fuente oficial MAPA / normativa enlazada."),
                    "url": href,
                    "source": "MAPA - Legislación",
                    "published": published.isoformat() if published else "",
                    "source_db": "MAPA - Legislación",
                }
            )
    return _dedupe(records)


def search_regulatory_sources(species: str, keyword_meta: dict, start_date: date, end_date: date, max_results: int) -> Tuple[List[dict], List[str]]:
    queries = build_regulation_queries(species, keyword_meta)
    records: List[dict] = []

    total_days = (end_date - start_date).days + 1
    if total_days > 0:
        if total_days <= MAX_BOE_SCAN_DAYS:
            days_to_scan = [start_date + timedelta(days=i) for i in range(total_days)]
        else:
            step = max(1, math.ceil(total_days / MAX_BOE_SCAN_DAYS))
            days_to_scan = [start_date + timedelta(days=i) for i in range(0, total_days, step)]

        for day in days_to_scan:
            try:
                records.extend(search_boe_sumario_day(day))
            except Exception:
                continue

    try:
        seed_terms = tuple(SPECIES_OPTIONS[species]["legislation_pages"] + keyword_meta["regulation_terms"][:3])
        records.extend(search_mapa_legislation_pages(seed_terms))
    except Exception:
        pass

    try:
        mapa_news = search_mapa_news_rss()
        records.extend(
            item for item in mapa_news
            if _date_in_range(_parse_date(item.get("published")), start_date, end_date)
        )
    except Exception:
        pass

    primary_terms = keyword_meta["species_terms"] + SPECIES_OPTIONS[species]["legislation_pages"]
    secondary_terms = keyword_meta["expanded_terms"][:8]
    support_terms = keyword_meta["regulation_terms"][:12] + [
        "real decreto", "reglamento", "ley", "boe", "normativa", "bienestar", "sanidad", "mapa"
    ]
    ranked = _sort_records(_dedupe(records), primary_terms, secondary_terms, support_terms)
    filtered = [item for item in ranked if item.get("score", 0) >= 0.4]
    return filtered[:max_results], queries


# ----------------------
# Scientific data search
# ----------------------

def build_science_queries(species: str, keyword_meta: dict) -> Dict[str, object]:
    profile = SPECIES_OPTIONS[species]
    species_terms = keyword_meta["species_terms"][:6]
    topic_terms = keyword_meta["expanded_terms"][:10] or profile["science"][:6]
    fallback_science = profile["science"][:6]

    species_block = " OR ".join(_safe_phrase(term) for term in species_terms)
    topic_block = " OR ".join(_safe_phrase(term) for term in (topic_terms or fallback_science))

    openalex = f"({species_block}) AND ({topic_block})"
    europepmc = f"({species_block}) AND ({topic_block})"
    crossref = " ".join(_unique_keep_order(species_terms[:4] + (topic_terms or fallback_science)[:8]))
    broad = " ".join(_unique_keep_order(species_terms[:4] + fallback_science[:4]))
    raw_external = " ".join(_unique_keep_order(species_terms[:3] + (keyword_meta["user_phrases"] or fallback_science[:3])))
    external_links = {
        "Google Scholar": f"https://scholar.google.com/scholar?q={quote_plus(raw_external)}",
        "ScienceDirect": f"https://www.sciencedirect.com/search?qs={quote_plus(raw_external)}",
        "AGRIS": f"https://agris.fao.org/search/en?query={quote_plus(raw_external)}",
        "CORE": f"https://core.ac.uk/search?q={quote_plus(raw_external)}",
    }
    return {
        **keyword_meta,
        "queries": {"openalex": openalex, "europepmc": europepmc, "crossref": crossref, "broad": broad},
        "external_links": external_links,
    }


@st.cache_data(show_spinner=False, ttl=3600)
def search_europe_pmc(query: str, start_date: date, end_date: date, max_results: int = 20) -> List[dict]:
    full_query = f"({query}) AND FIRST_PDATE:[{start_date.isoformat()} TO {end_date.isoformat()}]"
    params = {
        "query": full_query,
        "format": "json",
        "pageSize": max_results,
        "sort": "RELEVANCE",
        "resultType": "core",
    }
    data = _request("https://www.ebi.ac.uk/europepmc/webservices/rest/search", params=params, expect="json")
    results = data.get("resultList", {}).get("result", [])
    records: List[dict] = []
    for item in results:
        published = _parse_date(item.get("firstPublicationDate") or item.get("pubYear"))
        doi = item.get("doi")
        url = ""
        if doi:
            url = f"https://doi.org/{doi}"
        elif item.get("pmid"):
            url = f"https://europepmc.org/article/MED/{item['pmid']}"
        elif item.get("pmcid"):
            url = f"https://europepmc.org/article/PMC/{item['pmcid']}"
        records.append(
            {
                "title": _strip_html(item.get("title", "Sin título")),
                "snippet": _truncate(_strip_html(item.get("abstractText", "")) or item.get("journalTitle", "")),
                "url": url,
                "source": item.get("journalTitle", "Europe PMC"),
                "published": published.isoformat() if published else item.get("pubYear", ""),
                "authors": item.get("authorString", ""),
                "doi": doi or "",
                "journal": item.get("journalTitle", ""),
                "source_db": "Europe PMC",
            }
        )
    return _dedupe(records)


@st.cache_data(show_spinner=False, ttl=3600)
def search_openalex(query: str, start_date: date, end_date: date, max_results: int = 20) -> List[dict]:
    params = {
        "search": query,
        "filter": f"from_publication_date:{start_date.isoformat()},to_publication_date:{end_date.isoformat()},type:article|preprint,is_paratext:false",
        "per_page": max_results,
        "sort": "relevance_score:desc",
        "mailto": os.getenv("OPENALEX_EMAIL", ""),
    }
    params = {k: v for k, v in params.items() if v != ""}
    data = _request("https://api.openalex.org/works", params=params, expect="json")
    results = data.get("results", [])

    records: List[dict] = []
    for item in results:
        publication_date = item.get("publication_date") or ""
        published = _parse_date(publication_date)
        primary_location = item.get("primary_location") or {}
        best_oa = item.get("best_oa_location") or {}
        ids = item.get("ids") or {}
        landing_page = primary_location.get("landing_page_url") or best_oa.get("landing_page_url") or ids.get("doi") or item.get("doi") or item.get("id", "")
        journal_name = (((primary_location.get("source") or {}).get("display_name")) or ((best_oa.get("source") or {}).get("display_name")) or "OpenAlex")
        authors = ", ".join(
            authorship.get("author", {}).get("display_name", "")
            for authorship in (item.get("authorships") or [])[:6]
            if authorship.get("author", {}).get("display_name")
        )
        abstract = item.get("abstract_inverted_index")
        snippet = ""
        if isinstance(abstract, dict):
            tokens = []
            for token, positions in abstract.items():
                for pos in positions:
                    tokens.append((pos, token))
            snippet = " ".join(token for _, token in sorted(tokens)[:90])
        if not snippet:
            snippet = journal_name
        records.append(
            {
                "title": _strip_html(item.get("display_name", "Sin título")),
                "snippet": _truncate(snippet),
                "url": _clean_url(landing_page),
                "source": journal_name,
                "published": published.isoformat() if published else publication_date,
                "authors": authors,
                "doi": (item.get("doi") or ids.get("doi") or "").replace("https://doi.org/", ""),
                "journal": journal_name,
                "cited_by_count": item.get("cited_by_count", 0),
                "source_db": "OpenAlex",
            }
        )
    return _dedupe(records)


@st.cache_data(show_spinner=False, ttl=3600)
def search_crossref(query: str, start_date: date, end_date: date, max_results: int = 20) -> List[dict]:
    params = {
        "query.bibliographic": query,
        "filter": f"from-pub-date:{start_date.isoformat()},until-pub-date:{end_date.isoformat()},type:journal-article",
        "rows": max_results,
        "sort": "relevance",
        "select": "title,DOI,URL,publisher,container-title,author,issued,published-online,published-print,is-referenced-by-count,abstract",
        "mailto": os.getenv("CROSSREF_EMAIL", ""),
    }
    params = {k: v for k, v in params.items() if v != ""}
    data = _request("https://api.crossref.org/works", params=params, expect="json")
    items = data.get("message", {}).get("items", [])

    def crossref_date(entry: dict) -> str:
        for field in ["published-online", "published-print", "issued"]:
            parts = entry.get(field, {}).get("date-parts", [])
            if parts and parts[0]:
                vals = parts[0]
                year = vals[0]
                month = vals[1] if len(vals) > 1 else 1
                day = vals[2] if len(vals) > 2 else 1
                try:
                    return datetime(year, month, day).isoformat()
                except Exception:
                    continue
        return ""

    records: List[dict] = []
    for item in items:
        title = " ".join(item.get("title", [])).strip() or "Sin título"
        journal = " ".join(item.get("container-title", [])).strip() or item.get("publisher", "Crossref")
        authors = []
        for author in item.get("author", [])[:6]:
            given = author.get("given", "")
            family = author.get("family", "")
            full = f"{given} {family}".strip()
            if full:
                authors.append(full)
        doi = item.get("DOI", "")
        records.append(
            {
                "title": _strip_html(title),
                "snippet": _truncate(_strip_html(item.get("abstract", "")) or journal),
                "url": _clean_url(item.get("URL") or (f"https://doi.org/{doi}" if doi else "")),
                "source": journal,
                "published": crossref_date(item),
                "authors": ", ".join(authors),
                "doi": doi,
                "journal": journal,
                "cited_by_count": item.get("is-referenced-by-count", 0),
                "source_db": "Crossref",
            }
        )
    return _dedupe(records)


@st.cache_data(show_spinner=False, ttl=3600)
def search_semantic_scholar(query: str, start_date: date, end_date: date, max_results: int = 20) -> List[dict]:
    params = {
        "query": query,
        "limit": max_results,
        "fields": "title,abstract,year,authors,venue,url,externalIds,citationCount,publicationDate",
    }
    data = _request("https://api.semanticscholar.org/graph/v1/paper/search", params=params, expect="json")
    items = data.get("data", [])
    records: List[dict] = []
    for item in items:
        publication_date = item.get("publicationDate") or str(item.get("year", ""))
        published = _parse_date(publication_date)
        if published and not _date_in_range(published, start_date, end_date):
            continue
        external_ids = item.get("externalIds") or {}
        doi = external_ids.get("DOI", "")
        url = item.get("url") or (f"https://doi.org/{doi}" if doi else "")
        authors = ", ".join(a.get("name", "") for a in (item.get("authors") or [])[:6] if a.get("name"))
        records.append(
            {
                "title": _strip_html(item.get("title", "Sin título")),
                "snippet": _truncate(_strip_html(item.get("abstract", "")) or item.get("venue", "Semantic Scholar")),
                "url": _clean_url(url),
                "source": item.get("venue", "Semantic Scholar"),
                "published": published.isoformat() if published else publication_date,
                "authors": authors,
                "doi": doi,
                "journal": item.get("venue", ""),
                "cited_by_count": item.get("citationCount", 0),
                "source_db": "Semantic Scholar",
            }
        )
    return _dedupe(records)


def _score_science_record(item: dict, science_meta: dict) -> float:
    haystack = _normalize(
        " ".join(
            filter(
                None,
                [item.get("title", ""), item.get("snippet", ""), item.get("source", ""), item.get("journal", ""), item.get("authors", "")],
            )
        )
    )
    score = 0.0
    species_hits = 0
    topic_hits = 0
    for term in science_meta.get("species_terms", []):
        norm = _normalize(term)
        if norm and norm in haystack:
            species_hits += 1
            score += 2.0 if " " in norm else 1.0
    for term in science_meta.get("expanded_terms", []):
        norm = _normalize(term)
        if norm and norm in haystack:
            topic_hits += 1
            score += 3.0 if " " in norm else 1.2
    for term in science_meta.get("science_terms", []):
        norm = _normalize(term)
        if norm and norm in haystack:
            score += 0.4
    cited_by = item.get("cited_by_count") or 0
    if cited_by:
        score += min(math.log1p(cited_by), 3.5) * 0.25
    if item.get("doi"):
        score += 0.25
    source_bonus = {"Europe PMC": 1.2, "OpenAlex": 0.9, "Crossref": 0.7, "Semantic Scholar": 0.8}
    score += source_bonus.get(item.get("source_db", ""), 0.0)
    if topic_hits == 0:
        score -= 2.2
    if species_hits == 0:
        score -= 0.8
    return score


def search_scientific_sources(species: str, keyword_meta: dict, start_date: date, end_date: date, max_results: int) -> Tuple[List[dict], Dict[str, object]]:
    science_meta = build_science_queries(species, keyword_meta)
    queries = science_meta["queries"]
    target_fetch = max_results * SCIENTIFIC_FETCH_FACTOR
    collected: List[dict] = []
    for fetch_fn, query in [
        (search_europe_pmc, queries["europepmc"]),
        (search_openalex, queries["openalex"]),
        (search_crossref, queries["crossref"]),
        (search_semantic_scholar, queries["crossref"]),
    ]:
        try:
            collected.extend(fetch_fn(query, start_date, end_date, max_results=target_fetch))
        except Exception:
            continue

    deduped = _dedupe(collected)
    ranked = []
    for item in deduped:
        enriched = dict(item)
        enriched["score"] = _score_science_record(enriched, science_meta)
        ranked.append(enriched)
    ranked.sort(key=lambda x: (x.get("score", 0), x.get("published", ""), x.get("cited_by_count", 0)), reverse=True)
    filtered = [item for item in ranked if item.get("score", 0) >= 0.3]

    if len(filtered) < max(4, max_results // 2):
        extra: List[dict] = []
        for fetch_fn in [search_openalex, search_crossref]:
            try:
                extra.extend(fetch_fn(queries["broad"], start_date, end_date, max_results=target_fetch))
            except Exception:
                continue
        ranked = []
        for item in _dedupe(filtered + extra):
            enriched = dict(item)
            enriched["score"] = _score_science_record(enriched, science_meta)
            ranked.append(enriched)
        ranked.sort(key=lambda x: (x.get("score", 0), x.get("published", ""), x.get("cited_by_count", 0)), reverse=True)
        filtered = [item for item in ranked if item.get("score", 0) >= 0.2]

    return filtered[:max_results], science_meta


# -----------------
# Orchestration
# -----------------

def build_queries(species: str, user_keywords: str) -> dict:
    keyword_meta = expand_user_keywords(user_keywords, species)
    market_queries = build_market_queries(species, keyword_meta)
    regulation_queries = build_regulation_queries(species, keyword_meta)
    return {
        "keyword_meta": keyword_meta,
        "market_queries": market_queries,
        "regulation_queries": regulation_queries,
    }


def run_search(species: str, user_keywords: str, start_date: date, end_date: date, max_results: int) -> Tuple[Dict[str, List[dict]], Dict[str, object]]:
    query_meta = build_queries(species, user_keywords)
    keyword_meta = query_meta["keyword_meta"]
    results: Dict[str, List[dict]] = {"market": [], "science": [], "regulation": []}

    results["market"], market_queries = search_market_sources(species, keyword_meta, start_date, end_date, max_results)
    results["science"], science_meta = search_scientific_sources(species, keyword_meta, start_date, end_date, max_results)
    results["regulation"], regulation_queries = search_regulatory_sources(species, keyword_meta, start_date, end_date, max_results)

    query_meta["market_queries"] = market_queries
    query_meta["science_meta"] = science_meta
    query_meta["regulation_queries"] = regulation_queries
    return results, query_meta


def flatten_results(results: Dict[str, List[dict]]) -> List[dict]:
    flat: List[dict] = []
    for key, items in results.items():
        for item in items:
            enriched = dict(item)
            enriched["category"] = CATEGORY_LABELS[key]
            flat.append(enriched)
    return flat


def corpus_text(results: Dict[str, List[dict]], limit_per_category: int = MAX_CONTEXT_ITEMS) -> str:
    lines: List[str] = []
    for key in ["market", "science", "regulation"]:
        lines.append(f"\n## {CATEGORY_LABELS[key]}\n")
        for idx, item in enumerate(results.get(key, [])[:limit_per_category], start=1):
            lines.append(
                f"[{idx}] {item.get('title', '')}\n"
                f"Fecha: {item.get('published', '')[:10]}\n"
                f"Fuente: {item.get('source', '')}\n"
                f"Base: {item.get('source_db', '')}\n"
                f"Resumen: {item.get('snippet', '')}\n"
                f"URL: {item.get('url', '')}\n"
            )
    return "\n".join(lines)


def llm_is_available() -> bool:
    return bool(os.getenv("OPENAI_API_KEY")) and OpenAI is not None


def call_openai(system_prompt: str, user_prompt: str) -> str:
    if not llm_is_available():
        raise RuntimeError("No hay configuración de OpenAI disponible.")
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    try:
        response = client.responses.create(model=model, instructions=system_prompt, input=user_prompt)
        if getattr(response, "output_text", None):
            return response.output_text.strip()
    except Exception:
        pass
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        temperature=0.2,
    )
    return (response.choices[0].message.content or "").strip()


def extractive_brief(species: str, user_keywords: str, results: Dict[str, List[dict]], company_context: str, chat_history: List[dict], query_meta: dict) -> str:
    flat = flatten_results(results)
    if not flat:
        return "No se han recuperado resultados suficientes para elaborar el briefing."

    corpus = " ".join(filter(None, [item.get("title", "") + " " + item.get("snippet", "") for item in flat]))
    themes = _keywords_from_text(corpus, top_k=10)
    top_market = results.get("market", [])[:4]
    top_science = results.get("science", [])[:4]
    top_reg = results.get("regulation", [])[:4]
    expanded_terms = query_meta.get("keyword_meta", {}).get("expanded_terms", [])

    lines = [
        f"# Briefing radar | {species}",
        "",
        "## Resumen ejecutivo",
        f"Búsqueda enfocada en: **{user_keywords or species}**.",
        f"Resultados recuperados: **{len(results.get('market', []))}** de mercado, **{len(results.get('science', []))}** científico-técnicos y **{len(results.get('regulation', []))}** regulatorios.",
        f"Temas más repetidos: {', '.join(themes[:6]) if themes else 'sin patrón claro'}.",
    ]
    if expanded_terms:
        lines.append(f"La búsqueda amplió automáticamente sinónimos y términos relacionados: {', '.join(expanded_terms[:10])}.")

    lines.extend(["", "## Radar de mercado"])
    if top_market:
        for item in top_market:
            lines.append(f"- **{item['title']}** ({item.get('source', 'Fuente')}, {item.get('published', 's/f')[:10]}). {item.get('snippet', '')} {item.get('url', '')}")
    else:
        lines.append("- No se han encontrado resultados recientes de mercado con la combinación actual de filtros.")

    lines.extend(["", "## Radar científico-técnico"])
    if top_science:
        for item in top_science:
            journal = item.get("journal") or item.get("source", "Fuente científica")
            lines.append(f"- **{item['title']}** ({journal}, {item.get('published', 's/f')[:10]}, {item.get('source_db', '')}). {item.get('snippet', '')} {item.get('url', '')}")
    else:
        lines.append("- No se han encontrado artículos suficientes con la combinación actual de filtros.")

    lines.extend(["", "## Radar regulatorio"])
    if top_reg:
        for item in top_reg:
            lines.append(f"- **{item['title']}** ({item.get('source', 'Fuente oficial')}, {item.get('published', 's/f')[:10]}). {item.get('snippet', '')} {item.get('url', '')}")
    else:
        lines.append("- No se han encontrado novedades regulatorias relevantes con la combinación actual de filtros.")

    lines.extend([
        "",
        "## Recomendaciones preliminares para Nutreco Iberia",
        "- Convertir las señales repetidas en contenidos técnico-comerciales por especie y segmento.",
        "- Revisar semanalmente las publicaciones oficiales del MAPA sobre precios, coyuntura e indicadores económicos del sector.",
        "- Validar cualquier implicación regulatoria directamente en BOE/MAPA antes de trasladarla a clientes o claims.",
        "- Mantener una lista viva de palabras clave y sinónimos por especie para evitar pérdidas de cobertura.",
    ])

    if chat_history:
        lines.extend(["", "## Aclaraciones del chat previas al informe"])
        for turn in chat_history[-6:]:
            role = "Usuario" if turn["role"] == "user" else "App"
            lines.append(f"- **{role}:** {turn['content']}")

    lines.extend(["", "## Contexto corporativo utilizado", company_context.strip()])
    return "\n".join(lines)


def generate_brief(species: str, user_keywords: str, results: Dict[str, List[dict]], company_context: str, chat_history: List[dict], query_meta: dict) -> str:
    if not llm_is_available():
        return extractive_brief(species, user_keywords, results, company_context, chat_history, query_meta)
    system_prompt = (
        "Eres un analista senior de inteligencia de mercado y asuntos regulatorios para nutrición animal. "
        "Debes sintetizar únicamente con base en las fuentes suministradas. "
        "No inventes datos ni recomendaciones específicas no sustentadas. "
        "Escribe en español, con tono ejecutivo y estructura clara."
    )
    chat_block = "\n".join([f"{m['role']}: {m['content']}" for m in chat_history[-8:]]) if chat_history else "Sin aclaraciones adicionales."
    user_prompt = f"""
Genera un briefing ejecutable para Nutreco Iberia.

Especie/segmento: {species}
Palabras clave: {user_keywords or '(sin palabras clave adicionales)'}
Términos ampliados automáticamente: {', '.join(query_meta.get('keyword_meta', {}).get('expanded_terms', [])[:12])}
Consultas mercado: {', '.join(query_meta.get('market_queries', [])[:8])}
Consultas regulatorias: {', '.join(query_meta.get('regulation_queries', [])[:8])}

Contexto corporativo:
{company_context}

Aclaraciones previas del chat:
{chat_block}

Corpus de resultados:
{corpus_text(results)}

Estructura obligatoria:
1. Resumen ejecutivo.
2. Señales de mercado.
3. Hallazgos científico-técnicos.
4. Implicaciones regulatorias.
5. Recomendaciones priorizadas para Nutreco Iberia (inmediatas, 30-90 días, seguimiento).
6. Riesgos, vacíos de información y preguntas abiertas.

Reglas:
- No cites información no presente en el corpus.
- Marca de forma explícita cuando una conclusión sea tentativa.
- No generes bibliografía final porque la app la añadirá aparte.
"""
    return call_openai(system_prompt, user_prompt)


def answer_chat(question: str, species: str, user_keywords: str, results: Dict[str, List[dict]], company_context: str, chat_history: List[dict]) -> str:
    if not question.strip():
        return ""
    if llm_is_available():
        system_prompt = (
            "Responde como analista sectorial. Usa solo las fuentes suministradas. "
            "Si no hay base suficiente en las fuentes, dilo de forma explícita. Responde en español."
        )
        history_block = "\n".join([f"{m['role']}: {m['content']}" for m in chat_history[-8:]]) if chat_history else ""
        user_prompt = f"""
Contexto corporativo:
{company_context}

Especie/segmento: {species}
Palabras clave: {user_keywords or '(sin palabras clave adicionales)'}

Historial del chat:
{history_block}

Corpus de resultados:
{corpus_text(results)}

Pregunta del usuario:
{question}
"""
        return call_openai(system_prompt, user_prompt)

    candidate_items = []
    tokens = set(_keywords_from_text(question, top_k=12))
    for item in flatten_results(results):
        haystack = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
        score = sum(1 for token in tokens if token in haystack)
        if score > 0:
            candidate_items.append((score, item))
    candidate_items.sort(key=lambda x: x[0], reverse=True)

    if not candidate_items:
        return "No encuentro evidencia suficiente en los resultados actuales para responder con precisión. Prueba a ampliar fechas o ajustar palabras clave."

    lines = ["He localizado esta evidencia relevante en los resultados recuperados:"]
    for _, item in candidate_items[:4]:
        lines.append(f"- {item.get('title')} ({item.get('source', 'Fuente')}, {item.get('published', 's/f')[:10]}): {item.get('snippet', '')} {item.get('url', '')}")
    lines.append("Conclusión provisional: conviene validar este punto con una revisión manual de la fuente primaria antes de cerrar el informe.")
    return "\n".join(lines)


def bibliography_entries(results: Dict[str, List[dict]]) -> List[str]:
    entries: List[str] = []
    for item in flatten_results(results):
        published = item.get("published", "")[:10] if item.get("published") else "s/f"
        if item.get("category") == CATEGORY_LABELS["science"]:
            authors = item.get("authors", "Autoría no disponible")
            journal = item.get("journal") or item.get("source", "Fuente científica")
            doi_or_url = item.get("doi") or item.get("url", "")
            entries.append(f"{authors}. ({published}). {item.get('title')}. {journal}. {doi_or_url}")
        else:
            entries.append(f"{item.get('source', 'Fuente no indicada')}. ({published}). {item.get('title')}. {item.get('url', '')}")
    return entries


def build_docx_bytes(species: str, user_keywords: str, start_date: date, end_date: date, company_context: str, brief_text: str, results: Dict[str, List[dict]]) -> bytes:
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


def results_dataframe(items: List[dict]) -> pd.DataFrame:
    rows = []
    for item in items:
        rows.append(
            {
                "Fecha": item.get("published", "")[:10],
                "Fuente": item.get("source", ""),
                "Base": item.get("source_db", ""),
                "Título": item.get("title", ""),
                "Resumen": item.get("snippet", ""),
                "URL": item.get("url", ""),
                "Score": round(float(item.get("score", 0)), 2),
            }
        )
    return pd.DataFrame(rows, columns=["Fecha", "Fuente", "Base", "Título", "Resumen", "URL", "Score"])


def render_category_table(items: List[dict], label: str) -> None:
    st.subheader(label)
    if not items:
        st.info("Sin resultados con los filtros actuales.")
        return
    df = results_dataframe(items)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={"URL": st.column_config.LinkColumn("URL")},
    )
    with st.expander("Ver fuentes como listado con enlaces"):
        for item in items:
            title = item.get("title", "Sin título")
            source = item.get("source", "Fuente")
            published = item.get("published", "")[:10] or "s/f"
            url = item.get("url", "")
            snippet = item.get("snippet", "")
            st.markdown(f"- **{title}** ({source}, {published}) — {snippet}  ")
            if url:
                st.markdown(f"  [Abrir fuente]({url})")


def init_state() -> None:
    st.session_state.setdefault("search_results", None)
    st.session_state.setdefault("query_meta", {})
    st.session_state.setdefault("brief_text", "")
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("last_filters", {})


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    init_state()

    st.title(APP_TITLE)
    st.caption(
        "Radar de mercado, evidencia científico-técnica y vigilancia regulatoria. "
        "La capa de búsqueda funciona sin clave de OpenAI; la síntesis mejora si luego la activas."
    )

    with st.sidebar:
        st.header("Filtros")
        species = st.selectbox("Especie / segmento", list(SPECIES_OPTIONS.keys()))
        today = date.today()
        default_start = today - timedelta(days=90)
        start_date = st.date_input("Fecha inicio", value=default_start)
        end_date = st.date_input("Fecha fin", value=today)
        user_keywords = st.text_input(
            "Palabras clave",
            placeholder="Ej.: peste porcina africana, metano, precio leche, influenza aviar...",
        )
        max_results = st.slider("Máximo de resultados por bloque", min_value=5, max_value=25, value=12, step=1)
        company_context = st.text_area("Contexto corporativo / criterios de recomendación", value=DEFAULT_COMPANY_CONTEXT, height=190)
        run_button = st.button("Buscar y actualizar radar", use_container_width=True)
        generate_button = st.button("Generar briefing", use_container_width=True)

    if start_date > end_date:
        st.error("La fecha inicial no puede ser posterior a la fecha final.")
        return

    if run_button:
        with st.spinner("Recuperando fuentes..."):
            try:
                results, query_meta = run_search(species, user_keywords, start_date, end_date, max_results)
                st.session_state.search_results = results
                st.session_state.query_meta = query_meta
                st.session_state.last_filters = {
                    "species": species,
                    "keywords": user_keywords,
                    "start_date": start_date,
                    "end_date": end_date,
                    "company_context": company_context,
                }
                st.session_state.brief_text = ""
                st.session_state.chat_history = []
                st.success("Radar actualizado.")
            except Exception as exc:
                st.error(f"No se pudo completar la búsqueda: {exc}")

    results = st.session_state.search_results
    query_meta = st.session_state.query_meta or {}

    if results:
        col1, col2, col3 = st.columns(3)
        col1.metric("Mercado", len(results.get("market", [])))
        col2.metric("Científico-técnico", len(results.get("science", [])))
        col3.metric("Regulación", len(results.get("regulation", [])))

        with st.expander("Cómo se ha ampliado la búsqueda"):
            keyword_meta = query_meta.get("keyword_meta", {})
            expanded_terms = keyword_meta.get("expanded_terms", [])
            st.markdown(f"**Palabras clave originales:** {user_keywords or 'sin palabras clave adicionales'}")
            st.markdown(f"**Términos ampliados:** {', '.join(expanded_terms[:15]) if expanded_terms else 'sin ampliación'}")
            st.markdown(f"**Consultas de mercado:** {', '.join(query_meta.get('market_queries', [])[:8])}")
            st.markdown(f"**Consultas regulatorias:** {', '.join(query_meta.get('regulation_queries', [])[:8])}")
            science_links = query_meta.get("science_meta", {}).get("external_links", {})
            if science_links:
                st.markdown("**Atajos científicos externos:**")
                for name, link in science_links.items():
                    st.markdown(f"- [{name}]({link})")

        tab_market, tab_science, tab_reg, tab_chat, tab_brief = st.tabs(
            ["Mercado", "Científico-técnico", "Legislación", "Chat", "Briefing e informe"]
        )

        with tab_market:
            st.caption("Incluye prensa sectorial, publicaciones oficiales del MAPA sobre precios/mercados y noticias del Ministerio.")
            render_category_table(results.get("market", []), "Señales de mercado")

        with tab_science:
            render_category_table(results.get("science", []), "Evidencia científico-técnica")
            science_links = query_meta.get("science_meta", {}).get("external_links", {})
            if science_links:
                st.markdown("**Búsqueda externa complementaria:**")
                for name, link in science_links.items():
                    st.markdown(f"- [{name}]({link})")

        with tab_reg:
            st.caption("Incluye BOE, páginas oficiales de legislación del MAPA y noticias ministeriales con impacto normativo.")
            render_category_table(results.get("regulation", []), "Vigilancia regulatoria")

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
                        brief_text = generate_brief(species, user_keywords, results, company_context, st.session_state.chat_history, query_meta)
                        st.session_state.brief_text = brief_text
                    except Exception as exc:
                        st.error(f"No se pudo generar el briefing: {exc}")

            if st.session_state.brief_text:
                st.markdown(st.session_state.brief_text)
                docx_bytes = build_docx_bytes(species, user_keywords, start_date, end_date, company_context, st.session_state.brief_text, results)
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
                st.info("Primero ejecuta la búsqueda y luego genera el briefing.")
    else:
        st.info("Configura los filtros en la barra lateral y pulsa **Buscar y actualizar radar**.")

    st.divider()
    st.caption(
        "Aviso: esta herramienta no sustituye la revisión técnica, regulatoria ni jurídica. "
        "Antes de usar conclusiones en documentos externos o claims comerciales, valida cada punto con la fuente primaria."
    )


if __name__ == "__main__":
    main()
