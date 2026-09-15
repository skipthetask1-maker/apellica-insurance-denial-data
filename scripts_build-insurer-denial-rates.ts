// Builds content/insurer-denial-rates.generated.json from the CMS Transparency
// in Coverage PUF rows parsed at DENIALS_NDJSON (one row per marketplace plan,
// metrics repeated at issuer×state level). Run on the VPS:
//   DENIALS_NDJSON=/root/apellica-health-more-data-may-19/denials.ndjson npx tsx scripts/data/build-insurer-denial-rates.ts
//
// Rules (see /insurer-denial-rates/methodology):
//   - Stand-alone dental plans (metal_level Low/High) are dropped.
//   - Aggregation key is (issuer_id, state, plan_year); the PUF reports these
//     counts at the issuer level and repeats them on every plan row.
//   - Nothing is estimated. Rates are den_in / rx_in from the file. Where the
//     file gives a percentage and the counts, the counts win.
//   - The PUF for plan year Y reports claims from plan year Y-2 (data
//     dictionary). claims_year is recorded on every row.

import fs from "node:fs";
import path from "node:path";

type Raw = {
  plan_year: number; state: string; issuer_name: string; issuer_id: number; plan_id: string;
  plan_type: string; metal_level: string; url_claims_payment_policies: string | null;
  rx_in: number | null; rx_out: number | null; den_in: number | null; den_out: number | null;
  appeals_filed: number | null; appeals_overturned: number | null; appeals_overturn_pct: number | null;
  ext_filed: number | null; ext_overturned: number | null; ext_overturn_pct: number | null;
  plan_den_in: number | null; plan_den_out: number | null;
};

const DENTAL = new Set(["Low", "High"]);
const SRC = process.env.DENIALS_NDJSON || "/root/apellica-health-more-data-may-19/denials.ndjson";
const OUT = path.join(process.cwd(), "content", "insurer-denial-rates.generated.json");

function slugify(s: string): string {
  return s.toLowerCase().replace(/&/g, " and ").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}
function pct(num: number | null, den: number | null): number | null {
  if (num == null || den == null || den <= 0) return null;
  return Math.round((num / den) * 10000) / 10000; // fraction, 4 dp
}

const lines = fs.readFileSync(SRC, "utf8").split("\n").filter(Boolean);
const rows: Raw[] = lines.map((l) => JSON.parse(l));
const medical = rows.filter((r) => !DENTAL.has(r.metal_level));

type YearAgg = {
  plan_year: number; claims_year: number;
  rx_in: number; den_in: number; den_rate: number | null;
  rx_out: number | null; den_out: number | null; den_rate_out: number | null;
  appeals_filed: number | null; appeals_overturned: number | null; appeals_overturn_rate: number | null;
  ext_filed: number | null; ext_overturned: number | null; ext_overturn_rate: number | null;
  policy_url: string | null; plan_count: number;
  plans: { plan_id: string; plan_type: string; metal_level: string; plan_den_in: number | null }[];
};
type IssuerRow = {
  key: string; slug: string; issuer_id: number; issuer_name: string; state: string;
  latest_year: number; years: Record<string, YearAgg>;
};

const byKey = new Map<string, IssuerRow>();
for (const r of medical) {
  const key = `${r.issuer_id}-${r.state}`;
  let row = byKey.get(key);
  if (!row) {
    row = { key, slug: "", issuer_id: r.issuer_id, issuer_name: r.issuer_name, state: r.state, latest_year: 0, years: {} };
    byKey.set(key, row);
  }
  const y = String(r.plan_year);
  let ya = row.years[y];
  if (!ya) {
    ya = {
      plan_year: r.plan_year, claims_year: r.plan_year - 2,
      rx_in: r.rx_in ?? 0, den_in: r.den_in ?? 0, den_rate: pct(r.den_in, r.rx_in),
      rx_out: r.rx_out, den_out: r.den_out, den_rate_out: pct(r.den_out, r.rx_out),
      appeals_filed: r.appeals_filed, appeals_overturned: r.appeals_overturned,
      appeals_overturn_rate: pct(r.appeals_overturned, r.appeals_filed) ?? (r.appeals_overturn_pct != null ? r.appeals_overturn_pct / 100 : null),
      ext_filed: r.ext_filed, ext_overturned: r.ext_overturned,
      ext_overturn_rate: pct(r.ext_overturned, r.ext_filed) ?? (r.ext_overturn_pct != null ? r.ext_overturn_pct / 100 : null),
      policy_url: r.url_claims_payment_policies || null, plan_count: 0, plans: [],
    };
    row.years[y] = ya;
  }
  ya.plan_count += 1;
  ya.plans.push({ plan_id: r.plan_id, plan_type: r.plan_type, metal_level: r.metal_level, plan_den_in: r.plan_den_in });
  if (r.plan_year > row.latest_year) { row.latest_year = r.plan_year; row.issuer_name = r.issuer_name; }
}

// Slugs: from the latest issuer name; disambiguate collisions within a state.
const issuers = [...byKey.values()].sort((a, b) => a.state.localeCompare(b.state) || a.issuer_name.localeCompare(b.issuer_name));
const seen = new Map<string, number>();
for (const it of issuers) {
  const base = slugify(it.issuer_name);
  const k = `${it.state}/${base}`;
  const n = (seen.get(k) || 0) + 1; seen.set(k, n);
  it.slug = n === 1 ? base : `${base}-hios-${it.issuer_id}`;
  for (const y of Object.values(it.years)) y.plans.sort((a, b) => a.plan_id.localeCompare(b.plan_id));
}
// Second pass: if a base slug collided, the FIRST one also needs the suffix for symmetry.
for (const it of issuers) {
  const base = slugify(it.issuer_name);
  if ((seen.get(`${it.state}/${base}`) || 0) > 1 && !it.slug.includes("-hios-")) it.slug = `${base}-hios-${it.issuer_id}`;
}

const years = [...new Set(medical.map((r) => r.plan_year))].sort();
const out = {
  meta: {
    generated_at: new Date().toISOString().slice(0, 10),
    source_name: "CMS Transparency in Coverage Public Use File (Health Insurance Exchange PUFs)",
    source_url: "https://data.healthcare.gov/dataset/230fcdc8-3a0b-48d5-98d9-36744a87906e",
    dictionary_url: "https://www.cms.gov/files/document/transparency-coverage-puf-datadictionary-py25.pdf",
    puf_index_url: "https://www.cms.gov/marketplace/resources/data/public-use-files",
    plan_years: years,
    claims_years: Object.fromEntries(years.map((y) => [String(y), y - 2])),
    states: [...new Set(medical.map((r) => r.state))].sort(),
    dropped_dental_rows: rows.length - medical.length,
    source_rows: rows.length,
    issuer_state_pairs: issuers.length,
    license: "CC BY 4.0 for Apellica's derived tables; underlying CMS data is public domain",
  },
  issuers,
};
fs.writeFileSync(OUT, JSON.stringify(out));
const both = issuers.filter((i) => Object.keys(i.years).length === 2).length;
console.log(`rows=${rows.length} medical=${medical.length} dropped_dental=${rows.length - medical.length} issuer_state_pairs=${issuers.length} with_both_years=${both} states=${out.meta.states.length} -> ${OUT} (${(fs.statSync(OUT).size / 1024).toFixed(0)} KB)`);
