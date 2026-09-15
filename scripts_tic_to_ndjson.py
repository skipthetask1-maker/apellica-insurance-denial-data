#!/usr/bin/env python3
# CMS Transparency in Coverage PUF (xlsx) -> denials.ndjson rows in the shape
# scripts/data/build-insurer-denial-rates.ts expects. Individual QHP + SHOP
# sheets are medical; the SADP sheet is stand-alone dental and is skipped
# (the build script also drops metal levels Low/High as a second guard).
import glob, json, re, sys
import openpyxl
OUT = "/root/apellica-data/tic/denials.ndjson"
NULLS = {"*", "**", "***", "N/A", "", None, "Missing URL"}
def num(v):
    if v in NULLS: return None
    if isinstance(v, float) and v != v: return None
    if isinstance(v, (int, float)): return v
    s = str(v).strip().replace(",", "").replace("%", "")
    try:
        f = float(s); return int(f) if f.is_integer() else f
    except ValueError: return None
def txt(v): return None if v in NULLS else str(v).strip()
COLS = {
 "State":"state","Issuer_Name":"issuer_name","Issuer_ID":"issuer_id","Plan_ID":"plan_id","Plan_Type":"plan_type","Metal_Level":"metal_level",
 "URL_Claims_Payment_Policies":"url_claims_payment_policies",
 "Issuer_Claims_Received_In_Network":"rx_in","Issuer_Claims_Received_Out_of_Network":"rx_out",
 "Issuer_Claims_Denied_In_Network":"den_in","Issuer_Claims_Denied_Out_of_Network":"den_out",
 "Issuer_Internal_Appeals_Filed":"appeals_filed","Issuer_Number_Internal_Appeals_Overturned":"appeals_overturned","Issuer_Percent_Internal_Appeals_Overturned":"appeals_overturn_pct",
 "Issuer_External_Appeals_Filed":"ext_filed","Issuer_Number_External_Appeals_Overturned":"ext_overturned","Issuer_Percent_External_Appeals_Overturned":"ext_overturn_pct",
 "Plan_Number_Claims_Denied_In_Network":"plan_den_in","Plan_Number_Claims_Denied_Out_of_Network":"plan_den_out",
 "Plan_Number_Claims_Denied_Referral_Required":"r_referral","Plan_Number_Claims_Denied_Due_To_Out_Of_Network":"r_oon",
 "Plan_Number_Claims_Denied_Services_Excluded":"r_excluded","Plan_Number_Claims_Denied_Not_Medically_Necessary_Excluding_Behavioral_Health":"r_med_nec",
 "Plan_Number_Claims_Denied_Not_Medically_Necessary_Behavioral_Health_Only":"r_med_nec_bh",
 "Plan_Number_Claims_Denied_Due_To_Enrolle_Benefit_Limit_Reached":"r_benefit_limit","Plan_Number_Claims_Denied_Due_To_Member_Not_Covered":"r_not_covered",
 "Plan_Number_Claims_Denied_Due_To_Investigational_Experimental_Cosmetic_Proceduce":"r_experimental",
 "Plan_Number_Claims_Denied_Due_To_Administrative_Reason":"r_admin","Plan_Number_Claims_Denied_Other":"r_other",
 "Average Monthly Enrollment":"enrollment",
}
TEXT = {"state","issuer_name","plan_id","plan_type","metal_level","url_claims_payment_policies"}
n = 0; per = {}
with open(OUT, "w") as out:
    for f in sorted(glob.glob("/root/apellica-data/tic/20*/*.xlsx")):
        year = int(re.search(r"/(20\d\d)/", f).group(1))
        wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
        for ws in wb.worksheets:
            t = ws.title.lower()
            if "sadp" in t or "disclaimer" in t: continue
            market = "shop" if "shop" in t else "individual"
            rows = ws.iter_rows(values_only=True)
            hdr = None
            for row in rows:
                if row and any(isinstance(c, str) and c.strip() == "Issuer_Name" for c in row) and any(isinstance(c, str) and c.strip() == "State" for c in row):
                    hdr = [c.strip() if isinstance(c, str) else c for c in row]; break
            assert hdr, f"header not found in {f} {ws.title}"
            idx = {h: i for i, h in enumerate(hdr) if h}
            missing = [c for c in COLS if c not in idx]
            if missing: print("NOTE", f, ws.title, "missing columns:", missing)
            for row in rows:
                if not row or row[idx["State"]] in NULLS: continue
                rec = {"plan_year": year, "market": market}
                for src, dst in COLS.items():
                    v = row[idx[src]] if src in idx else None
                    rec[dst] = txt(v) if dst in TEXT else num(v)
                rec["issuer_id"] = int(rec["issuer_id"]) if rec["issuer_id"] is not None else None
                if rec["issuer_id"] is None or not rec["state"]: continue
                for k, v in list(rec.items()):
                    if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))): rec[k] = None
                out.write(json.dumps(rec, allow_nan=False) + "\n"); n += 1
                per.setdefault(year, set()).add((rec["issuer_id"], rec["state"]))
print("rows", n, {y: len(s) for y, s in per.items()})
