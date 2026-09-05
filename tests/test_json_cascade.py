import pytest
from src.parsers.json_cascade import (
    _strip_markdown_json_fence,
    _extract_json_object_candidates,
    _try_parse_model_json,
    parse_json_from_model_output,
)


def test_strip_markdown_json_fence():
    """Valida eliminación de delimitadores markdown envolventes de LLMs."""
    raw_with_json = "```json\n{\"content_array\": [\"Hola\"]}\n```"
    assert _strip_markdown_json_fence(raw_with_json) == "{\"content_array\": [\"Hola\"]}"

    raw_plain_block = "```\n{\"test\": 123}\n```"
    assert _strip_markdown_json_fence(raw_plain_block) == "{\"test\": 123}"

    raw_no_block = "{\"clean\": true}"
    assert _strip_markdown_json_fence(raw_no_block) == "{\"clean\": true}"


def test_extract_json_object_candidates_with_conversational_filler():
    """Valida extracción de JSON balanceado rodeado de texto conversacional no estructurado."""
    noisy_llm_response = (
        "¡Por supuesto! Aquí tienes el análisis y la respuesta generada:\n\n"
        "{\n"
        '  "content_array": ["¡Genial! Te cuento.", "¿Cuántos días entrenas?"],\n'
        '  "estado_conversacion": "2",\n'
        '  "send_booking_link": false\n'
        "}\n\n"
        "Quedo atento a si necesitas ajustar algo más."
    )

    candidates = _extract_json_object_candidates(noisy_llm_response)
    assert len(candidates) == 1
    parsed = _try_parse_model_json(candidates[0])
    assert parsed is not None
    assert parsed["estado_conversacion"] == "2"
    assert len(parsed["content_array"]) == 2


def test_try_parse_model_json_with_trailing_commas_and_smart_quotes():
    """Valida resiliencia ante comas sobrantes y comillas tipográficas generadas por LLMs."""
    payload_with_trailing_comma = '{"content_array": ["Hola",], "send_booking_link": true,}'
    parsed = _try_parse_model_json(payload_with_trailing_comma)
    assert parsed is not None
    assert parsed["send_booking_link"] is True

    payload_with_smart_quotes = '“content_array”: [“Hola qué tal”], “estado_conversacion”: “3”'
    full_payload = '{' + payload_with_smart_quotes + '}'
    parsed_quotes = _try_parse_model_json(full_payload)
    assert parsed_quotes is not None
    assert parsed_quotes["estado_conversacion"] == "3"


def test_parse_json_from_model_output_full_cascade():
    """Valida la cascada completa de parseo ante respuestas complejas o malformadas."""
    clean_markdown = "```json\n{\"content_array\": [\"Listo!\"], \"send_booking_link\": true}\n```"
    res = parse_json_from_model_output(clean_markdown)
    assert res["content_array"] == ["Listo!"]
    assert res["send_booking_link"] is True

    with pytest.raises(ValueError, match="No se pudo extraer ningún objeto JSON"):
        parse_json_from_model_output("Lo siento, no pude entender la petición.")
