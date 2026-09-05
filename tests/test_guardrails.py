import pytest
from src.guardrails.booking import (
    detect_explicit_booking_confirmation,
    detect_contextual_booking_confirmation,
    ensure_booking_link_message,
    message_has_url,
    message_indicates_link_delivery,
)
from src.guardrails.safety import (
    apply_style_and_safety_guardrails,
    contains_blocked_fallback_phrase,
)


def test_detect_explicit_booking_confirmation():
    """Valida detección determinista de intención de agendamiento explícita."""
    assert detect_explicit_booking_confirmation("pásame el enlace de calendly") is True
    assert detect_explicit_booking_confirmation("¿cuándo podemos agendar?") is True
    assert detect_explicit_booking_confirmation("perfecto, mándame el link para reservar cita") is True
    assert detect_explicit_booking_confirmation("me vendría bien hablarlo en una videollamada") is True
    assert detect_explicit_booking_confirmation("me encantaría agendar") is True

    # Negativos
    assert detect_explicit_booking_confirmation("hola, quería info de precios") is False
    assert detect_explicit_booking_confirmation("prefiero entrenar por las tardes en casa") is False


def test_detect_contextual_booking_confirmation():
    """Valida la prevención del 'Bug del Sí': solo activa reserva si el asistente propuso cita."""
    # Caso 1: Asistente ofreció videollamada -> Usuario responde afirmativo -> TRUE
    history_with_offer = [
        {"role": "assistant", "content": "¿Te vendría bien que agendemos una videollamada de 15 minutos para ver tu caso?"}
    ]
    assert detect_contextual_booking_confirmation(history_with_offer, "sí, perfecto") is True
    assert detect_contextual_booking_confirmation(history_with_offer, "dale") is True
    assert detect_contextual_booking_confirmation(history_with_offer, "me encantaría") is True

    # Caso 2: Asistente preguntó por hábitos -> Usuario responde afirmativo -> FALSE (¡CLAVE!)
    history_without_offer = [
        {"role": "assistant", "content": "¿Actualmente tienes dolor o alguna lesión al entrenar?"}
    ]
    assert detect_contextual_booking_confirmation(history_without_offer, "sí") is False
    assert detect_contextual_booking_confirmation(history_without_offer, "vale") is False


def test_ensure_booking_link_message():
    """Valida la inyección determinista del enlace de reserva sin duplicidades ni alucinaciones."""
    booking_link = "https://calendly.com/alpha-coaching/30min"

    # Caso 1: Se solicita link pero el LLM no lo incluyó en el texto -> Inyección garantizada
    msgs = ["¡Genial! Elige el horario que más te convenga en mi agenda."]
    result, ready = ensure_booking_link_message(msgs, send_booking=True, booking_link=booking_link)
    assert ready is True
    assert len(result) == 2
    assert booking_link in result[1]

    # Caso 2: El mensaje ya contiene el enlace -> No duplicar
    msgs_with_link = [f"Aquí tienes mi calendario: {booking_link}"]
    result2, ready2 = ensure_booking_link_message(msgs_with_link, send_booking=True, booking_link=booking_link)
    assert ready2 is True
    assert len(result2) == 1

    # Caso 3: No se solicita link -> Mantener mensajes intactos
    normal_msgs = ["Nuestro plan incluye seguimiento diario."]
    result3, ready3 = ensure_booking_link_message(normal_msgs, send_booking=False, booking_link=booking_link)
    assert ready3 is False
    assert len(result3) == 1


def test_apply_style_and_safety_guardrails():
    """Valida eliminación de caracteres prohibidos, mayúsculas iniciales y bloqueo de errores."""
    profile = {
        "identity_core": {"forbidden_words": ["¿", "¡"]},
        "refinements": ["empezar con mayuscula", "no usar punto"]
    }

    # Limpieza de signos prohibidos y mayúscula inicial
    input_msgs = ["¡hola! ¿cómo estás.", "genial."]
    cleaned = apply_style_and_safety_guardrails(input_msgs, profile)
    assert cleaned == ["Hola! cómo estás", "Genial"]

    # Bloqueo estricto de frases de fallback técnico
    with pytest.raises(RuntimeError, match="Guardrail de seguridad activado"):
        apply_style_and_safety_guardrails(["Disculpa, no pude procesar tu mensaje."], profile)
