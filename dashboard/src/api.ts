// Agent API client (ADR-012 polling flow). CloudFront OAC signs requests to the Lambda function URL,
// and for POST it needs the SHA-256 of the body in x-amz-content-sha256 (VER-08).

export interface Evidence { id: string; tool: string; args: Record<string, unknown>; result: Record<string, unknown> }
export interface Job {
  job_id: string;
  status: "pending" | "running" | "answered" | "unverified" | "budget_exceeded" | "error";
  question?: string;
  answer?: string;
  evidence?: Evidence[];
}

async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

export async function ask(question: string): Promise<string> {
  const body = JSON.stringify({ question });
  const res = await fetch("/api/ask", {
    method: "POST",
    headers: { "content-type": "application/json", "x-amz-content-sha256": await sha256Hex(body) },
    body,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status !== 202) throw new ApiError(data.error ?? `Request failed (${res.status})`, res.status);
  return data.job_id as string;
}

const TERMINAL = new Set(["answered", "unverified", "budget_exceeded", "error"]);

export async function waitForJob(jobId: string, onUpdate: (j: Job) => void, timeoutMs = 90_000): Promise<Job> {
  const started = Date.now();
  let delay = 1_000;
  while (Date.now() - started < timeoutMs) {
    await new Promise((r) => setTimeout(r, delay));
    const res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { cache: "no-store" });
    if (!res.ok) throw new ApiError(`Polling failed (${res.status})`, res.status);
    const job = (await res.json()) as Job;
    onUpdate(job);
    if (TERMINAL.has(job.status)) return job;
    delay = Math.min(delay * 1.4, 3_000);
  }
  throw new ApiError("The agent took too long to answer.", 504);
}
