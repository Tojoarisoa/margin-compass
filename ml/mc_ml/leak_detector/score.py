"""EV-03: precision, recall and MTTD of alerts against injected labels (KPI-06: P, R >= 0.8, MTTD < 24h)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .detect import Alert


@dataclass(frozen=True)
class Label:
    pattern_id: str
    start: date
    end: date | None  # None = ongoing


def score(alerts: list[Alert], labels: list[Label], tolerance_days: int = 3) -> dict:
    """An alert is a true positive when it starts within the label's span (+/- tolerance); a label is found
    by its earliest matching alert. MTTD is the mean of (detected - label start) in days over found labels."""
    def matches(a: Alert, lab: Label) -> bool:
        lo = lab.start - timedelta(days=tolerance_days)
        hi = (lab.end + timedelta(days=tolerance_days)) if lab.end else date.max
        return lo <= a.start <= hi

    tp_alerts = [a for a in alerts if any(matches(a, lab) for lab in labels)]
    found, delays = [], []
    for lab in labels:
        hits = sorted((a for a in alerts if matches(a, lab)), key=lambda a: a.detected)
        if hits:
            found.append(lab.pattern_id)
            delays.append((hits[0].detected - lab.start).days)
    precision = len(tp_alerts) / len(alerts) if alerts else 1.0
    recall = len(found) / len(labels) if labels else 1.0
    mttd = round(sum(delays) / len(delays), 2) if delays else None
    return {
        "precision": round(precision, 4), "recall": round(recall, 4), "mttd_days": mttd,
        "alerts": len(alerts), "labels": len(labels), "found": found,
        "passed": precision >= 0.8 and recall >= 0.8 and mttd is not None and mttd < 1.0 + 1e-9 if labels else False,
    }
