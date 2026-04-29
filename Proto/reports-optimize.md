# Report LLM Token Optimization

## Context

The Report page generates a business report using one LLM call. This document records the token strategy agreed on so we can revisit it when scaling.

## Report Structure (Hybrid)

Only two sections are LLM-written. Everything else is rendered deterministically from existing session state.

| Section | Writer |
|---|---|
| Executive Summary | LLM |
| Risk Overview table | Deterministic |
| Entity Findings table | Deterministic |
| Recommended Actions | LLM |

Pattern Analysis and Data Limitations were deliberately excluded — too speculative, better shown as data badges.

## Input Strategy

- **Aggregate stats**: compact JSON (no indent), ~80 tokens
- **Entity list**: flat strings, one per line — `RISK | Name | score X.XX | flag1, flag2 | PROVINCE`
- **No entity cap needed**: user is expected to flag 5–10 entities max; the full list fits comfortably in budget

Example entity line:
```
CRITICAL | Acme Foundation | score 0.91 | no_employees, high_transfer | ON
```

## Token Estimate (10 entities)

| Component | Tokens |
|---|---|
| System prompt | ~50 |
| Aggregate stats | ~80 |
| 10 entities (flat strings) | ~120 |
| Section instructions | ~40 |
| Executive Summary output | ~60 |
| Recommended Actions output | ~60 |
| **Total** | **~410** |

## Model Choice

Use **claude-sonnet-4-6** (not Haiku). At this volume (~410 tokens per report generation), the cost difference is negligible (under $0.002 per click) and quality is meaningfully better for government-audience prose.

## When to Revisit

If users start flagging 20+ entities, add Option A: cap entity context at top 5 by ghost score and note "X additional entities analyzed, top 5 shown" in the prompt. Do not change the flat string format or model.
