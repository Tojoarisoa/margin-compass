"""EV-06 step 3c: real AG-03 graph runs for the golden scenarios (PLAN.md §9, M4-05).

The rubric (`ev06.task_success`) and the judge (`ev06_judge`) default to each scenario's recorded outcome,
which only 13 of the 40 scenarios have. `graph_runner` drives the deployed graph (`run.ask`: intake, route,
specialist, verify, responder) on the scenario's question instead, with one model client per scenario, and
returns the run in the shape both scorers read (route, tools, status, answer, ledger).

Status mapping: `verified` and `needs_approval` are answered, `blocked` is blocked, everything else
(withheld, failed, capped) is `unverified` with no answer, so a capped or unverified run never passes an
answerable scenario (fail closed). A run with no route (ambiguous) reports route `unverified`.

`run_graph` replays recorded fixtures ($0, CI), records them (live Bedrock through the ops workflow, one
fixture per scenario in `golden/ev06_graph_fixtures/<model>/`) or runs live. Budget caps apply per scenario
as in production (`QuestionBudget`); no actions are proposed, as in the deployed API.

Step 3c-3b: the specialists get `search_knowledge` (AG-04 leak, AG-07 contract_policy) over a local index of
`knowledge/` built in memory with the deterministic hashing embedder (no network, $0). A replayed run whose
recorded requests no longer match (for example after the tool list changed) scores as a `drifted` fail
instead of aborting the replay; re-record to clear it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .ev06 import ev06
from .ev06_judge import judgeable, recorded
from .ev_scenarios import load_scenarios

FIXTURES = Path(__file__).resolve().parent.parent / "golden" / "ev06_graph_fixtures"
KNOWLEDGE = Path(__file__).resolve().parents[2] / "knowledge"
_ANSWERED = ("verified", "needs_approval")


def knowledge_tool(knowledge_dir: Path = KNOWLEDGE) -> Any:
    """`search_knowledge` over an in-memory hashing index of `knowledge_dir` (local, deterministic)."""
    from mc_rag import BM25Index, HashingEmbedder, LocalVectorStore, index_corpus, load_corpus
    from mc_rag.embed import DIMENSIONS

    from .tools import registry

    if not Path(knowledge_dir).is_dir():
        raise FileNotFoundError(f"knowledge corpus not found at {knowledge_dir}")
    embedder, store = HashingEmbedder(), LocalVectorStore(DIMENSIONS)
    index_corpus(Path(knowledge_dir), embedder, store)
    return registry.search_knowledge_spec(embedder=embedder, store=store, bm25=BM25Index(load_corpus(Path(knowledge_dir))))


def graph_runner(make_client: Callable[[str], Any], gold_dir: Path, model_key: str = "haiku-4-5",
                 knowledge_dir: Path = KNOWLEDGE) -> Callable[[dict[str, Any]], dict[str, Any]]:
    from .approvals import MemoryStore
    from .budget import BudgetExceeded, QuestionBudget
    from .config import MODELS
    from .graph import GraphState
    from .llm import BudgetedLLM, FixtureDrift
    from .run import ask
    from .tools import registry

    spec = MODELS[model_key]
    extra = {"query_gold": registry.query_gold_spec(gold_dir), "search_knowledge": knowledge_tool(knowledge_dir)}

    def run(sc: dict[str, Any]) -> dict[str, Any]:
        state = GraphState(sc["question"])
        llm = BudgetedLLM(make_client(sc["id"]), QuestionBudget(spec))
        drifted = False
        try:
            out = ask(sc["question"], llm, spec.target, run_id=f"ev06-{sc['id']}", approval_store=MemoryStore(),
                      extra=extra, state=state)
            status = "answered" if out["status"] in _ANSWERED else out["status"]
        except BudgetExceeded:  # capped: fails closed
            status = "unverified"
        except FixtureDrift:  # replay no longer matches the recording: fails closed, reported as drifted
            status, drifted = "unverified", True
        if status not in ("answered", "blocked"):
            status = "unverified"
        route = "blocked" if status == "blocked" else (state.route or "unverified")
        tools = list(dict.fromkeys(e.tool.split("@")[0] for e in state.ledger.entries))  # ledger keeps name@version
        return {"route": route, "tools": tools, "status": status, "drifted": drifted,
                "answer": state.answer if status == "answered" else "", "ledger": state.ledger}

    return run


def default_scenarios(include_unrecorded: bool = False) -> list[dict[str, Any]]:
    """The scenarios with no recorded outcome (the judge's `not_judged` list). Replay skips the ones marked
    `"recorded": false` (no graph fixture yet); record and live runs include them."""
    return [s for s in load_scenarios() if not judgeable(s) and (include_unrecorded or recorded(s))]


def run_graph(gold_dir: Path, model_key: str, mode: str = "replay", fixtures_dir: Path = FIXTURES,
              live_client: Any = None, scenarios: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Rubric (step 1) over real graph runs. replay: recorded fixtures; record: live, writes fixtures; live."""
    from .config import MODELS
    from .llm import BedrockLLM, RecordingLLM, ReplayLLM
    from .specialists import PROMPT_VERSION

    spec = MODELS[model_key]
    scs = scenarios if scenarios is not None else default_scenarios(include_unrecorded=mode != "replay")
    recorders: list[tuple[str, Any]] = []

    def make_client(sid: str) -> Any:
        path = fixtures_dir / model_key / f"{sid}.json"
        if mode == "replay":
            return ReplayLLM(path)
        if mode == "record":
            rec = RecordingLLM(live_client or BedrockLLM(), path)
            recorders.append((sid, rec))
            return rec
        return live_client or BedrockLLM()

    runner = graph_runner(make_client, gold_dir, model_key)
    runs: dict[str, dict[str, Any]] = {}

    def keep(sc: dict[str, Any]) -> dict[str, Any]:
        runs[sc["id"]] = out = runner(sc)
        return out

    out = ev06(keep, scs)
    for sid, rec in recorders:
        rec.save({"scenario_id": sid, "model_id": spec.target, "prompt_version": PROMPT_VERSION})
    summary = {k: {"route": r["route"], "tools": r["tools"], "status": "drifted" if r["drifted"] else r["status"]}
               for k, r in sorted(runs.items())}
    return {**out, "model": spec.target, "mode": mode, "runs": summary,
            "drifted": sorted(k for k, r in runs.items() if r["drifted"])}
