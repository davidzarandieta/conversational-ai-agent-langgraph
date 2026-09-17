# ADR 001: LangGraph State Machine vs Linear Chains (LangChain / LlamaIndex)

## Estado
**Aceptado** (Producción)

## Contexto y Planteamiento del Problema
En el desarrollo de un agente conversacional autónomo para Instagram DMs con clientes de alto valor (High-Ticket Fitness Coaching), la arquitectura de orquestación debe manejar:
1. **Flujos No Lineales**: Precondiciones que abortan el flujo antes de la llamada al modelo (control de facturación y descanso nocturno).
2. **Ciclos de Auto-Reparación**: Reintentos con inyección de directivas de corrección cuando el LLM emite JSON no conforme o truncado.
3. **Condiciones de Carrera**: Interrupción inmediata del envío si un agente humano interviene en el chat mientras el LLM computa la respuesta.
4. **Estado Tipado e Inmutable**: Trazabilidad completa de la mutación de estado a través de cada nodo.

Las abstracciones secuenciales tradicionales (como `RunnableSequence` de LangChain o pipelines lineales de LlamaIndex) asumen grafos dirigidos acíclicos (DAGs) puramente hacia adelante. En producción, forzar reintentos o bifurcaciones tempranas en cadenas lineales conduce a anidamientos de callbacks opacos y gestión de estado implícita y frágil.

## Drivers de Decisión
- **Cero Desperdicio de Tokens (Zero Token Waste)**: Capacidad de bifurcar y abortar antes del nodo de inferencia en <2ms.
- **Resiliencia de Parsing JSON**: Capacidad de crear bucles de auto-reparación cíclicos con contador de reintentos explícito (`llm_attempts <= max_attempts`).
- **Observabilidad y Depuración**: Cada transición de nodo debe generar un diff de estado serializable e inspeccionable.
- **Separación de Responsabilidades**: Desacoplar la inferencia cognitiva de las mutaciones con efectos secundarios (DB, WhatsApp/Instagram APIs).

## Opciones Consideradas

### Opción 1: Cadena Lineal Convencional (LangChain LCEL / SequentialChain)
- *Ventajas*: Rápido de prototipar con pocas líneas de código.
- *Inconvenientes*:
  - No soporta bucles nativos de reintento entre nodos.
  - El estado intermedio se pasa por convención o diccionarios no tipados.
  - Abortar a mitad de cadena requiere lanzar excepciones de control de flujo, ensuciando los logs de error y métricas de APM.

### Opción 2: Máquina de Estados con LangGraph (`StateGraph`) [ELEGIDA]
- *Ventajas*:
  - Grafo explícito con nodos asíncronos puros `async def node(state: SetterState) -> dict`.
  - Soporte de ciclos explícitos mediante aristas condicionales (`should_retry_or_fallback`).
  - Bifurcaciones condicionales nativas a nodos terminales de aborto (`_should_abort_preconditions`).
  - Estado fuertemente tipado mediante `TypedDict` (`SetterState`), permitiendo validación estática de tipos con `mypy`/`pyright`.
- *Inconvenientes*: Curva de aprendizaje más pronunciada y necesidad de diseñar la topología completa de antemano.

## Decisión Técnica
Se implementa la orquestación central mediante `langgraph.graph.StateGraph` utilizando `SetterState` como esquema canónico:

```python
# src/graph.py
workflow = StateGraph(SetterState)

workflow.add_node("validate_preconditions", validate_preconditions_node)
workflow.add_node("preprocess_media", preprocess_media_node)
workflow.add_node("run_ai_brain", run_ai_brain_node)
workflow.add_node("apply_guardrails", apply_guardrails_node)
workflow.add_node("enforce_booking_rules", enforce_booking_rules_node)
workflow.add_node("deliver_messages", deliver_messages_node)
workflow.add_node("persist_state_and_schedule", persist_state_and_schedule_node)
```

Las aristas condicionales gobiernan el flujo:
1. `validate_preconditions` -> Si saldo agotado o usuario pausado -> `END` (Zero Token Waste).
2. `apply_guardrails` -> Si JSON corrupto y reintentos < max -> Arista cíclica de vuelta a `run_ai_brain`.
3. `deliver_messages` -> Si se detecta intervención humana concurrente (`is_paused=True`) -> `END` sin entregar a ManyChat.

## Consecuencias y Métricas en Producción
- **Latencia**: La orquestación añade <1.5ms de overhead por turno.
- **Ahorro de Costes**: 100% de peticiones inválidas o en horas de descanso abortan con 0 tokens de inferencia.
- **Tasa de Recuperación**: El 98.4% de los JSONs defectuosos se corrigen en el ciclo de auto-reparación sin intervención humana.
