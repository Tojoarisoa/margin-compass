"""Command line.

  uv run mc-agents ask "What was bc-t0003's AI gross margin in September 2025?"   # live Bedrock
  uv run mc-agents eval                         # replay the M1-06 set ($0, no network)
  uv run mc-agents ev                           # EV-05 harness self-check + EV-07/08/13 ($0, no network)
  uv run mc-agents ev --ev05 record             # live Bedrock: EV-05 on the model's SQL, writes fixtures
  uv run mc-agents ev --ev06 record             # live Bedrock: EV-06 LLM judge, writes fixtures
  uv run mc-agents ev --ev06-graph record       # live Bedrock: EV-06 rubric on real graph runs, writes fixtures
  uv run mc-agents eval --mode record           # live Bedrock: re-record fixtures (costs < $0.01)

Gold defaults to ../data/local/gold (run the pipeline first).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .analyst import answer_question
from .config import DEFAULT_ANALYST_MODEL, MODELS
from .evaluate import run_eval
from .llm import BedrockLLM


def run_ev(gold: Path, ev05_mode: str = "reference", model_key: str = DEFAULT_ANALYST_MODEL,
           ev06_mode: str = "rubric", ev06_graph_mode: str = "off") -> dict:
    """Deterministic scorers. EV-05 `reference` replays each golden question's reference SQL (harness
    check); `replay`/`record`/`live` score the AG-03 specialist's own SQL. EV-06 replays the golden scenarios
    through the task-success rubric; `--ev06 replay|record|live` adds the LLM judge (`ev06_judge`), which
    must pass too. `--ev06-graph replay|record|live` also scores real AG-03 graph runs on the scenarios with
    no recorded outcome (`ev06_graph`), which must pass too. EV-07 uses the supervisor fast path."""
    from . import ev05, ev06, ev_scenarios
    from .tools.sql_guard import make_query_gold

    refs = {q["question"]: q["reference_sql"] for q in ev05.load_golden()}
    out = {
        "ev05": (ev05.score(make_query_gold(gold), lambda question: refs[question]) if ev05_mode == "reference"
                 else ev05.run_model(gold, model_key, ev05_mode)),
        "ev06": ev06.ev06(),  # deterministic rubric (step 1)
        "ev07": ev_scenarios.ev07(),
        "ev08": ev_scenarios.ev08(),
        "ev13": ev_scenarios.ev13(),
    }
    if ev06_mode != "rubric":
        from .ev06_judge import run_judge
        out["ev06_judge"] = run_judge(model_key, ev06_mode)  # step 2: rubric-based LLM judge
    if ev06_graph_mode != "off":
        from .ev06_graph import run_graph
        out["ev06_graph"] = run_graph(gold, model_key, ev06_graph_mode)  # step 3c: real graph runs
    out["passed"] = all(v["passed"] for v in out.values())
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mc-agents")
    p.add_argument("--gold", type=Path, default=Path("../data/local/gold"))
    p.add_argument("--model", choices=[k for k, m in MODELS.items() if m.tier == "mid"], default=DEFAULT_ANALYST_MODEL)
    sub = p.add_subparsers(dest="cmd", required=True)
    ask = sub.add_parser("ask")
    ask.add_argument("question")
    ev = sub.add_parser("eval")
    ev.add_argument("--mode", choices=("replay", "record", "live"), default="replay")
    ev.add_argument("--out", type=Path, default=None)
    nt = sub.add_parser("nightly", help="write the daily margin brief; --live adds LLM insights (Bedrock, capped at $0.50)")
    nt.add_argument("--data-root", type=Path, default=Path("../data/local"))
    nt.add_argument("--run-id", default="manual")
    nt.add_argument("--live", action="store_true")
    evp = sub.add_parser("ev")
    evp.add_argument("--out", type=Path, default=None)
    evp.add_argument("--ev05", choices=("reference", "replay", "record", "live"), default="reference",
                     help="EV-05 SQL source: reference SQL ($0) or the model (replay $0; record/live call Bedrock)")
    evp.add_argument("--ev06", choices=("rubric", "replay", "record", "live"), default="rubric",
                     help="EV-06: deterministic rubric only ($0), or also the LLM judge (replay $0; record/live call Bedrock)")
    evp.add_argument("--ev06-graph", choices=("off", "replay", "record", "live"), default="off",
                     help="EV-06 on real graph runs for the scenarios with no recorded outcome (replay $0; record/live call Bedrock)")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    if args.cmd == "ask":
        r = answer_question(args.question, gold_dir=args.gold, client=BedrockLLM(), model_key=args.model)
        print(r.answer)
        print(r.cost_line)
        return 0 if r.status == "answered" else 1
    if args.cmd == "nightly":
        from . import nightly
        keys = nightly.write(args.data_root, args.run_id, client=BedrockLLM() if args.live else None)
        brief = json.loads((args.data_root / keys[0]).read_text())
        print(json.dumps({"live": args.live, "actions": brief["action_count"],
                          "insights": sum("insight" in a for a in brief["top_actions"])}))
        return 0
    if args.cmd == "ev":
        report = run_ev(args.gold, args.ev05, args.model, args.ev06, args.ev06_graph)
        text = json.dumps(report, indent=2)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text + "\n")
        print(json.dumps({k: (v if k == "passed" else v.get("passed")) for k, v in report.items()}))
        return 0 if report["passed"] else 1
    report = run_eval(args.gold, args.model, args.mode)
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    print(json.dumps({k: report[k] for k in ("model", "mode", "passed", "total", "rates", "cost_usd_per_question", "max_llm_calls")}))
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
