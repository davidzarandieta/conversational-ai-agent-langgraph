from typing import Optional, Dict, Any


def acquire_user_processing_lock(
    col_users: Any, 
    user_id: str, 
    client_id: str
) -> Optional[Dict[str, Any]]:
    """
    Patrón de Exclusión Mutua Atómica (Locking Optimista con find_one_and_update):
    Adquiere el cerrojo de procesamiento estableciendo `is_processing=True` en una sola
    operación atómica indivisible en MongoDB.
    
    Evita condiciones de carrera producidas por:
    - Webhooks duplicados de Instagram (doble tap o reintentos de red).
    - Múltiples workers concurrentes procesando el mismo lead en paralelo.
    """
    query = {
        "user_id": user_id,
        "client_id": client_id,
        "is_processing": {"$ne": True},
        "is_paused": {"$ne": True},
        "billing_paused": {"$ne": True},
    }
    update = {"$set": {"is_processing": True}}

    # Requiere que la colección soporte find_one_and_update (PyMongo estándar)
    return col_users.find_one_and_update(
        query,
        update,
        return_document=True
    )


def release_user_processing_lock(
    col_users: Any, 
    user_id: str, 
    client_id: str,
    extra_sets: Optional[Dict[str, Any]] = None
) -> None:
    """
    Libera el bloqueo atómico (`is_processing=False`), permitiendo futuros turnos de conversación.
    """
    payload: Dict[str, Any] = {"is_processing": False}
    if extra_sets:
        payload.update(extra_sets)
    col_users.update_one(
        {"user_id": user_id, "client_id": client_id},
        {"$set": payload}
    )


def check_human_intervention_or_billing(
    col_users: Any, 
    user_id: str, 
    client_id: str
) -> bool:
    """
    Chequeo justo antes de la entrega del mensaje:
    Verifica si durante los 2-3 segundos de inferencia del LLM, un agente humano
    entró a la conversación y activó la pausa del bot (`is_paused=True`).
    Si el humano intervino, aborta la entrega para no pisar la conversación real.
    """
    user_doc = col_users.find_one(
        {"user_id": user_id, "client_id": client_id},
        {"_id": 0, "is_paused": 1, "billing_paused": 1}
    )
    if not user_doc:
        return False
    return bool(user_doc.get("is_paused", False) or user_doc.get("billing_paused", False))
