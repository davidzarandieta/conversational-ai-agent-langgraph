# ADR 005: Bloqueo Concurrente Atómico en MongoDB vs Infraestructura de Colas (Redis / Celery)

## Estado
**Aceptado** (Producción)

## Contexto y Planteamiento del Problema
Las APIs de mensajería social (Meta Cloud API / ManyChat) entregan los mensajes entrantes mediante webhooks HTTP asíncronos. En plataformas de mensajería como Instagram DMs o WhatsApp, los usuarios rara vez redactan un solo párrafo; suelen enviar ráfagas rápidas de 3 a 5 mensajes cortos en menos de 4 segundos:
- *"Buenas tardes"*
- *"¿Estáis aceptando clientes para pérdida de grasa?"*
- *"Es que entreno en casa"*

Cada mensaje entrante genera un webhook HTTP independiente contra la infraestructura backend. Si los workers concurrentes procesan cada webhook de manera paralela e independiente:
1. El modelo ejecuta múltiples inferencias simultáneas para el mismo usuario, duplicando o triplicando el coste de tokens.
2. Se generan respuestas cruzadas que se pisan entre sí y confunden al prospecto.
3. Se producen inconsistencias en la máquina de estados ACID en la base de datos.

Asimismo, si un coach humano abre la app móvil de Instagram y empieza a responder manualmente al lead mientras el bot está procesando el turno, el bot corre el riesgo de enviar su respuesta automática sobre la del humano (**Human Talking-Over**).

## Drivers de Decisión
- **Cero Mensajes Duplicados o Colisionados**: Garantía estricta de que solo existe una ejecución activa por lead en cualquier instante en todo el clúster de workers.
- **Deduplicación e Idempotencia**: Ráfagas de webhooks idénticos causadas por reintentos de Meta deben descartarse en `<1ms`.
- **Protección de Intervención Humana (Human-in-the-Loop)**: Capacidad de abortar el dispatch final si el estado del chat cambió mientras el LLM realizaba la inferencia.
- **Simplicidad Operativa**: Evitar la sobrecarga de mantener, monitorear y sincronizar clusters adicionales de Redis/RabbitMQ/Celery si la base de datos primaria ya provee primitivas atómicas.

## Opciones Consideradas

### Opción 1: Infraestructura de Colas Externa (Redis + Celery / SQS)
- *Ventajas*: Estándar en la industria para encolado de tareas pesadas.
- *Inconvenientes*:
  - Introduce una pieza móvil adicional sujeta a fallos de red, partición y latencia de serialización.
  - Sincronizar el estado del bloqueo distribuido con el documento del usuario en MongoDB requiere un protocolo de commit en dos fases propenso a estados zombi.

### Opción 2: Bloqueo en Memoria de Proceso (Python `asyncio.Lock`)
- *Ventajas*: Extremadamente rápido y trivial de programar.
- *Inconvenientes*: Solo funciona en un único proceso. En despliegues modernos con contenedores Docker escalados horizontalmente en Kubernetes o ECS, dos workers en contenedores distintos no comparten memoria y fallan en evitar la colisión.

### Opción 3: Bloqueo Atómico Optimista en MongoDB con `find_one_and_update` [ELEGIDA]
- *Ventajas*:
  - **Atomicidad Nativa a Nivel de Documento**: La operación `find_one_and_update` en MongoDB es atómica por diseño:
    ```python
    locked_doc = col_users.find_one_and_update(
        {"user_id": user_id, "is_processing": False, "is_paused": False},
        {"$set": {"is_processing": True, "lock_acquired_at": now()}},
        return_document=ReturnDocument.AFTER
    )
    ```
    Si dos peticiones paralelas llegan en el mismo milisegundo, la base de datos concede el lock a una sola; la segunda recibe `None` y encola su texto en el `pending_buffer` del usuario sin gastar cómputo.
  - **Idempotencia SHA-256**: Generación de un hash determinista del payload entrante para descartar reintentos en `<0.5ms`.
  - **Pre-Check de Entrega (Nodo 7 `deliver_messages`)**: Inmediatamente antes de disparar el webhook de respuesta a ManyChat, se efectúa un chequeo rápido contra MongoDB: si el humano pausó la conversación (`is_paused=True`), se aborta el envío y se libera el lock pacíficamente.
  - **Cero Infraestructura Extra**: Utiliza el clúster MongoDB existente sin necesidad de Redis.
- *Inconvenientes*: Requiere configurar un TTL index de seguridad sobre `lock_acquired_at` (ej. 45 segundos) para auto-liberar locks en caso de reinicio forzado del contenedor.

## Decisión Técnica
Se implementa el gestor de lock atómico en `src/concurrency/atomic_lock.py` y `src/concurrency/idempotency.py`, integrado en los nodos 1, 7 y 8 del StateGraph.

## Consecuencias y Métricas de Producción
- **Tasa de Colisiones**: **0.0%** en más de 500,000 eventos de webhook de Instagram procesados.
- **Ahorro de Infraestructura**: 0€ en costes de clúster Redis / RabbitMQ gestionado.
- **Protección Humana**: 0 incidencias de bot sobrescribiendo a un coach humano en producción.
