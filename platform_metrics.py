"""Phase 6 - platform synthesis: reads the canonical ledger after a cycle and emits
econ_state/platform_metrics.json. Pure derivation - no rng, no engine writes.
The questions this answers from the RUNNING economy, not from a pitch deck:
  1. Stripe question: what does the rail earn per rupee moved? (take rate per product)
  2. Shopify/Uber question: how much of the flow is party-to-party commerce the rail
     enables (merchant, agent commerce, workflows, trade) vs institutional disbursement?
  3. Airbnb question: is new supply forming? (month-over-month GPV growth per product)
"""
import json

P2P = ("merchant", "agent_commerce", "workflows", "trade")
INSTITUTIONAL = ("welfare", "hospital", "insurance", "credit", "certifications", "crop")

def compute(ledger_path="econ_state/ledger.json", out_path="econ_state/platform_metrics.json"):
    L = json.load(open(ledger_path))
    gpv = L["gpv_by_product"]
    hist = L["history"]
    # module-real fees: the per-cycle fees_shaped entries, summed - NOT the uniform
    # 25bps modeling layer in fees_by_product. Credit charges per disbursal, workflows
    # take 30bps of settled milestones, certification products run at 25bps.
    fees = {}
    for e in hist:
        for k, v in (e.get("fees_shaped") or {}).items():
            fees[k] = fees.get(k, 0) + v
    tot_gpv = sum(gpv.values()); tot_fees = sum(fees.values())
    take = {k: round(1e4 * fees.get(k, 0) / gpv[k], 1) for k in gpv if gpv.get(k, 0) > 0}
    p2p = sum(gpv.get(k, 0) for k in P2P)
    # month-over-month GPV from the last two cycles' per-product totals are not stored
    # per cycle in the cumulative maps, so read cycle-level settled value where present:
    def cycle_gpv(e):
        return sum((v or {}).get("value_settled", 0) + (v or {}).get("value_settled_lakh", 0) * 100000
                   for k, v in e.items() if isinstance(v, dict))
    mom = None
    if len(hist) >= 2:
        a, b = cycle_gpv(hist[-2]), cycle_gpv(hist[-1])
        if a > 0: mom = round(100.0 * (b - a) / a, 2)
    out = {
        "cycle": L["cycle"], "audit_valid": L["audit_valid"],
        "take_rate_bps_by_product": take,
        "take_rate_bps_overall": round(1e4 * tot_fees / tot_gpv, 1),
        "p2p_share_pct": round(100.0 * p2p / tot_gpv, 1),
        "p2p_gpv_crore": round(p2p / 1e7, 1),
        "institutional_gpv_crore": round((tot_gpv - p2p) / 1e7, 1),
        "gpv_total_crore": round(tot_gpv / 1e7, 1),
        "fees_total_crore": round(tot_fees / 1e7, 2),
        "gpv_mom_pct": mom,
    }
    json.dump(out, open(out_path, "w"), indent=1)
    return out

if __name__ == "__main__":
    print(json.dumps(compute(), indent=1))
