import re
import json
from typing import List, Optional, Dict, Any


def _strip_markdown_json_fence(text: str) -> str:
    """
    Paso 1: Elimina delimitadores markdown triples (```json ... ``` o ``` ... ```)
    si el modelo envolvió su respuesta JSON en bloques de código formateados.
    """
    clean = str(text or "").strip()
    if clean.startswith("```") and clean.endswith("```") and len(clean) >= 6:
        inner = clean[3:-3].strip()
        if inner.lower().startswith("json"):
            return inner[4:].strip()
        return inner
    return clean


def _extract_json_object_candidates(text: str) -> List[str]:
    """
    Paso 2: Máquina de estados que extrae subcadenas candidatas a objetos JSON balanceando
    llaves {} y gestionando adecuadamente cadenas entrecomilladas y caracteres de escape.
    Permite rescatar un JSON válido incluso si el modelo incluyó texto previo o posterior.
    """
    src = str(text or "")
    candidates: List[str] = []
    depth = 0
    start_idx = -1
    in_string = False
    escaped = False

    for idx, ch in enumerate(src):
        if in_string:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == "{":
            if depth == 0:
                start_idx = idx
            depth += 1
            continue

        if ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start_idx >= 0:
                candidate = src[start_idx:idx + 1].strip()
                if candidate:
                    candidates.append(candidate)
                start_idx = -1

    return candidates


def _escape_unescaped_json_controls(candidate: str) -> str:
    """
    Paso 3: Escapa saltos de línea (\n), retornos de carro (\r) y tabulaciones (\t)
    que no fueron escapados dentro de cadenas de texto en el JSON generado por el LLM.
    """
    src = str(candidate or "")
    out: List[str] = []
    in_string = False
    escaped = False

    for ch in src:
        if in_string:
            if escaped:
                out.append(ch)
                escaped = False
                continue
            if ch == "\\":
                out.append(ch)
                escaped = True
                continue
            if ch == '"':
                out.append(ch)
                in_string = False
                continue
            if ch == "\n":
                out.append("\\n")
                continue
            if ch == "\r":
                out.append("\\r")
                continue
            if ch == "\t":
                out.append("\\t")
                continue
            out.append(ch)
            continue

        out.append(ch)
        if ch == '"':
            in_string = True

    return "".join(out)


def _try_parse_model_json(candidate: str) -> Optional[dict]:
    """
    Paso 4: Intenta parsear un candidato aplicando normalización de comillas tipográficas
    (“ ” ‘ ’) y eliminando comas sobrantes antes de cierres (trailing commas).
    """
    raw = str(candidate or "").strip()
    if not raw:
        return None

    attempts = [
        raw,
        raw.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'"),
    ]

    for attempt in attempts:
        # Corrección de trailing commas: {"a": 1,} -> {"a": 1}
        trimmed = re.sub(r",\s*([}\]])", r"\1", attempt)
        escaped_controls = _escape_unescaped_json_controls(trimmed)

        for payload in [attempt, trimmed, escaped_controls]:
            try:
                parsed = json.loads(payload)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                continue

    return None


def parse_json_from_model_output(raw_text: str) -> Dict[str, Any]:
    """
    Orquestador principal de la Cascada de Parsing Resiliente:
    1. Comprueba tipos e input no vacío.
    2. Elimina delimitadores markdown ```json.
    3. Si falla json.loads directo, ejecuta la máquina de estados extractora de llaves.
    4. Aplica desinfección de comillas, comas y escapes.
    5. Devuelve el diccionario estructurado o lanza ValueError explicativo para reintento.
    """
    if not isinstance(raw_text, str):
        raise ValueError("La respuesta del modelo no es de tipo string")

    clean = _strip_markdown_json_fence(raw_text.strip())
    if not clean:
        raise ValueError("La respuesta del modelo está vacía")

    # Intentar parseo directo
    direct_parsed = _try_parse_model_json(clean)
    if isinstance(direct_parsed, dict):
        return direct_parsed

    # Cascada de extracción de candidatos
    candidates = _extract_json_object_candidates(clean)
    seen = set()
    for candidate in candidates:
        key = candidate.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        parsed = _try_parse_model_json(key)
        if isinstance(parsed, dict):
            return parsed

    raise ValueError(f"No se pudo extraer ningún objeto JSON válido de la respuesta: {raw_text[:100]}...")
