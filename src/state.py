from typing import TypedDict, Optional, List, Dict, Any


class SetterState(TypedDict, total=False):
    """
    Estado global inmutable/acumulativo que fluye a través de los nodos de LangGraph.
    Garantiza trazabilidad completa de cada ciclo de inferencia y decisión determinista.
    """
    # Identificadores de sesión y entidad
    user_id: str
    client_id: str
    username: str

    # Carga de entrada
    incoming_text: str
    combined_input_text: str
    history: List[Dict[str, Any]]
    user_doc: Dict[str, Any]
    client_profile: Dict[str, Any]

    # Control de flujo y precondiciones
    is_processing: bool
    should_abort: bool
    abort_reason: Optional[str]
    is_sleeping: bool
    booking_link_ready: bool
    booking_link_sent: bool

    # Motor cognitivo / Inferencia
    ai_raw_response: Optional[str]
    processed_input: Optional[Any]
    parsed_ai_output: Optional[Dict[str, Any]]
    ai_content_array: List[str]
    current_stage: str
    previous_stage: str
    send_booking_link: bool
    new_learnings: Optional[str]

    # Reintentos y resiliencia de formato
    llm_attempts: int
    max_attempts: int
    needs_retry: bool
    retry_instruction: Optional[str]

    # Control de entrega y concurrencia
    human_intervened: bool
    delivery_success: bool
