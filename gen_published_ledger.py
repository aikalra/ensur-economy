"""Writes docs/live_ledger.json: the PUBLISHED ledger artifact.
The canonical ledger (full history, every month) stays on the box and keeps growing;
the published copy is a rolling window so the dashboard write path stays small:
cumulative totals + per-product maps + the last 12 months of history."""
import json
WINDOW = 12
L = json.load(open("econ_state/ledger.json"))
out = {
    "note": "Rolling published artifact: cumulative totals plus the last %d months. The complete hash-chained history is canonical in the engine db on the build box." % WINDOW,
    "cycle": L["cycle"],
    "audit_valid": L["audit_valid"],
    "gpv_total": sum(L["gpv_by_product"].values()),
    "fees_total": sum(L["fees_by_product"].values()),
    "leaked_total": sum(L["leaked_by_product"].values()),
    "gpv_by_product": L["gpv_by_product"],
    "fees_by_product": L["fees_by_product"],
    "leaked_by_product": L["leaked_by_product"],
    "history": L["history"][-WINDOW:],
}
json.dump(out, open("docs/live_ledger.json", "w"), indent=1)
print("published ledger: cycle", out["cycle"], "| history months:", len(out["history"]))
