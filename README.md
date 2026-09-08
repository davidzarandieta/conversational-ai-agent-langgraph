# Conversational AI agent architecture

Reference implementation extracted and sanitized from a production conversational AI system — LangGraph orchestration, deterministic guardrails, and the concurrency handling that a real messaging integration ends up needing.

**[Try the interactive demo →](https://davidzarandieta.github.io/conversational-ai-agent-langgraph/)**

## What this is

A conversational AI agent that runs a business's lead qualification over a messaging channel (Instagram DMs) — it holds a conversation, adapts its tone and goals to whatever the business configures, and decides when it's appropriate to hand over a booking link, without a human in the loop for every message.

Structurally, it's a LangGraph state machine sitting between the messaging webhook and the LLM call. The state (`SetterState`) carries the conversation history, the client's configuration, and the model's output through a fixed set of nodes: check preconditions (billing, sleep hours, human pause) → compose context → call the model → parse and validate the output → apply guardrails → decide on booking → deliver or abort.

The core design principle is that the LLM only ever *proposes*. Anything with a side effect — sending a message, sending a booking link, advancing the conversation stage — goes through a deterministic check outside the model before it happens. The model doesn't have write access to anything on its own.

Context is split into a stable part (the client's configuration, tone, rules) and a dynamic part (the conversation so far), so the expensive, rarely-changing part can be cached instead of resent on every turn.

## Architecture

![Architecture diagram](docs/architecture-diagram.svg)

## Design decisions

| Piece | What I did | What I didn't do | Why |
|---|---|---|---|
| Orchestration | `StateGraph` with 7 nodes | One long linear function | A messaging agent isn't linear — it needs retry loops, conditional branches (billing, sleep hours), and typed state that's explicit instead of implicit |
| Booking guardrail | Two deterministic layers (explicit confirmation + contextual history check) | Asking the model itself whether to send the link | An extra LLM call for this adds real latency and cost for something a regex and a history check handle in under 2ms |
| Link injection | A separate function inserts the real URL when `send_booking_link=True` | Letting the model write the URL from memory | Models occasionally get URLs wrong or stale; this way the actual link is always the one on file |
| JSON parsing | A cascade: strip markdown fences → extract balanced braces → repair trailing commas/smart quotes → retry | Just calling `json.loads()` and hoping | Models don't reliably produce clean JSON, especially under smaller/faster models |
| Concurrency | Atomic `find_one_and_update` lock in MongoDB | A separate queue (RabbitMQ, Celery) | Didn't want extra infrastructure just to stop two workers from grabbing the same lead at once |
| Human handoff | A check right before sending | Sending blindly | If a human takes over the chat while the model is still "thinking," the system shouldn't talk over them |
| Cost | Anthropic's prompt caching on the stable part of the context | Sending the full prompt every turn | The client config and tone rules barely change between turns — caching them cuts token cost significantly |

## Demo

`docs/index.html` is a small interactive demo, deployed via GitHub Pages. One tab is a scripted chat simulator with an "engineering view" toggle that shows which guardrail fired and why at each step; the other is a clickable version of the architecture diagram where you can click into a node and see roughly what it does.

Run it locally:

```bash
open docs/index.html
```

Or just open the [deployed version](https://davidzarandieta.github.io/conversational-ai-agent-langgraph/).

## Structure

```text
├── src/                                # Core LangGraph production architecture
│   ├── state.py                        # SetterState definition (TypedDict)
│   ├── graph.py                        # StateGraph nodes and conditional edges
│   ├── guardrails/
│   │   ├── booking.py                  # 2-layer confirmation detection + Calendly link injection
│   │   └── safety.py                   # Style guardrails, punctuation filters & error masking
│   ├── parsers/
│   │   └── json_cascade.py             # 4-stage resilient JSON extraction and self-repair
│   ├── concurrency/
│   │   ├── atomic_lock.py              # Optimistic MongoDB lock & human-in-the-loop protection
│   │   └── idempotency.py              # Canonical SHA-256 payload hashing for deduplication
│   └── integrations/
│       └── mock_services.py            # In-memory service adapters for isolated tests
│
├── tests/                              # Automated test suite (15/15 passing)
│   ├── conftest.py                     # Shared test fixtures and client mock states
│   ├── test_harness.py                 # End-to-end testing of 4 critical business scenarios
│   ├── test_guardrails.py              # Unit tests for booking detection and safety rules
│   ├── test_json_cascade.py            # Unit tests for malformed JSON parsing resilience
│   └── test_concurrency.py             # Unit tests for atomic locking and deduplication
│
├── docs/                               # Interactive visual portfolio & live web demo
│   ├── architecture-diagram.svg        # High-resolution vector architecture diagram
│   ├── index.html                      # Interactive mobile simulator & dynamic graph canvas
│   └── dashboard-app/                  # Embedded production React 19 NeuralSetter dashboard
│
├── pytest.ini                          # Test runner configuration
└── requirements.txt                    # Project dependencies
```

## Running it

No external MongoDB instance or API keys needed — everything's mocked for testing.

```bash
git clone https://github.com/davidzarandieta/conversational-ai-agent-langgraph.git
cd conversational-ai-agent-langgraph
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. pytest -v
```


## About the sanitization

This is a cleaned-up version of a real system running in production with a paying customer. Client name, phone numbers, booking URLs, and anything specific to their business have been replaced with generic fixtures ("Alpha Coaching", `cliente_test_gym`, a fake Calendly link). The architecture and the bugs it fixes are real; the business details aren't.

Shared for portfolio and evaluation purposes. See [`LICENSE`](LICENSE) — please don't reuse the code commercially without asking first.

## Author

David Zarandieta Ortiz — [GitHub](https://github.com/davidzarandieta)
