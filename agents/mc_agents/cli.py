"""Command line.

  uv run mc-agents ask "What was bc-t0003's AI gross margin in September 2025?"   # live Bedrock
  uv run mc-agents eval                         # replay the M1-06 set ($0, no network)
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
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    if args.cmd == "ask":
        r = answer_question(args.question, gold_dir=args.gold, client=BedrockLLM(), model_key=args.model)
        print(r.answer)
        print(r.cost_line)
        return 0 if r.status == "answered" else 1
    report = run_eval(args.gold, args.model, args.mode)
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    print(json.dumps({k: report[k] for k in ("model", "mode", "passed", "total", "rates", "cost_usd_per_question", "max_llm_calls")}))
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
