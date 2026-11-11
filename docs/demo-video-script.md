# Demo video script (M6-04)

Internal draft, 2026-11-11. About 5 minutes, screen recording of the public dashboard plus voice-over. The narration follows the public-surface rule (AGENTS.md §6): no project status, budgets, model names, per-answer cost, or internal IDs on screen or in the voice-over. Every number shown is read from the dashboard at recording time; this script quotes none, because the synthetic data is rebuilt nightly.

Before recording: open the dashboard in a clean browser window at 1440 px wide, scroll to the top, and check that the synthetic-data notice is visible. Record a second take at phone width for the closing shot.

| # | Time | On screen | Voice-over |
| --- | --- | --- | --- |
| 1 | 0:00-0:20 | Top of the page: headline tiles and the synthetic-data notice. | "This is a margin cockpit for a fictional AI software company. Everything here is synthetic. The question it answers: which customers and features make or lose money once you count what the AI actually costs to serve?" |
| 2 | 0:20-0:50 | *Daily AI gross margin* chart, then the forecast band. | "Revenue minus the cost of every model call, every day. The band is the forecast: where margin is heading if nothing changes." |
| 3 | 0:50-1:20 | *Fully loaded cost to serve by feature*; *Unprofitable tenants* table. | "Cost broken down by feature, with shared infrastructure allocated. Here are the customers who cost more to serve than they pay, worst first." |
| 4 | 1:20-1:50 | *Daily margin brief* card. | "Each night the system writes a short brief: what moved, why, and what to look at. Every figure in it comes from a calculation, not from the language model." |
| 5 | 1:50-2:30 | *Cost-to-serve explorer*: pick one unprofitable customer, then the cost-quality plot. | "Drill into one customer: which features drive their cost, and how quality compares to cost for each one." |
| 6 | 2:30-3:00 | *Margin leaks*. | "Leaks are patterns that quietly erode margin: retries, oversized context, usage above plan. Each has a size in dollars." |
| 7 | 3:00-3:40 | *Forecast & pricing simulator*: change one plan price, then one engineering lever, then the cost-quality lab. | "What if we reprice this plan, or route simple requests to a smaller model? The simulator uses the same calculation the analyst uses, and a saving only counts if quality holds." |
| 8 | 3:40-4:10 | *Action Center*. | "Recommended actions, each with the role that would approve it. Nothing changes any real system: approvals are recorded, then the realized effect is measured." |
| 9 | 4:10-4:40 | *Ask the Cost-to-Serve Analyst*: type "Which feature lost the most margin last month, and why?", wait for the answer, show the cited evidence. Click thumbs up. | "You can ask in plain English. The analyst only answers from the data, shows its evidence, and refuses what it can't support." |
| 10 | 4:40-5:00 | *Pipeline and data health*, then *Architecture & about*; cut to the phone-width take. | "Behind it: a daily pipeline with data checks, and a design that scales to zero when nobody is looking. Synthetic data, real methods." |

## Fallbacks

- If the analyst shows "paused" or "unavailable right now", skip shot 9 and record it on another day; don't stage an answer.
- If a section is missing (for example the brief before the first nightly run), drop its shot rather than showing an empty card.
