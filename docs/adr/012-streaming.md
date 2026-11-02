# ADR-012: Streaming: Lambda Web Adapter behind CloudFront, polling fallback

- **Status:** Proposed
- **Date:** 2026-11-02
- **Related:** PLAN.md §10.1, ADR-006, VER-07, VER-08

## Context

Agent answers should stream to the browser. Python Lambdas don't stream natively, and the API sits behind CloudFront with OAC.

## Decision

- The agent API runs in a Python container with the **Lambda Web Adapter**, exposed through a **function URL (`AWS_IAM`, `RESPONSE_STREAM`)** behind CloudFront **OAC**.
- The browser client computes the SHA-256 of each POST body and sends it as **`x-amz-content-sha256`** (required by OAC for Lambda).
- A **polling fallback** (start job, poll status) ships from M1-07 regardless.

## Alternatives

| Option | Why not |
| --- | --- |
| WebSockets (API Gateway) | More moving parts and per-message cost |
| API Gateway REST streaming | Extra service and cost; CloudFront is already the single entry point |
| Lambda Web Functions | New AWS option for serverless HTTP servers with its own CloudFront OAC setup; pricing and free tier not yet checked. Evaluate in the M1-07 spike |

## Consequences

- **Open:** end-to-end streaming through an OAC-signed CloudFront origin; spike in M1-07. If it fails, polling becomes the default.
- **Revisit after** the M1-07 spike.

## Cost impact

$0 within Lambda (100 GB streaming free) and CloudFront allowances.

## Verified on

2026-11-02 (VER-07, VER-08): Python needs Lambda Web Adapter; OAC requires `AWS_IAM` and the payload-hash header on POST.
