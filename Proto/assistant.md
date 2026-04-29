# LLM Assistant — Contextual Advisor

## Concept

Add an LLM assistant that provides contextual advice to users as they use the app — not a generic chatbot, but a reactive advisor that watches what the user is doing and responds accordingly.

---

## Placement

- **Sidebar** — persistent assistant panel added at the bottom of the sidebar, visible on every page
- **Inline prompt bubbles** — contextual callouts injected under specific UI elements (e.g., threshold sliders, flagging checkboxes)

These are two valid patterns. The sidebar is easier to implement (one component). Inline bubbles are more impactful but require injecting UI into each view. Pick one pattern before building so it stays consistent.

---

## Stub pattern

Each suggestion is implemented as a deterministic heuristic first. The LLM slot-in later just replaces the message generation — the trigger conditions and UI stay the same. This means:
- The feature ships even if LLM is never added (fallback safety)
- Every heuristic rule doubles as a documented test case for the future LLM prompt

Internal shape each suggestion should conform to:
```python
@dataclass
class AssistantHint:
    trigger: str    # e.g. "flagged_list_too_large"
    message: str    # shown in UI
    severity: str   # "info" | "warning" | "tip"
    page: str       # which page triggered it
```

---

## Priority use cases (Fetch + Flagged only for now)

### 1. Scan result summary — LLM (Fetch page)

**Trigger:** after Way 1 or Way 2 scan completes.

**What it does:** one sentence summarizing the scan results — not just repeating the numbers, but interpreting them. Example: "47 entities flagged, mostly charities in Ontario with near-total government dependency and no reported program spend."

**Why LLM here:** summarization across multiple dimensions (count, geography, rule breakdown, entity type mix) is genuinely easier to express in natural language than a hardcoded template. The data passed to the LLM is small — just the rule hit counts, province breakdown, and entity type mix as JSON. One short call.

**Implementation notes:**
- Call after the scan button completes, before the results table renders
- Pass: total flagged, rules_triggered breakdown (count per rule), top province, top entity type, total FED dollars at risk
- Ask for: one sentence, plain English, no hedging
- Display as a highlighted info box above the results table

---

### 2. Flagging recommendation — heuristic (Fetch + Flagged pages)

**Trigger:** after scan (Fetch) or whenever flagged list changes (Flagged page).

**What it does:** advises whether the current flagged count is a good working set for analysis. No LLM needed — the logic is simple enough to hardcode.

**Heuristic thresholds:**
- < 3 entities: "Your flagged list is very small — you may want to loosen thresholds or flag more before running analysis."
- 3–30 entities: "Good working set for batch analysis."
- 31–100 entities: "Large flagged list — batch analysis will take longer. Consider narrowing by province or rule count."
- > 100 entities: "Too many to analyze individually. Tighten your thresholds or use Portfolio Analysis instead."

**Display:** small tip box below the flagged count, always visible, updates live as users add/remove entities.

---

### 3. Flagged list quality advisor — LLM (Flagged page)

**Trigger:** whenever the user lands on the Flagged page, applies a selection, or changes which entities are included for analysis.

**What it does:** gives a short recommendation on whether the current flagged list is ready for analysis. The assistant should consider both the **number** of entities and the **quality** of the selected entities. It can tell users whether they should proceed, go back to Fetch to add more candidates, or narrow the list by unselecting weaker entities before moving to Analyze.

**Why LLM here:** the decision is not only about count. A list of 5 entities with strong, diverse signals may be better than a list of 25 weak or repetitive entities. The LLM can explain the tradeoff in plain English by looking at entity names, rule counts, anomaly scores, provinces, entity types, and visible evidence signals.

**Example recommendations:**
- "This is a small but strong set: 8 selected entities, most with multiple rule hits and high funding gaps. You can proceed to Analyze."
- "This set may be too broad for a focused review. Consider unselecting entities with only one weak signal before analysis."
- "Only 2 entities are selected, and both appear to have limited evidence. Consider going back to Fetch and adding more candidates."

**Implementation notes:**
- Pass: selected count, total flagged count, rules_triggered summary, anomaly score range, top provinces, top entity types, and funding exposure summary
- Ask for: 1 recommendation sentence plus 1 short reason
- The assistant should never auto-select or remove entities; it only advises
- Display above the `Elevate These Entities by Analyzing Them` button so users see the recommendation before proceeding

---

## Use cases by page

### Fetch
- Scan result summary (LLM, see above)
- Flagging recommendation after scan (heuristic, see above)

### Flagged
- Flagging recommendation updated as list changes (same heuristic, re-evaluated on every add/remove)
- Flagged list quality advisor that recommends whether to proceed, add more entities, or narrow the selected subset

### Analyze
- Comment on batch results: "3 of your 5 flagged entities are CRITICAL — this pattern suggests a systemic issue, not isolated cases."
- Portfolio: "Department X has the highest risk rate — consider filtering Fetch to that department for deeper investigation."

### Report
- Prompt the user on next steps after a report is generated (referral, further research, escalation)

---

## Implementation timing

**Build after Analyze and Report are complete.**

Reasons:
- The advisor's value scales with how much of the app is working. Advice that reacts to analysis results is more useful than advice on rule sliders alone.
- Analyze and Report are still in progress — building the advisor now risks retrofitting it as pages change.
- The advisor touches every page, so designing it after the full flow exists ensures consistency.

---

## Technical approach (when ready)

- Watch `st.session_state` for relevant signals (flagged count, rule trigger counts, ghost scores, anomaly scores)
- Pass current state as a structured JSON context to the LLM — no DB calls from the advisor
- Render advisor output as a non-blocking info/warning callout (sidebar or inline)
- One LLM call per user-triggered action (not streaming; short responses only)
- Advisor should never block the user — always dismissible
