from __future__ import annotations

import io
import os
import re
import time
import unicodedata
import zipfile
from collections import Counter
from datetime import date, datetime, timezone
from html import unescape
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import feedparser
import requests
import streamlit as st
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from docx import Document

APP_TITLE = "Nutreco Iberia | Radar sectorial de mercado"
USER_AGENT = "Mozilla/5.0 (compatible; NutrecoRadar/6.0; +https://streamlit.io)"
REQUEST_TIMEOUT = 18
DEFAULT_MAX_RESULTS = 12

CATEGORY_LABELS = {
    "market": "Mercado",
    "science": "Científico-técnico",
    "regulation": "Legislación y regulación",
}

DEFAULT_COMPANY_CONTEXT = """Objetivo del radar:
- Detectar necesidades del mercado antes que el cliente las verbalice.
- Traducir señales de prensa, ciencia y regulación a oportunidades de producto, servicio y argumentario.
- Priorizar implicaciones accionables para Nutreco Iberia.
"""

MAPA_NEWS_RSS_URL = "https://www.mapa.gob.es/es/prensa/noticiasrss"
MAPA_MARKETS_URL = "https://www.mapa.gob.es/es/ganaderia/estadisticas/mercados_agricolas_ganaderos"
MAPA_LEGISLATION_URL = "https://www.mapa.gob.es/es/ganaderia/legislacion"
DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"

MARKET_MEDIA_DOMAINS = [
    "mapa.gob.es",
    "efeagro.com",
    "agrodigital.com",
    "interempresas.net",
    "avicultura.com",
    "porcino.info",
    "vacapinta.com",
    "eurocarne.com",
]

OFFICIAL_REGULATORY_DOMAINS = {
    "boe.es",
    "www.boe.es",
    "eur-lex.europa.eu",
    "mapa.gob.es",
    "www.mapa.gob.es",
    "aesan.gob.es",
    "www.aesan.gob.es",
    "efsa.europa.eu",
    "www.efsa.europa.eu",
    "sanidad.gob.es",
    "www.sanidad.gob.es",
    "miteco.gob.es",
    "www.miteco.gob.es",
}

LEGAL_ANCHORS = [
    "reglamento",
    "regulation",
    "real decreto",
    "ley",
    "orden",
    "resolucion",
    "resolución",
    "directiva",
    "directive",
    "decision",
    "decisión",
    "normativa",
    "legislacion",
    "legislation",
    "boe",
    "eur-lex",
    "regulatory",
    "wellfare",
    "welfare",
    "sanidad animal",
    "trazabilidad",
    "animal health law",
    "etiquetado",
]

MARKET_ANCHORS = [
    "precio",
    "precios",
    "cotizacion",
    "cotización",
    "mercado",
    "markets",
    "market",
    "boletin",
    "boletín",
    "noticia",
    "sector",
    "consumo",
    "demanda",
    "exportacion",
    "exportación",
    "importacion",
    "importación",
    "coste",
    "costes",
    "margen",
    "márgenes",
    "raw materials",
    "feed costs",
    "piensos",
]

SCIENCE_ANCHORS = [
    "trial",
    "review",
    "effect",
    "efficacy",
    "nutrition",
    "performance",
    "health",
    "welfare",
    "microbiota",
    "mastitis",
    "biosecurity",
    "pathogen",
    "emissions",
    "methane",
]

STOPWORDS = {
    "de", "la", "el", "los", "las", "y", "o", "en", "para", "por", "con", "del", "al", "un", "una",
    "que", "sobre", "entre", "como", "más", "menos", "muy", "sin", "from", "the", "and", "for", "this", "that",
    "market", "mercado", "sector", "regulation", "science", "technical", "animal", "animals", "ganaderia", "ganadería",
    "ministerio", "agricultura", "españa", "espana", "official", "update", "news", "article",
}

SPECIES_OPTIONS: Dict[str, Dict[str, object]] = {
    "Alimentación animal": {
        "aliases": [
            "alimentación animal", "nutrición animal", "piensos", "feed", "animal feed", "ganadería", "livestock",
            "porcino", "vacuno", "ovino", "caprino", "avicultura", "cunicultura",
        ],
        "science_fallback": ["animal nutrition", "feed efficiency", "gut health", "sustainability"],
    },
    "Avicultura de puesta": {
        "aliases": ["avicultura de puesta", "gallinas ponedoras", "huevos", "layers", "laying hens", "egg sector"],
        "science_fallback": ["laying hens", "egg quality", "shell quality", "salmonella", "nutrition"],
    },
    "Avicultura de carne": {
        "aliases": ["avicultura de carne", "pollos de engorde", "broilers", "broiler chickens", "pollo", "chicken meat sector"],
        "science_fallback": ["broilers", "gut health", "coccidiosis", "feed conversion", "necrotic enteritis"],
    },
    "Porcino": {
        "aliases": ["porcino", "cerdo", "swine", "pig", "pigs", "hog sector"],
        "science_fallback": ["swine nutrition", "gut health", "weaning", "biosecurity", "reproduction"],
    },
    "Vacuno de leche": {
        "aliases": ["vacuno de leche", "vacas de leche", "sector lácteo", "dairy cattle", "dairy cows", "milk sector"],
        "science_fallback": ["dairy cows", "transition cow", "mastitis", "milk quality", "rumen"],
    },
    "Vacuno de carne": {
        "aliases": ["vacuno de carne", "beef cattle", "beef sector", "cebaderos", "fattening cattle"],
        "science_fallback": ["beef cattle", "average daily gain", "welfare", "respiratory disease", "methane"],
    },
    "Ovino": {
        "aliases": ["ovino", "cordero", "sheep", "ovine", "lamb sector"],
        "science_fallback": ["sheep nutrition", "parasites", "milk quality", "reproduction", "bluetongue"],
    },
    "Caprino": {
        "aliases": ["caprino", "goat", "goats", "goat milk", "caprine sector"],
        "science_fallback": ["goat nutrition", "mastitis", "parasites", "reproduction", "milk quality"],
    },
    "Cunicultura": {
        "aliases": ["cunicultura", "conejo", "conejos", "rabbit production", "rabbit sector"],
        "science_fallback": ["rabbit nutrition", "digestive health", "enteropathy", "welfare", "reproduction"],
    },
}

TOPIC_OPTIONS: Dict[str, Dict[str, List[str]]] = {
    "Precios y cotizaciones": {
        "aliases": ["precios", "cotizaciones", "precio", "prices"],
        "market": ["precio", "precios", "cotizaciones", "mercado", "boletín de precios", "market prices"],
        "science": ["production efficiency", "feed conversion", "cost of production"],
        "regulation": ["comercialización", "mercado", "informes sectoriales"],
    },
    "Costes de alimentación": {
        "aliases": ["costes de alimentación", "coste de pienso", "feed costs", "feeding costs"],
        "market": ["costes de alimentación", "piensos", "feed costs", "raw materials", "materias primas"],
        "science": ["feed efficiency", "digestibility", "feed conversion", "nutrient utilization"],
        "regulation": ["piensos", "alimentación animal", "feed regulation"],
    },
    "Materias primas y piensos": {
        "aliases": ["materias primas", "piensos", "feed", "compound feed"],
        "market": ["materias primas", "piensos", "soja", "maíz", "cereales", "feed market"],
        "science": ["feed additives", "feed formulation", "nutritional value", "ingredient quality"],
        "regulation": ["feed hygiene", "aditivos", "alimentación animal"],
    },
    "Rentabilidad y márgenes": {
        "aliases": ["rentabilidad", "márgenes", "margen", "profitability"],
        "market": ["rentabilidad", "márgenes", "costes", "beneficio", "profitability"],
        "science": ["economic efficiency", "performance", "feed efficiency"],
        "regulation": ["ayudas", "mercado", "sector ganadero"],
    },
    "Consumo y demanda": {
        "aliases": ["consumo", "demanda", "consumer demand"],
        "market": ["consumo", "demanda", "retail", "hostelería", "consumer demand"],
        "science": ["consumer perception", "quality traits", "shelf life"],
        "regulation": ["etiquetado", "comercialización", "información alimentaria"],
    },
    "Exportación e importación": {
        "aliases": ["exportación", "importación", "trade", "export"],
        "market": ["exportación", "importación", "trade", "mercados exteriores", "export"],
        "science": ["trade disease risk", "quality assurance"],
        "regulation": ["comercio exterior", "certificación", "sanidad animal"],
    },
    "Bienestar animal": {
        "aliases": ["bienestar animal", "animal welfare", "welfare"],
        "market": ["bienestar animal", "certificación", "exigencias del mercado", "animal welfare"],
        "science": ["animal welfare", "stress", "behaviour", "housing"],
        "regulation": ["bienestar animal", "animal welfare", "transport", "housing requirements"],
    },
    "Bioseguridad": {
        "aliases": ["bioseguridad", "biosecurity"],
        "market": ["bioseguridad", "brotes", "riesgo sanitario", "biosecurity"],
        "science": ["biosecurity", "disease prevention", "farm biosecurity"],
        "regulation": ["bioseguridad", "sanidad animal", "control de enfermedades"],
    },
    "Sanidad animal": {
        "aliases": ["sanidad animal", "animal health"],
        "market": ["sanidad animal", "brotes", "alerta sanitaria", "animal health"],
        "science": ["animal health", "disease control", "epidemiology"],
        "regulation": ["sanidad animal", "animal health law", "control oficial"],
    },
    "Antimicrobianos y resistencias": {
        "aliases": ["antimicrobianos", "antibióticos", "resistencias", "AMR"],
        "market": ["antibióticos", "resistencias", "uso prudente", "AMR"],
        "science": ["antimicrobial resistance", "antibiotic reduction", "AMR"],
        "regulation": ["medicación veterinaria", "antimicrobianos", "resistencias"],
    },
    "Vacunación y prevención": {
        "aliases": ["vacunación", "vacunas", "prevención", "vaccination"],
        "market": ["vacunación", "prevención", "programas sanitarios"],
        "science": ["vaccination", "immunity", "disease prevention"],
        "regulation": ["programas sanitarios", "vacunación", "control de enfermedades"],
    },
    "Trazabilidad y movimientos": {
        "aliases": ["trazabilidad", "movimientos", "traceability", "animal movements"],
        "market": ["movimientos", "trazabilidad", "restricciones", "transport"],
        "science": ["traceability", "animal movements", "disease spread"],
        "regulation": ["trazabilidad", "movimientos", "identificación", "transport"],
    },
    "Sostenibilidad y emisiones": {
        "aliases": ["sostenibilidad", "emisiones", "sustainability", "emissions"],
        "market": ["sostenibilidad", "emisiones", "descarbonización", "ESG"],
        "science": ["emissions", "life cycle assessment", "sustainability", "carbon footprint"],
        "regulation": ["emisiones", "sostenibilidad", "clima", "medio ambiente"],
    },
    "Metano y huella de carbono": {
        "aliases": ["metano", "huella de carbono", "methane", "carbon footprint"],
        "market": ["metano", "huella de carbono", "descarbonización"],
        "science": ["methane", "enteric methane", "carbon footprint", "GHG"],
        "regulation": ["metano", "huella de carbono", "emisiones"],
    },
    "Calidad del producto": {
        "aliases": ["calidad del producto", "milk quality", "egg quality", "meat quality"],
        "market": ["calidad", "valor añadido", "calidad del producto"],
        "science": ["milk quality", "egg quality", "meat quality", "quality traits"],
        "regulation": ["calidad", "higiene", "seguridad alimentaria"],
    },
    "Reproducción y fertilidad": {
        "aliases": ["reproducción", "fertilidad", "reproduction", "fertility"],
        "market": ["fertilidad", "productividad", "reposición"],
        "science": ["reproduction", "fertility", "semen quality", "ovulation"],
        "regulation": ["reproducción", "centros de reproducción", "sanidad"],
    },
    "Salud intestinal": {
        "aliases": ["salud intestinal", "gut health", "intestinal health"],
        "market": ["salud intestinal", "eficiencia", "gut health"],
        "science": ["gut health", "microbiota", "intestinal integrity", "digestive health"],
        "regulation": ["aditivos", "nutrición", "salud intestinal"],
    },
    "Micotoxinas": {
        "aliases": ["micotoxinas", "mycotoxins"],
        "market": ["micotoxinas", "contaminación", "materias primas"],
        "science": ["mycotoxins", "deoxynivalenol", "aflatoxin", "detoxifiers"],
        "regulation": ["micotoxinas", "piensos", "seguridad alimentaria"],
    },
    "Salmonella": {
        "aliases": ["salmonella"],
        "market": ["salmonella", "alerta alimentaria", "brote"],
        "science": ["salmonella", "control", "vaccination", "hygiene"],
        "regulation": ["salmonella", "control oficial", "programas nacionales"],
    },
    "Coccidiosis": {
        "aliases": ["coccidiosis", "coccidia"],
        "market": ["coccidiosis", "brotes", "control"],
        "science": ["coccidiosis", "eimeria", "anticoccidials", "vaccination"],
        "regulation": ["coccidiosis", "medicación veterinaria", "control"],
    },
    "Mastitis": {
        "aliases": ["mastitis", "mamitis"],
        "market": ["mastitis", "calidad de leche", "coste sanitario"],
        "science": ["mastitis", "udder health", "somatic cell count", "intramammary infection"],
        "regulation": ["calidad de leche", "higiene", "mastitis"],
    },
    "Peste porcina africana": {
        "aliases": ["peste porcina africana", "PPA", "African swine fever", "ASF"],
        "market": ["peste porcina africana", "African swine fever", "restricciones", "exportación"],
        "science": ["African swine fever", "ASF", "ASFV", "biosecurity"],
        "regulation": ["peste porcina africana", "African swine fever", "zonificación", "movimientos"],
    },
    "Influenza aviar": {
        "aliases": ["influenza aviar", "avian influenza", "HPAI", "bird flu"],
        "market": ["influenza aviar", "avian influenza", "brotes", "restricciones"],
        "science": ["avian influenza", "HPAI", "H5N1", "biosecurity"],
        "regulation": ["influenza aviar", "avian influenza", "zonas de restricción", "bioseguridad"],
    },
    "Lengua azul": {
        "aliases": ["lengua azul", "bluetongue", "BTV"],
        "market": ["lengua azul", "bluetongue", "movimientos", "restricciones"],
        "science": ["bluetongue", "BTV", "vector control", "vaccination"],
        "regulation": ["lengua azul", "bluetongue", "movimientos", "vacunación"],
    },
    "Etiquetado y comercialización": {
        "aliases": ["etiquetado", "comercialización", "labeling", "marketing standards"],
        "market": ["etiquetado", "comercialización", "valor añadido"],
        "science": ["labeling", "quality traits", "consumer perception"],
        "regulation": ["etiquetado", "comercialización", "información alimentaria"],
    },
    "Normativa de alimentación animal": {
        "aliases": ["alimentación animal", "feed regulation", "feed hygiene", "piensos"],
        "market": ["piensos", "alimentación animal", "aditivos"],
        "science": ["feed regulation", "feed additives", "feed hygiene"],
        "regulation": ["alimentación animal", "piensos", "aditivos", "feed hygiene"],
    },
}


# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------

def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s\-/]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _strip_html(text: str) -> str:
    return BeautifulSoup(text or "", "html.parser").get_text(" ", strip=True)


def _truncate(text: str, max_len: int = 360) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _canonical_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/")
    return f"{parsed.netloc.lower()}{path.lower()}"


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _clean_url(url: str, base_url: str = "") -> str:
    if not url:
        return ""
    return urljoin(base_url, url.strip())


def _request(url: str, *, params: Optional[dict] = None, expect: str = "text"):
    last_error = None
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
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.6)
    raise RuntimeError(f"Error al consultar una fuente externa: {last_error}")


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
        return _normalize_datetime(date_parser.parse(str(value), fuzzy=True))
    except Exception:
        return None


def _date_in_range(value: Optional[datetime], start: date, end: date) -> bool:
    if value is None:
        return True
    return start <= value.date() <= end


def _unique_keep_order(items: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        clean = re.sub(r"\s+", " ", (item or "").strip())
        if not clean:
            continue
        key = _normalize(clean)
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def _record_key(item: dict) -> Tuple[str, str]:
    if item.get("doi"):
        return ("doi", _normalize(item["doi"]))
    if item.get("url"):
        return ("url", _canonical_url(item["url"]))
    return ("title", _normalize(item.get("title", "")))


def _dedupe(records: List[dict]) -> List[dict]:
    seen = set()
    out = []
    for item in records:
        key = _record_key(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _keywords_from_text(text: str, *, exclude: Sequence[str] = (), top_k: int = 8) -> List[str]:
    exclude_norm = {_normalize(t) for t in exclude}
    words = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñÜü0-9\-]{4,}", text.lower())
    counts = Counter()
    for word in words:
        norm = _normalize(word)
        if norm in STOPWORDS or norm in exclude_norm or len(norm) < 4:
            continue
        counts[norm] += 1
    return [w for w, _ in counts.most_common(top_k)]


def _contains_any(text: str, terms: Sequence[str]) -> bool:
    hay = _normalize(text)
    return any(_normalize(term) in hay for term in terms if term)


def _extract_ddg_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    if href.startswith("/") and "uddg=" not in href:
        return ""
    if "uddg=" in href:
        parsed = urlparse(href)
        query = parse_qs(parsed.query)
        if query.get("uddg"):
            return unquote(query["uddg"][0])
    return href


# -----------------------------------------------------------------------------
# Search profile
# -----------------------------------------------------------------------------

def build_search_profile(species: str, topics: Sequence[str]) -> Dict[str, List[str]]:
    species_data = SPECIES_OPTIONS[species]
    selected_topics = [topic for topic in topics if topic in TOPIC_OPTIONS]
    if not selected_topics:
        selected_topics = ["Precios y cotizaciones"]

    topic_aliases: List[str] = []
    market_terms: List[str] = []
    science_terms: List[str] = []
    regulation_terms: List[str] = []

    for topic in selected_topics:
        topic_info = TOPIC_OPTIONS[topic]
        topic_aliases.extend(topic_info["aliases"])
        market_terms.extend(topic_info["market"])
        science_terms.extend(topic_info["science"])
        regulation_terms.extend(topic_info["regulation"])

    if not science_terms:
        science_terms.extend(species_data.get("science_fallback", []))

    return {
        "selected_topics": selected_topics,
        "species_terms": _unique_keep_order(species_data["aliases"]),
        "topic_aliases": _unique_keep_order(topic_aliases),
        "market_terms": _unique_keep_order(market_terms),
        "science_terms": _unique_keep_order(science_terms + species_data.get("science_fallback", [])),
        "regulation_terms": _unique_keep_order(regulation_terms),
        "market_debug": _unique_keep_order(market_terms[:8]),
        "regulation_debug": _unique_keep_order(regulation_terms[:8]),
    }


# -----------------------------------------------------------------------------
# External sources
# -----------------------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=1800)
def search_google_news(query: str, start_date: date, end_date: date, max_results: int = 8) -> List[dict]:
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
def search_duckduckgo_html(query: str, max_results: int = 8) -> List[dict]:
    html = _request(DUCKDUCKGO_HTML_URL, params={"q": query, "kl": "es-es"}, expect="text")
    soup = BeautifulSoup(html, "html.parser")
    records: List[dict] = []
    results = soup.select("div.result")
    for result in results:
        anchor = result.select_one("a.result__a")
        if not anchor:
            continue
        href = _extract_ddg_url(anchor.get("href", ""))
        if not href:
            continue
        title = _strip_html(anchor.get_text(" ", strip=True))
        snippet_node = result.select_one("a.result__snippet") or result.select_one("div.result__snippet")
        snippet = _truncate(_strip_html(snippet_node.get_text(" ", strip=True)) if snippet_node else "")
        records.append(
            {
                "title": title or "Sin título",
                "snippet": snippet,
                "url": href,
                "source": _domain(href) or "DuckDuckGo",
                "published": "",
                "source_db": "DuckDuckGo",
                "query_used": query,
            }
        )
        if len(records) >= max_results:
            break
    return _dedupe(records)


@st.cache_data(show_spinner=False, ttl=3600)
def search_mapa_news_rss(max_items: int = 80) -> List[dict]:
    content = _request(MAPA_NEWS_RSS_URL, expect="content")
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
def search_mapa_market_portal() -> List[dict]:
    html = _request(MAPA_MARKETS_URL, expect="text")
    soup = BeautifulSoup(html, "html.parser")
    records: List[dict] = []
    for anchor in soup.find_all("a", href=True):
        title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        href = _clean_url(anchor.get("href", ""), MAPA_MARKETS_URL)
        if not title or not href or "mapa.gob.es" not in href:
            continue
        context = _truncate(re.sub(r"\s+", " ", anchor.parent.get_text(" ", strip=True)))
        records.append(
            {
                "title": title,
                "snippet": context or "Publicación del MAPA sobre mercados o precios ganaderos.",
                "url": href,
                "source": "MAPA - Mercados",
                "published": "",
                "source_db": "MAPA - Mercados",
            }
        )
    return _dedupe(records)


@st.cache_data(show_spinner=False, ttl=3600)
def search_mapa_legislation_index() -> List[dict]:
    html = _request(MAPA_LEGISLATION_URL, expect="text")
    soup = BeautifulSoup(html, "html.parser")
    records: List[dict] = []
    for anchor in soup.find_all("a", href=True):
        title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        href = _clean_url(anchor.get("href", ""), MAPA_LEGISLATION_URL)
        if not title or not href or "mapa.gob.es" not in href:
            continue
        records.append(
            {
                "title": title,
                "snippet": "Página oficial del MAPA relacionada con normativa o documentación sectorial.",
                "url": href,
                "source": "MAPA - Legislación",
                "published": "",
                "source_db": "MAPA - Legislación",
            }
        )
    return _dedupe(records)


@st.cache_data(show_spinner=False, ttl=3600)
def search_europe_pmc(query: str, start_date: date, end_date: date, max_results: int = 14) -> List[dict]:
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
        records.append(
            {
                "title": _strip_html(item.get("title", "Sin título")),
                "snippet": _truncate(_strip_html(item.get("abstractText", "")) or item.get("journalTitle", "")),
                "url": url,
                "source": item.get("journalTitle", "Europe PMC"),
                "published": published.isoformat() if published else "",
                "source_db": "Europe PMC",
                "doi": doi or "",
                "authors": item.get("authorString", ""),
            }
        )
    return _dedupe(records)


@st.cache_data(show_spinner=False, ttl=3600)
def search_openalex(query: str, start_date: date, end_date: date, max_results: int = 14) -> List[dict]:
    params = {
        "search": query,
        "filter": f"from_publication_date:{start_date.isoformat()},to_publication_date:{end_date.isoformat()},type:article|preprint,is_paratext:false",
        "per_page": max_results,
        "sort": "relevance_score:desc",
    }
    data = _request("https://api.openalex.org/works", params=params, expect="json")
    results = data.get("results", [])
    records: List[dict] = []
    for item in results:
        primary_location = item.get("primary_location") or {}
        best_oa = item.get("best_oa_location") or {}
        ids = item.get("ids") or {}
        url = primary_location.get("landing_page_url") or best_oa.get("landing_page_url") or item.get("doi") or ids.get("doi") or item.get("id", "")
        journal_name = ((primary_location.get("source") or {}).get("display_name")) or ((best_oa.get("source") or {}).get("display_name")) or "OpenAlex"
        authors = ", ".join(
            a.get("author", {}).get("display_name", "")
            for a in (item.get("authorships") or [])[:6]
            if a.get("author", {}).get("display_name")
        )
        snippet = journal_name
        if item.get("abstract_inverted_index"):
            pairs = []
            for token, positions in item["abstract_inverted_index"].items():
                for pos in positions:
                    pairs.append((pos, token))
            snippet = " ".join(token for _, token in sorted(pairs)[:90])
        records.append(
            {
                "title": _strip_html(item.get("display_name", "Sin título")),
                "snippet": _truncate(snippet),
                "url": _clean_url(url),
                "source": journal_name,
                "published": item.get("publication_date", ""),
                "source_db": "OpenAlex",
                "doi": (item.get("doi") or ids.get("doi") or "").replace("https://doi.org/", ""),
                "authors": authors,
            }
        )
    return _dedupe(records)


# -----------------------------------------------------------------------------
# Query builders
# -----------------------------------------------------------------------------

def _topic_phrase(profile: dict) -> str:
    aliases = profile["topic_aliases"]
    if not aliases:
        return ""
    return aliases[0]


def build_market_queries(species: str, profile: dict) -> List[str]:
    species_term = profile["species_terms"][0]
    topic_terms = profile["market_terms"][:4] or ["mercado"]
    queries = [
        f'{species_term} {topic_terms[0]} mercado precios',
        f'{species_term} {topic_terms[0]} site:mapa.gob.es',
        f'{species_term} {topic_terms[0]} boletín precios',
    ]

    domain_focus = ["mapa.gob.es", "efeagro.com", "agrodigital.com", "interempresas.net"]
    for domain, term in zip(domain_focus, topic_terms + topic_terms[:2]):
        queries.append(f'site:{domain} {species_term} {term}')

    if species == "Alimentación animal":
        queries.extend([
            f'alimentación animal {topic_terms[0]} mercado',
            f'ganadería {topic_terms[0]} ministerio agricultura',
        ])

    return _unique_keep_order(queries)[:8]


def build_regulation_queries(species: str, profile: dict) -> List[str]:
    species_term = profile["species_terms"][0]
    reg_terms = profile["regulation_terms"][:4] or profile["topic_aliases"][:2] or ["normativa"]
    queries = [
        f'site:boe.es {species_term} {reg_terms[0]} real decreto reglamento',
        f'site:eur-lex.europa.eu {species_term} {reg_terms[0]} regulation',
        f'site:mapa.gob.es {species_term} {reg_terms[0]} normativa',
        f'site:efsa.europa.eu {species_term} {reg_terms[0]}',
    ]
    if species == "Alimentación animal":
        queries.append(f'site:boe.es alimentación animal {reg_terms[0]} piensos reglamento')
    return _unique_keep_order(queries)[:6]


def build_science_queries(species: str, profile: dict) -> Dict[str, str]:
    species_terms = profile["species_terms"][:4]
    science_terms = profile["science_terms"][:6]
    species_block = " OR ".join(f'"{term}"' if " " in term else term for term in species_terms)
    topic_block = " OR ".join(f'"{term}"' if " " in term else term for term in science_terms)
    broad_text = " ".join(_unique_keep_order(species_terms + science_terms[:4]))
    return {
        "openalex": f"({species_block}) AND ({topic_block})",
        "europepmc": f"({species_block}) AND ({topic_block})",
        "broad": broad_text,
    }


# -----------------------------------------------------------------------------
# Scoring and filtering
# -----------------------------------------------------------------------------

def _score_text(text: str, primary_terms: Sequence[str], topic_terms: Sequence[str], support_terms: Sequence[str]) -> float:
    hay = _normalize(text)
    score = 0.0
    primary_hits = 0
    topic_hits = 0

    for term in primary_terms:
        norm = _normalize(term)
        if norm and norm in hay:
            score += 1.6 if " " in norm else 1.0
            primary_hits += 1

    for term in topic_terms:
        norm = _normalize(term)
        if norm and norm in hay:
            score += 2.5 if " " in norm else 1.6
            topic_hits += 1

    for term in support_terms:
        norm = _normalize(term)
        if norm and norm in hay:
            score += 0.45

    if topic_terms and topic_hits == 0:
        score -= 1.3
    if primary_terms and primary_hits == 0:
        score -= 0.5
    return score


def _sort_market(records: List[dict], profile: dict, start_date: date, end_date: date) -> List[dict]:
    out = []
    primary_terms = profile["species_terms"]
    topic_terms = profile["topic_aliases"] + profile["market_terms"][:6]
    support_terms = MARKET_ANCHORS + profile["market_terms"][:6]
    for item in records:
        text = " ".join([item.get("title", ""), item.get("snippet", ""), item.get("source", "")])
        score = _score_text(text, primary_terms, topic_terms, support_terms)
        dom = _domain(item.get("url", ""))
        if dom in MARKET_MEDIA_DOMAINS or item.get("source_db", "").startswith("MAPA"):
            score += 0.8
        published = _parse_date(item.get("published"))
        if published and _date_in_range(published, start_date, end_date):
            age_days = max((datetime.now() - published).days, 0)
            if age_days <= 30:
                score += 0.5
            elif age_days <= 180:
                score += 0.2
        out.append({**item, "score": round(score, 3)})
    out.sort(key=lambda x: (x.get("score", 0), x.get("published", "")), reverse=True)
    return out


def _sort_regulation(records: List[dict], profile: dict) -> List[dict]:
    out = []
    primary_terms = profile["species_terms"]
    topic_terms = profile["topic_aliases"] + profile["regulation_terms"][:8]
    support_terms = LEGAL_ANCHORS + profile["regulation_terms"][:6]
    generic_species = _normalize(primary_terms[0]) == _normalize("alimentación animal")

    for item in records:
        text = " ".join([item.get("title", ""), item.get("snippet", ""), item.get("source", ""), item.get("url", "")])
        score = _score_text(text, [] if generic_species else primary_terms, topic_terms, support_terms)
        dom = _domain(item.get("url", ""))
        official = dom in OFFICIAL_REGULATORY_DOMAINS or item.get("source_db", "").startswith("MAPA")
        topic_match = _contains_any(text, topic_terms)
        legal_match = _contains_any(text, LEGAL_ANCHORS)
        species_match = generic_species or _contains_any(text, primary_terms)

        if official:
            score += 1.3
        if not official:
            score -= 2.0
        if not topic_match:
            score -= 2.5
        if not legal_match:
            score -= 0.8
        if not species_match:
            score -= 1.2
        if official and topic_match and (species_match or generic_species):
            score += 0.8
        out.append({**item, "score": round(score, 3)})

    out.sort(key=lambda x: (x.get("score", 0), x.get("published", "")), reverse=True)
    return out


def _sort_science(records: List[dict], profile: dict) -> List[dict]:
    out = []
    primary_terms = profile["species_terms"]
    topic_terms = profile["topic_aliases"] + profile["science_terms"][:8]
    support_terms = SCIENCE_ANCHORS
    for item in records:
        text = " ".join([item.get("title", ""), item.get("snippet", ""), item.get("source", "")])
        score = _score_text(text, primary_terms, topic_terms, support_terms)
        if item.get("doi"):
            score += 0.4
        if item.get("source_db") == "OpenAlex":
            score += 0.2
        out.append({**item, "score": round(score, 3)})
    out.sort(key=lambda x: (x.get("score", 0), x.get("published", "")), reverse=True)
    return out


# -----------------------------------------------------------------------------
# Search orchestration
# -----------------------------------------------------------------------------

def search_market(species: str, profile: dict, start_date: date, end_date: date, max_results: int) -> Tuple[List[dict], List[str]]:
    queries = build_market_queries(species, profile)
    records: List[dict] = []

    for query in queries[:4]:
        try:
            records.extend(search_google_news(query, start_date, end_date, max_results=max_results))
        except Exception:
            pass

    for query in queries[:5]:
        try:
            records.extend(search_duckduckgo_html(query, max_results=6))
        except Exception:
            pass

    try:
        records.extend(search_mapa_market_portal())
    except Exception:
        pass

    try:
        rss_records = search_mapa_news_rss()
        records.extend(item for item in rss_records if _date_in_range(_parse_date(item.get("published")), start_date, end_date))
    except Exception:
        pass

    ranked = _sort_market(_dedupe(records), profile, start_date, end_date)
    filtered = [item for item in ranked if item.get("score", 0) >= 0.3 and item.get("url")]
    return filtered[:max_results], queries


def search_regulation(species: str, profile: dict, start_date: date, end_date: date, max_results: int) -> Tuple[List[dict], List[str]]:
    queries = build_regulation_queries(species, profile)
    records: List[dict] = []

    for query in queries:
        try:
            records.extend(search_duckduckgo_html(query, max_results=8))
        except Exception:
            pass

    try:
        records.extend(search_mapa_legislation_index())
    except Exception:
        pass

    try:
        official_news = search_google_news(f"site:mapa.gob.es {profile['species_terms'][0]} {profile['regulation_terms'][0] if profile['regulation_terms'] else profile['topic_aliases'][0]}", start_date, end_date, max_results=6)
        records.extend(official_news)
    except Exception:
        pass

    ranked = _sort_regulation(_dedupe(records), profile)
    filtered = [item for item in ranked if item.get("score", 0) >= 1.1 and item.get("url")]
    return filtered[:max_results], queries


def search_science(species: str, profile: dict, start_date: date, end_date: date, max_results: int) -> Tuple[List[dict], Dict[str, str]]:
    queries = build_science_queries(species, profile)
    records: List[dict] = []
    try:
        records.extend(search_europe_pmc(queries["europepmc"], start_date, end_date, max_results=max_results))
    except Exception:
        pass
    try:
        records.extend(search_openalex(queries["broad"], start_date, end_date, max_results=max_results))
    except Exception:
        pass

    ranked = _sort_science(_dedupe(records), profile)
    filtered = [item for item in ranked if item.get("score", 0) >= 0.2 and item.get("url")]
    return filtered[:max_results], queries


def run_search(species: str, topics: Sequence[str], start_date: date, end_date: date, max_results: int) -> Tuple[Dict[str, List[dict]], Dict[str, object]]:
    profile = build_search_profile(species, topics)
    market_results, market_queries = search_market(species, profile, start_date, end_date, max_results)
    science_results, science_queries = search_science(species, profile, start_date, end_date, max_results)
    regulation_results, regulation_queries = search_regulation(species, profile, start_date, end_date, max_results)

    return (
        {
            "market": market_results,
            "science": science_results,
            "regulation": regulation_results,
        },
        {
            "profile": profile,
            "market_queries": market_queries,
            "science_queries": science_queries,
            "regulation_queries": regulation_queries,
        },
    )


# -----------------------------------------------------------------------------
# Rendering and analysis
# -----------------------------------------------------------------------------

def format_date(value: str) -> str:
    dt = _parse_date(value)
    if not dt:
        return ""
    return dt.strftime("%d/%m/%Y")


def render_result_list(records: List[dict], title: str) -> None:
    st.subheader(title)
    if not records:
        st.info("No se han recuperado resultados relevantes con los filtros actuales.")
        return

    for idx, item in enumerate(records, start=1):
        title_line = item.get("title", "Sin título")
        source = item.get("source") or item.get("source_db") or "Fuente"
        published = format_date(item.get("published", ""))
        score = item.get("score")
        meta = source
        if published:
            meta += f" · {published}"
        if score is not None:
            meta += f" · score {score:.2f}"
        with st.expander(f"{idx}. {title_line}"):
            st.caption(meta)
            if item.get("snippet"):
                st.write(item["snippet"])
            if item.get("url"):
                st.markdown(f"[Abrir fuente]({item['url']})")
            if item.get("authors"):
                st.caption(item["authors"])


def render_query_debug(query_meta: Dict[str, object]) -> None:
    with st.expander("Transparencia de consultas y criterios", expanded=False):
        profile = query_meta.get("profile", {})
        st.markdown("**Especie y temas seleccionados**")
        st.write(profile.get("species_terms", [])[:4])
        st.write(profile.get("selected_topics", []))

        st.markdown("**Consultas de mercado**")
        st.code("\n".join(query_meta.get("market_queries", [])), language="text")

        st.markdown("**Consultas científicas**")
        science_queries = query_meta.get("science_queries", {})
        st.code(
            f"OpenAlex: {science_queries.get('openalex', '')}\n\n"
            f"Europe PMC: {science_queries.get('europepmc', '')}\n\n"
            f"Consulta amplia: {science_queries.get('broad', '')}",
            language="text",
        )

        st.markdown("**Consultas regulatorias**")
        st.code("\n".join(query_meta.get("regulation_queries", [])), language="text")


# -----------------------------------------------------------------------------
# Briefing and chat
# -----------------------------------------------------------------------------

def _category_summary(category: str, records: List[dict], profile: dict) -> str:
    if not records:
        return f"En **{CATEGORY_LABELS[category]}** no se han recuperado señales suficientemente relevantes con los filtros actuales."

    combined_text = " ".join((r.get("title", "") + " " + r.get("snippet", "")) for r in records[:8])
    recurring = _keywords_from_text(combined_text, exclude=profile["species_terms"] + profile["topic_aliases"], top_k=6)
    recurring_text = ", ".join(recurring[:4]) if recurring else "sin un patrón terminológico dominante"
    sources = ", ".join(_unique_keep_order((r.get("source") or r.get("source_db") or "Fuente") for r in records[:4]))
    return (
        f"En **{CATEGORY_LABELS[category]}** se han recuperado **{len(records)}** referencias. "
        f"Los focos que más se repiten son **{recurring_text}**. "
        f"Las fuentes mejor posicionadas proceden de **{sources}**."
    )


def _integrated_insight(species: str, topics: Sequence[str], results: Dict[str, List[dict]]) -> str:
    topic_text = ", ".join(topics)
    market_n = len(results.get("market", []))
    science_n = len(results.get("science", []))
    reg_n = len(results.get("regulation", []))

    strongest = []
    if market_n:
        strongest.append("la prensa sectorial y los boletines oficiales están generando señales de mercado accionables")
    if science_n:
        strongest.append("la literatura científica aporta base técnica para convertir esas señales en propuestas de valor")
    if reg_n:
        strongest.append("la capa regulatoria introduce condicionantes que pueden acelerar o frenar la adopción")

    if not strongest:
        strongest.append("la consulta necesita un rango temporal más amplio o una combinación distinta de temas")

    joined = "; ".join(strongest)
    return (
        f"Para **{species}**, en los temas **{topic_text}**, el radar sugiere que **{joined}**. "
        f"La lectura útil para marketing no es solo qué se publica, sino qué problema del cliente está detrás de cada señal y qué solución de Nutreco Iberia puede encajar mejor."
    )


def _recommendations_for_marketing(species: str, topics: Sequence[str], results: Dict[str, List[dict]]) -> List[str]:
    topic_text = ", ".join(topics[:3])
    recommendations = [
        f"Traducir las señales detectadas en **{species}** sobre **{topic_text}** a un argumentario técnico-comercial para red de ventas y equipo técnico.",
        "Priorizar contenido útil para cliente final: briefing comercial, ficha técnica, webinar o visita con foco en la necesidad observada.",
        "Cruzar las señales externas con feedback de campo para validar si el problema es coyuntural o estructural antes de mover portfolio o claims.",
        "Convertir cada novedad regulatoria relevante en un mensaje simple de impacto para cliente: qué cambia, a quién afecta y qué respuesta puede ofrecer Nutreco Iberia.",
        "Identificar huecos del portfolio actual y decidir si conviene reposicionar una solución existente, generar servicio técnico o explorar desarrollo de producto.",
    ]
    if results.get("market"):
        recommendations.append("Monitorizar semanalmente las fuentes de mercado mejor posicionadas y comparar la señal con precios, costes y presión competitiva.")
    if results.get("science"):
        recommendations.append("Usar la evidencia científica recuperada como soporte de diferenciación, siempre contrastando aplicabilidad práctica en granja.")
    if results.get("regulation"):
        recommendations.append("Revisar con antelación las obligaciones regulatorias detectadas para evitar mensajes comerciales o recomendaciones técnicas que queden desalineadas.")
    return _unique_keep_order(recommendations)[:6]


def generate_brief(species: str, topics: Sequence[str], start_date: date, end_date: date, results: Dict[str, List[dict]], company_context: str, query_meta: Dict[str, object]) -> str:
    profile = query_meta.get("profile", build_search_profile(species, topics))
    lines = [
        "# Briefing del radar sectorial",
        "",
        f"**Especie / segmento:** {species}",
        f"**Temas seleccionados:** {', '.join(topics)}",
        f"**Periodo analizado:** {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}",
        "",
        "## Resumen ejecutivo",
        _integrated_insight(species, topics, results),
        "",
        "## Síntesis integrada del radar",
        f"Entre las tres capas de búsqueda, el radar ha recuperado **{len(results.get('market', []))}** señales de mercado, **{len(results.get('science', []))}** referencias científico-técnicas y **{len(results.get('regulation', []))}** señales regulatorias. El valor para marketing está en priorizar necesidades del cliente que aparecen repetidamente y conectarlas con mensajes, servicios o soluciones de Nutreco Iberia.",
        "",
        "## Mercado",
        _category_summary("market", results.get("market", []), profile),
        "",
        "## Científico-técnico",
        _category_summary("science", results.get("science", []), profile),
        "",
        "## Legislación y regulación",
        _category_summary("regulation", results.get("regulation", []), profile),
        "",
        "## Implicaciones para marketing y desarrollo de soluciones",
    ]

    for rec in _recommendations_for_marketing(species, topics, results):
        lines.append(f"- {rec}")

    lines.extend([
        "",
        "## Contexto corporativo aplicado",
        company_context.strip() or DEFAULT_COMPANY_CONTEXT.strip(),
    ])
    return "\n".join(lines)


def bibliography_entries(results: Dict[str, List[dict]]) -> List[str]:
    entries = []
    for category in ["market", "science", "regulation"]:
        for item in results.get(category, []):
            title = item.get("title", "Sin título")
            source = item.get("source") or item.get("source_db") or "Fuente"
            published = format_date(item.get("published", ""))
            url = item.get("url", "")
            ref = f"{title}. {source}"
            if published:
                ref += f", {published}"
            if url:
                ref += f". {url}"
            entries.append(ref)
    return _unique_keep_order(entries)


def build_docx_bytes(species: str, topics: Sequence[str], start_date: date, end_date: date, brief_text: str, results: Dict[str, List[dict]]) -> bytes:
    doc = Document()
    doc.add_heading("Radar sectorial Nutreco Iberia", level=0)
    doc.add_paragraph(f"Especie / segmento: {species}")
    doc.add_paragraph(f"Temas seleccionados: {', '.join(topics)}")
    doc.add_paragraph(f"Periodo: {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}")

    for line in brief_text.splitlines():
        if line.startswith("# "):
            doc.add_heading(line[2:].strip(), level=1)
        elif line.startswith("## "):
            doc.add_heading(line[3:].strip(), level=2)
        elif line.startswith("- "):
            doc.add_paragraph(line[2:].strip(), style="List Bullet")
        elif line.strip():
            doc.add_paragraph(line.strip())

    doc.add_heading("Referencias", level=1)
    for ref in bibliography_entries(results):
        doc.add_paragraph(ref, style="List Bullet")

    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    return output.getvalue()


def answer_chat(question: str, results: Dict[str, List[dict]], species: str, topics: Sequence[str]) -> str:
    question_terms = [t for t in re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñÜü0-9\-]{4,}", question) if _normalize(t) not in STOPWORDS]
    candidates = []
    for category in ["market", "science", "regulation"]:
        for item in results.get(category, []):
            text = " ".join([item.get("title", ""), item.get("snippet", ""), item.get("source", "")])
            hits = sum(1 for term in question_terms if _normalize(term) in _normalize(text))
            if hits > 0:
                candidates.append((hits, category, item))

    candidates.sort(key=lambda x: x[0], reverse=True)
    if not candidates:
        return (
            f"No veo una coincidencia directa entre tu pregunta y los resultados recuperados para **{species}** en **{', '.join(topics)}**. "
            "Prueba a reformular la pregunta en términos de mercado, ciencia o regulación."
        )

    selected = candidates[:4]
    lines = [
        f"Para **{species}** y los temas **{', '.join(topics)}**, esto es lo más relevante que encuentro en los resultados actuales:",
        "",
    ]
    for _, category, item in selected:
        source = item.get("source") or item.get("source_db") or "Fuente"
        url = item.get("url", "")
        line = f"- **{CATEGORY_LABELS[category]}**: {item.get('title', 'Sin título')} ({source})"
        if url:
            line += f" — {url}"
        lines.append(line)
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# App state and README
# -----------------------------------------------------------------------------

def init_state() -> None:
    st.session_state.setdefault("search_results", None)
    st.session_state.setdefault("query_meta", None)
    st.session_state.setdefault("brief_text", "")
    st.session_state.setdefault("chat_history", [])


def read_readme() -> str:
    path = Path(__file__).with_name("README.md")
    if not path.exists():
        return "README no disponible."
    return path.read_text(encoding="utf-8")


# -----------------------------------------------------------------------------
# Main UI
# -----------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    init_state()

    st.title(APP_TITLE)
    st.caption(
        "Herramienta para marketing técnico: combina prensa sectorial, boletines oficiales, literatura científica y normativa "
        "para ayudar a detectar necesidades del mercado y convertirlas en oportunidades de producto, servicio o posicionamiento para Nutreco Iberia."
    )

    with st.sidebar:
        st.header("Filtros")
        species = st.selectbox("Especie / segmento", list(SPECIES_OPTIONS.keys()), index=0)
        topics = st.multiselect(
            "Temas a vigilar",
            list(TOPIC_OPTIONS.keys()),
            default=["Precios y cotizaciones", "Costes de alimentación"],
            max_selections=3,
            help="Selecciona hasta 3 temas. La app ya no usa texto libre para evitar búsquedas poco consistentes.",
        )
        today = date.today()
        start_date = st.date_input("Fecha inicio", value=today.replace(day=1))
        end_date = st.date_input("Fecha fin", value=today)
        max_results = st.slider("Máximo de resultados por bloque", min_value=5, max_value=25, value=12, step=1)
        company_context = st.text_area("Criterios internos / foco de negocio", value=DEFAULT_COMPANY_CONTEXT, height=140)
        run_button = st.button("Buscar y actualizar radar", use_container_width=True)
        generate_button = st.button("Generar briefing", use_container_width=True)

    if start_date > end_date:
        st.error("La fecha inicial no puede ser posterior a la fecha final.")
        return

    if not topics:
        st.warning("Selecciona al menos un tema para lanzar la búsqueda.")

    if run_button and topics:
        with st.spinner("Buscando señales de mercado, ciencia y regulación..."):
            try:
                results, query_meta = run_search(species, topics, start_date, end_date, max_results)
                st.session_state.search_results = results
                st.session_state.query_meta = query_meta
                st.session_state.brief_text = ""
                st.session_state.chat_history = []
                st.success("Radar actualizado.")
            except Exception as exc:
                st.error(f"No se pudo completar la búsqueda: {exc}")

    results = st.session_state.search_results
    query_meta = st.session_state.query_meta or {}

    if results:
        c1, c2, c3 = st.columns(3)
        c1.metric("Mercado", len(results.get("market", [])))
        c2.metric("Científico-técnico", len(results.get("science", [])))
        c3.metric("Regulación", len(results.get("regulation", [])))

        tabs = st.tabs(["Mercado", "Científico-técnico", "Legislación", "Chat", "Briefing", "Guía / README"])

        with tabs[0]:
            render_result_list(results.get("market", []), "Noticias, boletines y señales de mercado")
            render_query_debug(query_meta)

        with tabs[1]:
            render_result_list(results.get("science", []), "Literatura científico-técnica")

        with tabs[2]:
            render_result_list(results.get("regulation", []), "Normativa, regulación y páginas oficiales")

        with tabs[3]:
            st.write("Utiliza el chat para interrogar únicamente los resultados recuperados por la app.")
            for message in st.session_state.chat_history:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
            question = st.chat_input("Pregunta sobre las señales recuperadas")
            if question:
                st.session_state.chat_history.append({"role": "user", "content": question})
                with st.chat_message("user"):
                    st.markdown(question)
                answer = answer_chat(question, results, species, topics)
                with st.chat_message("assistant"):
                    st.markdown(answer)
                st.session_state.chat_history.append({"role": "assistant", "content": answer})

        with tabs[4]:
            if generate_button:
                st.session_state.brief_text = generate_brief(species, topics, start_date, end_date, results, company_context, query_meta)
            if st.session_state.brief_text:
                st.markdown(st.session_state.brief_text)
                docx_bytes = build_docx_bytes(species, topics, start_date, end_date, st.session_state.brief_text, results)
                st.download_button(
                    "Descargar informe Word (.docx)",
                    data=docx_bytes,
                    file_name=f"radar_{_normalize(species).replace(' ', '_')}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
                with st.expander("Referencias bibliográficas y documentales"):
                    for entry in bibliography_entries(results):
                        url_match = re.search(r"(https?://\S+)$", entry)
                        if url_match:
                            url = url_match.group(1)
                            text = entry[: entry.rfind(url)].strip().rstrip(".")
                            st.markdown(f"- {text}. [Enlace]({url})")
                        else:
                            st.markdown(f"- {entry}")
            else:
                st.info("Pulsa **Generar briefing** para crear el resumen integrado y el informe Word.")

        with tabs[5]:
            st.markdown(read_readme())
    else:
        st.info(
            "Selecciona una especie, marca los temas a vigilar y pulsa **Buscar y actualizar radar**. "
            "La app está orientada a que marketing detecte señales del mercado y las convierta en decisiones sobre mensajes, soluciones y portfolio."
        )
        with st.expander("Guía de uso (README)"):
            st.markdown(read_readme())

    st.divider()
    st.caption(
        "Aviso: el radar sirve para vigilancia y priorización. No sustituye una revisión técnica, regulatoria o jurídica antes de tomar decisiones externas o formular claims."
    )


if __name__ == "__main__":
    main()
