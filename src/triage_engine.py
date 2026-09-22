"""Streaming ticket-triage benchmark: the same synthetic ticket set run through
both Jev and Laya, one call per ticket, scored against known-correct labels.

Each ticket is an independent decision, so both models simply answer the exact
same state -- no path-dependency to work around. laya.presets.triage_questions()
bundles three question types at once (choice/noul/score) in a single call, so
this exercises the full shape of the typed-decision API.

`impact_scope` is added on top of the triage preset as a second, independent
score-type question (how many people the issue affects, unrelated to tone or
time pressure) -- with only one score question in the set, there's no way to
tell whether a model's weakness is specific to "frustration" or a general
pattern with score-type questions. Every level, including 0, is worded as
something present and has a matching phrase planted in the ticket, so a miss
can't be blamed on negated wording or on level 0 having nothing to match.
"""
import random
import time

from decision_models import get_model
from laya.presets import triage_questions
from ticket_gen import generate_ticket

LANES = ("jev", "laya")


def _build_questions():
    questions = dict(triage_questions())
    questions["impact_scope"] = {
        "type": "score",
        "instructions": "How many people does the issue in `message` affect?",
        "criteria": ["just the sender personally", "the sender's team", "the whole company or its customers"],
    }
    return questions


QUESTIONS = _build_questions()
N_BINS = 5
SCORE_QUESTIONS = {qid for qid, q in QUESTIONS.items() if q["type"] == "score"}


def _pick_and_confidence(ans, qtype):
    """Value the model actually predicted, and the probability mass it put on that value.

    Deliberately not the vendor's own "confidence" field -- that metric reads
    oddly near 50/50 calls. This is always "probability assigned to whatever
    ended up being predicted," consistent across choice/noul/score so
    calibration bucketing means the same thing for all three.
    """
    if qtype == "choice":
        predicted = ans["choice"]
        return predicted, ans["probabilities"].get(predicted, 0.0)
    if qtype == "noul":
        predicted = ans["noul"] >= 0.5
        return predicted, (ans["noul"] if predicted else 1.0 - ans["noul"])
    # score: the most likely rubric level. Rounding the expected value instead would
    # drag a spread-out distribution toward the middle level, even when the model's
    # own top pick is an extreme (e.g. {0: .55, 1: .32, 2: .13} -> E=0.58 -> 1).
    level, prob = max(ans["probabilities"].items(), key=lambda kv: kv[1])
    return int(level), prob


def run_triage_stream(n_tickets, emit, seed=None):
    models = {}
    for name in LANES:
        emit({"type": "status", "message": f"Loading {name}..."})
        try:
            models[name] = get_model(name)
        except Exception as exc:
            emit({"type": "model_unavailable", "model": name, "message": str(exc)})

    if not models:
        emit({"type": "error", "message": "No usable decision models available."})
        return

    rng = random.Random(seed)

    totals = {name: {qid: {"hits": 0, "n": 0} for qid in QUESTIONS} for name in models}
    calibration = {
        name: {qid: [{"hits": 0, "n": 0} for _ in range(N_BINS)] for qid in QUESTIONS}
        for name in models
    }
    score_error = {name: {qid: 0.0 for qid in SCORE_QUESTIONS} for name in models}
    disagreements = {qid: 0 for qid in QUESTIONS}
    disagreement_wins = {qid: {name: 0 for name in models} for qid in QUESTIONS}
    latency_sum = {name: 0.0 for name in models}
    latency_n = {name: 0 for name in models}

    start = time.monotonic()
    emit({"type": "benchmark_started", "tickets": n_tickets, "models": list(models.keys()),
          "questions": {qid: q["type"] for qid, q in QUESTIONS.items()}})

    for i in range(n_tickets):
        ticket = generate_ticket(rng)
        emit({
            "type": "ticket_start", "ticket": i, "total": n_tickets,
            "message": ticket["message"], "labels": ticket["labels"],
        })

        state = {"message": ticket["message"]}
        answers = {}
        latencies = {}
        for name, model in models.items():
            t0 = time.perf_counter()
            answers[name] = model.answer(state, QUESTIONS)
            latencies[name] = (time.perf_counter() - t0) * 1000
            latency_sum[name] += latencies[name]
            latency_n[name] += 1

        emit({"type": "ticket_timing", "ticket": i, "latency_ms": {n: round(v, 1) for n, v in latencies.items()}})

        for qid, qdef in QUESTIONS.items():
            qtype = qdef["type"]
            true_val = ticket["labels"][qid]
            picks = {}
            for name in models:
                ans = answers[name][qid]
                predicted, conf = _pick_and_confidence(ans, qtype)
                hit = predicted == true_val

                totals[name][qid]["n"] += 1
                totals[name][qid]["hits"] += 1 if hit else 0
                idx = min(int(conf * N_BINS), N_BINS - 1)
                calibration[name][qid][idx]["n"] += 1
                calibration[name][qid][idx]["hits"] += 1 if hit else 0
                if qtype == "score":
                    score_error[name][qid] += abs(ans["score"] - true_val)

                picks[name] = {"predicted": predicted, "hit": hit, "confidence": round(conf, 4)}

            disagree = len(set(str(p["predicted"]) for p in picks.values())) > 1
            if disagree:
                disagreements[qid] += 1
                for name, p in picks.items():
                    if p["hit"]:
                        disagreement_wins[qid][name] += 1

            emit({
                "type": "answer", "ticket": i, "question": qid, "qtype": qtype,
                "correct": true_val, "picks": picks, "disagree": disagree,
                "totals": {name: dict(totals[name][qid]) for name in models},
                "disagreements": disagreements[qid],
                "disagreement_wins": dict(disagreement_wins[qid]),
            })

        emit({"type": "ticket_done", "ticket": i})

    mean_error = {
        name: {qid: round(score_error[name][qid] / n_tickets, 4) for qid in SCORE_QUESTIONS}
        for name in models
    }
    avg_latency = {
        name: round(latency_sum[name] / latency_n[name], 1) if latency_n[name] else 0.0
        for name in models
    }

    emit({
        "type": "done",
        "elapsed": round(time.monotonic() - start, 2),
        "totals": totals,
        "calibration": calibration,
        "mean_abs_error": mean_error,
        "disagreements": disagreements,
        "disagreement_wins": disagreement_wins,
        "avg_latency_ms": avg_latency,
    })
