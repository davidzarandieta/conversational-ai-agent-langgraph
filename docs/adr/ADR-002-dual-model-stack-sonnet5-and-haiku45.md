# ADR 002: Dual-Model Stack (Claude Sonnet 5 + Claude Haiku 4.5) con Ephemeral Prompt Caching

## Estado
**Aceptado** (Producción)

## Contexto y Planteamiento del Problema
Un agente de venta consultiva para programas fitness de alto valor (€1,000 - €3,000) exige un razonamiento psicológico sumamente refinado:
- Identificación de sesgos de frustración y fracasos pasados con dietas y gimnasios.
- Manejo no agresivo de objeciones de precio.
- Transición orgánica desde el rapport hasta el agendamiento en Calendly sin sonar comercial.

Sin embargo, los usuarios en Instagram DMs se comunican con mensajes fragmentados, notas de voz y referencias elípticas (*"¿Y cuánto cuesta ese plan que dijiste?", "¿Tenéis plazas libres para el que no incluye nutrición?"*). Realizar una búsqueda vectorial RAG con frases ambiguas degrada severamente la relevancia del contexto recuperado. 

Por otro lado, invocar un modelo de frontera de gran escala para tareas auxiliares (como reescribir queries o resumir notas de voz extensas) incrementa drásticamente los costes de inferencia y la latencia perceptible por el usuario.

## Drivers de Decisión
- **Profundidad Cognitiva vs Coste**: Calidad de persuasión comercial de nivel humano en la respuesta final sin multiplicar el gasto operativo.
- **Latencia de Respuesta (TTFT)**: El usuario en Instagram espera respuestas en menos de 2-3 segundos; una cascada de múltiples LLMs lentos arruina la retención.
- **Eficiencia de Tokens**: Aprovechamiento de **Anthropic Ephemeral Prompt Caching** (bloque estático de identidad y reglas con TTL de 1 hora).

## Opciones Consideradas

### Opción 1: Modelo Único Grande (`Claude Sonnet 5` para todas las tareas)
- *Ventajas*: Menor complejidad de configuración y de código.
- *Inconvenientes*:
  - La reescritura de queries para RAG tardaría ~800ms adicionales antes de buscar en MongoDB.
  - El coste por mensaje crecería un 40% al usar Sonnet 5 para tareas puramente sintácticas.

### Opción 2: Modelo Único Pequeño (`Claude Haiku 4.5` para todo el pipeline)
- *Ventajas*: Máxima velocidad (<400ms) y coste mínimo.
- *Inconvenientes*:
  - Carece del nivel de empatía, matiz psicológico y sutileza consultiva requerida para ventas high-ticket.
  - Mayor propensión a caer en bucles de insistencia o desestimar el dolor emocional del prospecto.

### Opción 3: Arquitectura Especializada Dual-Model (`Sonnet 5` + `Haiku 4.5`) [ELEGIDA]
- *Ventajas*:
  - **Claude Haiku 4.5** (`claude-haiku-4-5-20251001`): Ejecuta la desambiguación sintáctica y expansión de queries RAG en `<180ms` a una fracción del coste.
  - **Claude Sonnet 5** (`claude-sonnet-5`): Asume el razonamiento estratégico, diagnóstico del prospecto y generación del array de mensajes.
  - **Anthropic Ephemeral Prompt Caching**: El bloque del prompt estático (manual del entrenador, límites éticos, catálogo) se cachea, alcanzando un **91.2% de descuento en tokens de entrada** y reduciendo el TTFT de 1.45s a **680ms**.
- *Inconvenientes*: Requiere orquestar llamadas asíncronas independientes dentro del grafo.

## Decisión Técnica
Se implementa la distribución multi-modelo en los nodos de LangGraph:
1. `retrieve_rag_context` (Nodo 3): Invoca a `Claude Haiku 4.5` para generar `rag_query` libre de elipsis previa búsqueda vectorial.
2. `run_ai_brain` (Nodo 4): Invoca a `Claude Sonnet 5` con la cabecera `cache_control={"type": "ephemeral"}` sobre el bloque de identidad y políticas del coach.

```python
# Inyección de caché efímera de Anthropic en run_ai_brain
system_prompt = [
    {
        "type": "text",
        "text": immutable_coach_handbook_and_policy,
        "cache_control": {"type": "ephemeral"}  # TTL 1 hora (91.2% ahorro)
    },
    {
        "type": "text",
        "text": f"Contexto RAG Bipolar:\n{rag_full_context}"
    }
]
```

## Consecuencias y Métricas de Producción
- **Coste por 1,000 turnos**: Reducido de $18.60 a **$2.14**.
- **Latencia p50**: Estabilizada en **680ms**.
- **Precisión RAG**: La contextualización previa con Haiku 4.5 incrementa el Mean Reciprocal Rank (MRR) en MongoDB Vector Search de 0.61 a **0.94**.
