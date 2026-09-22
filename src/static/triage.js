(function () {
  const LANES = ["jev", "laya"];
  const NAME = { jev: "Jev", laya: "Laya" };
  const FRUSTRATION_LABELS = ["calm", "concerned", "annoyed", "angry"];
  const URGENCY_LABELS = ["none", "soon", "blocking"];

  const countSelect = document.getElementById("count-select");
  const typeFilterSelect = document.getElementById("type-filter");
  const runBtn = document.getElementById("run-btn");
  const errorBanner = document.getElementById("error-banner");

  const benchStatus = document.getElementById("bench-status");
  const benchProgressFill = document.getElementById("bench-progress-fill");
  const ticketLabel = document.getElementById("ticket-label");
  const ticketFeed = document.getElementById("ticket-feed");

  const scoreEls = {};
  LANES.forEach((lane) => {
    scoreEls[lane] = {
      pct: document.getElementById(`score-pct-${lane}`),
      frac: document.getElementById(`score-frac-${lane}`),
      bar: document.getElementById(`score-bar-${lane}`),
      conf: document.getElementById(`score-conf-${lane}`),
      latency: document.getElementById(`score-latency-${lane}`),
    };
  });

  let selectedCount = 50;
  let running = false;
  let eventSource = null;
  let totalTickets = 0;
  let feedCount = 0;

  let questionIds = [];
  let questionTypes = {};
  let typeFilter = "all";
  const qTotals = {};
  LANES.forEach((lane) => (qTotals[lane] = {}));
  const confSum = {}, confN = {}, latencySum = {}, latencyN = {};
  LANES.forEach((lane) => {
    confSum[lane] = 0; confN[lane] = 0; latencySum[lane] = 0; latencyN[lane] = 0;
  });

  let currentTicket = null;

  function setActive(group, value) {
    group.querySelectorAll(".opt").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.value === String(value));
    });
  }

  countSelect.addEventListener("click", (e) => {
    const btn = e.target.closest(".opt");
    if (!btn || running) return;
    selectedCount = parseInt(btn.dataset.value, 10);
    setActive(countSelect, selectedCount);
  });

  typeFilterSelect.addEventListener("click", (e) => {
    const btn = e.target.closest(".opt");
    if (!btn) return;
    typeFilter = btn.dataset.value;
    setActive(typeFilterSelect, typeFilter);
    applyTypeFilter();
  });

  function applyTypeFilter() {
    ticketFeed.querySelectorAll(".ticket-row").forEach((row) => {
      row.style.display = typeFilter === "all" || row.dataset.qtype === typeFilter ? "" : "none";
    });
  }

  function clearError() {
    errorBanner.classList.add("hidden");
    errorBanner.textContent = "";
  }

  function showError(message) {
    errorBanner.textContent = message;
    errorBanner.classList.remove("hidden");
  }

  function setRunning(isRunning) {
    running = isRunning;
    countSelect.querySelectorAll(".opt").forEach((b) => (b.disabled = isRunning));
    runBtn.disabled = isRunning;
    runBtn.textContent = isRunning ? "Running..." : "Run triage benchmark";
  }

  function resetUI() {
    clearError();
    benchStatus.textContent = "Starting...";
    benchProgressFill.style.width = "0%";
    ticketLabel.textContent = "";
    ticketFeed.innerHTML = "";
    feedCount = 0;
    currentTicket = null;

    questionIds.forEach((qid) => {
      LANES.forEach((lane) => (qTotals[lane][qid] = { hits: 0, n: 0 }));
      const jevCell = document.getElementById(`q-${qid}-jev-acc`);
      const layaCell = document.getElementById(`q-${qid}-laya-acc`);
      const disCell = document.getElementById(`q-${qid}-disagree`);
      const h2hCell = document.getElementById(`q-${qid}-h2h`);
      if (jevCell) jevCell.textContent = "—";
      if (layaCell) layaCell.textContent = "—";
      if (disCell) disCell.textContent = "0";
      if (h2hCell) h2hCell.textContent = "—";
    });

    LANES.forEach((lane) => {
      confSum[lane] = 0; confN[lane] = 0; latencySum[lane] = 0; latencyN[lane] = 0;
      scoreEls[lane].pct.textContent = "—";
      scoreEls[lane].frac.textContent = "0 / 0 correct decisions";
      scoreEls[lane].bar.style.width = "0%";
      scoreEls[lane].conf.textContent = "—";
      scoreEls[lane].latency.textContent = "—";
    });
  }

  async function run() {
    resetUI();
    setRunning(true);

    let resp;
    try {
      resp = await fetch("/api/triage/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tickets: selectedCount }),
      });
    } catch (err) {
      showError("Could not reach the server.");
      setRunning(false);
      return;
    }

    const data = await resp.json();
    if (!resp.ok) {
      showError(data.error || "Failed to start benchmark.");
      setRunning(false);
      return;
    }

    connectStream();
  }

  function connectStream() {
    if (eventSource) eventSource.close();
    eventSource = new EventSource("/api/triage/stream");
    eventSource.onmessage = (e) => handleEvent(JSON.parse(e.data));
    eventSource.onerror = () => eventSource.close();
  }

  function updateOverallScoreboard() {
    LANES.forEach((lane) => {
      let hits = 0, n = 0;
      questionIds.forEach((qid) => {
        const t = qTotals[lane][qid];
        if (t) { hits += t.hits; n += t.n; }
      });
      const pct = n > 0 ? (hits / n) * 100 : 0;
      scoreEls[lane].pct.textContent = n > 0 ? `${pct.toFixed(1)}%` : "—";
      scoreEls[lane].frac.textContent = `${hits} / ${n} correct decisions`;
      scoreEls[lane].bar.style.width = `${pct}%`;
      scoreEls[lane].conf.textContent = confN[lane] > 0 ? `${((confSum[lane] / confN[lane]) * 100).toFixed(0)}%` : "—";
      scoreEls[lane].latency.textContent = latencyN[lane] > 0 ? `${(latencySum[lane] / latencyN[lane]).toFixed(0)}ms` : "—";
    });
  }

  function updateQuestionRow(qid) {
    LANES.forEach((lane) => {
      const t = qTotals[lane][qid];
      const cell = document.getElementById(`q-${qid}-${lane}-acc`);
      if (!cell || !t) return;
      cell.textContent = t.n > 0 ? `${((t.hits / t.n) * 100).toFixed(0)}% (${t.hits}/${t.n})` : "—";
    });
  }

  function formatPredicted(qid, value) {
    if (typeof value === "boolean") return value ? "yes" : "no";
    if (qid === "frustration" && typeof value === "number") {
      return `${value} (${FRUSTRATION_LABELS[value] || ""})`;
    }
    if (qid === "urgency_level" && typeof value === "number") {
      return `${value} (${URGENCY_LABELS[value] || ""})`;
    }
    return String(value);
  }

  function renderTicketCard(ticket) {
    const card = document.createElement("div");
    card.className = "ticket-card";

    const msg = document.createElement("div");
    msg.className = "ticket-message";
    msg.textContent = `#${ticket.index + 1}: ${ticket.message}`;
    card.appendChild(msg);

    const rows = document.createElement("div");
    rows.className = "ticket-rows";
    questionIds.forEach((qid) => {
      const answer = ticket.answers[qid];
      if (!answer) return;
      const row = document.createElement("div");
      row.className = "ticket-row";
      row.dataset.qtype = answer.qtype || questionTypes[qid] || "";
      if (typeFilter !== "all" && row.dataset.qtype !== typeFilter) row.style.display = "none";
      const qname = document.createElement("span");
      qname.className = "qname";
      qname.textContent = qid;
      row.appendChild(qname);

      LANES.forEach((lane) => {
        const p = answer.picks[lane];
        const span = document.createElement("span");
        if (p) {
          span.className = p.hit ? "pick-hit" : "pick-miss";
          const mark = p.hit ? "✓" : "✗";
          span.textContent = `${NAME[lane]}: ${formatPredicted(qid, p.predicted)} ${mark}`;
        }
        row.appendChild(span);
      });
      rows.appendChild(row);
    });
    card.appendChild(rows);

    ticketFeed.insertBefore(card, ticketFeed.firstChild);
    feedCount += 1;
    if (feedCount > 40) {
      while (ticketFeed.children.length > 40) {
        ticketFeed.removeChild(ticketFeed.lastChild);
      }
    }
  }

  function handleEvent(event) {
    switch (event.type) {
      case "status":
        benchStatus.textContent = event.message;
        break;

      case "model_unavailable":
        showError(`${NAME[event.model] || event.model} unavailable: ${event.message}`);
        break;

      case "benchmark_started":
        totalTickets = event.tickets;
        questionIds = Object.keys(event.questions);
        questionTypes = event.questions;
        questionIds.forEach((qid) => LANES.forEach((lane) => (qTotals[lane][qid] = { hits: 0, n: 0 })));
        benchStatus.textContent = `Running ${event.tickets} synthetic tickets...`;
        break;

      case "ticket_start":
        ticketLabel.textContent = `— ticket ${event.ticket + 1} / ${event.total}`;
        benchProgressFill.style.width = `${(event.ticket / event.total) * 100}%`;
        currentTicket = { index: event.ticket, message: event.message, labels: event.labels, answers: {} };
        break;

      case "ticket_timing":
        LANES.forEach((lane) => {
          const ms = event.latency_ms[lane];
          if (typeof ms === "number") {
            latencySum[lane] += ms;
            latencyN[lane] += 1;
          }
        });
        break;

      case "answer": {
        const qid = event.question;
        LANES.forEach((lane) => {
          const p = event.picks[lane];
          if (!p) return;
          qTotals[lane][qid] = event.totals[lane];
          confSum[lane] += p.confidence;
          confN[lane] += 1;
        });
        const disCell = document.getElementById(`q-${qid}-disagree`);
        if (disCell) disCell.textContent = String(event.disagreements);
        const h2hCell = document.getElementById(`q-${qid}-h2h`);
        if (h2hCell) {
          const w = event.disagreement_wins;
          h2hCell.textContent = event.disagreements > 0 ? `Jev ${w.jev} / Laya ${w.laya}` : "—";
        }
        updateQuestionRow(qid);
        updateOverallScoreboard();
        if (currentTicket && currentTicket.index === event.ticket) {
          currentTicket.answers[qid] = event;
        }
        break;
      }

      case "ticket_done":
        if (currentTicket && currentTicket.index === event.ticket) {
          renderTicketCard(currentTicket);
        }
        break;

      case "done":
        benchProgressFill.style.width = "100%";
        benchStatus.textContent = `Done: ${totalTickets} tickets in ${event.elapsed.toFixed(1)}s`;
        setRunning(false);
        break;

      case "error":
        showError(event.message);
        benchStatus.textContent = "Error";
        setRunning(false);
        break;

      case "stream_end":
        if (eventSource) eventSource.close();
        break;

      default:
        break;
    }
  }

  runBtn.addEventListener("click", run);
})();
