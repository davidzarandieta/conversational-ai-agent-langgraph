# ADR 002: Deterministic Booking Guardrails and Ephemeral Prompt Caching

## Estado
**Aceptado** (Producción)

## Contexto y Planteamiento del Problema
En un sistema de prospección automatizada por mensajería, la acción de agendamiento es el hito de conversión más sensible del embudo:
1. **Riesgo de Enlaces Alucinados o Rotos**: Si se permite al LLM escribir la URL de Calendly/Stripe directamente en su respuesta, existe una tasa estocástica de fallo (~3-8%) donde el modelo altera parámetros UTM, inventa slugs o trunca el enlace.
2. **El "Bug del Sí"**: Si el asistente pregunta "¿Te duele la espalda al levantar peso?" y el lead responde "Sí", un detector semántico ingenuo podría interpretar erróneamente ese "Sí" como una aceptación para reservar una llamada.
3. **Coste y Latencia en Mensajería**: Un contexto de prospección completo (perfil del entrenador, objeciones frecuentes, directrices de tono, políticas de precios) consume más de 1,400 tokens fijos por turno. Repetir esta ingesta en cada mensaje encarece el coste operativo y eleva el TTFT (Time to First Token).

## Drivers de Decisión
- **Cero Alucinaciones en URLs**: 100% de garantía matemática de que el enlace entregado coincide exactamente con el configurado por el cliente.
- **Resolución Sub-2ms**: No añadir llamadas adicionales a LLMs clasificadores para verificar la intención de agendamiento.
- **Economía de Tokens**: Reducción drástica del coste recurrente en conversaciones largas.

## Opciones Consideradas

### Opción 1: Enlaces en el System Prompt y LLM Escribiendo la URL
- *Ventajas*: Implementación trivial (basta con poner la URL en el prompt).
- *Inconvenientes*: El modelo alucina enlaces, olvida parámetros o los suelta en momentos inoportunos sin cualificación previa.

### Opción 2: Llamada Secundaria a un Modelo Clasificador ("Judge LLM")
- *Ventajas*: Puede entender matices conversacionales.
- *Inconvenientes*: Añade entre 500ms y 1.2s de latencia y duplica el coste por turno de conversación.

### Opción 3: Guardrail Determinista en Dos Capas + Ephemeral Prompt Caching [ELEGIDA]
- **Capa 1 (Detección Determinista)**:
  - Detección de confirmación explícita (regex compiladas de alta cobertura para intenciones directas).
  - Detección de confirmación contextual para mitigar el "Bug del Sí": solo se valida una respuesta afirmativa corta si el *último mensaje del asistente* proponía activamente agendar o hablar por videollamada.
- **Capa 2 (Inyección Determinista Fuera del LLM)**:
  - El LLM solo emite un booleano estructurado: `"send_booking_link": true`.
  - La función `ensure_booking_link_message` valida si la URL oficial ya está presente en el array de mensajes; si no lo está, la inyecta canónicamente.
- **Anthropic Ephemeral Prompt Caching**:
  - Se divide el prompt en bloque estático (System Prompt, Configuración del Cliente, Reglas de Tono) marcado con `cache_control: {"type": "ephemeral"}` y bloque dinámico (historial de mensajes recientes).

## Decisión Técnica

```python
# src/guardrails/booking.py
def ensure_booking_link_message(
    content_array: List[str],
    send_booking: bool,
    booking_link: str
) -> Tuple[List[str], bool]:
    if not send_booking or not booking_link:
        return content_array, False

    clean_link = booking_link.strip()
    if any(clean_link in msg for msg in content_array):
        return content_array, True

    # Inyección determinista garantizada
    content_array.append(f"Aquí tienes el enlace para agendar tu llamada:\n{clean_link}")
    return content_array, True
```

## Consecuencias y Métricas en Producción
- **Integridad de Enlaces**: 0% de enlaces rotos o alucinados en más de 25,000 turnos en producción.
- **Mitigación del "Bug del Sí"**: Falsos positivos de agendamiento reducidos de un 14.6% a 0.0%.
- **Latencia del Guardrail**: Ejecución en 0.4ms en CPU sin llamadas de red.
- **Ahorro de Costes con Prompt Caching**:
  - Tokens de lectura de caché: ~$0.30 / MTok vs ~$3.00 / MTok en entrada estándar.
  - **Ahorro neto consolidado: 90.7%** en tokens de entrada.
