adar de necesidades del mercado | Nutreco Iberia

Aplicación Streamlit pensada para que el departamento tecnico-comercial-marketing lea el mercado con criterio técnico y regulatorio, y convierta esa lectura en oportunidades de producto, servicios y soluciones para Nutreco Iberia.

## Qué hace esta versión

La app trabaja en tres bloques separados:

- **Mercado y noticias**
- **Científico-técnico**
- **Legislación y regulación**

La lógica principal de esta versión es deliberadamente más guiada que antes:

- **ya no usa un campo libre de palabras clave**;
- usa **propuestas curadas de búsqueda** por bloque;
- permite **selección múltiple de especies**;
- incorpora las opciones **All species** y **Alimentación animal**;
- permite lanzar la búsqueda con un botón por bloque o con un botón para buscar todo el radar;
- mantiene la exportación a **Word (.docx)**;
- muestra el propio **README dentro de la app**.

## Objetivo de negocio

El radar no está pensado solo para “recoger información”. Su finalidad es ayudar a marketing a responder preguntas como estas:

- qué necesidades de mercado aparecen con más fuerza,
- qué tensiones económicas o sanitarias pueden abrir una oportunidad,
- qué evidencias científico-técnicas pueden apoyar una solución,
- qué límites regulatorios condicionan el posicionamiento,
- y dónde puede tener sentido desarrollar, adaptar o priorizar un producto o servicio de Nutreco Iberia.

## Especies y segmentos disponibles

Se pueden seleccionar una o varias opciones al mismo tiempo:

- All species
- Alimentación animal
- Avicultura de puesta
- Avicultura de carne
- Porcino
- Vacuno de leche
- Vacuno de carne
- Ovino
- Caprino
- Cunicultura

### Cómo interpretar dos opciones especiales

**All species**
: realiza una lectura transversal del sector ganadero.

**Alimentación animal**
: orienta la vigilancia a noticias y referencias sobre piensos, nutrición animal, materias primas, aditivos, formulación y regulación feed, de manera genérica y multisectorial.

## Propuestas curadas de búsqueda

Cada bloque incluye **más de 50 opciones** con selección múltiple.

### 1. Mercado y noticias

Ejemplos:

- precios y cotizaciones,
- boletines oficiales de precios,
- coste del pienso,
- materias primas y piensos,
- cereales y energía,
- harina de soja y proteínas,
- rentabilidad y márgenes,
- exportación,
- importación,
- comercio internacional,
- logística y transporte,
- sacrificio y mataderos,
- precio de la leche,
- precio del cerdo,
- precio del pollo,
- precio del huevo,
- precio del vacuno,
- precio del cordero,
- sostenibilidad como driver de compra,
- noticias del MAPA y del sector.

### 2. Científico-técnico

Ejemplos:

- nutrición y formulación,
- eficiencia alimentaria,
- salud intestinal,
- probióticos,
- prebióticos,
- ácidos orgánicos,
- enzimas,
- aminoácidos,
- micotoxinas,
- calidad del agua,
- bioseguridad y prevención,
- reducción de antimicrobianos,
- estrés térmico,
- metano y huella de carbono,
- salud ruminal,
- mastitis y calidad de leche,
- reproducción y fertilidad,
- calidad del huevo,
- coccidiosis,
- salmonella,
- influenza aviar,
- peste porcina africana,
- lengua azul,
- parasitismo en pequeños rumiantes,
- sensores y ganadería de precisión.

### 3. Legislación y regulación

Ejemplos:

- bienestar animal,
- bienestar en transporte,
- bienestar en sacrificio,
- bioseguridad y sanidad animal,
- Ley de Sanidad Animal de la UE,
- notificación obligatoria de enfermedades,
- peste porcina africana,
- influenza aviar,
- lengua azul,
- uso de antimicrobianos,
- medicamentos veterinarios,
- piensos medicamentosos,
- higiene de los piensos,
- aditivos para alimentación animal,
- etiquetado de piensos,
- contaminantes y residuos,
- trazabilidad,
- identificación y movimientos,
- controles oficiales,
- ayudas PAC y ecoesquemas,
- emisiones de amoniaco,
- metano y gases de efecto invernadero,
- declaraciones y claims ambientales,
- deforestación y materias primas importadas.

## Motores de búsqueda usados

### Mercado y noticias

Combina resultados de:

- **Google News RSS**
- **DuckDuckGo Web Search**

El objetivo aquí es cubrir:

- prensa sectorial,
- noticias generales relevantes,
- boletines y páginas del MAPA,
- y páginas con lectura de mercado útiles para marketing.

### Científico-técnico

Combina resultados de:

- **OpenAlex**
- **Europe PMC**

Así se mejora bastante la recuperación frente a búsquedas científicas demasiado cerradas.

### Legislación y regulación

Usa búsquedas restringidas y filtradas para priorizar dominios oficiales como:

- `boe.es`
- `eur-lex.europa.eu`
- `mapa.gob.es`
- `aesan.gob.es`
- `efsa.europa.eu`
- `miteco.gob.es`
- `sanidad.gob.es`

Además, la app intenta filtrar ruido de otras especies y descarta resultados regulatorios que no parezcan normativos ni oficiales.

## Cómo usar la app

### Flujo recomendado

1. Selecciona una o varias especies o segmentos.
2. Define el intervalo de fechas.
3. Elige propuestas de búsqueda en mercado, ciencia y regulación.
4. Pulsa uno de estos botones:
   - **Buscar mercado / noticias**
   - **Buscar científico-técnico**
   - **Buscar regulación**
   - **Buscar todo el radar**
5. Revisa cada pestaña de resultados.
6. Genera el briefing.
7. Descarga el informe Word si necesitas editarlo o presentarlo.

### Cuándo usar “All species”

Úsalo cuando quieras una lectura macro del sector o cuando estés vigilando una tendencia transversal, por ejemplo:

- materias primas,
- sostenibilidad,
- claims ambientales,
- feed additives,
- presión regulatoria sobre emisiones,
- tendencias de consumo.

### Cuándo usar “Alimentación animal”

Úsalo cuando la vigilancia esté centrada en:

- piensos,
- formulación,
- aditivos,
- higiene feed,
- claims de alimentación animal,
- materias primas y costes feed,
- soluciones aplicables a varias especies.

## Briefing

La app puede generar un briefing integrando:

- señales de mercado,
- referencias científicas,
- regulación,
- e implicaciones preliminares para Nutreco Iberia.

Sin `OPENAI_API_KEY`, el briefing es **extractivo**, pero funcional.

Con `OPENAI_API_KEY`, la síntesis puede ser más rica.

## Instalación local

```bash
python -m venv .venv
source .venv/bin/activate   # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Ejecución

```bash
streamlit run main.py
```

## Dependencias

Las dependencias actuales son:

- streamlit
- requests
- feedparser
- pandas
- python-dateutil
- beautifulsoup4
- python-docx
- openai

## Estructura mínima del repositorio

```text
.
├── main.py
├── requirements.txt
└── README.md
```

## Limitaciones actuales

1. **No sustituye validación experta.** La app ayuda a priorizar señales.
2. **El bloque regulatorio sigue dependiendo de la indexación pública.** Es mejor que antes, pero no sustituye una base jurídica especializada.
3. **La calidad del bloque de mercado depende de la visibilidad pública de prensa, boletines y páginas oficiales.**
4. **La selección múltiple muy amplia puede ralentizar la búsqueda.** Conviene empezar por 2 a 5 propuestas por bloque.
5. **No hay almacenamiento persistente ni histórico interno de búsquedas.**

## Mejoras futuras razonables

- histórico de búsquedas y comparativa temporal,
- taxonomías propias de Nutreco Iberia,
- alertas automáticas por tema,
- fuentes sectoriales premium,
- filtrado jurídico más estructurado,
- y una capa de conocimiento interno corporativo.
