#!/usr/bin/env python3
"""Month-to-date AWS cost report for the ops workflow (one Cost Explorer call, $0.01).

Prints Markdown: cost by service (credits and refunds excluded), the budget's actual spend, and the
FOCUS export's recent executions. Exit code 0 even when Cost Explorer has no data yet, so the caller
can decide; the summary says so explicitly.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal


def aws(*args: str) -> tuple[int, str]:
    p = subprocess.run(["aws", *args, "--output", "json"], capture_output=True, text=True)
    return p.returncode, (p.stdout if p.returncode == 0 else p.stderr).strip()


def main() -> int:
    today = datetime.now(UTC).date()
    start, end = today.replace(day=1), today + timedelta(days=1)
    out = [f"## AWS cost report ({today.isoformat()} UTC)", ""]
    code, body = aws("ce", "get-cost-and-usage", "--time-period", f"Start={start},End={end}", "--granularity", "MONTHLY",
                     "--metrics", "UnblendedCost", "--group-by", "Type=DIMENSION,Key=SERVICE",
                     "--filter", json.dumps({"Not": {"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Credit", "Refund"]}}}))
    if code != 0:
        out += ["**Cost Explorer: no data** (" + body.splitlines()[-1][:200] + ")", ""]
        total = None
    else:
        rows, total = [], Decimal(0)
        for period in json.loads(body)["ResultsByTime"]:
            for g in period["Groups"]:
                amount = Decimal(g["Metrics"]["UnblendedCost"]["Amount"])
                total += amount
                if amount:
                    rows.append((g["Keys"][0], amount))
        out += [f"Month to date ({start} → {today}): **${total.quantize(Decimal('0.0001'))}** (M1 exit: < $0.50 → "
                f"{'met' if total < Decimal('0.50') else 'NOT met'})", "", "| Service | USD |", "| --- | --- |"]
        out += [f"| {k} | {v.quantize(Decimal('0.000001'))} |" for k, v in sorted(rows, key=lambda r: -r[1])] or ["| (none) | 0 |"]
        out.append("")
    code, body = aws("sts", "get-caller-identity", "--query", "Account")
    account = json.loads(body) if code == 0 else ""
    code, body = aws("budgets", "describe-budget", "--account-id", account, "--budget-name", "mc-shared-foundation-monthly-total")
    if code == 0:
        b = json.loads(body)["Budget"]
        spend = b.get("CalculatedSpend", {}).get("ActualSpend", {}).get("Amount", "?")
        out += [f"Budget actual: ${spend} of ${b['BudgetLimit']['Amount']} (last updated {b.get('LastUpdatedTime', '?')})", ""]
    code, body = aws("bcm-data-exports", "list-exports")
    if code == 0:
        for e in json.loads(body).get("Exports", []):
            c2, ex = aws("bcm-data-exports", "list-executions", "--export-arn", e["ExportArn"])
            runs = json.loads(ex).get("Executions", []) if c2 == 0 else []
            out.append(f"FOCUS export `{e.get('ExportName', '?')}`: {len(runs)} execution(s)"
                       + (f", latest {runs[0]['ExecutionStatus']['StatusCode']}" if runs else ""))
    print("\n".join(out).replace(account, "<account>") if account else "\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
