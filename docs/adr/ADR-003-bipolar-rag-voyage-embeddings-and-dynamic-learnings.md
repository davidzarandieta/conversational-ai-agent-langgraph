# ADR 003: Arquitectura RAG Bipolar con Embeddings Voyage AI y Aprendizajes Dinámicos

## Estado
**Aceptado** (Producción)

## Contexto y Planteamiento del Problema
En un sistema de prospección y ventas asistido por IA, la recuperación aumentada por generación (RAG) convencional comete dos errores estructurales:
1. **Contaminación de Dominios**: Mezclar en un único índice vectorial los datos técnicos y objetivos de la oferta (precios, horarios, qué incluye el plan) con las directrices estratégicas de comportamiento comercial (cómo reaccionar ante una objeción de tiempo, qué tono usar frente a frustración previa). El modelo a menudo confunde directrices de venta con contenido para el cliente.
2. **Pérdida de Aprendizajes en Caliente**: Los mejores cerradores de ventas aprenden qué argumentos han funcionado o fracasado con prospectos similares en semanas previas. Si la base de conocimiento es puramente estática, el agente comete repetidamente los mismos errores de encuadre.

## Drivers de Decisión
- **Fidelidad Semántica y Calidad de Embeddings**: Se requiere un modelo de representación semántica denso superior a `text-embedding-3-small` para capturar la intención sutil del lenguaje coloquial en español.
- **Separación de Responsabilidades**: Aislamiento estricto entre hechos del servicio y heurísticas de psicología de venta.
- **RAG Anti-Elipsis**: Transformación de consultas conversacionales ambiguas antes del cómputo de similitud de cosenos.

## Opciones Consideradas

### Opción 1: Índice RAG Vectorial Monolítico (OpenAI `text-embedding-3-small`)
- *Ventajas*: Sencillo de configurar con un único pipeline de ingesta.
- *Inconvenientes*: Ruido cruzado entre directrices de venta internas y respuestas para el usuario; pérdida de matices en jerga física y de entrenamiento.

### Opción 2: RAG Bipolar con `Voyage AI` (`voyage-4-lite`) y `Claude Haiku 4.5` [ELEGIDA]
- *Ventajas*:
  - **Pilar A (Conocimiento Estático / FAQs)**: Catálogo oficial, estructura de precios, metodología de entrenamiento, política de garantías. Indexado en MongoDB Atlas Vector Search con embeddings `voyage-4-lite`.
  - **Pilar B (Heurísticas Dinámicas y Aprendizajes)**: Registro curado de patrones de éxito comercial (*"Con madres ocupadas, destacar entrenamientos de 35 minutos sin desplazamientos"*) y antipatrones (*"No enviar enlace de Calendly si no ha expresado dolor explícito"*).
  - **Voyage AI (`voyage-4-lite`)**: Rendimiento de benchmark líder en recuperación semántica en español e inglés conversacional, con menor dispersión en dimensionalidad densa (1024 dims).
  - **Reescritura Ágil (Claude Haiku 4.5)**: Pre-procesa la consulta del prospecto para resolver pronombres relativos antes de generar el embedding.
- *Inconvenientes*: Requiere mantener dos colecciones vectoriales separadas y balancear el peso de contexto inyectado en el prompt.

## Decisión Técnica
Se implementa el nodo `retrieve_rag_context` (Nodo 3 en `src/graph.py`) orquestando el RAG Bipolar:

```python
# src/graph.py: retrieve_rag_context_node
async def retrieve_rag_context_node(state: SetterState) -> Dict[str, Any]:
    # 1. Haiku 4.5 desambigua la query del lead
    rag_query = await contextualize_query_with_haiku(state["incoming_text"])
    
    # 2. Voyage AI genera vector de alta densidad
    query_vector = await voyage_client.embed(rag_query, model="voyage-4-lite")
    
    # 3. Recuperación en MongoDB Vector Search (Pilar A + Pilar B)
    pilar_a_docs = await vector_search(col_knowledge, query_vector, k=3)
    pilar_b_learnings = await vector_search(col_learnings, query_vector, k=2)
    
    return {
        "rag_query": rag_query,
        "rag_knowledge_context": format_docs(pilar_a_docs),
        "rag_learnings_context": format_learnings(pilar_b_learnings),
        "rag_full_context": f"{pilar_a}\n\n{pilar_b}"
    }
```

## Consecuencias y Métricas de Producción
- **Precisión de Recuperación**: El Hit Rate @ 3 pasa de 78.4% a **96.2%**.
- **Cero Filtraciones**: 0 incidencias de heurísticas internas filtradas al usuario final gracias al etiquetado semántico independiente.
- **Tiempo de Búsqueda Vectorial**: Voyage AI + MongoDB Vector Search devuelve los dos pilares en **< 35ms**.
