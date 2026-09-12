"""Verified workflows as mini-businesses (user steering 2026-09-12 ~9:02 AM):
"the core of ensur is how you make everything into a mini business, into workflows. Verified workflows."
"If you treat everything as a micro business, you have to have all the security layers, the verification layers, everything."

Two outputs:
1. WORKFLOW ANATOMY: each product = an ordered verification/security stack (its real rule pack).
2. MINI-BUSINESS P&L: what the workflow is worth to ONE business running it for 12 months.
Rates marked MEASURED come from the live ledger; the rest are labeled baseline assumptions.
"""
import json

led = json.load(open("econ_state/ledger.json"))
hist = led["history"]
FEE_RATE = 0.0025
COC = 0.12  # cost of capital p.a. (assumption)

def tot(prod, key):
    return sum(h.get(prod, {}).get(key, 0) for h in hist)

# measured rates from the running economy
m_cert = tot("merchant", "certified"); m_hold = tot("merchant", "hold")
m_settled = tot("merchant", "value_settled")
m_ticket = m_settled / max(m_cert, 1)                       # MEASURED avg merchant ticket
m_hold_rate = m_hold / max(m_cert + m_hold, 1)              # MEASURED merchant hold rate
t_cert = tot("trade", "certified"); t_settled = tot("trade", "value_settled_lakh") * 100000
t_deal = t_settled / max(t_cert, 1)                         # MEASURED avg trade deal
h_cert = tot("hospital", "certified"); h_hold = tot("hospital", "hold")
h_hold_rate = h_hold / max(h_cert + h_hold, 1)              # MEASURED hospital hold rate

ANATOMY = {
 "welfare": ["welfare_eligible", "registry_valid", "name_match", "property_limit",
             "trade_conflict_clear", "account_concentration", "identity_unique_on_rolls", "liveness_recent"],
 "hospital": ["empanelled_hospital", "patient_real", "patient_alive", "billing_matches_record",
              "no_concurrent_admission", "liveness_recent"],
 "merchant": ["merchant_kyb", "delivery_scanned", "route_physically_plausible", "delivered_at_buyer",
              "no_buyer_dispute", "counterparty_independent_device", "no_money_loop"],
 "trade": ["shipment_filed_with_customs", "invoice_matches_customs", "condition_maintained",
           "physical_custody_predates_docs", "payee_registry_valid", "doc_uniqueness_global"],
 "crop": ["trigger_confirmed", "payee_alive", "land_verified", "acreage_consistent",
          "name_match", "identity_unique_on_rolls", "account_concentration"],
}

# baseline assumptions (same labeled set as continuous.py)
BASE_DAYS = {"welfare": 45, "hospital": 2, "merchant": 2, "trade": 7, "crop": 180}
BASE_COST = {"welfare": 300, "hospital": 150, "merchant": 5, "trade": 2000, "crop": 500}

def pl(name, product, monthly_volume, unit_value, note):
    """12-month P&L for one business running this verified workflow."""
    year_value = monthly_volume * unit_value * 12
    fees = year_value * FEE_RATE
    capital_gain = year_value * BASE_DAYS[product] / 365 * COC
    cost_savings = monthly_volume * 12 * BASE_COST[product]
    net = capital_gain + cost_savings - fees
    return {"business": name, "workflow": product, "layers": len(ANATOMY[product]),
            "annual_value_certified": round(year_value), "fees_paid": round(fees),
            "capital_released_value": round(capital_gain), "cost_savings": round(cost_savings),
            "net_value": round(net), "roi_on_fees": round(net / max(fees, 1), 1), "note": note}

panel = [
 pl("Kirana merchant, 60 deliveries/mo", "merchant", 60, round(m_ticket),
    f"Avg ticket Rs {round(m_ticket):,} MEASURED in economy. Settles at the doorstep, not T+2. Hold rate {100*m_hold_rate:.1f}% MEASURED."),
 pl("Wheat farmer, 3 acres, 2 seasons", "crop", 0.5, 60000,
    "Parametric payout at the drought trigger; no claim filed, no 180-day survey wait. Satellite layer beats survey collusion."),
 pl("Empanelled hospital, 300 admissions/mo", "hospital", 300, 30000,
    f"Pre-auth at admission, not after 2-day manual review. Honest-delay rate {100*h_hold_rate:.2f}% MEASURED; genuine readmissions held, never denied."),
 pl("Textile exporter, 4 shipments/mo", "trade", 4, round(t_deal),
    f"Avg deal Rs {round(t_deal/100000,1)} lakh MEASURED. Finance releases at physical custody proof, not after 7-day document checking."),
 pl("Welfare household, Rs 2,000/mo", "welfare", 1, 2000,
    "Continuous certification: the benefit arrives every month the contract is true. Value is the 45-day enrollment wait removed and zero wrongful exclusion."),
]

# What the P&L teaches: one flat ad-valorem rate cannot fit every workflow.
# Sustainable price per workflow = value delivered / 3 (customer keeps 3x ROI), in the workflow's own unit.
TARGET_ROI = 3
pricing = {}
for p in panel:
    vd = p["capital_released_value"] + p["cost_savings"]
    sustainable = vd / TARGET_ROI
    pricing[p["workflow"]] = {
        "value_delivered_per_year": vd, "sustainable_fee_per_year": round(sustainable),
        "flat_fee_roi_at_025pct": p["roi_on_fees"],
        "verdict": ("ad-valorem 0.25% sustainable" if p["roi_on_fees"] >= TARGET_ROI
                    else "ad-valorem fails here - price per event, not per rupee")}
json.dump({"anatomy": ANATOMY, "panel": panel, "pricing_lesson": pricing,
           "measured": {"merchant_ticket": round(m_ticket), "merchant_hold_rate": round(m_hold_rate, 4),
                        "trade_deal_lakh": round(t_deal/100000, 2), "hospital_hold_rate": round(h_hold_rate, 4)},
           "assumptions": {"fee_rate": FEE_RATE, "cost_of_capital": COC,
                           "baseline_settle_days": BASE_DAYS, "baseline_cost_per_decision": BASE_COST}},
          open("workflow_panel.json", "w"), indent=2)
for p in panel:
    print(f"{p['business']}: net Rs {p['net_value']:,}/yr on Rs {p['fees_paid']:,} fees (ROI {p['roi_on_fees']}x)")
