/**
 * report-writer.js — Formats and saves the anomaly detector report.
 */

const fs   = require('fs');
const path = require('path');

const SEVERITY_LABEL = {
  CRITICAL: '[CRITICAL]',
  HIGH:     '[HIGH]',
  MEDIUM:   '[MEDIUM]',
  LOW:      '[LOW]',
};

function writeReport(report, options = {}) {
  const { focus, topN = 10 } = options;
  const date        = new Date().toISOString().split('T')[0];
  const focusLabel  = focus ? focus.toUpperCase() : 'CRA + FED + AB';
  const totalFound  = report.findings ? report.findings.length : 0;

  // ── Markdown ─────────────────────────────────────────────────────────
  let md = `# Public Funds Anomaly Report\n\n`;
  md += `**Generated:** ${date}  |  **Datasets:** ${focusLabel}  |  **Findings:** ${totalFound}\n\n`;
  md += `---\n\n`;
  md += `## Executive Summary\n\n${report.summary}\n\n`;
  md += `---\n\n`;

  for (const f of (report.findings || [])) {
    const label = SEVERITY_LABEL[f.severity] || `[${f.severity}]`;
    md += `## ${f.rank}. ${label} ${f.anomaly_type}`;
    if (f.entity) md += ` — ${f.entity}`;
    md += '\n\n';

    const meta = [`**Dataset:** ${f.dataset}`];
    if (f.bn)     meta.push(`**BN:** ${f.bn}`);
    if (f.amount) meta.push(`**Amount:** ${f.amount}`);
    md += meta.join('  |  ') + '\n\n';

    md += `**Evidence:** ${f.evidence}\n\n`;
    md += `**Why it matters:** ${f.why_it_matters}\n\n`;
    md += `---\n\n`;
  }

  // ── Save file ─────────────────────────────────────────────────────────
  const suffix   = focus ? `-${focus}` : '';
  const filename = `anomaly-report-${date}${suffix}.md`;
  const outPath  = path.resolve(process.cwd(), filename);
  fs.writeFileSync(outPath, md, 'utf8');

  // ── Also save machine-readable JSON alongside ─────────────────────────
  const jsonPath = outPath.replace(/\.md$/, '.json');
  fs.writeFileSync(jsonPath, JSON.stringify({ generated: date, focus: focusLabel, ...report }, null, 2), 'utf8');

  // ── Print to console ──────────────────────────────────────────────────
  console.log('\n' + '═'.repeat(70));
  console.log(md);
  console.log(`Report saved to: ${outPath}`);
  console.log(`JSON saved to:   ${jsonPath}`);

  return { mdPath: outPath, jsonPath };
}

module.exports = { writeReport };
