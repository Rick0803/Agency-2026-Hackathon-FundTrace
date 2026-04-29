# Workflow Illustration — Image Generation Instructions

## Purpose

This image appears on the FundTrace home page to explain the 4-step investigation workflow at a glance. It should communicate the full story: where the data comes from, what happens at each step, and what comes out the other end.

## Overall Layout

Horizontal flow, left to right. Three zones:

1. **Data Sources** (left) — two stacked input boxes feeding into Step 1
2. **4 Workflow Steps** (middle) — connected by arrows
3. **Output** (right) — what the user gets after completing Step 4

Wide aspect ratio recommended: 1600 × 600px or 16:5.

---

## Zone 1 — Data Sources (left side)

Two stacked boxes with a merge arrow pointing right into Step 1.

**Box 1 (top)**
- Label: `CRA T3010 Charity Filings`
- Icon: document / tax form
- Subtext: `Revenue · Expenses · Employees · Transfers`
- Colour: slate blue or neutral grey

**Box 2 (bottom)**
- Label: `Federal Grants & Contributions`
- Icon: government building or money transfer
- Subtext: `1.27M grant records · 100+ departments`
- Colour: slate blue or neutral grey

A bracket or merge arrow connects both boxes into a single arrow pointing to Step 1.

---

## Zone 2 — Workflow Steps (middle)

Four step cards connected by right-pointing arrows. Each card has:
- Step number (top)
- Step name (bold)
- One-line description
- Key output label (bottom, smaller text)

### Step 1 — Search Organizations
- Colour: Blue (`#4C78A8`)
- Icon: magnifying glass over a database
- Description: `Browse CRA + FED records using rules, AI detection, or natural language search`
- Output label: `Candidate list`

### Step 2 — Review Shortlist
- Colour: Amber / Yellow (`#F8B429`)
- Icon: checklist with flags
- Description: `Add suspicious organizations to your shortlist — remove false positives`
- Output label: `Flagged set (5–20 orgs)`

### Step 3 — Run Analysis
- Colour: Green (`#59A14F`)
- Icon: magnifying glass over a bar chart
- Description: `Ghost score computed across 5 dimensions: gov dependency, program spend, employees, transfers, funding gap`
- Output label: `Risk labels + signals`

### Step 4 — View Report
- Colour: Teal (`#76B7B2`)
- Icon: document with a download arrow
- Description: `AI-written executive summary + evidence table exportable as PDF or CSV`
- Output label: `Audit-ready findings`

---

## Zone 3 — Output (right side)

A single output box to the right of Step 4, connected by an arrow.

**Contents (stacked vertically):**
- 🔴 `Ghost Score: 0.91 — CRITICAL` (red, bold)
- 🟠 `Risk signals: no employees · high transfer · gov dependency 97%` (orange, smaller)
- 📄 `Downloadable report` (neutral, icon)

Colour: light red or warm off-white background with a red left border.

---

## Visual Style

- Clean, flat design — no gradients or drop shadows
- White or very light grey background
- Bold sans-serif font (Inter, DM Sans, or similar)
- Step cards should have rounded corners
- Arrows between steps: thick, dark grey, right-pointing chevron style
- The data source merge arrow should be visually distinct (thinner, branching)

## Tone

Professional and investigative — this is a government accountability tool. Avoid playful or startup-style aesthetics. Think audit dashboard, not consumer app.

## What to Avoid

- Generic icons that could apply to any app (avoid shopping carts, people icons, smiley faces)
- Showing the word "FundTrace" in the illustration itself (the title is already above it on the page)
- More than 3 lines of text per card — keep it scannable
- Dark backgrounds — the app uses a light theme
