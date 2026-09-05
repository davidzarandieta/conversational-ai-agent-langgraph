import re
from typing import List, Dict, Any
from .booking import message_has_url


def contains_blocked_fallback_phrase(text: str) -> bool:
    """
    Detecta frases de error interno o fallback técnico que jamás deben filtrarse al lead.
    Previene que fallos de infraestructura o excepciones crudas lleguen al usuario final.
    """
    msg = str(text or "").strip().lower()
    if not msg:
        return False
    blocked_patterns = [
        r"\bno\s+pude\s+procesar\b",
        r"\bno\s+he\s+podido\s+procesar\b",
        r"\berror\s+interno\b",
        r"\bexcepci[oó]n\s+del\s+sistema\b",
        r"\blo\s+siento,\s+ha\s+ocurrido\s+un\s+error\b",
    ]
    return any(re.search(pattern, msg) for pattern in blocked_patterns)


def apply_style_and_safety_guardrails(
    messages: List[str], 
    client_profile: Dict[str, Any]
) -> List[str]:
    """
    Aplica filtros deterministas de estilo, tono y seguridad sobre las respuestas del LLM:
    1. Elimina caracteres o muletillas prohibidas (ej. signos de apertura ¿, ¡).
    2. Homogeniza mayúsculas iniciales según directivas de refinamiento.
    3. Bloquea de inmediato respuestas que contengan filtraciones de errores técnicos.
    """
    raw_array = messages if isinstance(messages, list) else [str(messages)]
    refinements = client_profile.get("refinements", [])
    refinements_text = " ".join(refinements).lower() if isinstance(refinements, list) else str(refinements).lower()
    forbidden_chars = client_profile.get("identity_core", {}).get("forbidden_words", [])

    sanitized_messages: List[str] = []
    for raw in raw_array:
        msg = str(raw or "").strip()
        if not msg:
            continue

        # 1. Filtro de caracteres prohibidos
        for forbidden in forbidden_chars:
            if forbidden in ["¿", "¡"] or len(forbidden) <= 2:
                msg = msg.replace(forbidden, "")

        # 2. Refinamiento de puntuación (ejemplo: omitir puntos finales en mensajes de chat casual)
        if "punto" in refinements_text and "no" in refinements_text and not message_has_url(msg):
            msg = msg.replace(".", "")

        msg = msg.strip()

        # 3. Mayúscula inicial si está configurada
        if "mayuscula" in refinements_text or "mayúscula" in refinements_text:
            if msg:
                msg = msg[0].upper() + msg[1:]

        # 4. Chequeo de seguridad: bloquear frases de fallback técnico
        if contains_blocked_fallback_phrase(msg):
            raise RuntimeError(f"Guardrail de seguridad activado: frase de fallback técnico detectada ('{msg}')")

        sanitized_messages.append(msg)

    return sanitized_messages
