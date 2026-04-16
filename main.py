import io
import json
import math
import os
import re
import time
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus, urlparse

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
USER_AGENT = "Mozilla/5.0 (compatible; NutrecoRadar/2.0; +https://streamlit.io)"
REQUEST_TIMEOUT = 25
MAX_CONTEXT_ITEMS = 8
SCIENTIFIC_FETCH_FACTOR = 3

SPECIES_OPTIONS: Dict[str, Dict[str, List[str]]] = {
    "Avicultura de puesta": {
        "aliases": [
            "avicultura de puesta",
            "gallinas ponedoras",
            "layers",
            "laying hens",
            "egg production",
            "egg laying",
            "poultry layers",
        ],
        "market": ["egg market", "egg price", "huevo", "costes", "consumo", "packing", "retail"],
        "science": ["nutrition", "shell quality", "salmonella", "welfare", "persistencia de puesta", "feed efficiency"],
        "regulation": ["welfare", "housing", "salmonella", "egg labelling", "biosecurity"],
    },
    "Avicultura de carne": {
        "aliases": [
            "avicultura de carne",
            "pollos de engorde",
            "broilers",
            "broiler chickens",
            "broiler production",
            "meat poultry",
            "chicken meat production",
        ],
        "market": ["broiler market", "chicken price", "poultry market", "costes", "consumo", "exportación"],
        "science": ["nutrition", "gut health", "coccidiosis", "necrotic enteritis", "performance", "welfare"],
        "regulation": ["biosecurity", "welfare", "avian influenza", "residues", "food safety"],
    },
    "Porcino": {
        "aliases": [
            "porcino",
            "swine",
            "pig",
            "pigs",
            "pig production",
            "sow",
            "piglet",
            "finisher pigs",
        ],
        "market": ["swine market", "hog price", "pig price", "feed costs", "export", "import", "slaughter"],
        "science": ["nutrition", "gut health", "weaning", "reproduction", "biosecurity", "feed efficiency"],
        "regulation": ["African swine fever", "biosecurity", "welfare", "emissions", "transport"],
    },
    "Vacuno de leche": {
        "aliases": [
            "vacuno de leche",
            "dairy cattle",
            "dairy cows",
            "milk production",
            "lechero",
            "dairy herd",
        ],
        "market": ["milk price", "dairy market", "farmgate milk price", "costes", "margen", "exportación"],
        "science": ["nutrition", "rumen", "fertility", "mastitis", "transition cow", "methane"],
        "regulation": ["emissions", "antibiotics", "welfare", "sustainability", "milk quality"],
    },
    "Vacuno de carne": {
        "aliases": [
            "vacuno de carne",
            "beef cattle",
            "beef production",
            "feedlot",
            "cebaderos",
            "fattening cattle",
        ],
        "market": ["beef market", "beef price", "cattle price", "feedlot margins", "costes", "exportación"],
        "science": ["nutrition", "average daily gain", "respiratory disease", "welfare", "methane", "carcass"],
        "regulation": ["transport", "welfare", "emissions", "traceability", "antibiotics"],
    },
    "Ovino": {
        "aliases": [
            "ovino",
            "sheep",
            "ovine",
            "sheep production",
            "lamb",
            "dairy sheep",
            "meat sheep",
        ],
        "market": ["lamb price", "sheep market", "ovine milk", "costes", "exportación"],
        "science": ["nutrition", "parasites", "reproduction", "rumen", "milk quality", "trace minerals"],
        "regulation": ["bluetongue", "traceability", "animal movements", "welfare", "biosecurity"],
    },
    "Caprino": {
        "aliases": [
            "caprino",
            "goat",
            "goats",
            "goat production",
            "dairy goats",
            "goat milk",
        ],
        "market": ["goat milk", "goat cheese", "caprine market", "costes", "retail"],
        "science": ["nutrition", "mastitis", "parasites", "reproduction", "kid growth", "digestibility"],
        "regulation": ["traceability", "animal movements", "welfare", "sanidad", "milk hygiene"],
    },
    "Cunicultura": {
        "aliases": [
            "cunicultura",
            "rabbit production",
            "rabbits",
            "meat rabbits",
            "rabbit farming",
            "conejo",
        ],
        "market": ["rabbit market", "rabbit meat", "precio conejo", "costes", "consumo"],
        "science": ["nutrition", "enteropathy", "digestive health", "welfare", "reproduction", "mortality"],
        "regulation": ["welfare", "medication", "biosecurity", "antimicrobials"],
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

STOPWORDS_ES = {
    "de", "la", "el", "los", "las", "y", "o", "en", "para", "por", "con", "del", "al", "un",
    "una", "se", "que", "sobre", "from", "the", "and", "for", "into", "than", "this", "that",
    "entre", "como", "más", "menos", "its", "are", "was", "were", "has", "have", "had",
    "market", "mercado", "regulation", "science", "technical", "legislation", "animal", "production",
    "study", "review", "using", "effect", "effects", "analysis", "research", "results", "paper",
}

TERM_SYNONYMS: Dict[str, List[str]] = {
    "peste porcina africana": ["African swine fever", "ASF", "ASFV", "wild boar", "biosecurity"],
    "ppa": ["peste porcina africana", "African swine fever", "ASF", "ASFV"],
    "influenza aviar": ["avian influenza", "bird flu", "highly pathogenic avian influenza", "HPAI", "H5N1"],
    "ia": ["influenza aviar", "avian influenza", "HPAI", "H5N1"],
    "lengua azul": ["bluetongue", "BTV", "orbivirus"],
    "mastitis": ["udder health", "intramammary infection"],
    "mamitis": ["mastitis", "udder health", "intramammary infection"],
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
    "metritis": ["uterine disease", "reproductive disease"],
    "fertilidad": ["fertility", "reproduction"],
    "reproduccion": ["reproduction", "fertility"],
    "digestibilidad": ["digestibility", "ileal digestibility", "nutrient utilization"],
    "sanidad": ["health", "disease", "animal health"],
    "nutricion": ["nutrition", "feeding", "diet", "feed formulation"],
    "piensos": ["feed", "compound feed", "feed formulation"],
    "costes de alimentacion": ["feed cost", "feed costs", "raw materials", "commodity prices", "soybean meal", "corn"],
    "coste de alimentacion": ["feed cost", "feed costs", "raw materials", "commodity prices"],
    "precio leche": ["milk price", "farmgate milk price", "dairy prices"],
    "precio huevo": ["egg price", "egg market"],
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


def _strip_html(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", BeautifulSoup(text, "html.parser").get_text(" ", strip=True)).strip()


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return date_parser.parse(value)
    except Exception:
        return None


def _date_in_range(value: Optional[datetime], start: date, end: date) -> bool:
    if value is None:
        return True
    current = value.date()
    return start <= current <= end


def _truncate(text: str, max_len: int = 420) -> str:
    if len(text or "") <= max_len:
        return text or ""
    return (text or "")[: max_len - 1].rstrip() + "…"


def _clean_url(url: str) -> str:
    if not url:
        return ""
    return url.strip()


def _canonical_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/")
    return f"{parsed.netloc.lower()}{path.lower()}"


def _request(url: str, *, params: Optional[dict] = None, expect: str = "json"):
    last_error: Optional[Exception] = None
    for attempt in range(2):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json, application/xml, text/xml, */*"},
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
                time.sleep(1.0)
    raise RuntimeError(f"Error al consultar la fuente externa: {last_error}")


def _unique_keep_order(items: Iterable[str]) -> List[str]:
    seen = set()
    out = []
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


def _safe_phrase(term: str) -> str:
    term = re.sub(r'["“”]', "", term.strip())
    if not term:
        return ""
    if " " in term or "-" in term:
        return f'"{term}"'
    return term


def _maybe_translate_phrase(term: str) -> List[str]:
    normalized = _normalize(term)
    words = normalized.split()
    if not words:
        return []
    translated_words = [WORD_TRANSLATIONS.get(word, word) for word in words]
    if translated_words == words:
        return []
    candidate = " ".join(translated_words)
    if candidate == normalized:
        return []
    return [candidate]


def parse_user_phrases(text: str) -> List[str]:
    if not text:
        return []
    raw_parts = re.split(r"[\n;,|]+", text)
    parts = []
    for part in raw_parts:
        cleaned = re.sub(r"\s+", " ", part).strip(" .")
        if not cleaned:
            continue
        parts.append(cleaned)
    return _unique_keep_order(parts)


def expand_phrase(phrase: str) -> List[str]:
    normalized = _normalize(phrase)
    expansions = [phrase]

    if normalized in TERM_SYNONYMS:
        expansions.extend(TERM_SYNONYMS[normalized])

    expansions.extend(_maybe_translate_phrase(phrase))

    if 2 <= len(normalized.split()) <= 4:
        for token in normalized.split():
            if token in TERM_SYNONYMS:
                expansions.extend(TERM_SYNONYMS[token][:3])

    if normalized.isupper() or len(normalized) <= 5:
        for key, values in TERM_SYNONYMS.items():
            if normalized in {_normalize(v) for v in values}:
                expansions.append(key)
                expansions.extend(values[:4])

    return _unique_keep_order(expansions)


def expand_user_keywords(user_keywords: str, species: str) -> Dict[str, List[str]]:
    profile = SPECIES_OPTIONS[species]
    user_phrases = parse_user_phrases(user_keywords)
    expanded_terms: List[str] = []
    for phrase in user_phrases:
        expanded_terms.extend(expand_phrase(phrase))

    topic_terms = _unique_keep_order(expanded_terms)
    if not topic_terms:
        topic_terms = _unique_keep_order(profile["science"][:5])

    market_terms = _unique_keep_order(topic_terms + profile["market"][:6])
    science_terms = _unique_keep_order(topic_terms + profile["science"][:6])
    regulation_terms = _unique_keep_order(topic_terms + profile["regulation"][:6])

    return {
        "user_phrases": user_phrases,
        "expanded_terms": topic_terms,
        "market_terms": market_terms,
        "science_terms": science_terms,
        "regulation_terms": regulation_terms,
        "species_terms": _unique_keep_order(profile["aliases"]),
    }


def build_science_queries(species: str, user_keywords: str) -> Dict[str, object]:
    expanded = expand_user_keywords(user_keywords, species)
    species_terms = expanded["species_terms"][:6]
    topic_terms = expanded["expanded_terms"][:10]
    fallback_science = SPECIES_OPTIONS[species]["science"][:6]

    species_block = " OR ".join(_safe_phrase(term) for term in species_terms)
    topic_block = " OR ".join(_safe_phrase(term) for term in (topic_terms or fallback_science))

    openalex = f"({species_block}) AND ({topic_block})"
    europepmc = f"({species_block}) AND ({topic_block})"
    crossref = " ".join(_unique_keep_order(species_terms[:4] + (topic_terms or fallback_science)[:8]))
    broad = " ".join(_unique_keep_order(species_terms[:4] + fallback_science[:4]))

    raw_external = " ".join(_unique_keep_order(species_terms[:3] + (expanded["user_phrases"] or fallback_science[:3])))
    external_links = {
        "Google Scholar": f"https://scholar.google.com/scholar?q={quote_plus(raw_external)}",
        "ScienceDirect": f"https://www.sciencedirect.com/search?qs={quote_plus(raw_external)}",
        "AGRIS": f"https://agris.fao.org/search/en?query={quote_plus(raw_external)}",
        "CORE": f"https://core.ac.uk/search?q={quote_plus(raw_external)}",
    }

    return {
        **expanded,
        "queries": {
            "openalex": openalex,
            "europepmc": europepmc,
            "crossref": crossref,
            "broad": broad,
        },
        "external_links": external_links,
    }


def build_queries(species: str, user_keywords: str) -> Dict[str, object]:
    science_meta = build_science_queries(species, user_keywords)
    species_terms = science_meta["species_terms"][:5]
    user_terms = science_meta["expanded_terms"][:8]
    market_terms = science_meta["market_terms"][:8]
    regulation_terms = science_meta["regulation_terms"][:8]

    def query_line(core_terms: List[str], support_terms: List[str]) -> str:
        chunks = _unique_keep_order(core_terms + support_terms)
        return " ".join(_safe_phrase(term) for term in chunks[:16])

    market_query = query_line(species_terms + user_terms[:6], market_terms)
    regulation_query = query_line(species_terms + user_terms[:6], regulation_terms + ["EUR-Lex", "EFSA", "BOE", "regulation", "legislation"])

    return {
        "market": market_query,
        "science": science_meta,
        "regulation": regulation_query,
    }


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
    counts = Counter(w for w in words if w not in STOPWORDS_ES)
    return [w for w, _ in counts.most_common(top_k)]


def _score_record(item: dict, species_terms: List[str], topic_terms: List[str], category_terms: List[str]) -> float:
    haystack = _normalize(
        " ".join(
            filter(
                None,
                [
                    item.get("title", ""),
                    item.get("snippet", ""),
                    item.get("source", ""),
                    item.get("journal", ""),
                    item.get("authors", ""),
                    item.get("keywords", ""),
                ],
            )
        )
    )

    score = 0.0

    species_hits = 0
    for term in species_terms:
        normalized = _normalize(term)
        if normalized and normalized in haystack:
            species_hits += 1
            score += 2.0 if " " in normalized else 1.0

    topic_hits = 0
    for term in topic_terms:
        normalized = _normalize(term)
        if normalized and normalized in haystack:
            topic_hits += 1
            score += 3.0 if " " in normalized else 1.25

    for term in category_terms:
        normalized = _normalize(term)
        if normalized and normalized in haystack:
            score += 0.5

    cited_by = item.get("cited_by_count") or 0
    if cited_by:
        score += min(math.log1p(cited_by), 3.5) * 0.25

    source_bonus = {
        "Europe PMC": 1.2,
        "OpenAlex": 0.9,
        "Crossref": 0.7,
        "Semantic Scholar": 0.8,
    }
    score += source_bonus.get(item.get("source_db", ""), 0.0)

    if item.get("doi"):
        score += 0.25

    published = _parse_date(item.get("published"))
    if published:
        age_days = max((datetime.now() - published).days, 0)
        if age_days <= 365:
            score += 0.8
        elif age_days <= 3 * 365:
            score += 0.4

    if topic_terms and topic_hits == 0:
        score -= 2.5
    if species_hits == 0:
        score -= 1.0

    return score


def _sort_scientific_results(records: List[dict], science_meta: dict) -> List[dict]:
    species_terms = science_meta.get("species_terms", [])
    topic_terms = science_meta.get("expanded_terms", []) or SPECIES_OPTIONS[next(iter(SPECIES_OPTIONS))]["science"]
    category_terms = science_meta.get("science_terms", [])

    scored = []
    for item in records:
        enriched = dict(item)
        enriched["score"] = _score_record(enriched, species_terms, topic_terms, category_terms)
        scored.append(enriched)

    scored.sort(
        key=lambda item: (
            item.get("score", 0),
            item.get("published", ""),
            item.get("cited_by_count", 0),
        ),
        reverse=True,
    )
    return scored


@st.cache_data(show_spinner=False, ttl=3600)
def search_google_news(query: str, start_date: date, end_date: date, max_results: int = 10) -> List[dict]:
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
        if entry.get("source") and isinstance(entry.get("source"), dict):
            source = entry.get("source", {}).get("title", source)
        summary = _strip_html(entry.get("summary", ""))
        records.append(
            {
                "title": _strip_html(entry.get("title", "Sin título")),
                "snippet": _truncate(summary),
                "url": _clean_url(entry.get("link", "")),
                "source": source,
                "published": published.isoformat() if published else "",
                "source_db": "Google News",
            }
        )
        if len(records) >= max_results:
            break
    return _dedupe(records)


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
        abstract = _strip_html(item.get("abstract", ""))
        records.append(
            {
                "title": _strip_html(title),
                "snippet": _truncate(abstract or journal),
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
    year_range = f"{start_date.year}-{end_date.year}"
    params = {
        "query": query,
        "fields": "title,abstract,url,venue,year,publicationDate,authors,citationCount,externalIds",
        "year": year_range,
        "limit": max_results,
    }
    data = _request("https://api.semanticscholar.org/graph/v1/paper/search/bulk", params=params, expect="json")
    items = data.get("data", [])

    records: List[dict] = []
    for item in items:
        published = _parse_date(item.get("publicationDate") or str(item.get("year", "")))
        if published and not _date_in_range(published, start_date, end_date):
            continue
        external_ids = item.get("externalIds") or {}
        doi = external_ids.get("DOI", "")
        authors = ", ".join(author.get("name", "") for author in (item.get("authors") or [])[:6] if author.get("name"))
        records.append(
            {
                "title": _strip_html(item.get("title", "Sin título")),
                "snippet": _truncate(_strip_html(item.get("abstract", "")) or item.get("venue", "Semantic Scholar")),
                "url": _clean_url(item.get("url") or (f"https://doi.org/{doi}" if doi else "")),
                "source": item.get("venue") or "Semantic Scholar",
                "published": published.isoformat() if published else "",
                "authors": authors,
                "doi": doi,
                "journal": item.get("venue") or "Semantic Scholar",
                "cited_by_count": item.get("citationCount", 0),
                "source_db": "Semantic Scholar",
            }
        )
    return _dedupe(records)


def search_regulatory_sources(query: str, start_date: date, end_date: date, max_results: int = 10) -> List[dict]:
    domain_hint = 'site:eur-lex.europa.eu OR site:boe.es OR site:mapa.gob.es OR site:efsa.europa.eu OR site:miteco.gob.es'
    combined_query = f"{query} regulation legislation normativa reglamento directiva EFSA EUR-Lex BOE {domain_hint}"
    records = search_google_news(combined_query, start_date, end_date, max_results=max_results)
    if records:
        return records
    fallback_query = f"{query} normativa regulación reglamento ley decisión EFSA BOE EUR-Lex"
    return search_google_news(fallback_query, start_date, end_date, max_results=max_results)


def search_scientific_sources(science_meta: dict, start_date: date, end_date: date, max_results: int) -> List[dict]:
    queries = science_meta["queries"]
    target_fetch = max_results * SCIENTIFIC_FETCH_FACTOR
    collected: List[dict] = []

    for source_name, fetch_fn, query in [
        ("Europe PMC", search_europe_pmc, queries["europepmc"]),
        ("OpenAlex", search_openalex, queries["openalex"]),
        ("Crossref", search_crossref, queries["crossref"]),
        ("Semantic Scholar", search_semantic_scholar, queries["crossref"]),
    ]:
        try:
            collected.extend(fetch_fn(query, start_date, end_date, max_results=target_fetch))
        except Exception:
            continue

    deduped = _dedupe(collected)
    ranked = _sort_scientific_results(deduped, science_meta)
    filtered = [item for item in ranked if item.get("score", 0) >= 0.5]

    if len(filtered) < max(4, max_results // 2):
        broad_query = queries["broad"]
        extra: List[dict] = []
        for fetch_fn in [search_openalex, search_crossref]:
            try:
                extra.extend(fetch_fn(broad_query, start_date, end_date, max_results=target_fetch))
            except Exception:
                continue
        ranked = _sort_scientific_results(_dedupe(filtered + extra), science_meta)
        filtered = [item for item in ranked if item.get("score", 0) >= 0.3]

    return filtered[:max_results]


def run_search(species: str, user_keywords: str, start_date: date, end_date: date, max_results: int) -> Tuple[Dict[str, List[dict]], Dict[str, object]]:
    queries = build_queries(species, user_keywords)
    results = {"market": [], "science": [], "regulation": []}

    results["market"] = search_google_news(queries["market"], start_date, end_date, max_results=max_results)
    results["science"] = search_scientific_sources(queries["science"], start_date, end_date, max_results=max_results)
    results["regulation"] = search_regulatory_sources(queries["regulation"], start_date, end_date, max_results=max_results)

    return results, queries


def flatten_results(results: Dict[str, List[dict]]) -> List[dict]:
    flat = []
    for key, items in results.items():
        for item in items:
            enriched = dict(item)
            enriched["category"] = CATEGORY_LABELS[key]
            flat.append(enriched)
    return flat


def corpus_text(results: Dict[str, List[dict]], limit_per_category: int = MAX_CONTEXT_ITEMS) -> str:
    lines = []
    for key in ["market", "science", "regulation"]:
        lines.append(f"\n## {CATEGORY_LABELS[key]}\n")
        for idx, item in enumerate(results.get(key, [])[:limit_per_category], start=1):
            lines.append(
                f"[{idx}] {item.get('title', '')}\n"
                f"Fecha: {item.get('published', '')}\n"
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
    last_error = None

    try:
        response = client.responses.create(
            model=model,
            instructions=system_prompt,
            input=user_prompt,
        )
        output_text = getattr(response, "output_text", None)
        if output_text:
            return output_text.strip()
    except Exception as exc:  # pragma: no cover
        last_error = exc

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:  # pragma: no cover
        last_error = exc
        raise RuntimeError(f"No se pudo generar la salida con OpenAI: {last_error}")


def extractive_brief(species: str, user_keywords: str, results: Dict[str, List[dict]], company_context: str, chat_history: List[dict], query_meta: Optional[dict] = None) -> str:
    flat = flatten_results(results)
    if not flat:
        return "No se han recuperado resultados suficientes para elaborar el briefing."

    corpus = " ".join(filter(None, [item.get("title", "") + " " + item.get("snippet", "") for item in flat]))
    themes = _keywords_from_text(corpus, top_k=10)
    top_market = results.get("market", [])[:3]
    top_science = results.get("science", [])[:4]
    top_reg = results.get("regulation", [])[:3]

    science_sources = Counter(item.get("source_db", "") for item in results.get("science", []))
    expanded_terms = (query_meta or {}).get("science", {}).get("expanded_terms", []) if query_meta else []

    lines = [
        f"# Briefing radar | {species}",
        "",
        "## Resumen ejecutivo",
        f"Búsqueda enfocada en: **{user_keywords or species}**.",
        f"Se han recuperado **{len(results.get('market', []))}** resultados de mercado, **{len(results.get('science', []))}** científico-técnicos y **{len(results.get('regulation', []))}** regulatorios.",
        f"Temas que más se repiten en los resultados: {', '.join(themes[:6]) if themes else 'sin patrón claro'}." ,
    ]

    if expanded_terms:
        lines.append(f"La búsqueda científica se amplió automáticamente con sinónimos y términos relacionados como: {', '.join(expanded_terms[:8])}.")
    if science_sources:
        lines.append("Cobertura científica recuperada: " + ", ".join(f"{k}: {v}" for k, v in science_sources.items() if k) + ".")

    lines.extend(["", "## Radar de mercado"])
    if top_market:
        for item in top_market:
            lines.append(f"- **{item['title']}** ({item.get('source', 'Fuente no indicada')}, {item.get('published', 's/f')[:10]}). {item.get('snippet', '')}")
    else:
        lines.append("- No se han encontrado resultados recientes de mercado con la combinación actual de filtros.")

    lines.extend(["", "## Radar científico-técnico"])
    if top_science:
        for item in top_science:
            journal = item.get("journal") or item.get("source", "Fuente científica")
            base = item.get("source_db", "")
            lines.append(f"- **{item['title']}** ({journal}, {item.get('published', 's/f')[:10]}, {base}). {item.get('snippet', '')}")
    else:
        lines.append("- No se han encontrado artículos suficientes con la combinación actual de filtros.")

    lines.extend(["", "## Radar regulatorio"])
    if top_reg:
        for item in top_reg:
            lines.append(f"- **{item['title']}** ({item.get('source', 'Fuente oficial')}, {item.get('published', 's/f')[:10]}). {item.get('snippet', '')}")
    else:
        lines.append("- No se han encontrado novedades regulatorias recientes con la combinación actual de filtros.")

    lines.extend([
        "",
        "## Recomendaciones preliminares para Nutreco Iberia",
        "- Preparar un argumentario técnico-comercial apoyado en las señales de mercado y en la evidencia científica recuperada.",
        "- Verificar si los hallazgos tienen implicaciones sobre posicionamiento, formación interna o revisión del portafolio.",
        "- Revisar el impacto regulatorio antes de convertir cualquier conclusión en claim comercial o recomendación técnica.",
        "- Establecer seguimiento quincenal de los temas recurrentes detectados por el radar.",
    ])

    if chat_history:
        lines.extend(["", "## Aclaraciones del chat previas al informe"])
        for turn in chat_history[-6:]:
            role = "Usuario" if turn["role"] == "user" else "App"
            lines.append(f"- **{role}:** {turn['content']}")

    lines.extend(["", "## Contexto corporativo utilizado", company_context.strip()])
    return "\n".join(lines)


def generate_brief(species: str, user_keywords: str, results: Dict[str, List[dict]], company_context: str, chat_history: List[dict], query_meta: Optional[dict] = None) -> str:
    if not llm_is_available():
        return extractive_brief(species, user_keywords, results, company_context, chat_history, query_meta=query_meta)

    system_prompt = (
        "Eres un analista senior de inteligencia de mercado y asuntos regulatorios para nutrición animal. "
        "Debes sintetizar únicamente con base en las fuentes suministradas. "
        "No inventes datos ni recomendaciones específicas no sustentadas. "
        "Escribe en español, con tono ejecutivo y estructura clara."
    )

    chat_block = "\n".join([f"{m['role']}: {m['content']}" for m in chat_history[-8:]]) if chat_history else "Sin aclaraciones adicionales."
    expanded_terms = ", ".join((query_meta or {}).get("science", {}).get("expanded_terms", [])[:12]) if query_meta else ""
    user_prompt = f"""
Genera un briefing ejecutable para Nutreco Iberia.

Especie/segmento: {species}
Palabras clave: {user_keywords or '(sin palabras clave adicionales)'}
Términos ampliados automáticamente: {expanded_terms or '(no aplica)'}

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
        haystack = _normalize(f"{item.get('title', '')} {item.get('snippet', '')} {item.get('source', '')}")
        score = sum(1 for token in tokens if token in haystack)
        if score > 0:
            candidate_items.append((score, item))
    candidate_items.sort(key=lambda x: x[0], reverse=True)

    if not candidate_items:
        return "No encuentro evidencia suficiente en los resultados actuales para responder con precisión. Prueba a ampliar fechas o cambiar palabras clave."

    lines = ["He localizado la siguiente evidencia relevante en los resultados recuperados:"]
    for _, item in candidate_items[:4]:
        lines.append(
            f"- {item.get('title')} ({item.get('source', 'Fuente')}, {item.get('published', 's/f')[:10]}, {item.get('source_db', '')}): {item.get('snippet', '')}"
        )
    lines.append("Conclusión provisional: conviene validar este punto con una nueva búsqueda más específica antes de cerrar el informe.")
    return "\n".join(lines)


def bibliography_entries(results: Dict[str, List[dict]]) -> List[str]:
    entries = []
    for item in flatten_results(results):
        published = item.get("published", "")[:10] if item.get("published") else "s/f"
        if item.get("category") == CATEGORY_LABELS["science"]:
            authors = item.get("authors", "Autoría no disponible")
            journal = item.get("journal") or item.get("source", "Fuente científica")
            doi_or_url = item.get("doi") or item.get("url", "")
            source_db = item.get("source_db", "")
            entries.append(f"{authors}. ({published}). {item.get('title')}. {journal}. {doi_or_url} [{source_db}]")
        else:
            entries.append(f"{item.get('source', 'Fuente no indicada')}. ({published}). {item.get('title')}. {item.get('url', '')}")
    return entries


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
            p.add_run(f" | {item.get('source', 'Fuente')} | {item.get('published', '')[:10]} | {item.get('source_db', '')}\n")
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
    if not items:
        return pd.DataFrame(columns=["Fecha", "Base", "Fuente", "Título", "Resumen", "URL"])
    rows = []
    for item in items:
        rows.append(
            {
                "Fecha": item.get("published", "")[:10],
                "Base": item.get("source_db", ""),
                "Fuente": item.get("source", ""),
                "Título": item.get("title", ""),
                "Resumen": item.get("snippet", ""),
                "URL": item.get("url", ""),
            }
        )
    return pd.DataFrame(rows)


def render_category_table(items: List[dict], label: str) -> None:
    st.subheader(label)
    if not items:
        st.info("Sin resultados con los filtros actuales.")
        return
    df = results_dataframe(items)
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_science_debug(query_meta: Optional[dict]) -> None:
    if not query_meta:
        return
    science = query_meta.get("science", {})
    with st.expander("Cómo se ha ampliado la búsqueda científica"):
        user_phrases = science.get("user_phrases", [])
        expanded_terms = science.get("expanded_terms", [])
        queries = science.get("queries", {})

        st.markdown("**Entrada del usuario**")
        st.write(", ".join(user_phrases) if user_phrases else "Sin palabras clave específicas; se han usado términos técnicos por defecto del segmento.")

        st.markdown("**Términos ampliados automáticamente**")
        st.write(", ".join(expanded_terms[:20]) if expanded_terms else "Sin ampliaciones.")

        st.markdown("**Consultas científicas generadas**")
        st.code(
            f"OpenAlex: {queries.get('openalex', '')}\n\n"
            f"Europe PMC: {queries.get('europepmc', '')}\n\n"
            f"Crossref/Semantic Scholar: {queries.get('crossref', '')}",
            language="text",
        )

        links = science.get("external_links", {})
        if links:
            st.markdown("**Atajos de búsqueda externa**")
            cols = st.columns(len(links))
            for idx, (name, url) in enumerate(links.items()):
                cols[idx].link_button(name, url, use_container_width=True)



def init_state() -> None:
    st.session_state.setdefault("search_results", None)
    st.session_state.setdefault("query_meta", None)
    st.session_state.setdefault("brief_text", "")
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("last_filters", {})



def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    init_state()

    st.title(APP_TITLE)
    st.caption(
        "Radar de mercado, evidencia científico-técnica y vigilancia regulatoria para especies de interés. "
        "La capa científica combina varias fuentes bibliográficas públicas y amplía automáticamente las palabras clave con sinónimos y términos relacionados."
    )

    with st.sidebar:
        st.header("Filtros")
        species = st.selectbox("Especie / segmento", list(SPECIES_OPTIONS.keys()))
        today = date.today()
        default_start = today - timedelta(days=180)
        start_date = st.date_input("Fecha inicio", value=default_start)
        end_date = st.date_input("Fecha fin", value=today)
        user_keywords = st.text_input(
            "Palabras clave",
            placeholder="Ej.: peste porcina africana, metano, precios leche, influenza aviar...",
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
                results, queries = run_search(species, user_keywords, start_date, end_date, max_results)
                st.session_state.search_results = results
                st.session_state.query_meta = queries
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
    query_meta = st.session_state.query_meta

    if results:
        col1, col2, col3 = st.columns(3)
        col1.metric("Mercado", len(results.get("market", [])))
        col2.metric("Científico-técnico", len(results.get("science", [])))
        col3.metric("Regulación", len(results.get("regulation", [])))

        tab_market, tab_science, tab_reg, tab_chat, tab_brief = st.tabs(
            ["Mercado", "Científico-técnico", "Legislación", "Chat", "Briefing e informe"]
        )

        with tab_market:
            render_category_table(results.get("market", []), "Señales de mercado")

        with tab_science:
            render_science_debug(query_meta)
            render_category_table(results.get("science", []), "Evidencia científico-técnica")

        with tab_reg:
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
                        answer = answer_chat(
                            question,
                            species,
                            user_keywords,
                            results,
                            company_context,
                            st.session_state.chat_history,
                        )
                        st.markdown(answer)
                st.session_state.chat_history.append({"role": "assistant", "content": answer})

        with tab_brief:
            if generate_button:
                with st.spinner("Generando briefing..."):
                    try:
                        brief_text = generate_brief(
                            species,
                            user_keywords,
                            results,
                            company_context,
                            st.session_state.chat_history,
                            query_meta=query_meta,
                        )
                        st.session_state.brief_text = brief_text
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
                st.info("Primero ejecuta la búsqueda y luego genera el briefing.")

    else:
        st.info(
            "Configura los filtros de la barra lateral y pulsa **Buscar y actualizar radar**. "
            "Después podrás conversar con la app y generar el informe en Word."
        )

    st.divider()
    st.caption(
        "Aviso: esta herramienta no sustituye la revisión técnica, regulatoria ni jurídica. "
        "Antes de usar conclusiones en documentos externos o claims comerciales, valida cada punto con la fuente primaria."
    )


# =========================
# Improved market/regulatory search and link rendering
# =========================

OFFICIAL_REGULATORY_DOMAINS = [
    "boe.es",
    "eur-lex.europa.eu",
    "efsa.europa.eu",
    "food.ec.europa.eu",
    "ec.europa.eu",
    "europa.eu",
    "mapa.gob.es",
    "miteco.gob.es",
]


def _ymd(value: date) -> str:
    return value.strftime("%Y%m%d")


def _gdelt_range(start_date: date, end_date: date) -> Optional[Tuple[date, date]]:
    today = date.today()
    max_lookback = today - timedelta(days=89)
    clipped_start = max(start_date, max_lookback)
    clipped_end = min(end_date, today)
    if clipped_start > clipped_end:
        return None
    return clipped_start, clipped_end


def _gdelt_timestamp(value: date, *, end_of_day: bool = False) -> str:
    if end_of_day:
        dt = datetime(value.year, value.month, value.day, 23, 59, 59)
    else:
        dt = datetime(value.year, value.month, value.day, 0, 0, 0)
    return dt.strftime("%Y%m%d%H%M%S")


def _flatten_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return ", ".join(filter(None, (_flatten_text(item) for item in value)))
    if isinstance(value, dict):
        preferred = [
            value.get("descripcion"),
            value.get("descripcionMateria"),
            value.get("nombre"),
            value.get("value"),
            value.get("texto"),
            value.get("titulo"),
        ]
        flat = ", ".join(filter(None, (_flatten_text(item) for item in preferred)))
        if flat:
            return flat
        return ", ".join(filter(None, (_flatten_text(item) for item in value.values())))
    return str(value)


@st.cache_data(show_spinner=False, ttl=3600)
def search_gdelt_articles(query: str, start_date: date, end_date: date, max_results: int = 20) -> List[dict]:
    clipped = _gdelt_range(start_date, end_date)
    if not clipped:
        return []
    gdelt_start, gdelt_end = clipped

    base_url = "https://api.gdeltproject.org/api/v2/doc/doc"
    base_params = {
        "query": query,
        "mode": "artlist",
        "maxrecords": max_results,
        "sort": "DateDesc",
        "STARTDATETIME": _gdelt_timestamp(gdelt_start),
        "ENDDATETIME": _gdelt_timestamp(gdelt_end, end_of_day=True),
    }

    data = None
    for fmt in ["jsonfeed", "json"]:
        try:
            data = _request(base_url, params={**base_params, "format": fmt}, expect="json")
            if data:
                break
        except Exception:
            continue
    if not data:
        return []

    items = data.get("items") or data.get("articles") or data.get("data") or []
    if isinstance(items, dict):
        items = items.get("items") or items.get("articles") or []

    records: List[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = _clean_url(item.get("url") or item.get("url_mobile") or item.get("external_url") or "")
        title = _strip_html(item.get("title") or item.get("headline") or "Sin título")
        published_raw = item.get("date_published") or item.get("date_modified") or item.get("seendate") or item.get("pubDate") or ""
        published = _parse_date(published_raw)
        if published and not _date_in_range(published, start_date, end_date):
            continue

        domain = item.get("domain") or urlparse(url).netloc or item.get("source") or "GDELT"
        language = item.get("language") or ""
        source_country = item.get("sourcecountry") or item.get("source_country") or ""
        summary = _strip_html(item.get("summary") or item.get("content_text") or item.get("content_html") or "")
        if not summary:
            parts = []
            if domain:
                parts.append(f"Dominio: {domain}")
            if language:
                parts.append(f"Idioma: {language}")
            if source_country:
                parts.append(f"País fuente: {source_country}")
            summary = " | ".join(parts) or "Resultado recuperado a través de GDELT."

        records.append(
            {
                "title": title,
                "snippet": _truncate(summary),
                "url": url,
                "source": domain,
                "published": published.isoformat() if published else str(published_raw),
                "source_db": "GDELT",
                "language": language,
            }
        )
    return _dedupe(records)


def _walk_objects(payload):
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            yield from _walk_objects(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from _walk_objects(value)


def _extract_boe_documents(payload) -> List[dict]:
    documents: List[dict] = []
    for obj in _walk_objects(payload):
        if not isinstance(obj, dict):
            continue
        if obj.get("identificador") and obj.get("titulo"):
            documents.append(obj)
    return documents


@st.cache_data(show_spinner=False, ttl=3600)
def search_boe_legislation(query_terms: Tuple[str, ...], start_date: date, end_date: date, max_results: int = 15) -> List[dict]:
    cleaned_terms = []
    for term in query_terms:
        norm = _normalize(term)
        if len(norm) < 3:
            continue
        cleaned_terms.append(term.replace('"', '').strip())
    cleaned_terms = _unique_keep_order(cleaned_terms)[:8]
    if not cleaned_terms:
        return []

    clauses = []
    for term in cleaned_terms:
        safe = term.strip()
        if not safe:
            continue
        phrase = _safe_phrase(safe)
        clauses.append(f"(titulo:{phrase} OR texto:{phrase})")

    query_obj = {
        "query": {
            "query_string": {"query": " OR ".join(clauses)},
            "range": {"fecha_publicacion": {"gte": _ymd(start_date), "lte": _ymd(end_date)}},
        },
        "sort": [{"fecha_publicacion": "desc"}],
    }

    params = {"query": json.dumps(query_obj, ensure_ascii=False), "limit": max_results}
    data = _request(
        "https://boe.es/datosabiertos/api/legislacion-consolidada",
        params=params,
        expect="json",
    )

    documents = _extract_boe_documents(data)
    records: List[dict] = []
    for item in documents:
        identifier = item.get("identificador", "")
        title = _strip_html(item.get("titulo", "Sin título"))
        published = str(item.get("fecha_publicacion", ""))
        if len(published) == 8 and published.isdigit():
            published = f"{published[:4]}-{published[4:6]}-{published[6:8]}"

        snippet_bits = []
        for label, field in [
            ("Rango", item.get("rango")),
            ("Departamento", item.get("departamento")),
            ("Ámbito", item.get("ambito")),
            ("Materia", item.get("materia") or item.get("materias")),
            ("Vigencia", item.get("fecha_vigencia")),
        ]:
            flat = _flatten_text(field)
            if flat:
                snippet_bits.append(f"{label}: {flat}")
        snippet = " | ".join(snippet_bits) or "Documento normativo recuperado desde la API oficial del BOE."

        records.append(
            {
                "title": title,
                "snippet": _truncate(snippet),
                "url": f"https://www.boe.es/buscar/doc.php?id={identifier}" if identifier else "",
                "source": "BOE",
                "published": published,
                "source_db": "BOE API",
                "identifier": identifier,
            }
        )
    return _dedupe(records)


def _build_text_query(terms: List[str], *, extras: Optional[List[str]] = None, limit: int = 14) -> str:
    chunks = _unique_keep_order((terms or []) + (extras or []))
    return " ".join(chunks[:limit]).strip()


def build_queries(species: str, user_keywords: str) -> Dict[str, object]:
    science_meta = build_science_queries(species, user_keywords)
    species_terms = science_meta["species_terms"][:5]
    topic_terms = science_meta["expanded_terms"][:10]
    market_terms = _unique_keep_order(science_meta["market_terms"] + [
        "prices",
        "price",
        "costs",
        "cost",
        "demand",
        "supply",
        "trade",
        "imports",
        "exports",
        "margin",
        "production",
        "consumption",
    ])
    regulation_terms = _unique_keep_order(science_meta["regulation_terms"] + [
        "regulation",
        "legislation",
        "law",
        "decree",
        "order",
        "decision",
        "EFSA",
        "EUR-Lex",
        "BOE",
        "official journal",
        "animal health law",
        "implementing regulation",
    ])

    core_terms = _unique_keep_order((science_meta["user_phrases"] or []) + topic_terms[:6] + species_terms[:3])

    market_queries = _unique_keep_order(
        [
            _build_text_query(species_terms[:3] + topic_terms[:5], extras=["market", "prices", "costs", "trade", "demand"]),
            _build_text_query(species_terms[:3] + topic_terms[:5], extras=market_terms[:7]),
            _build_text_query(species_terms[:3], extras=["feed costs", "raw materials", "production", "consumption", "retail"] + topic_terms[:4]),
        ]
    )

    regulation_queries = _unique_keep_order(
        [
            _build_text_query(species_terms[:3] + topic_terms[:5], extras=["regulation", "legislation", "EFSA", "EUR-Lex", "BOE"]),
            _build_text_query(species_terms[:3] + topic_terms[:5], extras=regulation_terms[:8]),
        ]
    )

    official_google_queries = _unique_keep_order(
        [
            f"{regulation_queries[0]} site:boe.es" if regulation_queries else "",
            f"{regulation_queries[0]} site:eur-lex.europa.eu" if regulation_queries else "",
            f"{regulation_queries[0]} site:efsa.europa.eu" if regulation_queries else "",
            f"{regulation_queries[0]} site:mapa.gob.es" if regulation_queries else "",
        ]
    )

    raw_market_search = _build_text_query(core_terms[:6], extras=["market", "prices", "costs"])
    raw_reg_search = _build_text_query(core_terms[:6], extras=["regulation", "EFSA", "EUR-Lex", "BOE"])

    return {
        "market": {
            "queries": market_queries,
            "expanded_terms": topic_terms,
            "market_terms": market_terms,
            "species_terms": species_terms,
            "external_links": {
                "Google News": f"https://news.google.com/search?q={quote_plus(raw_market_search)}",
                "Google": f"https://www.google.com/search?q={quote_plus(raw_market_search)}",
            },
        },
        "science": science_meta,
        "regulation": {
            "queries": regulation_queries,
            "official_google_queries": official_google_queries,
            "boe_terms": _unique_keep_order((science_meta["user_phrases"] or []) + topic_terms[:8] + [species]),
            "expanded_terms": topic_terms,
            "regulation_terms": regulation_terms,
            "species_terms": species_terms,
            "external_links": {
                "EUR-Lex / Google": f"https://www.google.com/search?q={quote_plus(raw_reg_search + ' site:eur-lex.europa.eu')}",
                "BOE / Google": f"https://www.google.com/search?q={quote_plus(raw_reg_search + ' site:boe.es')}",
                "EFSA / Google": f"https://www.google.com/search?q={quote_plus(raw_reg_search + ' site:efsa.europa.eu')}",
            },
        },
    }


def _search_google_news_batch(queries: List[str], start_date: date, end_date: date, max_results: int) -> List[dict]:
    collected: List[dict] = []
    usable_queries = [q for q in queries if q][:3]
    if not usable_queries:
        return []
    per_query = max(4, min(12, max_results + 2))
    for query in usable_queries:
        date_hint = f" after:{start_date.isoformat()} before:{(end_date + timedelta(days=1)).isoformat()}"
        try:
            collected.extend(search_google_news(query + date_hint, start_date, end_date, max_results=per_query))
        except Exception:
            continue
    return _dedupe(collected)


def _search_gdelt_batch(queries: List[str], start_date: date, end_date: date, max_results: int, domains: Optional[List[str]] = None) -> List[dict]:
    collected: List[dict] = []
    usable_queries = [q for q in queries if q][:3]
    if not usable_queries:
        return []
    per_query = max(5, min(20, max_results + 4))
    for query in usable_queries:
        enriched_query = query
        if domains:
            domain_block = " OR ".join(f"domainis:{domain}" for domain in domains)
            enriched_query = f"({query}) ({domain_block})"
        try:
            items = search_gdelt_articles(enriched_query, start_date, end_date, max_results=per_query)
            collected.extend(items)
            if not items and domains:
                collected.extend(search_gdelt_articles(query, start_date, end_date, max_results=per_query))
        except Exception:
            continue
    return _dedupe(collected)


def _score_generic_record(item: dict, species_terms: List[str], topic_terms: List[str], category_terms: List[str], mode: str) -> float:
    haystack = _normalize(
        " ".join(
            filter(
                None,
                [
                    item.get("title", ""),
                    item.get("snippet", ""),
                    item.get("source", ""),
                    item.get("url", ""),
                    item.get("source_db", ""),
                ],
            )
        )
    )
    score = 0.0

    species_hits = 0
    for term in species_terms:
        norm = _normalize(term)
        if norm and norm in haystack:
            species_hits += 1
            score += 1.5 if " " in norm else 0.8

    topic_hits = 0
    for term in topic_terms:
        norm = _normalize(term)
        if norm and norm in haystack:
            topic_hits += 1
            score += 2.0 if " " in norm else 1.0

    for term in category_terms:
        norm = _normalize(term)
        if norm and norm in haystack:
            score += 0.4

    url = (item.get("url") or "").lower()
    domain = urlparse(url).netloc.lower()

    if item.get("url"):
        score += 0.25

    source_db = item.get("source_db", "")
    if mode == "market":
        if source_db == "GDELT":
            score += 0.9
        elif source_db == "Google News":
            score += 0.5
        if any(token in haystack for token in ["price", "prices", "cost", "costs", "market", "trade", "export", "import", "consumption"]):
            score += 0.8
    elif mode == "regulation":
        if source_db == "BOE API":
            score += 2.5
        elif source_db == "GDELT":
            score += 0.8
        if any(domain.endswith(official) or official in domain for official in OFFICIAL_REGULATORY_DOMAINS):
            score += 1.6
        if any(token in haystack for token in ["regulation", "legislation", "directive", "decision", "decree", "order", "norma", "normativa", "ley", "efsa", "eur-lex", "boe"]):
            score += 1.0

    published = _parse_date(item.get("published"))
    if published:
        age_days = max((datetime.now() - published).days, 0)
        if age_days <= 30:
            score += 1.0
        elif age_days <= 90:
            score += 0.6
        elif age_days <= 365:
            score += 0.2

    if topic_terms and topic_hits == 0:
        score -= 1.5
    if species_hits == 0:
        score -= 0.7

    return score


def _sort_generic_results(records: List[dict], meta: dict, mode: str) -> List[dict]:
    species_terms = meta.get("species_terms", [])
    topic_terms = meta.get("expanded_terms", [])
    if mode == "market":
        category_terms = meta.get("market_terms", [])
    else:
        category_terms = meta.get("regulation_terms", [])

    enriched = []
    for item in records:
        current = dict(item)
        current["score"] = _score_generic_record(current, species_terms, topic_terms, category_terms, mode)
        enriched.append(current)

    enriched.sort(key=lambda item: (item.get("score", 0), item.get("published", "")), reverse=True)
    return enriched


def search_market_sources(market_meta: dict, start_date: date, end_date: date, max_results: int = 10) -> List[dict]:
    collected: List[dict] = []
    queries = market_meta.get("queries", [])

    collected.extend(_search_google_news_batch(queries[:2], start_date, end_date, max_results=max_results))
    collected.extend(_search_gdelt_batch(queries[:2], start_date, end_date, max_results=max_results))

    deduped = _dedupe(collected)
    ranked = _sort_generic_results(deduped, market_meta, "market")
    filtered = [item for item in ranked if item.get("score", 0) >= 0.2]
    if not filtered:
        filtered = ranked
    return filtered[:max_results]


def search_regulatory_sources(reg_meta: dict, start_date: date, end_date: date, max_results: int = 10) -> List[dict]:
    collected: List[dict] = []

    boe_terms = tuple(reg_meta.get("boe_terms", [])[:8])
    try:
        collected.extend(search_boe_legislation(boe_terms, start_date, end_date, max_results=max_results))
    except Exception:
        pass

    collected.extend(_search_gdelt_batch(reg_meta.get("queries", [])[:2], start_date, end_date, max_results=max_results, domains=OFFICIAL_REGULATORY_DOMAINS))
    collected.extend(_search_google_news_batch(reg_meta.get("official_google_queries", [])[:3], start_date, end_date, max_results=max_results))
    collected.extend(_search_google_news_batch(reg_meta.get("queries", [])[:1], start_date, end_date, max_results=max_results))

    deduped = _dedupe(collected)
    ranked = _sort_generic_results(deduped, reg_meta, "regulation")
    filtered = [item for item in ranked if item.get("score", 0) >= 0.2]
    if not filtered:
        filtered = ranked
    return filtered[:max_results]


def run_search(species: str, user_keywords: str, start_date: date, end_date: date, max_results: int) -> Tuple[Dict[str, List[dict]], Dict[str, object]]:
    queries = build_queries(species, user_keywords)
    results = {"market": [], "science": [], "regulation": []}

    results["market"] = search_market_sources(queries["market"], start_date, end_date, max_results=max_results)
    results["science"] = search_scientific_sources(queries["science"], start_date, end_date, max_results=max_results)
    results["regulation"] = search_regulatory_sources(queries["regulation"], start_date, end_date, max_results=max_results)

    return results, queries


def bibliography_entries(results: Dict[str, List[dict]]) -> List[str]:
    entries = []
    for item in flatten_results(results):
        published = item.get("published", "")[:10] if item.get("published") else "s/f"
        url = item.get("url", "")
        if item.get("category") == CATEGORY_LABELS["science"]:
            authors = item.get("authors", "Autoría no disponible")
            journal = item.get("journal") or item.get("source", "Fuente científica")
            doi_or_url = item.get("doi") or url
            source_db = item.get("source_db", "")
            entry = f"{authors}. ({published}). {item.get('title')}. {journal}. {doi_or_url} [{source_db}]"
        else:
            entry = f"{item.get('source', 'Fuente no indicada')}. ({published}). {item.get('title')}. {url}"
        entries.append(entry)
    return entries


def results_dataframe(items: List[dict]) -> pd.DataFrame:
    if not items:
        return pd.DataFrame(columns=["Fecha", "Base", "Fuente", "Título", "Resumen", "URL"])
    rows = []
    for item in items:
        rows.append(
            {
                "Fecha": item.get("published", "")[:10],
                "Base": item.get("source_db", ""),
                "Fuente": item.get("source", ""),
                "Título": item.get("title", ""),
                "Resumen": item.get("snippet", ""),
                "URL": item.get("url", ""),
            }
        )
    return pd.DataFrame(rows)


def render_category_table(items: List[dict], label: str) -> None:
    st.subheader(label)
    if not items:
        st.info("Sin resultados con los filtros actuales.")
        return

    for idx, item in enumerate(items, start=1):
        title = item.get("title", "Sin título")
        url = item.get("url", "")
        source = item.get("source", "Fuente no indicada")
        published = item.get("published", "")[:10] or "s/f"
        source_db = item.get("source_db", "")
        snippet = item.get("snippet", "")

        if url:
            st.markdown(f"**{idx}. [{title}]({url})**")
        else:
            st.markdown(f"**{idx}. {title}**")
        st.caption(f"{source} · {published} · {source_db}")
        if snippet:
            st.write(snippet)
        if url:
            st.markdown(f"[Abrir fuente]({url})")
        st.markdown("---")

    with st.expander("Vista tabular con enlaces"):
        df = results_dataframe(items)
        try:
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                column_config={"URL": st.column_config.LinkColumn("URL", display_text="Abrir")},
            )
        except Exception:
            st.dataframe(df, use_container_width=True, hide_index=True)


def render_science_debug(query_meta: Optional[dict]) -> None:
    if not query_meta:
        return
    science = query_meta.get("science", {})
    with st.expander("Cómo se ha ampliado la búsqueda científica"):
        user_phrases = science.get("user_phrases", [])
        expanded_terms = science.get("expanded_terms", [])
        queries = science.get("queries", {})

        st.markdown("**Entrada del usuario**")
        st.write(", ".join(user_phrases) if user_phrases else "Sin palabras clave específicas; se han usado términos técnicos por defecto del segmento.")

        st.markdown("**Términos ampliados automáticamente**")
        st.write(", ".join(expanded_terms[:20]) if expanded_terms else "Sin ampliaciones.")

        st.markdown("**Consultas científicas generadas**")
        st.code(
            f"OpenAlex: {queries.get('openalex', '')}\n\n"
            f"Europe PMC: {queries.get('europepmc', '')}\n\n"
            f"Crossref/Semantic Scholar: {queries.get('crossref', '')}",
            language="text",
        )

        links = science.get("external_links", {})
        if links:
            st.markdown("**Atajos externos**")
            for name, url in links.items():
                st.markdown(f"- [{name}]({url})")


def render_market_debug(query_meta: Optional[dict]) -> None:
    if not query_meta:
        return
    market = query_meta.get("market", {})
    with st.expander("Cómo se ha construido la búsqueda de mercado"):
        st.markdown("**Términos ampliados**")
        st.write(", ".join(market.get("expanded_terms", [])[:20]) or "Sin ampliación específica.")

        st.markdown("**Consultas ejecutadas**")
        for query in market.get("queries", []):
            st.code(query, language="text")

        links = market.get("external_links", {})
        if links:
            st.markdown("**Atajos externos**")
            for name, url in links.items():
                st.markdown(f"- [{name}]({url})")



def render_regulatory_debug(query_meta: Optional[dict]) -> None:
    if not query_meta:
        return
    regulation = query_meta.get("regulation", {})
    with st.expander("Cómo se ha construido la búsqueda regulatoria"):
        st.markdown("**Términos ampliados**")
        st.write(", ".join(regulation.get("expanded_terms", [])[:20]) or "Sin ampliación específica.")

        st.markdown("**Consultas ejecutadas**")
        for query in regulation.get("queries", []):
            st.code(query, language="text")
        if regulation.get("boe_terms"):
            st.markdown("**Términos enviados a la API del BOE**")
            st.write(", ".join(regulation.get("boe_terms", [])[:12]))

        links = regulation.get("external_links", {})
        if links:
            st.markdown("**Atajos externos**")
            for name, url in links.items():
                st.markdown(f"- [{name}]({url})")


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    init_state()

    st.title(APP_TITLE)
    st.caption(
        "Radar de mercado, evidencia científico-técnica y vigilancia regulatoria para especies de interés. "
        "La app prioriza enlaces directos a las fuentes recuperadas y combina varias búsquedas para no quedarse solo en una única base."
    )

    with st.sidebar:
        st.header("Filtros")
        species = st.selectbox("Especie / segmento", list(SPECIES_OPTIONS.keys()))
        today = date.today()
        default_start = today - timedelta(days=180)
        start_date = st.date_input("Fecha inicio", value=default_start)
        end_date = st.date_input("Fecha fin", value=today)
        user_keywords = st.text_input(
            "Palabras clave",
            placeholder="Ej.: peste porcina africana, metano, precios leche, influenza aviar...",
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
                results, queries = run_search(species, user_keywords, start_date, end_date, max_results)
                st.session_state.search_results = results
                st.session_state.query_meta = queries
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
    query_meta = st.session_state.query_meta

    if results:
        col1, col2, col3 = st.columns(3)
        col1.metric("Mercado", len(results.get("market", [])))
        col2.metric("Científico-técnico", len(results.get("science", [])))
        col3.metric("Regulación", len(results.get("regulation", [])))

        tab_market, tab_science, tab_reg, tab_chat, tab_brief = st.tabs(
            ["Mercado", "Científico-técnico", "Legislación", "Chat", "Briefing e informe"]
        )

        with tab_market:
            render_market_debug(query_meta)
            render_category_table(results.get("market", []), "Señales de mercado")

        with tab_science:
            render_science_debug(query_meta)
            render_category_table(results.get("science", []), "Evidencia científico-técnica")

        with tab_reg:
            render_regulatory_debug(query_meta)
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
                        answer = answer_chat(
                            question,
                            species,
                            user_keywords,
                            results,
                            company_context,
                            st.session_state.chat_history,
                        )
                        st.markdown(answer)
                st.session_state.chat_history.append({"role": "assistant", "content": answer})

        with tab_brief:
            if generate_button:
                with st.spinner("Generando briefing..."):
                    try:
                        brief_text = generate_brief(
                            species,
                            user_keywords,
                            results,
                            company_context,
                            st.session_state.chat_history,
                            query_meta=query_meta,
                        )
                        st.session_state.brief_text = brief_text
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
                    for item in flatten_results(results):
                        title = item.get("title", "Sin título")
                        url = item.get("url", "")
                        published = item.get("published", "")[:10] or "s/f"
                        source = item.get("source", "Fuente")
                        if url:
                            st.markdown(f"- [{title}]({url}) — {source} ({published})")
                        else:
                            st.markdown(f"- {title} — {source} ({published})")
            else:
                st.info("Primero ejecuta la búsqueda y luego genera el briefing.")

    else:
        st.info(
            "Configura los filtros de la barra lateral y pulsa **Buscar y actualizar radar**. "
            "Después podrás conversar con la app y generar el informe en Word."
        )

    st.divider()
    st.caption(
        "Aviso: esta herramienta no sustituye la revisión técnica, regulatoria ni jurídica. "
        "Antes de usar conclusiones en documentos externos o claims comerciales, valida cada punto con la fuente primaria."
    )


if __name__ == "__main__":
    main()
