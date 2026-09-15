# Apellica open data: U.S. health insurance denials and appeals

Reproducible tabulations of three public records, published by [Apellica](https://apellica.com/research) under CC BY 4.0.

| File | What it is | Source | Page |
|---|---|---|---|
| `insurer-denial-rates.csv` | One row per issuer-year: in-network claims received/denied, internal appeals filed/overturned, external reviews, for every HealthCare.gov medical issuer, plan years 2024 to 2026 (2022 to 2024 claims) | CMS Transparency in Coverage public use files | https://apellica.com/insurer-denial-rates |
| `insurer-denial-rates.dataset.json` | schema.org Dataset descriptor with methodology and caveats | same | same |
| `state-denial-rankings-2024-claims.csv` | 30 HealthCare.gov states ranked by median issuer denial rate, pooled rates, appeals per 1,000 denials | same | https://apellica.com/research/state-denial-rankings-2026 |
| `denial-rate-changes-2023-2024.csv` | Year-over-year change for 149 issuer filings present in both years | same | https://apellica.com/research/denial-rate-changes-2026 |
| `appeal-participation-2024.csv` | Appeals per 1,000 denials and overturn rates by issuer | same | https://apellica.com/research/appeal-participation-gap-2026 |
| `california-imr-aggregates.csv` | 42,710 California Independent Medical Review decisions aggregated by treatment × diagnosis (n, overturned, years, argument tags) | California DMHC IMR determinations (CHHS Open Data) | https://apellica.com/appeal-outcomes |
| `california-imr.dataset.json` | Dataset descriptor | same | same |
| `external-review-index.csv` | State external-review totals and reversal rates from regulators' annual reports; gaps shown as gaps | state regulators | https://apellica.com/external-review-index |
| `scripts_tic_to_ndjson.py` | Converts the CMS PUF xlsx files (Ind QHP + SHOP sheets) to NDJSON | | |
| `scripts_build-insurer-denial-rates.ts` | Aggregates the NDJSON to issuer-year rows (drops stand-alone dental) | | |
| `scripts_ingest-ca-imr.py` | Downloads and loads the DMHC IMR CSV, tags findings, builds aggregates | | |

## Limits, stated plainly
- CMS figures are self-reported by issuers at the issuer-and-state level and cover HealthCare.gov plans only (32 states). "Denied" includes duplicate, administrative and eligibility denials. The file for plan year Y carries claims from year Y-2. Rankings use filings with at least 1,000 in-network claims.
- The California IMR record is the population of cases that reached independent review, not a sample of all denials. A decision counts as overturned when the plan was reversed in whole or in part. Combinations under 5 decisions are not published.
- Nothing here predicts an individual claim. It describes populations.

## Citation
Apellica (2026). Apellica open data: U.S. health insurance denials and appeals, v1.0 (2026-09-15). https://github.com/skipthetask1-maker/apellica-insurance-denial-data and https://apellica.com/research. CC BY 4.0.

Corrections: editorial@apellica.com. Press: press@apellica.com. Apellica is an appeal-preparation service, not a law firm.
