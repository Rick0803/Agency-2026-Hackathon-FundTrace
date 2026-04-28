/**
 * anomaly-detector.js — Agentic public funds anomaly investigator.
 *
 * Uses Claude (claude-sonnet-4-6) with tool-use to autonomously query the
 * government dataset, identify the highest-priority accountability anomalies,
 * and produce a ranked Markdown report.
 *
 * Usage:
 *   node scripts/anomaly-detector.js                  # all datasets, top 10
 *   node scripts/anomaly-detector.js --focus=cra      # CRA only
 *   node scripts/anomaly-detector.js --focus=fed      # FED only
 *   node scripts/anomaly-detector.js --focus=ab       # AB only
 *   node scripts/anomaly-detector.js --top=20         # top 20 findings
 *
 * Requires:
 *   ANTHROPIC_API_KEY in general/.env (or general/.env.public)
 *   DB_CONNECTION_STRING in the same env files
 */

// ── Environment: loaded by db.js, but we need the API key before that ──
const path = require('path');
const fs   = require('fs');

const publicEnv = path.join(__dirname, '..', '.env.public');
if (fs.existsSync(publicEnv)) require('dotenv').config({ path: publicEnv });

const adminEnv = path.join(__dirname, '..', '.env');
if (fs.existsSync(adminEnv)) require('dotenv').config({ path: adminEnv, override: true });

// ── Deps ────────────────────────────────────────────────────────────────
const Anthropic              = require('@anthropic-ai/sdk');
const { end }                = require('../lib/db');
const { TOOL_DEFINITIONS, executeTool } = require('../lib/agent-tools');
const { writeReport }        = require('../lib/report-writer');

// ── CLI args ────────────────────────────────────────────────────────────
const args = Object.fromEntries(
  process.argv.slice(2)
    .filter(a => a.startsWith('--'))
    .map(a => a.slice(2).split('='))
);

const FOCUS = args.focus || null;  // 'cra' | 'fed' | 'ab' | null (all)
const TOP_N = Math.min(parseInt(args.top || '10', 10), 30);
const MODEL = args.model || 'claude-sonnet-4-6';
const MAX_ITERATIONS = parseInt(args['max-iter'] || '40', 10);

// ── Validate ────────────────────────────────────────────────────────────
if (!process.env.ANTHROPIC_API_KEY) {
  console.error(
    'ERROR: ANTHROPIC_API_KEY not set.\n' +
    'Add it to general/.env:\n' +
    '  ANTHROPIC_API_KEY=sk-ant-...\n'
  );
  process.exit(1);
}

if (FOCUS && !['cra', 'fed', 'ab'].includes(FOCUS)) {
  console.error(`ERROR: --focus must be one of: cra, fed, ab (got "${FOCUS}")`);
  process.exit(1);
}

// ── System prompt ────────────────────────────────────────────────────────
function buildSystemPrompt() {
  const focusNote = FOCUS
    ? `Focus your investigation exclusively on the ${FOCUS.toUpperCase()} dataset.`
    : 'Investigate all three datasets: CRA, FED, and AB. Prioritize cross-dataset findings.';

  return `You are a government accountability investigator with read-only access to Canadian government financial data across three datasets:

- CRA: Charity T3010 filings — board directors, financial flows, gifts between charities (2020–2024)
- FED: Federal grants & contributions — 1.275M records of government funding to recipients nationwide
- AB: Alberta grants, contracts, and sole-source contracts — 1.98M grant records, 67K contracts

${focusNote}

Your mission: Find the top ${TOP_N} anomalies suggesting misuse of public funds, conflicts of interest, or accountability failures. Investigate autonomously using the tools provided.

INVESTIGATION STRATEGY:
1. Start broad — use get_top_risks for each relevant dataset/category to survey high-risk rows
2. Dig deeper — use query_database to get context, dollar amounts, names, and patterns
3. Prioritize: (a) cross-dataset anomalies, (b) highest dollar values, (c) deliberate structuring vs. error
4. For promising leads, use get_entity_profile to see if the entity appears in multiple datasets
5. Discover available tables when needed: SELECT table_name FROM information_schema.tables WHERE table_schema = 'cra'
6. When you have enough evidence for ${TOP_N} well-supported findings, call write_report

KNOWN ANOMALY PATTERNS:
- Circular gifting: charities A→B→A or A→B→C→A with symmetric dollar flows in the same fiscal year
- Zombie recipients: high-value federal grants to orgs with no registered BN or that have ceased activity
- Non-compliant sole-source: AB contracts with permitted_situation = 'z' (no valid justification)
- Amendment creep: federal grants repeatedly amended upward (3+ amendments, large total increase)
- Overhead burden: charity admin+fundraising costs exceed charitable program spending
- Individual recipients: federal grants to sole proprietors (recipient_type = 'P') at high values
- Ghost capacity: funding to entities with no verifiable business registration

SEVERITY GUIDELINES:
- CRITICAL: >$1M involved + clear pattern suggesting fraud or deliberate structuring
- HIGH: Significant public funds at risk, strong evidence of policy violation
- MEDIUM: Notable pattern, lower certainty or smaller amounts
- LOW: Procedural concern worth flagging

IMPORTANT: Only call write_report when you are confident in your findings. Each finding must have specific data evidence (row counts, dollar amounts, entity names) — not just observations that a pattern "may exist".`;
}

// ── Agent loop ────────────────────────────────────────────────────────────
async function runAgent() {
  const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
  const systemPrompt = buildSystemPrompt();

  const focusLabel = FOCUS ? FOCUS.toUpperCase() : 'CRA + FED + AB';
  const initialMessage =
    `Begin your investigation of ${focusLabel} data. Find and rank the top ${TOP_N} public fund anomalies. Start with get_top_risks across available categories, then dig into the most promising leads with query_database.`;

  console.log(`\nPublic Funds Anomaly Detector`);
  console.log(`Dataset: ${focusLabel}  |  Top ${TOP_N} findings  |  Model: ${MODEL}`);
  console.log('─'.repeat(60));

  const messages = [{ role: 'user', content: initialMessage }];

  let report       = null;
  let iteration    = 0;
  let toolCallCount = 0;

  while (!report && iteration < MAX_ITERATIONS) {
    iteration++;

    const response = await client.messages.create({
      model:      MODEL,
      max_tokens: 8192,
      system:     systemPrompt,
      tools:      TOOL_DEFINITIONS,
      messages,
    });

    // Append assistant turn
    messages.push({ role: 'assistant', content: response.content });

    // Print any text blocks from the assistant
    for (const block of response.content) {
      if (block.type === 'text' && block.text.trim()) {
        console.log(`\n[agent] ${block.text.trim()}`);
      }
    }

    if (response.stop_reason === 'end_turn') {
      console.log('\n[agent] Investigation complete (end_turn).');
      break;
    }

    if (response.stop_reason === 'max_tokens') {
      console.warn('\n[warn] Hit max_tokens — agent may be mid-thought. Continuing...');
    }

    if (response.stop_reason === 'tool_use' || response.stop_reason === 'max_tokens') {
      const toolResults = [];

      for (const block of response.content) {
        if (block.type !== 'tool_use') continue;

        toolCallCount++;
        console.log(`\n[tool #${toolCallCount}] ${block.name}`);

        let result;
        try {
          result = await executeTool(block.name, block.input);
        } catch (err) {
          result = { error: `Tool execution error: ${err.message}` };
        }

        // Capture the report if write_report was called
        if (block.name === 'write_report' && result.__report) {
          report = result.__report;
          result = { status: 'Report captured. Investigation complete.' };
        }

        const resultStr = JSON.stringify(result);
        const preview   = resultStr.length > 200 ? resultStr.slice(0, 200) + '…' : resultStr;
        console.log(`       → ${preview}`);

        toolResults.push({
          type:        'tool_result',
          tool_use_id: block.id,
          content:     resultStr,
        });
      }

      // Only add tool_result turn if there are results to add
      if (toolResults.length > 0) {
        messages.push({ role: 'user', content: toolResults });
      }
    }
  }

  if (iteration >= MAX_ITERATIONS && !report) {
    console.warn(`\n[warn] Reached max iterations (${MAX_ITERATIONS}) without a write_report call.`);
    console.warn('The agent may need more iterations (--max-iter=60) or a tighter --focus.');
  }

  return report;
}

// ── Entry point ───────────────────────────────────────────────────────────
async function main() {
  let report;

  try {
    report = await runAgent();
  } finally {
    await end().catch(() => {});
  }

  if (report) {
    writeReport(report, { focus: FOCUS, topN: TOP_N });
    process.exit(0);
  } else {
    process.exit(1);
  }
}

main().catch(err => {
  console.error('\n[fatal]', err.message || err);
  process.exit(1);
});
