# Jev vs Laya — Ticket Triage Benchmark

A small Flask app that runs the same stream of synthetic customer-support tickets through two typed-decision ("System-1") models side by side, scores both against known-correct labels, and shows the results live in the browser.

| Model | Where it runs | Package |
|-------|---------------|---------|
| **Jev** | Cloud API from [typesafe.ai](https://console.typesafe.ai) | `jev` (imported as `typesafe_sdk`) |
| **Laya** | Locally, weights from Hugging Face ([`convaiinnovations/laya-typed-decisions`](https://huggingface.co/convaiinnovations/laya-typed-decisions)) | `laya` |

Each ticket is generated with its correct labels already known, so the accuracy numbers are exact and don't depend on anyone's judgement.

## Features

- **Live head-to-head scoreboard**: overall accuracy, average confidence and average latency for each model.
- **Per-question breakdown**: accuracy for each question, how often the two models disagreed, and which model was right when they did.
- **Live ticket feed**: every ticket, what each model predicted, and the correct answer. You can filter by question type (`choice` / `noul` / `score`).
- **Calibration and error data**: the final `done` event reports confidence-bucketed calibration and the mean absolute error for score questions.
- **Graceful degradation**: if one model can't load (for example, no Jev API key), the benchmark still runs with the other one.

## What gets measured

Every ticket is answered with a single call per model that asks all of these typed questions at once. The first five come from `laya.presets.triage_questions()`; `urgency_level` is added in [src/triage_engine.py](src/triage_engine.py).

| Question | Type | Values |
|----------|------|--------|
| `intent` | choice | `refund`, `technical_help`, `billing_question`, `information`, `cancellation`, `other` |
| `is_urgent` | noul (yes/no probability) | true / false |
| `frustration` | score | 0 calm · 1 concerned · 2 annoyed · 3 angry |
| `urgency_level` | score | 0 no time pressure · 1 needs attention soon · 2 blocking / hard deadline |
| `refund_requested` | noul | true / false |
| `churn_risk` | noul | true / false |

How each prediction is scored:

- **choice**: the option the model picked.
- **noul**: `true` if the probability is ≥ 0.5.
- **score**: the expected value rounded to the nearest rubric level.

For calibration, "confidence" means the probability the model gave to the value it actually predicted. This is deliberately not each vendor's own `confidence` field, so the number means the same thing for all three question types.

## Project structure

```
.
├── requirements.txt
├── .env                    # API keys (not committed)
└── src/
    ├── app.py              # Flask server, API routes, Laya pre-warm on startup
    ├── decision_models.py  # Common wrapper for Jev and Laya with normalized answers
    ├── triage_engine.py    # Benchmark loop, scoring, calibration, streamed events
    ├── ticket_gen.py       # Synthetic ticket generator with known-correct labels
    ├── templates/
    │   └── triage.html     # Dashboard UI
    └── static/
        ├── style.css
        └── triage.js       # Client: starts runs, reads the SSE stream, renders results
```

## Getting started

### Prerequisites

- Python 3.10+ (developed on 3.14)
- A [typesafe.ai](https://console.typesafe.ai) API key, needed only for Jev
- A Hugging Face access token, recommended for downloading Laya's weights
- Enough disk space and RAM for a ModernBERT-large-based model; the first run downloads it

### Installation

```bash
git clone <repo-url> jev-vs-laya
cd jev-vs-laya

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### Configuration

Create a `.env` file in the project root. It is already listed in `.gitignore`.

```dotenv
# Hugging Face token used to download Laya's weights
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxx

# Required only for the Jev model. Get a key at https://console.typesafe.ai
TYPESAFE_API_KEY=xxxxxxxxxxxxxxxxxxxx
```

### Run

```bash
cd src
python app.py
```

Open **http://localhost:5050**, choose a ticket count (20 / 50 / 100 / 200) and click **Run triage benchmark**.

When the server starts, it loads Laya's encoder in the background. Building the model takes about 20 seconds, and doing it at startup means the first run doesn't have to wait for it. Look for `[prewarm] Laya decision model loaded and ready.` in the console.

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Dashboard UI |
| `POST` | `/api/triage/start` | Starts a run. Body: `{"tickets": <1–500>}`. Returns `400` for an invalid count and `409` if a run is already in progress. |
| `GET` | `/api/triage/stream` | Server-Sent Events stream of the current run |

Only one run can be active at a time.

Example:

```bash
curl -X POST localhost:5050/api/triage/start \
     -H 'Content-Type: application/json' -d '{"tickets": 20}'
curl -N localhost:5050/api/triage/stream
```

### Stream events

Each SSE message is a JSON object with a `type` field:

| `type` | When | Key fields |
|--------|------|------------|
| `status` | While models load | `message` |
| `model_unavailable` | A model failed to load | `model`, `message` |
| `benchmark_started` | Run begins | `tickets`, `models`, `questions` |
| `ticket_start` | Each ticket | `ticket`, `total`, `message`, `labels` |
| `ticket_timing` | After both models answer | `latency_ms` per model |
| `answer` | For each question on each ticket | `question`, `qtype`, `correct`, `picks`, `disagree`, `totals`, `disagreements`, `disagreement_wins` |
| `ticket_done` | Ticket finished | `ticket` |
| `done` | Run finished | `elapsed`, `totals`, `calibration`, `mean_abs_error`, `disagreements`, `disagreement_wins`, `avg_latency_ms` |
| `error` | Unrecoverable failure | `message` |
| `stream_end` | Always sent last | — |

## How the synthetic tickets are built

[src/ticket_gen.py](src/ticket_gen.py) builds each message by picking from separate phrase banks for intent, refund request, churn threat, urgency and frustration. The bank a phrase came from **is** its label, so the correct answers are known without any manual labelling. The result still reads like a normal support email:

> Hi team, We were charged twice for our Pro plan last cycle. Please look into the duplicate charge. Please refund the charge as soon as possible. This needs to be resolved today. I'm getting pretty frustrated with these repeated issues. Thanks,

Low-stakes intents (`information`, `other`) never include urgency, refund or churn phrases, and they skew toward low frustration.

## Extending

- **Add a question**: add it to `_build_questions()` in `triage_engine.py` and produce a matching label in `generate_ticket()`.
- **Add a model**: subclass `DecisionModel` in `decision_models.py`, return answers in the normalized shape documented at the top of that file, register it in `get_model()`, and add its name to `LANES`. The template and `triage.js` currently assume the two lanes `jev` and `laya`.
- **Reproducible runs**: `run_triage_stream()` accepts a `seed` argument.

## Troubleshooting

- **"Jev needs a TYPESAFE_API_KEY"**: add the key to `.env` and restart the server. The benchmark keeps running with Laya only.
- **Slow first run / "Could not preload Laya"**: check your network connection and `HF_TOKEN`. The model is downloaded into the Hugging Face cache the first time.
- **"A triage run is already in progress"**: wait for the current run to finish. Only one run is allowed at a time.
- **Port 5050 already in use**: change `port=` at the bottom of `src/app.py`.

## Tech stack

Flask 3.1 · python-dotenv · `laya` 0.3.5 · `jev` 0.3.0 · vanilla JavaScript with Server-Sent Events
