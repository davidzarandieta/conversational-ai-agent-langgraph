import hashlib
import json
from typing import Any, Dict


def stable_sha256(payload: Any) -> str:
    """
    Calcula un hash SHA-256 canónico y determinista a partir de cualquier estructura
    serializable en JSON (ordenando claves de diccionarios).
    """
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def generate_idempotency_token(
    user_id: str, 
    client_id: str, 
    message_text: str, 
    inbound_timestamp: str = ""
) -> str:
    """
    Genera un token de deduplicación de 24 caracteres a partir de la firma del mensaje.
    Permite descartar reintentos idénticos enviados en ventanas de tiempo de red cortas.
    """
    seed = f"{client_id}:{user_id}:{message_text.strip()}:{inbound_timestamp}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
