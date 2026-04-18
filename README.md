# Radar sectorial Nutreco Iberia (Streamlit)

Aplicación para que el departamento de marketing pueda leer mejor las necesidades del mercado y traducir señales externas en oportunidades de producto, servicio, argumentario y soporte técnico.

La app combina tres capas:

- **Mercado**: prensa sectorial, noticias, boletines oficiales y actualizaciones institucionales.
- **Científico-técnico**: literatura científica pública.
- **Legislación y regulación**: normativa y páginas oficiales.

## Qué ha cambiado en esta versión

La app **ya no usa un campo libre de palabras clave**. En su lugar, utiliza una **selección cerrada de temas** para mejorar la consistencia de la búsqueda y reducir ruido.

También añade un segmento específico de **"Alimentación animal"** para vigilar señales transversales de todas las especies ganaderas.

## Segmentos disponibles

- Alimentación animal
- Avicultura de puesta
- Avicultura de carne
- Porcino
- Vacuno de leche
- Vacuno de carne
- Ovino
- Caprino
- Cunicultura

## Temas disponibles

La app ofrece más de 20 temas estructurados. Se pueden seleccionar hasta 3 por búsqueda:

- Precios y cotizaciones
- Costes de alimentación
- Materias primas y piensos
- Rentabilidad y márgenes
- Consumo y demanda
- Exportación e importación
- Bienestar animal
- Bioseguridad
- Sanidad animal
- Antimicrobianos y resistencias
- Vacunación y prevención
- Trazabilidad y movimientos
- Sostenibilidad y emisiones
- Metano y huella de carbono
- Calidad del producto
- Reproducción y fertilidad
- Salud intestinal
- Micotoxinas
- Salmonella
- Coccidiosis
- Mastitis
- Peste porcina africana
- Influenza aviar
- Lengua azul
- Etiquetado y comercialización
- Normativa de alimentación animal

## Cómo funciona

### 1. Mercado
La búsqueda de mercado está pensada como radar de necesidades del cliente y del sector. Prioriza:

- noticias de prensa,
- páginas institucionales del MAPA,
- boletines y páginas de mercado,
- medios especializados ganaderos.

### 2. Científico-técnico
La capa científica usa fuentes públicas como **Europe PMC** y **OpenAlex**.

### 3. Regulación
La capa regulatoria prioriza dominios oficiales y exige relevancia temática real para evitar ruido:

- `boe.es`
- `eur-lex.europa.eu`
- `mapa.gob.es`
- `efsa.europa.eu`
- otros dominios oficiales relacionados

## Flujo recomendado de uso

1. Seleccionar especie o segmento.
2. Escoger 1 a 3 temas.
3. Definir el rango de fechas.
4. Pulsar **Buscar y actualizar radar**.
5. Revisar los bloques de mercado, ciencia y regulación.
6. Utilizar el chat para interrogar los resultados ya recuperados.
7. Generar el briefing integrado.
8. Exportar el informe en Word para edición o presentación.

## Qué debe leer marketing en la salida

La app no está pensada solo para “ver noticias”. Está pensada para responder estas preguntas:

- ¿Qué preocupación real está emergiendo en clientes y sector?
- ¿Qué está empujando esa preocupación: precio, sanidad, regulación, demanda o sostenibilidad?
- ¿Qué evidencia técnica ayuda a sostener una propuesta?
- ¿Qué riesgo regulatorio condiciona el mensaje o la solución?
- ¿Qué oportunidad concreta abre esto para Nutreco Iberia?

## Exportación

La app genera un briefing visible en pantalla y un informe en **Word (.docx)** con:

- resumen ejecutivo,
- síntesis integrada,
- lectura por bloque,
- implicaciones para marketing,
- referencias bibliográficas y documentales.

## Ejemplos útiles

- Porcino + Peste porcina africana
- Avicultura de puesta + Precios y cotizaciones
- Vacuno de leche + Mastitis
- Ovino + Lengua azul
- Alimentación animal + Materias primas y piensos
- Alimentación animal + Normativa de alimentación animal

## Limitaciones

1. La app ayuda a detectar y priorizar señales, pero no sustituye validación experta.
2. La calidad del resultado depende de la disponibilidad pública de las fuentes.
3. Algunas fuentes web pueden cambiar estructura y requerir ajustes futuros.
4. No incorpora todavía fuentes internas privadas.

## Estructura mínima del repositorio

```text
.
├── main.py
├── requirements.txt
└── README.md
```

## Ejecución local

```bash
pip install -r requirements.txt
streamlit run main.py
```
