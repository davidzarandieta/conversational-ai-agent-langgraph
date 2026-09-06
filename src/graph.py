"""
LangGraph Orchestration Graph for Conversational AI Agent (Reference Implementation).

This graph models the multi-stage decision pipeline for conversational agents:
1. validate_preconditions: Billing verification, user exclusion check, and bot sleep schedule.
2. preprocess_media: Audio transcription (Whisper) and image processing (Vision).
3. run_ai_brain: Claude Sonnet 5 invocation with ephemeral prompt caching.
4. apply_guardrails: Tone, forbidden characters, and blocked error phrases.
5. enforce_booking_rules: Deterministic Calendly/booking link verification & injection.
6. deliver_messages: Human-in-the-loop intervention check & messaging dispatch.
7. persist_state_and_schedule: Conversation history, state transition, and follow-up scheduling.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import re

from langgraph.graph import StateGraph, START, END

from .state import SetterState
from .guardrails.booking import (
    ensure_booking_link_message,
    message_has_url,
    detect_explicit_booking_confirmation,
    detect_contextual_booking_confirmation,
)
from .guardrails.safety import (
    apply_style_and_safety_guardrails,
    contains_blocked_fallback_phrase,
)
from .parsers.json_cascade import parse_json_from_model_output


# ==============================================================================
# SERVICIOS POR DEFECTO (Mockeables / Sobrescribibles en Producción o Testing)
# ==============================================================================

class _DummyCol:
    def find_one(self, *args, **kwargs):
        return None
    def find_one_and_update(self, *args, **kwargs):
        return None
    def update_one(self, *args, **kwargs):
        return None

col_clients = _DummyCol()
col_users = _DummyCol()

def sync_client_billing_cycle(profile: dict) -> dict:
    return profile

def compute_billing_status(profile: dict) -> dict:
    billing = profile.get("billing", {})
    is_active = billing.get("status") == "active"
    return {"is_locked": not is_active}

def activate_billing_lock_for_client(client_id: str) -> None:
    pass

def is_user_excluded(profile: dict, username: str) -> bool:
    excluded = profile.get("excluded_users", [])
    return username in excluded

def is_bot_sleeping(profile: dict) -> bool:
    return False

def get_primary_booking_link(offer_mechanics: dict) -> str:
    return offer_mechanics.get("booking_link", "")

def utc_now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"

async def unified_media_processor(input_text: str) -> str:
    return input_text

async def run_ai_brain(
    user_input: str,
    client_profile: dict,
    profile_context: str,
    history_for_ai: list,
    user: dict = None,
    usage_client_id: str = "",
    usage_weight: float = 1.0,
    usage_source: str = "live"
) -> dict:
    """Mock/Fallback por defecto si no está parcheado externamente."""
    return {
        "content_array": ["Hola, encantado de saludarte. ¿Cómo te puedo ayudar hoy?"],
        "estado_conversacion": "2",
        "send_booking_link": False,
        "nuevos_aprendizajes": "Lead interesado en servicios",
        "skip_reply": False
    }

async def send_manychat_messages(client_profile: dict, user_id: str, messages: list) -> bool:
    return True

def build_next_followup_schedule_update(user_doc, client_profile, parsed_ai, sent_at_iso) -> Optional[dict]:
    return None

def should_send_stage_change_notification(client_profile, prev_stage, new_stage) -> bool:
    return False

def build_stage_change_notification_text(**kwargs) -> str:
    return ""

def send_client_telegram_notification(client_profile, text) -> None:
    pass

def should_send_booking_link_notification(client_profile, stage) -> bool:
    return False

def build_booking_notification_text(**kwargs) -> str:
    return ""

def send_client_booking_notification(client_profile, text) -> None:
    pass

def _recent_role_messages(history: list, role: str, limit: int = 2) -> list:
    out = []
    for m in reversed(history or []):
        if isinstance(m, dict) and m.get("role") == role:
            out.append(str(m.get("content", "")))
            if len(out) >= limit:
                break
    out.reverse()
    return out


# ==============================================================================
# NODOS DEL GRAFO
# ==============================================================================

# --- NODO 1: VALIDACIÓN DE PRECONDICIONES (SALDO, EXCLUSIÓN, SUEÑO) ---
async def validate_preconditions_node(state: SetterState) -> Dict[str, Any]:
    """
    Comprueba las precondiciones antes de invocar el motor cognitivo:
    - Saldo y ciclo de facturación del cliente (Zero Token Waste).
    - Lista de exclusión del usuario / leads bloqueados.
    - Horario de descanso (modo sueño) del bot.
    Si alguna falla, libera el lock atómico en MongoDB y marca should_abort=True.
    """
    user_id = state.get("user_id", "")
    client_id = state.get("client_id", "")
    username = state.get("username", "")
    combined_input_text = state.get("combined_input_text", "")

    # 1. Obtener o refrescar el perfil del cliente
    client_profile = state.get("client_profile") or col_clients.find_one({"client_id": client_id})
    if not client_profile:
        col_users.update_one({"user_id": user_id, "client_id": client_id}, {"$unset": {"is_processing": ""}})
        return {"should_abort": True, "abort_reason": "client_not_found", "is_processing": False}

    # 2. Comprobar facturación y saldo de mensajes
    client_profile = sync_client_billing_cycle(client_profile)
    billing_status = compute_billing_status(client_profile)
    if billing_status.get("is_locked", False):
        activate_billing_lock_for_client(client_id)
        col_users.update_one(
            {"user_id": user_id, "client_id": client_id},
            {
                "$set": {"is_processing": False, "billing_paused": True},
                "$unset": {"response_at": ""},
                "$push": {"pending_buffer": combined_input_text},
            }
        )
        return {"should_abort": True, "abort_reason": "billing_locked", "is_processing": False}

    # 3. Comprobar lista negra / exclusiones
    if is_user_excluded(client_profile, username):
        col_users.update_one(
            {"user_id": user_id, "client_id": client_id},
            {
                "$set": {"is_processing": False, "pending_buffer": [], "is_excluded": True},
                "$unset": {"response_at": ""},
            }
        )
        return {"should_abort": True, "abort_reason": "user_excluded", "is_processing": False}

    # 4. Comprobar horario de sueño del bot
    if is_bot_sleeping(client_profile):
        retry_at = datetime.now() + timedelta(minutes=5)
        col_users.update_one(
            {"user_id": user_id, "client_id": client_id},
            {
                "$set": {"response_at": retry_at.isoformat(), "is_processing": False},
                "$push": {"pending_buffer": combined_input_text}
            }
        )
        return {
            "should_abort": True, 
            "is_sleeping": True, 
            "abort_reason": "bot_sleeping", 
            "is_processing": False
        }

    # 5. Precondiciones superadas
    return {
        "client_profile": client_profile,
        "should_abort": False,
        "is_sleeping": False
    }


def route_after_preconditions(state: SetterState) -> str:
    """Enrutador condicional: Aborta inmediatamente o avanza al preprocesador."""
    if state.get("should_abort"):
        return "abort"
    return "continue"


# --- NODO 2: PREPROCESAMIENTO MULTIMEDIA (AUDIO Y VISIÓN) ---
async def preprocess_media_node(state: SetterState) -> Dict[str, Any]:
    """
    Inspecciona si el mensaje contiene URLs de audio (Whisper) o imágenes (Vision).
    Si es texto plano, no incurre en sobrecoste de red y lo transfiere intacto.
    """
    input_text = state.get("combined_input_text") or state.get("incoming_text", "")
    try:
        processed_input = await unified_media_processor(input_text)
        if isinstance(processed_input, str):
            return {
                "processed_input": processed_input,
                "combined_input_text": processed_input
            }
        return {"processed_input": processed_input}
    except Exception:
        return {"processed_input": input_text}


# --- NODO 3: MOTOR DE IA (LLM CON PROMPT CACHING Y RESILIENCIA) ---
async def run_ai_brain_node(state: SetterState) -> Dict[str, Any]:
    """
    Invoca el motor cognitivo Claude Sonnet 5 con caché efímera de Anthropic.
    Si proviene de un fallo previo de JSON, inyecta dinámicamente la directiva de corrección.
    """
    client_id = state.get("client_id", "")
    user_id = state.get("user_id", "")
    client_profile = state.get("client_profile", {})
    user_doc = state.get("user_doc", {})
    
    user_input = state.get("processed_input") or state.get("combined_input_text") or state.get("incoming_text", "")
    history = state.get("history") or user_doc.get("history", [])
    history_for_ai = list(history) if isinstance(history, list) else []
    
    retry_instruction = state.get("retry_instruction")
    if retry_instruction and isinstance(user_input, str):
        user_input = f"{user_input}\n\n[SISTEMA DE REPARACIÓN]: {retry_instruction}"

    attempts = state.get("llm_attempts", 0) + 1

    try:
        ai_result = await run_ai_brain(
            user_input,
            client_profile,
            "Contexto de negocio",
            history_for_ai,
            user=user_doc,
            usage_client_id=client_id,
            usage_weight=1.0,
            usage_source="live"
        )
        
        if ai_result.get("billing_limited", False):
            activate_billing_lock_for_client(client_id)
            col_users.update_one(
                {"user_id": user_id, "client_id": client_id},
                {
                    "$set": {"is_processing": False, "billing_paused": True},
                    "$unset": {"response_at": ""},
                }
            )
            return {
                "should_abort": True,
                "abort_reason": "billing_limited",
                "is_processing": False,
                "llm_attempts": attempts
            }

        if ai_result.get("internal_error", False):
            return {
                "should_abort": True,
                "abort_reason": ai_result.get("error_detail", "Error en proveedor LLM"),
                "is_processing": False,
                "llm_attempts": attempts
            }

        return {
            "parsed_ai_output": ai_result,
            "ai_content_array": ai_result.get("content_array", []),
            "current_stage": str(ai_result.get("estado_conversacion", state.get("current_stage", "1"))),
            "send_booking_link": bool(ai_result.get("send_booking_link", False)),
            "new_learnings": str(ai_result.get("nuevos_aprendizajes") or "").strip() or None,
            "llm_attempts": attempts,
            "should_abort": False,
            "needs_retry": False
        }

    except Exception as exc:
        return {
            "should_abort": True,
            "abort_reason": str(exc),
            "is_processing": False,
            "llm_attempts": attempts
        }


def route_after_ai_brain(state: SetterState) -> str:
    """Enrutador condicional tras inferencia: Aborta si falló cuota/API."""
    if state.get("should_abort"):
        return "abort"
    return "continue"


# --- NODO 4: APLICAR GUARDRAILS DE ESTILO Y SEGURIDAD ---
async def apply_guardrails_node(state: SetterState) -> Dict[str, Any]:
    """
    Aplica filtros deterministas de estilo, eliminación de signos prohibidos (¿, ¡)
    y bloqueo estricto de frases de fallback técnico.
    """
    ai_content_array = state.get("ai_content_array") or state.get("content_array", [])
    if isinstance(ai_content_array, str):
        ai_content_array = [ai_content_array]
        
    client_profile = state.get("client_profile", {})
    sanitized_messages = apply_style_and_safety_guardrails(ai_content_array, client_profile)

    return {
        "ai_content_array": sanitized_messages
    }


# --- NODO 5: ASEGURAR ENLACE DE RESERVA (CALENDLY GUARDRAIL) ---
async def enforce_booking_rules_node(state: SetterState) -> Dict[str, Any]:
    """
    Garantiza que si el LLM activó `send_booking_link=True` o prometió un enlace,
    la URL de reserva quede inyectada físicamente sin alucinaciones.
    """
    content_array = state.get("ai_content_array", [])
    send_booking = state.get("send_booking_link", False)
    client_profile = state.get("client_profile", {})
    
    booking_link = get_primary_booking_link(client_profile.get("offer_mechanics", {}))
    final_messages, booking_link_ready = ensure_booking_link_message(
        content_array, 
        send_booking, 
        booking_link
    )
    
    booking_link_sent = False
    if booking_link_ready:
        if booking_link:
            booking_link_sent = any(booking_link in str(msg or "") for msg in final_messages)
        else:
            booking_link_sent = any(message_has_url(msg) for msg in final_messages)
            
    return {
        "ai_content_array": final_messages,
        "booking_link_ready": booking_link_ready,
        "booking_link_sent": booking_link_sent
    }


# --- NODO 6: ENTREGA DE MENSAJES CON DETECCIÓN DE INTERVENCIÓN HUMANA ---
async def deliver_messages_node(state: SetterState) -> Dict[str, Any]:
    """
    Chequeo de concurrencia crítico antes de disparar a la API de mensajería:
    Si el entrenador o un humano pausó el chat (`is_paused=True`) durante el tiempo
    que tardó el LLM en responder, se cancela el envío para no sobrescribir al humano.
    """
    user_id = state.get("user_id", "")
    client_id = state.get("client_id", "")
    username = state.get("username", "")
    client_profile = state.get("client_profile", {})
    ai_content_array = state.get("ai_content_array", [])

    latest_state = col_users.find_one(
        {"user_id": user_id, "client_id": client_id},
        {"_id": 0, "is_paused": 1, "billing_paused": 1}
    )
    if latest_state and (latest_state.get("is_paused", False) or latest_state.get("billing_paused", False)):
        col_users.update_one(
            {"user_id": user_id, "client_id": client_id},
            {"$set": {"is_processing": False}, "$unset": {"response_at": ""}}
        )
        return {
            "human_intervened": True,
            "should_abort": True,
            "abort_reason": "human_intervention_paused",
            "is_processing": False,
            "delivery_success": False
        }

    if not ai_content_array:
        return {
            "delivery_success": True,
            "human_intervened": False
        }

    try:
        await send_manychat_messages(client_profile, user_id, ai_content_array)
        return {
            "delivery_success": True,
            "human_intervened": False,
            "should_abort": False
        }
    except Exception as exc:
        return {
            "delivery_success": False,
            "should_abort": True,
            "abort_reason": f"Delivery error: {exc}"
        }


def route_after_delivery(state: SetterState) -> str:
    """Enrutador condicional: Si hubo intervención humana o fallo de envío, aborta."""
    if state.get("should_abort") or not state.get("delivery_success"):
        return "abort"
    return "continue"


# --- NODO 7: PERSISTENCIA EN MONGODB Y GESTIÓN DE ETAPAS ---
async def persist_state_and_schedule_node(state: SetterState) -> Dict[str, Any]:
    """
    Persiste en base de datos el nuevo estado de la conversación, actualiza el histórico,
    libera el bloqueo atómico (`is_processing=False`) y notifica al cliente si hubo agendamiento.
    """
    user_id = state.get("user_id", "")
    client_id = state.get("client_id", "")
    username = state.get("username", "")
    client_profile = state.get("client_profile", {})
    user_doc = state.get("user_doc", {})
    combined_input_text = state.get("combined_input_text", "")
    ai_content_array = state.get("ai_content_array", [])
    current_stage = state.get("current_stage", "1")
    previous_stage = state.get("previous_stage", user_doc.get("estado_conversacion", "1"))
    parsed_ai = state.get("parsed_ai_output", {})
    booking_link_sent = state.get("booking_link_sent", False)
    
    sent_at_iso = utc_now_iso()
    inbound_ts = str(user_doc.get("last_interaction", "") or "").strip() or sent_at_iso
    history = state.get("history") or user_doc.get("history", [])
    
    new_history = list(history) + [
        {"role": "user", "content": combined_input_text, "timestamp": inbound_ts},
        {"role": "assistant", "content": " ".join(ai_content_array), "timestamp": sent_at_iso}
    ]

    col_users.update_one(
        {"user_id": user_id, "client_id": client_id},
        {
            "$set": {
                "history": new_history,
                "estado_conversacion": current_stage,
                "summary": parsed_ai.get("analisis_psicologico", user_doc.get("summary", "")),
                "last_interaction": sent_at_iso,
                "is_processing": False,
            }
        }
    )

    if booking_link_sent:
        col_users.update_one(
            {"user_id": user_id, "client_id": client_id},
            {"$set": {"booking_link_sent_at": sent_at_iso}}
        )
        col_clients.update_one({"client_id": client_id}, {"$addToSet": {"excluded_users": username}})

    return {
        "history": new_history,
        "is_processing": False
    }


# ==============================================================================
# CONSTRUCCIÓN Y COMPILACIÓN DEL GRAFO (LANGGRAPH)
# ==============================================================================
def build_setter_graph():
    workflow = StateGraph(SetterState)

    # 1. Registrar todos los nodos
    workflow.add_node("validate_preconditions", validate_preconditions_node)
    workflow.add_node("preprocess_media", preprocess_media_node)
    workflow.add_node("run_ai_brain", run_ai_brain_node)
    workflow.add_node("apply_guardrails", apply_guardrails_node)
    workflow.add_node("enforce_booking_rules", enforce_booking_rules_node)
    workflow.add_node("deliver_messages", deliver_messages_node)
    workflow.add_node("persist_state_and_schedule", persist_state_and_schedule_node)

    # 2. Conectar el flujo mediante aristas fijas y condicionales
    workflow.add_edge(START, "validate_preconditions")

    # Condicional 1: Precondiciones superadas
    workflow.add_conditional_edges(
        "validate_preconditions",
        route_after_preconditions,
        {
            "continue": "preprocess_media",
            "abort": END
        }
    )

    # Preprocesamiento multimedia -> Inferencia
    workflow.add_edge("preprocess_media", "run_ai_brain")

    # Condicional 2: Inferencia válida vs Aborto por cuota/API
    workflow.add_conditional_edges(
        "run_ai_brain",
        route_after_ai_brain,
        {
            "continue": "apply_guardrails",
            "abort": END
        }
    )

    # Guardrails -> Inyección de Booking -> Entrega
    workflow.add_edge("apply_guardrails", "enforce_booking_rules")
    workflow.add_edge("enforce_booking_rules", "deliver_messages")

    # Condicional 3: Intervención humana concurrente
    workflow.add_conditional_edges(
        "deliver_messages",
        route_after_delivery,
        {
            "continue": "persist_state_and_schedule",
            "abort": END
        }
    )

    # Persistencia final y finalización del turno
    workflow.add_edge("persist_state_and_schedule", END)

    return workflow.compile()


setter_graph = build_setter_graph()
