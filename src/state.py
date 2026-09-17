from typing import TypedDict, Optional, List, Dict, Any


class SetterState(TypedDict, total=False):
    """
    Estado global fuertemente tipado que fluye a través de los 8 nodos de LangGraph.
    Garantiza trazabilidad completa en cada ciclo de inferencia, recuperación semántica
    RAG, guardrails deterministas y control de concurrencia distribuida.
    """
    # Identificadores de sesión y entidad
    user_id: str
    client_id: str
    username: str

    # Carga entrante y multimedia (Whisper / Vision)
    incoming_text: str
    combined_input_text: str
    history: List[Dict[str, Any]]
    user_doc: Dict[str, Any]
    client_profile: Dict[str, Any]
    media_type: Optional[str]
    media_url: Optional[str]
    audio_duration: Optional[int]

    # Control de flujo y precondiciones
    is_processing: bool
    should_abort: bool
    abort_reason: Optional[str]
    is_sleeping: bool
    billing_locked: bool

    # Contexto Semántico RAG (Voyage AI + Claude Haiku 4.5)
    rag_query: Optional[str]
    rag_knowledge_context: Optional[str]
    rag_learnings_context: Optional[str]
    rag_full_context: Optional[str]

    # Motor cognitivo / Inferencia (Claude Sonnet 5)
    ai_raw_response: Optional[str]
    processed_input: Optional[Any]
    parsed_ai_output: Optional[Dict[str, Any]]
    ai_content_array: List[str]
    current_stage: str
    previous_stage: str
    send_booking_link: bool
    new_learnings: Optional[str]

    # Parseo resiliente y reintentos en cascada
    llm_attempts: int
    max_attempts: int
    needs_retry: bool
    retry_instruction: Optional[str]

    # Guardrails deterministas, entrega y concurrencia
    booking_link_ready: bool
    booking_link_sent: bool
    human_intervened: bool
    delivery_success: bool
