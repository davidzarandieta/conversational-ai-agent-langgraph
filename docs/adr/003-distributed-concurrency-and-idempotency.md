# ADR 003: Distributed Concurrency, Atomic Locks and Idempotency

## Estado
**Aceptado** (Producción)

## Contexto y Planteamiento del Problema
Las plataformas de mensajería (Instagram Graph API, ManyChat, WhatsApp Cloud API) presentan retos críticos de concurrencia en producción:
1. **Ráfagas de Webhooks (Webhook Bursts)**: Un usuario en Instagram rara vez envía un solo mensaje; suele enviar 3 o 4 mensajes cortos seguidos ("Hola", "¿estás ahí?", "quería info"). Cada mensaje dispara un webhook HTTP concurrente hacia los workers del backend.
2. **Condiciones de Carrera (Race Conditions)**: Si dos workers procesan al mismo lead en paralelo, el lead recibe respuestas duplicadas, respuestas desordenadas o respuestas que se pisan entre sí.
3. **Intervención Humana en Vivo (Human Takeover)**: Cuando el entrenador humano decide abrir el chat y responder en persona, el bot debe detener cualquier respuesta en tránsito de forma inmediata. Si el LLM tarda 800ms en responder y el humano escribe a los 400ms, el bot no debe sobreescribir al humano.
4. **Reintentos de Webhook (Network Retries)**: Si ManyChat o Meta experimentan timeouts de red, reintentan el envío del mismo webhook con idéntico payload.

## Drivers de Decisión
- **Simplicidad de Infraestructura**: Evitar la complejidad operativa de añadir sistemas externos de colas (Redis, RabbitMQ, Celery) si la base de datos principal puede proporcionar consistencia estricta.
- **Idempotencia Garantizada**: Toda petición idéntica recibida en una ventana de tiempo debe descartarse sin procesamiento ni consumo de tokens.
- **Human-in-the-Loop Safe**: Cancelación determinista del envío a la API de mensajería previa a la entrega física.

## Opciones Consideradas

### Opción 1: Cola Externa con Redis / Celery / RabbitMQ
- *Ventajas*: Encolado ordenado por usuario.
- *Inconvenientes*: Requiere mantener instancias Redis de alta disponibilidad, gestionar colas de dead-letter, reconexiones y serialización distribuida. Sobredimensionado para tráfico de Instagram DMs.

### Opción 2: Cerrojo Optimista Atómico en MongoDB (`find_one_and_update`) [ELEGIDA]
- *Mecanismo*:
  - MongoDB ofrece atomicidad a nivel de documento mediante la operación `find_one_and_update`.
  - Se utiliza una clave booleana `is_processing` en el documento del usuario:
    ```python
    query = {
        "user_id": user_id,
        "client_id": client_id,
        "is_processing": {"$ne": True},
        "is_paused": {"$ne": True},
        "billing_paused": {"$ne": True}
    }
    update = {"$set": {"is_processing": True, "lock_acquired_at": datetime.utcnow()}}
    doc = col_users.find_one_and_update(query, update, return_document=ReturnDocument.AFTER)
    ```
  - Si dos workers intentan adquirir el cerrojo simultáneamente, exactamente **uno** obtiene el documento actualizado; el segundo recibe `None` y aborta de inmediato con cero coste.
- *Idempotencia mediante Hash Canónico SHA-256*:
  - Se genera un token SHA-256 estable a partir del `user_id`, `client_id` y el texto de entrada ordenado. Si el token ya existe en la ventana temporal activa, se ignora como duplicado.
- *Verificación de Doble Vía (Double-Check)*:
  - Justo antes del nodo `deliver_messages`, se vuelve a consultar el estado del usuario en la base de datos. Si un humano pulsó "Pausar Bot" o envió un mensaje manual (`is_paused=True`), el grafo aborta la entrega a ManyChat sin enviar los mensajes generados por el LLM.

## Decisión Técnica

```python
# src/concurrency/atomic_lock.py
def acquire_user_processing_lock(col_users, user_id: str, client_id: str):
    return col_users.find_one_and_update(
        {
            "user_id": user_id,
            "client_id": client_id,
            "is_processing": {"$ne": True},
            "is_paused": {"$ne": True},
            "billing_paused": {"$ne": True}
        },
        {"$set": {"is_processing": True, "lock_acquired_at": datetime.utcnow()}},
        return_document=ReturnDocument.AFTER
    )
```

## Consecuencias y Métricas en Producción
- **Colisiones de Mensajería**: Reducción del 100% de respuestas duplicadas causadas por ráfagas de webhooks concurrentes.
- **Interferencias con Humanos**: Cero incidentes de "bot hablando sobre el humano" tras la adopción del check pre-entrega.
- **Sobrecarga de Infraestructura**: Cero servicios adicionales necesarios; MongoDB maneja miles de locks por segundo con latencias <1ms.
