# 🧪 Harness de Evals para NeuralSetter

Conjunto de escenarios curados para evaluar el **comportamiento end-to-end del sistema conversacional** (la parte probabilística y emergente del LLM combinada con los guardrails deterministas), complementando la suite de pruebas unitarias de `pytest`.

---

## 🎯 Categorías de Evaluación

| Categoría | Casos | Qué mide | Por qué importa |
|---|---|---|---|
| **`guardrail_enlace`** | `booking_001` al `006` | Activación rigurosa del link de Calendly solo ante confirmación real, ausencia de URLs falsas y respeto a negativas. | Es la pieza de conversión más crítica: un falso positivo o enviar un link roto tiene coste directo de negocio. |
| **`robustez_manipulacion`** | `robustness_001` al `006` | Resistencia ante inyecciones de prompt (precio, JSON fingido, escape sintáctico, extracción de system prompt y manipulación emocional). | Seguridad de la aplicación y protección contra alucinaciones o rupturas de políticas comerciales. |

---

## 🚀 Cómo Ejecutar

### 1. Ejecución rápida en modo Replay / Caché (Coste 0€, latencia < 0.1s)
Usa las últimas respuestas registradas para verificar rápidamente que los matchers y el pipeline funcionan:
```bash
python3 -m evals.runner
```

### 2. Ejecución en Vivo contra Claude (Anthropic API)
Invoca al modelo real para evaluar el comportamiento estocástico frente a cambios de prompt o actualizaciones de versión:
```bash
python3 -m evals.runner --live
```

### 3. Filtrar por categoría o caso específico
```bash
# Ejecutar solo la categoría de guardrail de enlace
python3 -m evals.runner --category guardrail_enlace

# Ejecutar un caso concreto
python3 -m evals.runner --case booking_001
```

---

## 📈 Histórico y Observabilidad (`history.jsonl`)

Cada ejecución registra automáticamente una entrada en `evals/history.jsonl` con:
- `timestamp`: Momento exacto de la prueba.
- `mode`: `live` o `cached`.
- `pass_rate`: Porcentaje de éxito global.
- `categories`: Desglose de tasa de éxito por categoría.

Esto permite auditar regresiones de comportamiento a lo largo del tiempo:
> *"Al optimizar el prompt para reducir tokens, la categoría de guardrail_enlace se mantuvo al 100% y la de robustez en 6/6."*

---

## ➕ Cómo Añadir un Caso Nuevo

> **Regla de oro de ingeniería:** Cada bug real detectado en producción (un falso positivo, una alucinación o un lead que confundió al bot) debe convertirse en un caso de regresión aquí.

Crea un archivo YAML en `evals/cases/` siguiendo la estructura:
```yaml
id: booking_007
category: guardrail_enlace
description: "Breve descripción del fallo o comportamiento a evitar"
client_config: fixtures/client_generico.json
history:
  - role: lead
    text: "..."
  - role: assistant
    text: "..."
current_message:
  role: lead
  text: "..."
expected:
  send_booking_link: false
  must_not_contain: ["texto prohibido"]
  reason: "Explicación del criterio de negocio aplicado"
```
