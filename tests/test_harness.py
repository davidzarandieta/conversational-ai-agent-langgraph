"""
Production Test Harness for Conversational AI Agent (LangGraph).
Validates the 4 core business and concurrency scenarios:
- Escenario 1: Flujo normal (Happy Path) -> IA responde y entrega vía ManyChat.
- Escenario 2: Inyección de Booking Link -> Enlace de Calendly garantizado determinísticamente.
- Escenario 3: Bloqueo de facturación -> Aborta sin gastar tokens de inferencia (Zero Token Waste).
- Escenario 4: Intervención humana concurrente -> Cancela la entrega si el humano intervino.
"""

import os
os.environ.setdefault("JWT_SECRET", "dummy_jwt_test_secret_for_tests")  # gitleaks:allow
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy-key")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017/")
os.environ.setdefault("COOKIE_SECURE", "false")

import asyncio
import pytest
from unittest.mock import patch, AsyncMock

from src.graph import setter_graph


# ==============================================================================
# FIXTURES Y HELPERS DE ESTADO
# ==============================================================================
DEFAULT_CLIENT_PROFILE = {
    "client_id": "cliente_test_gym",
    "business_name": "Alpha Coaching",
    "identity_core": {"forbidden_words": ["¿", "¡"]},
    "refinements": ["empezar con mayuscula"],
    "offer_mechanics": {
        "booking_link": "https://calendly.com/alpha-coaching/30min"
    },
    "billing": {"status": "active"},
    "timezone": "Europe/Madrid"
}


def build_base_state(user_input: str, overrides: dict = None) -> dict:
    state = {
        "user_id": "lead_instagram_123",
        "client_id": "cliente_test_gym",
        "username": "lead_test",
        "combined_input_text": user_input,
        "client_profile": DEFAULT_CLIENT_PROFILE.copy(),
        "user_doc": {
            "user_id": "lead_instagram_123",
            "username": "lead_test",
            "history": [],
            "estado_conversacion": "1",
            "is_processing": True
        },
        "history": [],
        "current_stage": "1",
        "previous_stage": "1",
        "llm_attempts": 0,
        "max_attempts": 3,
        "is_processing": True
    }
    if overrides:
        state.update(overrides)
    return state


# ==============================================================================
# BANCO DE PRUEBAS (LOS 4 ESCENARIOS)
# ==============================================================================

@pytest.mark.asyncio
async def test_escenario_1_happy_path():
    """Escenario 1: Conversación normal, Claude responde y ManyChat entrega."""
    print("👉 Ejecutando Escenario 1: Flujo normal (Happy Path)...")
    initial_state = build_base_state("Hola, quería saber cómo funciona vuestro plan")

    mock_claude_output = {
        "content_array": ["¡Hola! Qué tal.", "Nuestro plan es 100% personalizado según tus objetivos."],
        "estado_conversacion": "2",
        "send_booking_link": False,
        "nuevos_aprendizajes": "Interesado en saber funcionamiento general",
        "skip_reply": False
    }

    mock_brain = AsyncMock(return_value=mock_claude_output)
    mock_manychat = AsyncMock(return_value=True)

    with patch("src.graph.run_ai_brain", mock_brain), \
         patch("src.graph.send_manychat_messages", mock_manychat), \
         patch("src.graph.sync_client_billing_cycle", side_effect=lambda x: x), \
         patch("src.graph.compute_billing_status", return_value={"is_locked": False}), \
         patch("src.graph.is_user_excluded", return_value=False), \
         patch("src.graph.is_bot_sleeping", return_value=False), \
         patch("src.graph.col_users.update_one"), \
         patch("src.graph.col_users.find_one", return_value={"is_paused": False}):
        
        final_state = await setter_graph.ainvoke(initial_state)

    # Verificaciones rigurosas
    assert final_state.get("should_abort") is False, "El grafo no debió abortar"
    assert final_state.get("delivery_success") is True, "ManyChat debió entregar"
    assert final_state.get("current_stage") == "2", "Debió avanzar a etapa 2"
    mock_brain.assert_awaited_once()  # Se llamó a la IA exactamente 1 vez
    mock_manychat.assert_awaited_once()  # Se envió a ManyChat exactamente 1 vez
    print("   ✅ Escenario 1 Superado: Mensajes procesados y entregados.")


@pytest.mark.asyncio
async def test_escenario_2_booking_link_injection():
    """Escenario 2: Lead pide cita -> Se garantiza el link de Calendly en el mensaje."""
    print("👉 Ejecutando Escenario 2: Inyección de Booking Link...")
    initial_state = build_base_state("Perfecto, ¿cuándo podemos agendar una llamada?")

    mock_claude_output = {
        "content_array": ["¡Genial! Elige el hueco que mejor te venga en mi agenda."],
        "estado_conversacion": "3",
        "send_booking_link": True,
        "skip_reply": False
    }

    mock_brain = AsyncMock(return_value=mock_claude_output)
    mock_manychat = AsyncMock(return_value=True)

    with patch("src.graph.run_ai_brain", mock_brain), \
         patch("src.graph.send_manychat_messages", mock_manychat), \
         patch("src.graph.sync_client_billing_cycle", side_effect=lambda x: x), \
         patch("src.graph.compute_billing_status", return_value={"is_locked": False}), \
         patch("src.graph.is_user_excluded", return_value=False), \
         patch("src.graph.is_bot_sleeping", return_value=False), \
         patch("src.graph.col_users.update_one"), \
         patch("src.graph.col_clients.update_one"), \
         patch("src.graph.col_users.find_one", return_value={"is_paused": False}):
        
        final_state = await setter_graph.ainvoke(initial_state)

    # Verificaciones
    assert final_state.get("booking_link_sent") is True, "Debió marcarse booking_link_sent"
    mensajes = final_state.get("ai_content_array", [])
    assert any("calendly.com/alpha-coaching" in msg for msg in mensajes), "El link de Calendly debe estar inyectado"
    print("   ✅ Escenario 2 Superado: Link de reserva inyectado y detectado.")


@pytest.mark.asyncio
async def test_escenario_3_billing_lock():
    """Escenario 3: Cliente sin saldo -> Aborta de inmediato y NUNCA llama al LLM."""
    print("👉 Ejecutando Escenario 3: Bloqueo de facturación...")
    initial_state = build_base_state("Hola, ¿cuánto cuesta?")

    mock_brain = AsyncMock()

    with patch("src.graph.sync_client_billing_cycle", side_effect=lambda x: x), \
         patch("src.graph.compute_billing_status", return_value={"is_locked": True}), \
         patch("src.graph.activate_billing_lock_for_client"), \
         patch("src.graph.run_ai_brain", mock_brain), \
         patch("src.graph.col_users.update_one"):
        
        final_state = await setter_graph.ainvoke(initial_state)

    # Verificaciones: Zero Token Waste
    assert final_state.get("should_abort") is True, "El grafo debió abortar por saldo"
    assert final_state.get("abort_reason") == "billing_locked", "La razón debe ser billing_locked"
    mock_brain.assert_not_called()  # Cero llamadas y cero coste en tokens
    print("   ✅ Escenario 3 Superado: Abortó sin gastar tokens de inferencia.")


@pytest.mark.asyncio
async def test_escenario_4_human_intervention():
    """Escenario 4: Entrenador pausa el chat mientras la IA pensaba -> No envía a ManyChat."""
    print("👉 Ejecutando Escenario 4: Intervención humana concurrente...")
    initial_state = build_base_state("Hola!")

    mock_claude_output = {
        "content_array": ["¡Hola! ¿En qué te ayudo?"],
        "skip_reply": False
    }

    mock_manychat = AsyncMock()

    with patch("src.graph.run_ai_brain", AsyncMock(return_value=mock_claude_output)), \
         patch("src.graph.send_manychat_messages", mock_manychat), \
         patch("src.graph.sync_client_billing_cycle", side_effect=lambda x: x), \
         patch("src.graph.compute_billing_status", return_value={"is_locked": False}), \
         patch("src.graph.is_user_excluded", return_value=False), \
         patch("src.graph.is_bot_sleeping", return_value=False), \
         patch("src.graph.col_users.update_one"), \
         patch("src.graph.col_users.find_one", return_value={"is_paused": True}):
        
        final_state = await setter_graph.ainvoke(initial_state)

    # Verificaciones: Race Condition Handled
    assert final_state.get("human_intervened") is True, "Debió detectar intervención humana"
    assert final_state.get("should_abort") is True, "Debió abortar el envío"
    mock_manychat.assert_not_called()  # Cancelado para no pisar al humano
    print("   ✅ Escenario 4 Superado: Envío cancelado para proteger al agente humano.")


# ==============================================================================
# EJECUTOR DIRECTO (STANDALONE)
# ==============================================================================
async def main():
    print("\n🧪 ======================================================")
    print("   INICIANDO TEST HARNESS DE CONVERSATIONAL AI AGENT")
    print("======================================================\n")
    
    await test_escenario_1_happy_path()
    await test_escenario_2_booking_link_injection()
    await test_escenario_3_billing_lock()
    await test_escenario_4_human_intervention()

    print("\n🎉 ======================================================")
    print("   ¡TODOS LOS ESCENARIOS DEL HARNESS HAN PASADO AL 100%!")
    print("======================================================\n")


if __name__ == "__main__":
    asyncio.run(main())
