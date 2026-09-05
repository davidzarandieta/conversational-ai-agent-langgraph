import re
from typing import List, Dict, Any, Tuple, Optional


def message_has_url(text: str) -> bool:
    """Comprueba si el texto contiene una URL web (http o https)."""
    return bool(re.search(r"https?://\S+", str(text or "")))


def message_indicates_link_delivery(text: str) -> bool:
    """
    Detecta mediante expresiones regulares si el texto del mensaje promete
    o introduce la entrega de un enlace de reserva/llamada.
    """
    msg = str(text or "").strip().lower()
    if not msg:
        return False
    delivery_patterns = [
        r"\baqu[ií]\s+tienes?\b.{0,50}\b(link|enlace)\b",
        r"\bte\s+dejo\b.{0,50}\b(link|enlace)\b",
        r"\b(enlace|link)\b.{0,50}\b(agendar|agenda|videollamada|llamada|hueco)\b",
    ]
    return any(re.search(pattern, msg) for pattern in delivery_patterns)


def detect_explicit_booking_confirmation(text_blob: str) -> bool:
    """
    Capa 1 de Guardrail: Detección determinista de intención de agendamiento explícita.
    Analiza peticiones directas de enlace, agenda o llamada telefónica/videollamada.
    """
    text = str(text_blob or "").strip().lower()
    if not text:
        return False

    booking_intent_patterns = [
        r"\b(p[aá]same|m[aá]ndame|env[ií]ame)\b.{0,40}\b(link|enlace|calendly|agenda|reserva|cita)\b",
        r"\b(quiero|me\s+interesa|si|sí|vale|ok|perfecto|dale|de\s+acuerdo)\b.{0,40}\b(agendar|agenda|llamada|cita|reserva|link|enlace)\b",
        r"\b(cu[aá]ndo\s+podemos\s+agendar|agendamos|vamos\s+a\s+agendar)\b",
        r"\b(me\s+vendr[ií]a\s+bien)\b.{0,40}\b(cara\s+a\s+cara|hablarlo|videollamada|llamada|agendar)\b",
        r"\b(me\s+encantar[ií]a)\b.{0,40}\b(agendar|llamada|videollamada|link|enlace)\b",
    ]
    return any(re.search(pattern, text) for pattern in booking_intent_patterns)


def detect_contextual_booking_confirmation(history_messages: List[Dict[str, Any]], current_user_value: str) -> bool:
    """
    Capa 2 de Guardrail: Detección contextual de agendamiento.
    Resuelve el problema clásico de falsos positivos cuando el usuario responde 'sí' o 'de acuerdo':
    solo activa el agendamiento si el asistente propuso una llamada o videollamada en sus turnos recientes.
    """
    current_text = str(current_user_value or "").strip().lower()
    if not current_text:
        return False

    affirmative_patterns = [
        r"^\s*(si|sí|ok|vale|perfecto|genial|dale|de\s+acuerdo|claro|hacer)([\s,]+(si|sí|ok|vale|perfecto|genial|dale|de\s+acuerdo|claro|por\s+favor))*[.!?]*\s*$",
        r"\b(me\s+vendr[ií]a\s+bien)\b.{0,20}\b(cara\s+a\s+cara|hablarlo)\b",
        r"^\s*me\s+encantar[ií]a\s*[.!?]*\s*$",
    ]
    if not any(re.search(pattern, current_text) for pattern in affirmative_patterns):
        return False

    # Extraer el contenido de los últimos mensajes del asistente
    recent_assistant_text = " ".join([
        str(m.get("content", ""))
        for m in (history_messages or [])[-4:]
        if isinstance(m, dict) and m.get("role") == "assistant"
    ]).lower()

    if not recent_assistant_text:
        return False

    # Validar si el asistente había ofrecido explícitamente una llamada o enlace
    return bool(re.search(r"\b(videollamada|llamada|agendar|agenda|calendly|link|enlace|hueco)\b", recent_assistant_text))


def ensure_booking_link_message(
    content_array: List[str], 
    send_booking: bool, 
    booking_link: str
) -> Tuple[List[str], bool]:
    """
    Garantiza determinísticamente que si se activó la intención de agendamiento (send_booking=True
    o promesa en el texto), el mensaje contenga el enlace real de agenda configurado.
    Evita alucinaciones donde el LLM dice 'aquí te dejo el enlace' pero olvida incluir la URL.
    """
    messages = [str(m).strip() for m in (content_array or []) if str(m or "").strip()]
    implied_delivery = any(message_indicates_link_delivery(msg) for msg in messages)
    
    if not send_booking and not implied_delivery:
        return messages, False

    # Si ya contiene una URL válida, no duplicamos
    if any(message_has_url(msg) for msg in messages):
        return messages, True

    link = str(booking_link or "").strip()
    if not link:
        return messages, False

    # Inyección determinista
    messages.append(f"Aquí tienes el enlace para agendar: {link}")
    return messages, True
