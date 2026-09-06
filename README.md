# Conversational AI agent architecture

Reference implementation extracted and sanitized from a production conversational AI system — LangGraph orchestration, deterministic guardrails, and the concurrency handling that a real messaging integration ends up needing.

**[Try the interactive demo →](https://davidzarandieta.github.io/conversational-ai-agent-langgraph/)**

## Why this exists

Once you put an LLM behind a real messaging channel (WhatsApp, Instagram DMs), a handful of problems show up that a simple prompt-and-response loop doesn't handle:

- The model says "here's my link" and then doesn't actually include the URL.
- A user replies "yes" to something completely unrelated to booking, and a naive system reads that as confirmation and sends a link it shouldn't.
- Two messages arrive close together (or a webhook retries), and both get processed at the same time for the same user.
- The model wraps its JSON in markdown, or uses a smart quote instead of a straight one, and `json.loads()` blows up.

None of these are exotic edge cases — they're just what happens once real users are typing into the thing. This repo is the part of the system built to handle them: a LangGraph state machine with deterministic checks sitting around the model, instead of trusting the model to get every detail right on its own.

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

open docs/index.html


Or just open the [deployed version](https://davidzarandieta.github.io/conversational-ai-agent-langgraph/).

## Structure

├── src/
│ ├── state.py # SetterState (TypedDict)
│ ├── graph.py # nodes and conditional edges
│ ├── guardrails/
│ │ ├── booking.py # confirmation detection + link injection
│ │ └── safety.py # style/content filters
│ ├── parsers/
│ │ └── json_cascade.py # JSON extraction and repair
│ ├── concurrency/
│ │ ├── atomic_lock.py
│ │ └── idempotency.py
│ └── integrations/
│ └── mock_services.py # in-memory adapters for tests
│
├── tests/
│ ├── test_harness.py # the 4 core scenarios
│ ├── test_guardrails.py
│ ├── test_json_cascade.py
│ └── test_concurrency.py
│
├── docs/
│ ├── architecture-diagram.svg
│ └── index.html
│
├── pytest.ini
└── requirements.txt


## Running it

No external MongoDB instance or API keys needed — everything's mocked for testing.

git clone https://github.com/davidzarandieta/conversational-ai-agent-langgraph.git
cd conversational-ai-agent-langgraph
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. pytest -v


## About the sanitization

This is a cleaned-up version of a real system running in production with a paying customer. Client name, phone numbers, booking URLs, and anything specific to their business have been replaced with generic fixtures ("Alpha Coaching", `cliente_test_gym`, a fake Calendly link). The architecture and the bugs it fixes are real; the business details aren't.

Shared for portfolio and evaluation purposes. See [`LICENSE`](LICENSE) — please don't reuse the code commercially without asking first.

## Author

David Zarandieta Ortiz — [GitHub](https://github.com/davidzarandieta)
