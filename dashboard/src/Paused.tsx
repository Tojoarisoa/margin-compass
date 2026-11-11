// Kill-switch notice (PLAN.md §11.3; docs/runbooks/kill-switch-game-day.md, gap G1 step 1).
// Reads publish/latest/kill_switch.json when it exists ({"active": true, "since": "<ISO time>"}); the switch's
// handler writes it and removes it when lifted. Missing or unreadable file = no notice: the static site never depends on it.
import { useEffect, useState } from "react";

export interface KillSwitchFlag { active?: boolean; since?: string }

export function isPaused(flag: unknown): boolean {
  return typeof flag === "object" && flag !== null && (flag as KillSwitchFlag).active === true;
}

export function PausedNotice() {
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    fetch("/publish/latest/kill_switch.json", { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d: unknown) => setPaused(isPaused(d)))
      .catch(() => setPaused(false));
  }, []);
  if (!paused) return null;
  return (
    <div className="banner" role="status">
      <strong>The analyst is paused for now.</strong> The dashboard figures stay available; questions will work again later.
    </div>
  );
}
