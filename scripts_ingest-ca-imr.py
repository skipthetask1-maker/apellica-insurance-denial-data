#!/usr/bin/env python3
"""Ingest California DMHC Independent Medical Review determinations (public
CHHS open data, every decision since 2001) into Postgres for the Appeal
Outcomes Library (/appeal-outcomes). Aggregates only are published; per-
decision rows are stored for search and excerpting, never as pages.

Source: https://data.chhs.ca.gov/dataset/independent-medical-review-imr-determinations-trend
CSV columns: ReferenceID, ReportYear, DiagnosisCategory, DiagnosisSubCategory,
TreatmentCategory, TreatmentSubCategory, Determination, Type, AgeRange,
PatientGender, IMRType, DaysToReview, DaysToAdopt, Findings.

Argument tags are keyword matches on the reviewer's findings text (see TAGS);
they describe what the findings mention, not why the case was decided.

Cron (VPS, monthly): 5 5 3 * * REFRESH=1 /usr/bin/python3 <repo>/scripts/data/ingest-ca-imr.py >> /var/log/apellica-imr-ingest.log 2>&1
"""
import csv, hashlib, os, re, subprocess, time, urllib.request
from datetime import datetime, timezone

DATA_DIR = os.environ.get("DATA_DIR", "/root/apellica-data/imr")
CSV_URL = "https://data.chhs.ca.gov/dataset/b79b3447-4c10-4ae6-84e2-1076f83bb24e/resource/3340c5d7-4054-4d03-90e0-5f44290ed095/download/independent-medical-review-imr-determinations-trends.csv"
REFRESH = os.environ.get("REFRESH") == "1"
DOCKER_PSQL = ["docker", "exec", "-i", "apellica-pg-prod", "psql", "-U", "apellica", "-d", "apellica", "-v", "ON_ERROR_STOP=1", "-q"]
csv.field_size_limit(10**9)

# Keep in sync with lib/data/imr-tags.ts (the UI labels). Order matters only for display.
TAGS = {
    "prior_therapies_failed": r"(failed|did not respond|refractory|inadequate response|not (been )?effective|unsuccessful)\b.{0,60}\b(therap|treatment|medication|trial|regimen)",
    "contraindicated": r"contraindicat",
    "guidelines_support": r"(guideline|criteria|consensus|standard of care|recommend)s?\b.{0,40}\b(support|recommend|indicate|met|satisf)",
    "literature": r"(peer[- ]reviewed|published|scientific|medical) (literature|studies|evidence)",
    "fda_label": r"\bFDA[- ]approved|off[- ]label",
    "no_alternative": r"no (reasonable|appropriate|safe|other|alternative) (alternative|option|treatment)",
    "records_lacking": r"(record|documentation|information)s? (does not|did not|do not|fail(s|ed)? to|is insufficient|was insufficient|lack)",
    "experimental": r"experimental|investigational",
    "step_therapy": r"step therapy|fail(ed)? first|first[- ]line (agent|therapy|treatment)",
    "urgent": r"\burgent|emergen(t|cy)",
}
TAG_RX = {k: re.compile(v, re.I) for k, v in TAGS.items()}

DDL = """
CREATE TABLE IF NOT EXISTS imr_decisions (
  reference_id   TEXT PRIMARY KEY,
  report_year    INT,
  dx_cat         TEXT, dx_sub TEXT, tx_cat TEXT, tx_sub TEXT,
  dx_cat_slug    TEXT, tx_sub_slug TEXT,
  determination  TEXT, decision_type TEXT, age_range TEXT, gender TEXT, imr_type TEXT,
  days_to_review INT, days_to_adopt INT,
  findings       TEXT,
  overturned     BOOL,
  tags           TEXT[] NOT NULL DEFAULT '{}',
  findings_tsv   TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', coalesce(findings, ''))) STORED,
  ingested_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS imr_decisions_tsv ON imr_decisions USING GIN (findings_tsv);
CREATE INDEX IF NOT EXISTS imr_decisions_tags ON imr_decisions USING GIN (tags);
CREATE INDEX IF NOT EXISTS imr_decisions_txdx ON imr_decisions (tx_sub_slug, dx_cat_slug);
CREATE INDEX IF NOT EXISTS imr_decisions_year ON imr_decisions (report_year);
CREATE TABLE IF NOT EXISTS imr_sources (source TEXT PRIMARY KEY, downloaded_at TIMESTAMPTZ, sha256 TEXT, row_count INT);
"""

MV = """
DROP MATERIALIZED VIEW IF EXISTS imr_aggregates;
CREATE MATERIALIZED VIEW imr_aggregates AS
SELECT tx_sub_slug, dx_cat_slug, min(tx_sub) AS tx_sub, min(dx_cat) AS dx_cat,
       count(*)::int AS n, sum(CASE WHEN overturned THEN 1 ELSE 0 END)::int AS overturned,
       min(report_year) AS year_min, max(report_year) AS year_max,
       sum(CASE WHEN decision_type ILIKE 'medical necessity%' THEN 1 ELSE 0 END)::int AS n_med_nec,
       sum(CASE WHEN decision_type ILIKE 'experimental%' THEN 1 ELSE 0 END)::int AS n_experimental,
       sum(CASE WHEN decision_type ILIKE 'urgent%' THEN 1 ELSE 0 END)::int AS n_urgent,
       sum(CASE WHEN report_year >= extract(year FROM now())::int - 5 THEN 1 ELSE 0 END)::int AS n_recent,
       sum(CASE WHEN report_year >= extract(year FROM now())::int - 5 AND overturned THEN 1 ELSE 0 END)::int AS overturned_recent
FROM imr_decisions
WHERE tx_sub_slug <> '' AND dx_cat_slug <> ''
GROUP BY tx_sub_slug, dx_cat_slug;
CREATE UNIQUE INDEX IF NOT EXISTS imr_aggregates_key ON imr_aggregates (tx_sub_slug, dx_cat_slug);

DROP MATERIALIZED VIEW IF EXISTS imr_tag_stats;
CREATE MATERIALIZED VIEW imr_tag_stats AS
SELECT tx_sub_slug, dx_cat_slug, t.tag,
       count(*)::int AS n, sum(CASE WHEN overturned THEN 1 ELSE 0 END)::int AS overturned
FROM imr_decisions d, unnest(d.tags) AS t(tag)
WHERE tx_sub_slug <> '' AND dx_cat_slug <> ''
GROUP BY tx_sub_slug, dx_cat_slug, t.tag;
CREATE INDEX IF NOT EXISTS imr_tag_stats_key ON imr_tag_stats (tx_sub_slug, dx_cat_slug);

DROP MATERIALIZED VIEW IF EXISTS imr_treatments;
CREATE MATERIALIZED VIEW imr_treatments AS
SELECT tx_sub_slug, min(tx_sub) AS tx_sub, min(tx_cat) AS tx_cat, count(*)::int AS n,
       sum(CASE WHEN overturned THEN 1 ELSE 0 END)::int AS overturned, min(report_year) AS year_min, max(report_year) AS year_max
FROM imr_decisions WHERE tx_sub_slug <> '' GROUP BY tx_sub_slug;
CREATE UNIQUE INDEX IF NOT EXISTS imr_treatments_key ON imr_treatments (tx_sub_slug);
"""

def psql(script: str) -> str:
    p = subprocess.run(DOCKER_PSQL, input=script, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip()[:600])
    return p.stdout

def esc(v):
    if v is None or v == "" or v == "\\N": return "\\N"
    return str(v).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")

def slugify(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower().replace("&", " and ").replace("/", " "))).strip("-")

def int_or_null(v):
    v = (v or "").strip()
    return v if re.fullmatch(r"-?\d+", v) else "\\N"

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "imr.csv")
    if REFRESH or not os.path.exists(path):
        req = urllib.request.Request(CSV_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=900) as r, open(path, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk: break
                f.write(chunk)
        print("downloaded", path)
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    psql(DDL)
    prev = psql("SELECT sha256 FROM imr_sources WHERE source = 'ca_dmhc_imr';").strip()
    if prev == sha and not os.environ.get("FORCE"):
        print("unchanged since last ingest (sha match); nothing to do"); return

    rows = []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            ref = (r.get("ReferenceID") or "").strip()
            if not ref: continue
            findings = (r.get("Findings") or "").strip()
            det = (r.get("Determination") or "").strip()
            overturned = "t" if det.lower().startswith("overturned") else ("f" if det.lower().startswith("upheld") else "\\N")
            tags = [k for k, rx in TAG_RX.items() if rx.search(findings)]
            rows.append([ref, int_or_null(r.get("ReportYear")), r.get("DiagnosisCategory"), r.get("DiagnosisSubCategory"), r.get("TreatmentCategory"), r.get("TreatmentSubCategory"),
                         slugify(r.get("DiagnosisCategory")), slugify(r.get("TreatmentSubCategory")),
                         det, r.get("Type"), r.get("AgeRange"), r.get("PatientGender"), r.get("IMRType"),
                         int_or_null(r.get("DaysToReview")), int_or_null(r.get("DaysToAdopt")), findings, overturned,
                         "{" + ",".join('"' + t + '"' for t in tags) + "}"])
    print("rows parsed", len(rows))
    cols = "(reference_id, report_year, dx_cat, dx_sub, tx_cat, tx_sub, dx_cat_slug, tx_sub_slug, determination, decision_type, age_range, gender, imr_type, days_to_review, days_to_adopt, findings, overturned, tags)"
    data = "".join("\t".join(esc(c) for c in r) + "\n" for r in rows)
    script = (
        "BEGIN;\n"
        "CREATE TEMP TABLE imr_stage (LIKE imr_decisions INCLUDING DEFAULTS EXCLUDING GENERATED);\n"
        f"COPY imr_stage {cols} FROM STDIN WITH (FORMAT text);\n" + data + "\\.\n"
        "DELETE FROM imr_stage a USING imr_stage b WHERE a.reference_id = b.reference_id AND a.ctid < b.ctid;\n"
        f"INSERT INTO imr_decisions {cols} SELECT reference_id, report_year, dx_cat, dx_sub, tx_cat, tx_sub, dx_cat_slug, tx_sub_slug, determination, decision_type, age_range, gender, imr_type, days_to_review, days_to_adopt, findings, overturned, tags FROM imr_stage "
        "ON CONFLICT (reference_id) DO UPDATE SET report_year = EXCLUDED.report_year, dx_cat = EXCLUDED.dx_cat, dx_sub = EXCLUDED.dx_sub, tx_cat = EXCLUDED.tx_cat, tx_sub = EXCLUDED.tx_sub, dx_cat_slug = EXCLUDED.dx_cat_slug, tx_sub_slug = EXCLUDED.tx_sub_slug, determination = EXCLUDED.determination, decision_type = EXCLUDED.decision_type, age_range = EXCLUDED.age_range, gender = EXCLUDED.gender, imr_type = EXCLUDED.imr_type, days_to_review = EXCLUDED.days_to_review, days_to_adopt = EXCLUDED.days_to_adopt, findings = EXCLUDED.findings, overturned = EXCLUDED.overturned, tags = EXCLUDED.tags, ingested_at = now();\n"
        f"INSERT INTO imr_sources (source, downloaded_at, sha256, row_count) VALUES ('ca_dmhc_imr', now(), '{sha}', {len(rows)}) ON CONFLICT (source) DO UPDATE SET downloaded_at = now(), sha256 = EXCLUDED.sha256, row_count = EXCLUDED.row_count;\n"
        "COMMIT;\n" + MV +
        "ANALYZE imr_decisions;\n"
        "SELECT count(*) AS decisions, sum(CASE WHEN overturned THEN 1 ELSE 0 END) AS overturned, min(report_year), max(report_year) FROM imr_decisions;\n"
        "SELECT count(*) AS combos, sum(CASE WHEN n >= 20 THEN 1 ELSE 0 END) AS combos_n20 FROM imr_aggregates;\n"
    )
    t0 = time.time()
    print(psql(script).strip())
    print(f"done in {time.time() - t0:.0f}s at {datetime.now(timezone.utc).isoformat()}")

if __name__ == "__main__":
    main()
