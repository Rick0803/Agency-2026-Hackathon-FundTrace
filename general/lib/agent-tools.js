/**
 * agent-tools.js — Tool definitions and executors for the anomaly-detector agent.
 *
 * Each tool exposes read-only access to the government data. The query_database
 * tool uses BEGIN READ ONLY so any accidental DML is rejected at the DB level.
 * get_top_risks provides shortcuts to known pre-computed tables; if a table
 * doesn't exist yet Claude will get an informative error and can fall back to
 * writing its own SQL via query_database.
 */

const { pool } = require('./db');

// ═══════════════════════════════════════════════════════════════════════
//  TOOL DEFINITIONS  (Anthropic tool-use schema format)
// ═══════════════════════════════════════════════════════════════════════

const TOOL_DEFINITIONS = [
  {
    name: 'query_database',
    description: [
      'Execute a read-only SQL SELECT query against the government data database.',
      'Available schemas: cra (charity T3010 data), fed (federal grants & contributions),',
      'ab (Alberta grants/contracts/sole-source), general (entity resolution golden records).',
      'To discover tables: SELECT table_name FROM information_schema.tables WHERE table_schema = \'cra\'.',
      'Always use LIMIT (max 100) to avoid overloading the context.',
      'The database user is read-only — INSERT/UPDATE/DELETE will be rejected.',
    ].join(' '),
    input_schema: {
      type: 'object',
      properties: {
        sql: {
          type: 'string',
          description: 'A read-only SELECT (or WITH … SELECT) SQL query. No DML.',
        },
        description: {
          type: 'string',
          description: 'One-sentence explanation of what this query is trying to find.',
        },
      },
      required: ['sql', 'description'],
    },
  },

  {
    name: 'get_top_risks',
    description: [
      'Shortcut to pre-ranked anomaly rows from known analysis tables.',
      'Use this before writing custom SQL — it surfaces the highest-risk rows',
      'with minimal effort. Falls back with an error if the table is not yet populated.',
    ].join(' '),
    input_schema: {
      type: 'object',
      properties: {
        dataset: {
          type: 'string',
          enum: ['cra', 'fed', 'ab', 'general'],
          description: 'Which dataset to query.',
        },
        category: {
          type: 'string',
          enum: [
            'loops',        // CRA: circular gifting
            'score',        // CRA: charity risk score 0-30
            'overhead',     // CRA: overhead-heavy charities
            'zombie',       // FED: high-value grants to ceased/unverifiable recipients
            'amendment',    // FED: grants amended upward repeatedly
            'individual',   // FED: sole-proprietor / individual recipients (not orgs)
            'sole_source',  // AB: sole-source contracts without valid justification
            'cross_dataset',// general: entities flagged in 2+ datasets
          ],
          description: 'Anomaly category to retrieve.',
        },
        limit: {
          type: 'number',
          description: 'Max rows to return. Default 10, max 50.',
        },
      },
      required: ['dataset', 'category'],
    },
  },

  {
    name: 'get_entity_profile',
    description: [
      'Look up a golden record for an organization by name or 9-digit business number (BN).',
      'Returns canonical name, which datasets the entity appears in, and financial profiles.',
      'Use this to check if a high-risk entity also appears in other datasets.',
    ].join(' '),
    input_schema: {
      type: 'object',
      properties: {
        name_or_bn: {
          type: 'string',
          description: 'Organization name (partial ok, uses trigram search) or 9-digit BN.',
        },
      },
      required: ['name_or_bn'],
    },
  },

  {
    name: 'write_report',
    description: [
      'Write the final accountability report. Call this ONLY when you have finished',
      'investigating and have your top findings ranked by severity. The report will',
      'be saved to disk and printed to the console.',
    ].join(' '),
    input_schema: {
      type: 'object',
      properties: {
        summary: {
          type: 'string',
          description: 'Executive summary of the investigation findings (3-5 sentences).',
        },
        findings: {
          type: 'array',
          description: 'Ranked list of anomalies, most severe first.',
          items: {
            type: 'object',
            properties: {
              rank:         { type: 'number', description: 'Rank (1 = most severe).' },
              severity:     { type: 'string', enum: ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] },
              entity:       { type: 'string', description: 'Organization or recipient name.' },
              bn:           { type: 'string', description: 'Business number if available.' },
              dataset:      { type: 'string', description: 'CRA | FED | AB | Cross-dataset' },
              anomaly_type: { type: 'string', description: 'e.g. Circular Gifting, Zombie Recipient' },
              amount:       { type: 'string', description: 'Dollar amount involved (formatted string).' },
              evidence:     { type: 'string', description: 'Specific data evidence for this finding.' },
              why_it_matters: {
                type: 'string',
                description: 'Accountability significance in 1-2 sentences.',
              },
            },
            required: ['rank', 'severity', 'entity', 'dataset', 'anomaly_type', 'evidence', 'why_it_matters'],
          },
        },
      },
      required: ['summary', 'findings'],
    },
  },
];

// ═══════════════════════════════════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════════════════════════════════

/** Serialize query result rows, converting BigInt and Date safely. */
function serializeRows(rows) {
  return JSON.parse(
    JSON.stringify(rows, (_key, val) =>
      typeof val === 'bigint' ? val.toString() : val
    )
  );
}

/** Run SQL inside a READ ONLY transaction against the pool. */
async function runReadOnly(sql, params = []) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN READ ONLY');
    const result = await client.query(sql, params);
    await client.query('COMMIT');
    return serializeRows(result.rows);
  } catch (err) {
    await client.query('ROLLBACK').catch(() => {});
    throw err;
  } finally {
    client.release();
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  TOOL EXECUTORS
// ═══════════════════════════════════════════════════════════════════════

async function executeQuery({ sql, description }) {
  // Basic guard: must start with SELECT or WITH (CTEs)
  const trimmed = sql.trim().toUpperCase();
  if (!/^(SELECT|WITH|EXPLAIN)\b/.test(trimmed)) {
    return { error: 'Only SELECT / WITH / EXPLAIN queries are permitted.' };
  }

  console.log(`  [query] ${description}`);
  try {
    const rows = await runReadOnly(sql);
    return { row_count: rows.length, rows: rows.slice(0, 100) };
  } catch (err) {
    return { error: err.message };
  }
}

/** Pre-built queries for known risk categories. */
const TOP_RISK_QUERIES = {
  cra: {
    loops: (limit) => `
      SELECT lp.bn,
             ci.legal_name,
             lp.loop_count,
             lp.total_symmetric_flow,
             cs.total_score
        FROM cra.loop_participants lp
        JOIN cra.cra_identification ci ON ci.bn = lp.bn AND ci.fpe = (
               SELECT MAX(fpe) FROM cra.cra_identification WHERE bn = lp.bn
             )
        LEFT JOIN cra.charity_scores cs ON cs.bn = lp.bn
       ORDER BY lp.total_symmetric_flow DESC NULLS LAST
       LIMIT ${limit}`,

    score: (limit) => `
      SELECT cs.bn,
             ci.legal_name,
             cs.total_score,
             cs.loop_score,
             cs.overhead_score,
             cs.financial_score
        FROM cra.charity_scores cs
        JOIN cra.cra_identification ci ON ci.bn = cs.bn AND ci.fpe = (
               SELECT MAX(fpe) FROM cra.cra_identification WHERE bn = cs.bn
             )
       ORDER BY cs.total_score DESC
       LIMIT ${limit}`,

    overhead: (limit) => `
      SELECT ci.bn,
             ci.legal_name,
             fd.field_4100 AS admin_expense,
             fd.field_4110 AS fundraising_expense,
             fd.field_4120 AS charitable_programs,
             CASE WHEN COALESCE(fd.field_4120,0) = 0 THEN NULL
                  ELSE ROUND(
                    (COALESCE(fd.field_4100,0) + COALESCE(fd.field_4110,0))::numeric
                    / (COALESCE(fd.field_4100,0) + COALESCE(fd.field_4110,0) + COALESCE(fd.field_4120,0))
                    * 100, 1)
             END AS overhead_pct,
             fd.fpe
        FROM cra.cra_financial_details fd
        JOIN cra.cra_identification ci ON ci.bn = fd.bn AND ci.fpe = fd.fpe
       WHERE fd.fpe = (SELECT MAX(fpe) FROM cra.cra_financial_details WHERE bn = fd.bn)
         AND COALESCE(fd.field_4100,0) + COALESCE(fd.field_4110,0) > 50000
         AND COALESCE(fd.field_4120,0) > 0
       ORDER BY overhead_pct DESC NULLS LAST
       LIMIT ${limit}`,
  },

  fed: {
    zombie: (limit) => `
      SELECT recipient_legal_name,
             recipient_business_number,
             recipient_type,
             SUM(agreement_value) AS total_value,
             COUNT(*) AS grant_count,
             MAX(agreement_end_date) AS last_end_date
        FROM fed.grants_contributions
       WHERE (recipient_business_number IS NULL OR recipient_business_number = '')
         AND agreement_value > 500000
       GROUP BY recipient_legal_name, recipient_business_number, recipient_type
       ORDER BY total_value DESC
       LIMIT ${limit}`,

    amendment: (limit) => `
      SELECT agreement_number,
             MAX(recipient_legal_name) AS recipient,
             COUNT(*) AS amendment_count,
             MIN(agreement_value) AS initial_value,
             MAX(agreement_value) AS final_value,
             MAX(agreement_value) - MIN(agreement_value) AS value_increase,
             MAX(owner_org_title) AS department
        FROM fed.grants_contributions
       WHERE is_amendment = true OR amendment_number > 0
       GROUP BY agreement_number
      HAVING COUNT(*) >= 3
         AND MAX(agreement_value) > MIN(agreement_value)
       ORDER BY value_increase DESC
       LIMIT ${limit}`,

    individual: (limit) => `
      SELECT recipient_legal_name,
             recipient_type,
             province_territory_of_recipient,
             SUM(agreement_value) AS total_value,
             COUNT(*) AS grant_count,
             MAX(owner_org_title) AS top_department
        FROM fed.grants_contributions
       WHERE recipient_type = 'P'
         AND agreement_value > 0
       GROUP BY recipient_legal_name, recipient_type, province_territory_of_recipient
       ORDER BY total_value DESC
       LIMIT ${limit}`,
  },

  ab: {
    sole_source: (limit) => `
      SELECT vendor_name,
             SUM(contract_value) AS total_value,
             COUNT(*) AS contract_count,
             STRING_AGG(DISTINCT permitted_situation, ', ') AS justification_codes,
             STRING_AGG(DISTINCT ministry_name, '; ') AS ministries
        FROM ab.ab_sole_source
       WHERE permitted_situation = 'z'
          OR permitted_situation IS NULL
       GROUP BY vendor_name
       ORDER BY total_value DESC NULLS LAST
       LIMIT ${limit}`,
  },

  general: {
    cross_dataset: (limit) => `
      SELECT canonical_name,
             bn_root,
             dataset_sources,
             confidence,
             cra_profile,
             fed_profile,
             ab_profile
        FROM general.entity_golden_records
       WHERE array_length(dataset_sources, 1) >= 2
       ORDER BY array_length(dataset_sources, 1) DESC, confidence DESC
       LIMIT ${limit}`,
  },
};

async function getTopRisks({ dataset, category, limit = 10 }) {
  const cap = Math.min(Number(limit) || 10, 50);
  const categoryQueries = TOP_RISK_QUERIES[dataset];

  if (!categoryQueries || !categoryQueries[category]) {
    return {
      error: `No pre-built query for dataset="${dataset}" category="${category}". ` +
             `Try query_database with custom SQL, or list available tables with: ` +
             `SELECT table_name FROM information_schema.tables WHERE table_schema = '${dataset}'`,
    };
  }

  const sql = categoryQueries[category](cap);
  console.log(`  [get_top_risks] ${dataset}/${category} (limit ${cap})`);
  try {
    const rows = await runReadOnly(sql);
    return { dataset, category, row_count: rows.length, rows };
  } catch (err) {
    return {
      error: `Query failed: ${err.message}. The table may not be populated yet. ` +
             `Try query_database to discover available tables.`,
    };
  }
}

async function getEntityProfile({ name_or_bn }) {
  const isBN = /^\d{9}$/.test(name_or_bn.trim());
  console.log(`  [get_entity_profile] ${name_or_bn}`);

  try {
    let rows;
    if (isBN) {
      rows = await runReadOnly(
        `SELECT id, canonical_name, bn_root, bn_variants, dataset_sources,
                cra_profile, fed_profile, ab_profile, confidence, aliases
           FROM general.entity_golden_records
          WHERE bn_root = $1
          LIMIT 5`,
        [name_or_bn.trim()]
      );
    } else {
      rows = await runReadOnly(
        `SELECT id, canonical_name, bn_root, bn_variants, dataset_sources,
                cra_profile, fed_profile, ab_profile, confidence, aliases
           FROM general.entity_golden_records
          WHERE canonical_name % $1
          ORDER BY similarity(canonical_name, $1) DESC
          LIMIT 5`,
        [name_or_bn]
      );
    }
    return { row_count: rows.length, results: rows };
  } catch (err) {
    return { error: err.message };
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  DISPATCHER
// ═══════════════════════════════════════════════════════════════════════

async function executeTool(toolName, toolInput) {
  switch (toolName) {
    case 'query_database':   return executeQuery(toolInput);
    case 'get_top_risks':    return getTopRisks(toolInput);
    case 'get_entity_profile': return getEntityProfile(toolInput);
    case 'write_report':     return { __report: toolInput };
    default:                 return { error: `Unknown tool: ${toolName}` };
  }
}

module.exports = { TOOL_DEFINITIONS, executeTool };
