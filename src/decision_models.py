"""Unified wrapper around the two System-1 decision engines this app compares:

- Laya (convaiinnovations/laya-typed-decisions): local weights, loaded once and reused.
- Jev (typesafe.ai): a cloud API, needs TYPESAFE_API_KEY in the environment.

answer(state, questions) -> {qid: normalized_answer} answers general multi-type typed
questions (choice/score/noul in one call), e.g. laya.presets.triage_questions(),
normalized to a vendor-independent shape so callers don't need to branch on which
model answered:
    choice: {"type": "choice", "choice": str, "probabilities": {opt: float}, "confidence": float}
    score:  {"type": "score", "score": float, "legend": {lvl: str}, "probabilities": {lvl: float}, "confidence": float}
    noul:   {"type": "noul", "noul": float, "confidence": float}
"confidence" is each vendor's own reported field (Jev's noul answers don't ship one, so it's
computed the same way Laya computes its own: max(noul, 1 - noul)). Callers that want
"probability the model assigned to what it actually predicted" for calibration purposes
should derive it from probabilities/noul/score themselves -- see triage_engine.py for why
the raw vendor confidence field isn't a reliable stand-in for that.
"""
import os
import threading

_laya_agent = None
_laya_lock = threading.Lock()


def _normalize_choice(choice, probabilities, confidence):
    return {
        "type": "choice", "choice": choice,
        "probabilities": {str(k): float(v) for k, v in probabilities.items()},
        "confidence": float(confidence),
    }


def _normalize_score(score, legend, probabilities, confidence):
    return {
        "type": "score", "score": float(score),
        "legend": {str(k): v for k, v in legend.items()},
        "probabilities": {str(k): float(v) for k, v in probabilities.items()},
        "confidence": float(confidence),
    }


def _normalize_noul(noul):
    noul = float(noul)
    return {"type": "noul", "noul": noul, "confidence": round(max(noul, 1.0 - noul), 4)}


class DecisionModel:
    name = "base"

    def answer(self, state, questions):
        raise NotImplementedError


class LayaModel(DecisionModel):
    name = "laya"

    def __init__(self):
        global _laya_agent
        with _laya_lock:
            if _laya_agent is None:
                import laya
                _laya_agent = laya.load("convaiinnovations/laya-typed-decisions")
        self.agent = _laya_agent

    def answer(self, state, questions):
        result = self.agent.predict(state, questions)
        out = {}
        for qid, ans in result["answers"].items():
            if ans["type"] == "choice":
                out[qid] = _normalize_choice(ans["choice"], ans["probabilities"], ans["confidence"])
            elif ans["type"] == "score":
                out[qid] = _normalize_score(ans["score"], ans["legend"], ans["probabilities"], ans["confidence"])
            else:
                out[qid] = _normalize_noul(ans["noul"])
        return out


class JevModel(DecisionModel):
    name = "jev"

    def __init__(self):
        api_key = os.environ.get("TYPESAFE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Jev needs a TYPESAFE_API_KEY. Get one at https://console.typesafe.ai, "
                "add it to your .env file, then restart the server."
            )
        from typesafe_sdk import TypeSafeClient
        self.client = TypeSafeClient(api_key=api_key)

    def answer(self, state, questions):
        result = self.client.system_one(state=state, questions=questions)
        out = {}
        for qid, ans in result.answers.items():
            if ans.type == "choice":
                out[qid] = _normalize_choice(ans.choice, ans.probabilities, ans.confidence)
            elif ans.type == "score":
                out[qid] = _normalize_score(ans.score, ans.legend, ans.probabilities, ans.confidence)
            else:
                out[qid] = _normalize_noul(ans.noul)
        return out


def get_model(name):
    if name == "laya":
        return LayaModel()
    if name == "jev":
        return JevModel()
    raise ValueError(f"Unknown decision model: {name}")
