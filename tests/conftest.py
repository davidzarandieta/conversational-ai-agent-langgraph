import os
import pytest

# Variables de entorno dummy para garantizar tests herméticos y sin fugas
os.environ.setdefault("JWT_SECRET", "test-secret-key-32-chars-long-123456")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy-key")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017/")
os.environ.setdefault("COOKIE_SECURE", "false")


@pytest.fixture
def default_client_profile() -> dict:
    """Perfil de cliente de referencia para Alpha Coaching."""
    return {
        "client_id": "cliente_test_gym",
        "business_name": "Alpha Coaching",
        "identity_core": {
            "forbidden_words": ["¿", "¡"],
            "coach_name": "Alex"
        },
        "refinements": [
            "empezar con mayuscula",
            "no usar punto al final"
        ],
        "offer_mechanics": {
            "booking_link": "https://calendly.com/alpha-coaching/30min",
            "consultation_name": "Sesión de Valoración 1 a 1"
        },
        "billing": {"status": "active"},
        "timezone": "Europe/Madrid",
        "excluded_users": []
    }


@pytest.fixture
def create_base_state(default_client_profile):
    """Fábrica de estados iniciales para el grafo."""
    def _create(user_input: str, overrides: dict = None) -> dict:
        state = {
            "user_id": "lead_instagram_123",
            "client_id": "cliente_test_gym",
            "username": "lead_test",
            "incoming_text": user_input,
            "combined_input_text": user_input,
            "client_profile": default_client_profile.copy(),
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
            "is_processing": True,
            "should_abort": False,
        }
        if overrides:
            state.update(overrides)
        return state
    return _create
