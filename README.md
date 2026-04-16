# Radar sectorial Nutreco Iberia (Streamlit)

Aplicación Streamlit para vigilar tres bloques de información por especie/segmento:

- **Mercado**
- **Científico-técnico**
- **Legislación y regulación**

La app está pensada como base funcional para un radar interno. Permite:

- elegir especie/segmento con un desplegable,
- acotar por intervalo de fechas,
- añadir palabras clave,
- recuperar fuentes públicas,
- conversar con la app para afinar el enfoque,
- generar un briefing visible en pantalla,
- exportar el resultado a **Word (.docx)**,
- listar referencias bibliográficas y documentales al final del informe.

## Segmentos incluidos

- Avicultura de puesta
- Avicultura de carne
- Porcino
- Vacuno de leche
- Vacuno de carne
- Ovino
- Caprino
- Cunicultura

## Arquitectura resumida

### 1. Mercado
Búsqueda mediante **Google News RSS** con queries construidas a partir de:

- especie/segmento,
- palabras clave del usuario,
- términos asociados a mercado.

### 2. Científico-técnico
Búsqueda en **Europe PMC** usando:

- especie/segmento,
- palabras clave del usuario,
- términos técnicos,
- filtro por fecha.

### 3. Legislación y regulación
Búsqueda de novedades regulatorias con query orientada a dominios oficiales, por ejemplo:

- `eur-lex.europa.eu`
- `boe.es`
- `mapa.gob.es`
- `efsa.europa.eu`
- `miteco.gob.es`

## Resumen y chat

La app funciona en dos modos:

### Sin clave de OpenAI
Genera un briefing extractivo y respuestas básicas a preguntas sobre los resultados recuperados.

### Con clave de OpenAI
La síntesis mejora sensiblemente. La app generará:

- resumen ejecutivo,
- señales de mercado,
- hallazgos científico-técnicos,
- implicaciones regulatorias,
- recomendaciones priorizadas para Nutreco Iberia,
- riesgos, vacíos y preguntas abiertas.

## Variables de entorno opcionales

```bash
OPENAI_API_KEY=tu_clave
OPENAI_MODEL=gpt-4.1-mini
```

Si no defines estas variables, la aplicación seguirá funcionando, pero con una síntesis menos potente.

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

## Flujo de uso recomendado

1. Selecciona el segmento.
2. Define el rango de fechas.
3. Añade palabras clave.
4. Pulsa **Buscar y actualizar radar**.
5. Revisa los resultados por pestaña.
6. Usa el chat para concretar dudas.
7. Pulsa **Generar briefing**.
8. Descarga el **.docx** para edición y presentación.

## Ejemplos de búsqueda

- `peste porcina africana`
- `influenza aviar`
- `precio leche y metano`
- `lengua azul`
- `costes de alimentación`
- `bienestar animal`
- `emisiones`
- `salmonella`

## Puntos fuertes de esta base

- estructura clara para marketing técnico,
- separación entre mercado, técnica y regulación,
- exportación a Word,
- referencias al final,
- adaptable a GitHub y Streamlit Cloud.

## Limitaciones actuales

1. **No sustituye una revisión experta.** La app ayuda a detectar señales; no debe usarse como único soporte para decisiones regulatorias o claims.
2. **La calidad del bloque regulatorio depende de la recuperabilidad pública.** Puede requerir un conector adicional o APIs específicas más adelante.
3. **La calidad del resumen mejora con LLM.** Sin OpenAI, el briefing es útil pero más simple.
4. **No incluye autenticación ni almacenamiento persistente.**
5. **No incorpora todavía fuentes privadas internas** (SharePoint, Drive, bases documentales internas, etc.).

## Siguientes mejoras recomendadas

- añadir un fichero de configuración de fuentes por especie,
- incorporar scoring de relevancia,
- guardar histórico de búsquedas,
- generar PDF además de Word,
- incluir alertas automáticas por tema,
- conectar bases internas o feeds corporativos,
- añadir taxonomías propias de Nutreco Iberia para recomendaciones más finas.

## Estructura mínima del repositorio

```text
.
├── main.py
├── requirements.txt
└── README.md
```

## Despliegue en GitHub / Streamlit Community Cloud

1. Crea un repositorio en GitHub.
2. Sube `main.py`, `requirements.txt` y `README.md`.
3. En Streamlit Community Cloud, conecta el repositorio.
4. Define `OPENAI_API_KEY` en **Secrets** si quieres activar la síntesis avanzada.
5. Despliega la app.

## Nota final

Esta versión está planteada como un **MVP funcional**. Sirve para validar flujo, utilidad y adopción interna. Cuando el equipo confirme el valor del radar, lo razonable será pasar a una segunda fase con:

- fuentes mejor curadas,
- clasificación más robusta,
- prompts y reglas específicas por especie,
- capa de conocimiento corporativo,
- y control más fino de trazabilidad documental.
