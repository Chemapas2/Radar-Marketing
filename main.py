import io
import os
import re
from collections import Counter
from datetime import date, datetime
from typing import Dict, List, Optional
from urllib.parse import quote

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
USER_AGENT = "Mozilla/5.0 (compatible; NutrecoRadar/1.0; +https://streamlit.io)"
REQUEST_TIMEOUT = 25
MAX_CONTEXT_ITEMS = 8

SPECIES_OPTIONS: Dict[str, Dict[str, List[str]]] = {
    "Avicultura de puesta": {
        "keywords": ["avicultura de puesta", "gallinas ponedoras", "layers", "egg production"],
        "market": ["mercado", "precio huevo", "costes", "consumo", "exportación", "importación"],
        "technical": ["nutrición", "sanidad", "calidad del huevo", "bienestar", "persistencia de puesta"],
        "regulation": ["normativa", "bienestar", "salmonella", "huevo", "etiquetado", "bioseguridad"],
    },
    "Avicultura de carne": {
        "keywords": ["avicultura de carne", "broilers", "pollos de engorde", "broiler production"],
        "market": ["mercado", "precio pollo", "costes", "integración", "consumo", "exportación"],
        "technical": ["nutrición", "rendimiento", "salud intestinal", "coccidiosis", "bienestar"],
        "regulation": ["normativa", "bienestar", "bioseguridad", "influenza aviar", "residuos"],
    },
    "Porcino": {
        "keywords": ["porcino", "swine", "pig production", "cerdo"],
        "market": ["mercado", "precio cerdo", "piensos", "costes", "exportación", "importación"],
        "technical": ["nutrición", "sanidad", "eficiencia", "reproducción", "destete", "bioseguridad"],
        "regulation": ["normativa", "bioseguridad", "peste porcina africana", "bienestar", "emisiones"],
    },
    "Vacuno de leche": {
        "keywords": ["vacuno de leche", "dairy cattle", "lechero", "dairy cows"],
        "market": ["mercado lácteo", "precio leche", "costes", "margen", "exportación", "consumo"],
        "technical": ["nutrición", "salud ruminal", "fertilidad", "mastitis", "eficiencia"],
        "regulation": ["normativa", "antibióticos", "sostenibilidad", "emisiones", "bienestar"],
    },
    "Vacuno de carne": {
        "keywords": ["vacuno de carne", "beef cattle", "cebo", "beef production"],
        "market": ["mercado vacuno", "precio carne", "costes", "cebaderos", "exportación"],
        "technical": ["nutrición", "ganancia media diaria", "salud respiratoria", "bienestar"],
        "regulation": ["normativa", "bienestar", "transporte", "emisiones", "trazabilidad"],
    },
    "Ovino": {
        "keywords": ["ovino", "sheep", "sheep production", "cordero"],
        "market": ["mercado ovino", "precio cordero", "leche ovina", "costes"],
        "technical": ["nutrición", "reproducción", "parasitismo", "rumen", "productividad"],
        "regulation": ["normativa", "lengua azul", "bienestar", "movimientos", "trazabilidad"],
    },
    "Caprino": {
        "keywords": ["caprino", "goat", "goat production", "leche caprina"],
        "market": ["mercado caprino", "precio leche", "queso", "costes"],
        "technical": ["nutrición", "parasitismo", "mamitis", "reproducción", "eficiencia"],
        "regulation": ["normativa", "bienestar", "movimientos", "trazabilidad", "sanidad"],
    },
    "Cunicultura": {
        "keywords": ["cunicultura", "rabbits", "rabbit production", "conejo"],
        "market": ["mercado conejo", "precio conejo", "costes", "consumo"],
        "technical": ["nutrición", "enteropatía", "rendimiento", "bienestar", "sanidad"],
        "regulation": ["normativa", "bienestar", "medicación", "bioseguridad"],
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
}


def _strip_html(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", BeautifulSoup(text, "html.parser").get_text(" ", strip=True)).strip()


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


def _truncate(text: str, max_len: int = 380) -> str:
    if len(text or "") <= max_len:
        return text or ""
    return (text or "")[: max_len - 1].rstrip() + "…"


def _dedupe(records: List[dict]) -> List[dict]:
    seen = set()
    deduped = []
    for item in records:
        key = (item.get("title", "").strip().lower(), item.get("url", "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _keywords_from_text(text: str, top_k: int = 8) -> List[str]:
    words = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñÜü0-9\-]{4,}", text.lower())
    counts = Counter(w for w in words if w not in STOPWORDS_ES)
    return [w for w, _ in counts.most_common(top_k)]


def build_queries(species: str, user_keywords: str) -> Dict[str, str]:
    profile = SPECIES_OPTIONS[species]
    base = " OR ".join([f'"{k}"' for k in profile["keywords"][:4]])
    user_bits = [x.strip() for x in re.split(r"[,;]", user_keywords or "") if x.strip()]
    user_clause = " OR ".join([f'"{x}"' for x in user_bits]) if user_bits else ""

    market_terms = " OR ".join([f'"{k}"' for k in profile["market"]])
    technical_terms = " OR ".join([f'"{k}"' for k in profile["technical"]])
    regulation_terms = " OR ".join([f'"{k}"' for k in profile["regulation"]])

    if user_clause:
        combined = f"({base}) AND ({user_clause})"
    else:
        combined = f"({base})"

    return {
        "market": f"{combined} AND ({market_terms})",
        "science": f"{combined} AND ({technical_terms})",
        "regulation": f"{combined} AND ({regulation_terms})",
    }


@st.cache_data(show_spinner=False, ttl=3600)
def search_google_news(query: str, start_date: date, end_date: date, max_results: int = 10) -> List[dict]:
    url = (
        "https://news.google.com/rss/search?q="
        + quote(query)
        + "&hl=es&gl=ES&ceid=ES:es"
    )
    response = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    feed = feedparser.parse(response.content)

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
                "url": entry.get("link", ""),
                "source": source,
                "published": published.isoformat() if published else "",
            }
        )
        if len(records) >= max_results:
            break
    return _dedupe(records)


@st.cache_data(show_spinner=False, ttl=3600)
def search_europe_pmc(query: str, start_date: date, end_date: date, max_results: int = 10) -> List[dict]:
    full_query = f"({query}) AND FIRST_PDATE:[{start_date.isoformat()} TO {end_date.isoformat()}]"
    params = {
        "query": full_query,
        "format": "json",
        "pageSize": max_results,
        "sort": "FIRST_PDATE_D",
    }
    response = requests.get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params=params,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    data = response.json()
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
            }
        )
    return _dedupe(records)


def search_regulatory_sources(query: str, start_date: date, end_date: date, max_results: int = 10) -> List[dict]:
    domain_filters = "(site:eur-lex.europa.eu OR site:boe.es OR site:mapa.gob.es OR site:efsa.europa.eu OR site:miteco.gob.es)"
    combined_query = f"{query} {domain_filters}"
    records = search_google_news(combined_query, start_date, end_date, max_results=max_results)
    if records:
        return records
    fallback_query = f"{query} normativa regulación reglamento ley decisión EFSA BOE EUR-Lex"
    return search_google_news(fallback_query, start_date, end_date, max_results=max_results)


def run_search(species: str, user_keywords: str, start_date: date, end_date: date, max_results: int) -> Dict[str, List[dict]]:
    queries = build_queries(species, user_keywords)
    results = {"market": [], "science": [], "regulation": []}

    market_query = queries["market"]
    results["market"] = search_google_news(market_query, start_date, end_date, max_results=max_results)

    science_query = queries["science"]
    results["science"] = search_europe_pmc(science_query, start_date, end_date, max_results=max_results)

    regulation_query = queries["regulation"]
    results["regulation"] = search_regulatory_sources(regulation_query, start_date, end_date, max_results=max_results)
    return results


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


def extractive_brief(species: str, user_keywords: str, results: Dict[str, List[dict]], company_context: str, chat_history: List[dict]) -> str:
    flat = flatten_results(results)
    if not flat:
        return "No se han recuperado resultados suficientes para elaborar el briefing."

    corpus = " ".join(filter(None, [item.get("title", "") + " " + item.get("snippet", "") for item in flat]))
    themes = _keywords_from_text(corpus, top_k=10)
    top_market = results.get("market", [])[:3]
    top_science = results.get("science", [])[:3]
    top_reg = results.get("regulation", [])[:3]

    lines = [
        f"# Briefing radar | {species}",
        "",
        "## Resumen ejecutivo",
        f"Búsqueda enfocada en: **{user_keywords or species}**.",
        f"Se han recuperado **{len(results.get('market', []))}** resultados de mercado, **{len(results.get('science', []))}** científico-técnicos y **{len(results.get('regulation', []))}** regulatorios.",
        f"Temas que más se repiten en los resultados: {', '.join(themes[:6]) if themes else 'sin patrón claro'}." ,
        "",
        "## Radar de mercado",
    ]

    if top_market:
        for item in top_market:
            lines.append(f"- **{item['title']}** ({item.get('source', 'Fuente no indicada')}, {item.get('published', 's/f')[:10]}). {item.get('snippet', '')}")
    else:
        lines.append("- No se han encontrado resultados recientes de mercado con la combinación actual de filtros.")

    lines.extend(["", "## Radar científico-técnico"])
    if top_science:
        for item in top_science:
            journal = item.get("journal") or item.get("source", "Fuente científica")
            lines.append(f"- **{item['title']}** ({journal}, {item.get('published', 's/f')[:10]}). {item.get('snippet', '')}")
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


def generate_brief(species: str, user_keywords: str, results: Dict[str, List[dict]], company_context: str, chat_history: List[dict]) -> str:
    if not llm_is_available():
        return extractive_brief(species, user_keywords, results, company_context, chat_history)

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
        return "No encuentro evidencia suficiente en los resultados actuales para responder con precisión. Prueba a ampliar fechas o cambiar palabras clave."

    lines = ["He localizado la siguiente evidencia relevante en los resultados recuperados:"]
    for _, item in candidate_items[:4]:
        lines.append(
            f"- {item.get('title')} ({item.get('source', 'Fuente')}, {item.get('published', 's/f')[:10]}): {item.get('snippet', '')}"
        )
    lines.append("Conclusión provisional: conviene validar este punto con una nueva búsqueda más específica antes de cerrar el informe.")
    return "\n".join(lines)


def bibliography_entries(results: Dict[str, List[dict]]) -> List[str]:
    entries = []
    for item in flatten_results(results):
        published = item.get("published", "")[:10] if item.get("published") else "s/f"
        if item.get("category") == CATEGORY_LABELS["science"]:
            authors = item.get("authors", "Autoría no disponible")
            journal = item.get("journal") or item.get("source", "Europe PMC")
            doi_or_url = item.get("doi") or item.get("url", "")
            entries.append(f"{authors}. ({published}). {item.get('title')}. {journal}. {doi_or_url}")
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
    if not items:
        return pd.DataFrame(columns=["Fecha", "Fuente", "Título", "Resumen", "URL"])
    rows = []
    for item in items:
        rows.append(
            {
                "Fecha": item.get("published", "")[:10],
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


def init_state() -> None:
    st.session_state.setdefault("search_results", None)
    st.session_state.setdefault("brief_text", "")
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("last_filters", {})


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    init_state()

    st.title(APP_TITLE)
    st.caption(
        "Radar de mercado, evidencia científico-técnica y vigilancia regulatoria para especies de interés. "
        "La app usa fuentes públicas; la calidad del briefing mejora si configuras una clave de OpenAI para la síntesis."
    )

    with st.sidebar:
        st.header("Filtros")
        species = st.selectbox("Especie / segmento", list(SPECIES_OPTIONS.keys()))
        today = date.today()
        default_start = date(today.year, max(1, today.month - 2), 1)
        start_date = st.date_input("Fecha inicio", value=default_start)
        end_date = st.date_input("Fecha fin", value=today)
        user_keywords = st.text_input(
            "Palabras clave",
            placeholder="Ej.: peste porcina africana, metano, precios leche, influenza aviar...",
        )
        max_results = st.slider("Máximo de resultados por bloque", min_value=5, max_value=20, value=10, step=1)
        company_context = st.text_area("Contexto corporativo / criterios de recomendación", value=DEFAULT_COMPANY_CONTEXT, height=190)
        run_button = st.button("Buscar y actualizar radar", use_container_width=True)
        generate_button = st.button("Generar briefing", use_container_width=True)

    if start_date > end_date:
        st.error("La fecha inicial no puede ser posterior a la fecha final.")
        return

    if run_button:
        with st.spinner("Recuperando fuentes..."):
            try:
                st.session_state.search_results = run_search(species, user_keywords, start_date, end_date, max_results)
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


if __name__ == "__main__":
    main()
