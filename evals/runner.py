#!/usr/bin/env python3
"""
Harness de Evals para Conversational AI Agent (NeuralSetter).
Evalúa el comportamiento end-to-end del sistema frente a escenarios curados en YAML.
Soporta modo Replay / Caché para desarrollo ágil y CI/CD (coste 0€, <0.2s)
y modo en vivo (--live) contra la API de Anthropic Claude Sonnet 5.
"""
import os
import sys
import json
import yaml
import time
import argparse
import asyncio
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from collections import defaultdict
from typing import List, Dict, Any, Tuple, Optional

# Añadir la raíz del proyecto al sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Variables de entorno por defecto para evitar fallos si no hay .env cargado
os.environ.setdefault("JWT_SECRET", "test-secret-eval-runner-12345678")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017/")
os.environ.setdefault("COOKIE_SECURE", "false")

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from src.guardrails.booking import ensure_booking_link_message
from src.graph import run_ai_brain, get_primary_booking_link

CACHE_FILE = PROJECT_ROOT / "evals" / ".cache_responses.json"
HISTORY_FILE = PROJECT_ROOT / "evals" / "history.jsonl"


@dataclass
class EvalResult:
    case_id: str
    category: str
    passed: bool
    details: str
    latency_ms: int = 0
    actual_response: Optional[Dict[str, Any]] = None


def load_fixtures(fixtures_dir: Path) -> Dict[str, Any]:
    fixtures = {}
    if not fixtures_dir.exists():
        return fixtures
    for f in fixtures_dir.glob("*.json"):
        with open(f, "r", encoding="utf-8") as fp:
            fixtures[f.name] = json.load(fp)
    return fixtures


def load_cases(cases_dir: Path, category_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    cases = []
    if not cases_dir.exists():
        return cases
    for f in sorted(cases_dir.glob("*.yaml")):
        with open(f, "r", encoding="utf-8") as fp:
            case_data = yaml.safe_load(fp)
            if category_filter and case_data.get("category") != category_filter:
                continue
            cases.append(case_data)
    return cases


def evaluate_expectations(actual_result: Dict[str, Any], expected: Dict[str, Any]) -> Tuple[bool, str]:
    """Evalúa las aserciones semánticas declaradas en el YAML."""
    checks = []
    
    # 1. Validación de send_booking_link
    if "send_booking_link" in expected:
        actual_flag = bool(actual_result.get("send_booking_link", False))
        expected_flag = bool(expected["send_booking_link"])
        passed = (actual_flag == expected_flag)
        checks.append((
            "send_booking_link", 
            passed, 
            f"esperado={expected_flag}, obtenido={actual_flag}"
        ))

    # Construir el texto unificado del mensaje final entregado
    messages = actual_result.get("content_array", [])
    full_text = " ".join(str(m) for m in messages).lower()

    # 2. Validación de textos requeridos (must_contain)
    for phrase in expected.get("must_contain", []):
        present = phrase.lower() in full_text
        checks.append((
            f"must_contain('{phrase}')", 
            present, 
            "PRESENTE" if present else f"NO ENCONTRADO en: '{full_text[:120]}...'"
        ))

    # 3. Validación de textos prohibidos (must_not_contain)
    for phrase in expected.get("must_not_contain", []):
        absent = phrase.lower() not in full_text
        checks.append((
            f"must_not_contain('{phrase}')", 
            absent, 
            "AUSENTE (OK)" if absent else f"ENCONTRADO en: '{full_text[:120]}...'"
        ))

    all_passed = all(ok for _, ok, _ in checks)
    failed_reasons = [f"{name} -> {desc}" for name, ok, desc in checks if not ok]
    details = "; ".join(failed_reasons) if failed_reasons else "Todas las aserciones pasaron"
    
    return all_passed, details


async def execute_case(
    case: Dict[str, Any], 
    client_profile: Dict[str, Any], 
    live: bool, 
    cached_responses: Dict[str, Any]
) -> EvalResult:
    case_id = case["id"]
    category = case.get("category", "general")
    history_yaml = case.get("history", [])
    current_msg = case.get("current_message", {})
    expected = case.get("expected", {})

    # Mapear roles de YAML ('lead' -> 'user', 'assistant' -> 'assistant')
    formatted_history = []
    for turn in history_yaml:
        role = "user" if turn.get("role") in ("lead", "user") else "assistant"
        formatted_history.append({"role": role, "content": turn.get("text", "")})

    user_input = current_msg.get("text", "")
    booking_link = get_primary_booking_link(client_profile.get("offer_mechanics", {}))

    start_time = time.time()
    raw_ai_result = None

    if not live and case_id in cached_responses:
        # Usar respuesta grabada (modo Replay / Caché de coste cero)
        raw_ai_result = cached_responses[case_id]
    else:
        # Ejecutar en vivo llamando al motor cognitivo
        try:
            raw_ai_result = await run_ai_brain(
                user_input=user_input,
                client_profile=client_profile,
                profile_context="Evaluación Evals Harness",
                history_for_ai=formatted_history,
                usage_client_id=client_profile.get("client_id", "eval_client"),
                usage_weight=0.0,
                usage_source="eval"
            )
            if live:
                cached_responses[case_id] = raw_ai_result
        except Exception as e:
            return EvalResult(
                case_id=case_id,
                category=category,
                passed=False,
                details=f"Error de ejecución en run_ai_brain: {e}",
                latency_ms=int((time.time() - start_time) * 1000)
            )

    latency_ms = int((time.time() - start_time) * 1000)

    # Pasar por el guardrail real de enlace post-LLM
    claude_messages = raw_ai_result.get("content_array", [])
    claude_send_booking = bool(raw_ai_result.get("send_booking_link", False))

    final_messages, _ = ensure_booking_link_message(
        content_array=claude_messages,
        send_booking=claude_send_booking,
        booking_link=booking_link
    )

    actual_system_output = {
        "send_booking_link": claude_send_booking,
        "content_array": final_messages,
        "raw_claude_messages": claude_messages,
        "estado_conversacion": raw_ai_result.get("estado_conversacion", "")
    }

    # Evaluar aserciones declaradas en el caso
    passed, details = evaluate_expectations(actual_system_output, expected)

    return EvalResult(
        case_id=case_id,
        category=category,
        passed=passed,
        details=details,
        latency_ms=latency_ms,
        actual_response=actual_system_output
    )


def print_report(results: List[EvalResult], mode: str) -> bool:
    print("\n" + "=" * 68)
    print(f" 🧪 NEURALSETTER EVALS RUNNER — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f" Modo: {'🔴 EN VIVO (Anthropic API Claude Sonnet 5)' if mode == 'live' else '🟢 REPLAY / CACHÉ (Coste 0€, <0.2s)'}")
    print("=" * 68)

    by_category = defaultdict(list)
    for r in results:
        by_category[r.category].append(r)

    total_passed = sum(1 for r in results if r.passed)
    total_cases = len(results)
    pass_rate = (total_passed / total_cases * 100) if total_cases > 0 else 0.0

    for category, cat_results in by_category.items():
        cat_passed = sum(1 for r in cat_results if r.passed)
        cat_total = len(cat_results)
        cat_rate = (cat_passed / cat_total * 100) if cat_total > 0 else 0.0
        icon = "✅" if cat_passed == cat_total else "⚠️"
        print(f"\n{icon} Categoría: {category.upper()} [{cat_passed}/{cat_total}] ({cat_rate:.1f}%)")
        print("-" * 68)

        for r in cat_results:
            status_symbol = "  ✓" if r.passed else "  ✗"
            timing = f"({r.latency_ms}ms)" if r.latency_ms > 0 else ""
            print(f"{status_symbol} {r.case_id:<18} {timing}")
            if not r.passed:
                print(f"      └─ Fallo: {r.details}")

    print("\n" + "=" * 68)
    score_color = "🎉" if total_passed == total_cases else "⚠️"
    print(f" {score_color} RESULTADO GLOBAL: {total_passed}/{total_cases} tests superados ({pass_rate:.1f}%)")
    print("=" * 68 + "\n")

    return total_passed == total_cases


def log_history(results: List[EvalResult], mode: str):
    by_category = defaultdict(list)
    for r in results:
        by_category[r.category].append(r)

    entry = {
        "timestamp": datetime.now().isoformat(),
        "mode": mode,
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "pass_rate": round(sum(1 for r in results if r.passed) / len(results), 3) if results else 0,
        "categories": {
            cat: {
                "passed": sum(1 for r in items if r.passed),
                "total": len(items),
                "rate": round(sum(1 for r in items if r.passed) / len(items), 3)
            }
            for cat, items in by_category.items()
        }
    }

    try:
        with open(HISTORY_FILE, "a", encoding="utf-8") as fp:
            fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


async def main():
    parser = argparse.ArgumentParser(description="Runner de Evals para Conversational AI Agent")
    parser.add_argument("--live", action="store_true", help="Ejecutar contra Anthropic API real en lugar de caché")
    parser.add_argument("--category", type=str, default=None, help="Filtrar por categoría (ej: guardrail_enlace)")
    parser.add_argument("--case", type=str, default=None, help="Ejecutar un caso específico por su ID")
    args = parser.parse_args()

    fixtures_dir = PROJECT_ROOT / "evals" / "fixtures"
    cases_dir = PROJECT_ROOT / "evals" / "cases"

    fixtures = load_fixtures(fixtures_dir)
    default_client = fixtures.get("client_generico.json", {})

    cases = load_cases(cases_dir, args.category)
    if args.case:
        cases = [c for c in cases if c.get("id") == args.case]

    if not cases:
        print("❌ No se encontraron casos de evaluación que coincidan con los filtros.")
        sys.exit(1)

    cached_responses = {}
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as fp:
                cached_responses = json.load(fp)
        except Exception:
            cached_responses = {}

    mode_str = "live" if args.live else "cached"
    
    if not args.live and not cached_responses:
        print("ℹ️ No existe archivo de caché (.cache_responses.json). Activando ejecución en vivo...")
        mode_str = "live"
        args.live = True

    results = []
    print(f"Cargando {len(cases)} casos dorados de evaluación...")
    for case in cases:
        fixture_name = Path(case.get("client_config", "fixtures/client_generico.json")).name
        client_cfg = fixtures.get(fixture_name, default_client)
        res = await execute_case(case, client_cfg, args.live, cached_responses)
        results.append(res)

    if args.live:
        with open(CACHE_FILE, "w", encoding="utf-8") as fp:
            json.dump(cached_responses, fp, indent=2, ensure_ascii=False)

    success = print_report(results, mode_str)
    log_history(results, mode_str)

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
