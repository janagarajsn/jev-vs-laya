import json
import os
import queue
import threading

import dotenv
from flask import Flask, Response, jsonify, render_template, request

from decision_models import get_model
from triage_engine import LANES, QUESTIONS as TRIAGE_QUESTIONS, run_triage_stream

dotenv.load_dotenv()

app = Flask(__name__)

_triage_lock = threading.Lock()
_triage_state = {"running": False, "queue": None}
MAX_TRIAGE_TICKETS = 500


@app.route("/")
def index():
    question_types = {qid: q["type"] for qid, q in TRIAGE_QUESTIONS.items()}
    return render_template("triage.html", lanes=LANES, questions=question_types)


def _run_triage(n_tickets):
    q = _triage_state["queue"]

    def emit(event):
        q.put(event)

    try:
        run_triage_stream(n_tickets, emit)
    except Exception as exc:
        emit({"type": "error", "message": str(exc)})
    finally:
        emit({"type": "stream_end"})
        _triage_state["running"] = False


@app.route("/api/triage/start", methods=["POST"])
def api_triage_start():
    data = request.get_json(force=True) or {}
    n_tickets = data.get("tickets")

    if not isinstance(n_tickets, int) or not (1 <= n_tickets <= MAX_TRIAGE_TICKETS):
        return jsonify(error=f"Ticket count must be between 1 and {MAX_TRIAGE_TICKETS}."), 400

    with _triage_lock:
        if _triage_state["running"]:
            return jsonify(error="A triage run is already in progress. Wait for it to finish."), 409
        _triage_state["running"] = True
        _triage_state["queue"] = queue.Queue()
        thread = threading.Thread(target=_run_triage, args=(n_tickets,), daemon=True)
        thread.start()

    return jsonify(ok=True)


@app.route("/api/triage/stream")
def api_triage_stream():
    q = _triage_state["queue"]
    if q is None:
        return Response("", mimetype="text/event-stream")

    def gen():
        while True:
            event = q.get()
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("type") == "stream_end":
                break

    return Response(gen(), mimetype="text/event-stream")


def _prewarm_laya():
    """Load Laya's encoder at server startup instead of on the user's first click.

    Building the ModernBERT-large encoder from config (before the downloaded checkpoint
    weights overwrite it) takes ~20s regardless of the Hugging Face cache; doing this in
    the background while the server starts hides that cost from the first triage run.
    """
    try:
        get_model("laya")
        print("[prewarm] Laya decision model loaded and ready.")
    except Exception as exc:
        print(f"[prewarm] Could not preload Laya: {exc}")


if __name__ == "__main__":
    DEBUG = True
    if not DEBUG or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        threading.Thread(target=_prewarm_laya, daemon=True).start()
    app.run(debug=DEBUG, threaded=True, port=5050)
