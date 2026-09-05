from src.integrations.mock_services import MockMongoCollection
from src.concurrency.atomic_lock import (
    acquire_user_processing_lock,
    release_user_processing_lock,
    check_human_intervention_or_billing,
)
from src.concurrency.idempotency import generate_idempotency_token, stable_sha256


def test_atomic_lock_acquisition_and_race_prevention():
    """Valida que dos peticiones simultáneas sobre el mismo usuario no puedan correr en paralelo."""
    col_users = MockMongoCollection([
        {
            "user_id": "lead_123",
            "client_id": "cliente_test_gym",
            "is_processing": False,
            "is_paused": False,
            "billing_paused": False
        }
    ])

    # Worker 1 adquiere el cerrojo
    doc_w1 = acquire_user_processing_lock(col_users, "lead_123", "cliente_test_gym")
    assert doc_w1 is not None
    assert doc_w1.get("is_processing") is True

    # Worker 2 intenta adquirir el cerrojo concurrentemente -> Debe ser RECHAZADO (None)
    doc_w2 = acquire_user_processing_lock(col_users, "lead_123", "cliente_test_gym")
    assert doc_w2 is None

    # Worker 1 libera el cerrojo
    release_user_processing_lock(col_users, "lead_123", "cliente_test_gym")

    # Worker 2 (o una nueva petición) ya puede adquirirlo
    doc_w3 = acquire_user_processing_lock(col_users, "lead_123", "cliente_test_gym")
    assert doc_w3 is not None
    assert doc_w3.get("is_processing") is True


def test_atomic_lock_rejects_paused_or_billing_locked_users():
    """Valida que usuarios con el bot pausado por un humano o con facturación bloqueada no sean procesados."""
    col_users = MockMongoCollection([
        {
            "user_id": "lead_paused",
            "client_id": "cliente_test_gym",
            "is_processing": False,
            "is_paused": True,
            "billing_paused": False
        },
        {
            "user_id": "lead_billing_locked",
            "client_id": "cliente_test_gym",
            "is_processing": False,
            "is_paused": False,
            "billing_paused": True
        }
    ])

    assert acquire_user_processing_lock(col_users, "lead_paused", "cliente_test_gym") is None
    assert acquire_user_processing_lock(col_users, "lead_billing_locked", "cliente_test_gym") is None
    assert check_human_intervention_or_billing(col_users, "lead_paused", "cliente_test_gym") is True


def test_sha256_idempotency_determinism():
    """Valida que la firma de idempotencia sea canónica e independiente del orden de claves en dicts."""
    payload_a = {"user_id": "123", "action": "send_link", "step": 2}
    payload_b = {"step": 2, "action": "send_link", "user_id": "123"}

    assert stable_sha256(payload_a) == stable_sha256(payload_b)

    token_1 = generate_idempotency_token("lead_123", "client_gym", "Hola, me interesa info")
    token_2 = generate_idempotency_token("lead_123", "client_gym", "Hola, me interesa info")
    assert token_1 == token_2
    assert len(token_1) == 24
