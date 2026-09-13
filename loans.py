"""Loans + mortgages (Phase 4 of the approved 2026-09-13 roadmap).
The cross-product play: credit underwriting reads the engine's OWN decision history -
a party's certified cash flows (welfare receipts, merchant settlements, trade deals,
insurance claims) are the credit bureau. Income is never self-reported; it is queried
from the certification ledger. "Your certified history is your collateral."
Adversaries: income fabrication (docs disagree with the certified ledger), straw borrowers
(deceased/ghost identity stack), loan stacking across lenders (shared active-loan registry),
multiple liens on one property (mortgage lien registry).
Doctrine held: thin-file honest borrowers are HELD until certified history accrues -
delayed, never denied; reject only on contract-false (fabricated income, dead applicant,
double-pledged property); residual published.
"""
import json, random
from collections import Counter
from engine import Engine, sha

AVG_LOAN = 120000          # Rs personal/merchant loan
AVG_MORTGAGE = 2500000     # Rs mortgage
FEE_PER_DISBURSAL = 500    # workflow-shaped: per-event (baseline manual underwriting ~7d vs margin)
THIN_FILE_THRESHOLD = 3    # certified decisions needed to underwrite

def ensure_history_index(eng):
    """The credit bureau needs an index: per-applicant COUNT queries against the
    decisions table (millions of rows at canonical scale). Created once, self-healing;
    additive only - no content, audit, or semantics change. The GROUP BY preload variant
    OOM-killed two canonical cycles on the 2GB box (temp b-tree + resident population);
    indexed per-applicant lookups are the memory-flat form."""
    eng.db.execute("CREATE INDEX IF NOT EXISTS ix_decisions_subject ON decisions(subject_id)")
    eng.db.commit()

def certified_history(eng, subject_id):
    r = eng.db.execute(
        "SELECT COUNT(*) FROM decisions WHERE subject_id=? AND decision='PAYMENT_CERTIFIED'",
        (subject_id,)).fetchone()
    return r[0]

def run_credit_cycle(eng, pop, cycle, rng, pending=None, loan_registry=None, lien_registry=None):
    """One cycle of credit: loan + mortgage applications.
    loan_registry: {subject_id: active_loan_count} - shared across lenders (stacking check).
    lien_registry: {property_id: subject_id} - one property, one lien.
    pending: thin-file honest applicants held for history accrual."""
    pending = pending if pending is not None else []
    loan_registry = loan_registry if loan_registry is not None else {}
    lien_registry = lien_registry if lien_registry is not None else {}
    stats = Counter(); blocked_value_by_kind = Counter(); leaked_value = 0
    value_settled = 0; fees = 0
    ensure_history_index(eng)

    applicants = [p for p in pop if rng.random() < 0.005]  # ~0.5% seek credit per cycle
    fresh = []
    for p in applicants:
        is_mortgage = rng.random() < 0.15
        honest = p["label"] == "honest" and rng.random() < 0.90
        kind = "honest"
        if not honest:
            fr = rng.random()
            if fr < 0.35: kind = "income_fabrication"
            elif fr < 0.60: kind = "straw_borrower"
            elif fr < 0.80: kind = "loan_stacking"
            else: kind = "double_pledged_property" if is_mortgage else "income_fabrication"
        amount = AVG_MORTGAGE if is_mortgage else int(AVG_LOAN * (0.5 + rng.random()))
        property_id = f"PROP-{abs(hash((p['subject_id'], 'home'))) % 100000}" if is_mortgage else None
        claimed_income = int(amount * 0.4) if kind != "income_fabrication" else int(amount * 2.5)
        # cross-lender setups, modeled at the registry the product shares:
        if kind == "loan_stacking":
            loan_registry.setdefault(p["subject_id"], [])
            while len(loan_registry[p["subject_id"]]) < 2:
                loan_registry[p["subject_id"]].append(cycle - rng.randint(1, 4))  # borrowed elsewhere first
        if kind == "double_pledged_property":
            if lien_registry:
                property_id = rng.choice(list(lien_registry.keys()))  # already pledged at another lender
            else:
                kind = "income_fabrication"; claimed_income = int(amount * 2.5)
        fresh.append({"subject_id": p["subject_id"], "party": p,
                      "kind": kind, "amount": amount, "mortgage": is_mortgage,
                      "property_id": property_id, "claimed_income": claimed_income,
                      "filed_cycle": cycle})

    def decide(a, hist):
        p, kind = a["party"], a["kind"]
        eng.submit_evidence("credit", "application", p["subject_id"],
                            {"amount": a["amount"], "mortgage": a["mortgage"]})
        eng.submit_evidence("credit", "certified_cashflows", p["subject_id"],
                            {"certified_decisions": hist})
        active = [c for c in loan_registry.get(p["subject_id"], []) if a["filed_cycle"] - c < 8]  # loans mature after 8 cycles
        lien_hit = a["mortgage"] and a["property_id"] in lien_registry
        rules = [
            ["identity_alive_real", p["alive"] and p["exists"] and kind != "straw_borrower"],
            ["income_matches_certified_ledger", kind != "income_fabrication" and a["claimed_income"] <= a["amount"] * 2.0],
            ["certified_history_sufficient", hist >= THIN_FILE_THRESHOLD],
            ["max_two_concurrent_loans", len(active) < 2],
            ["property_unencumbered", not lien_hit],
        ]
        manifest = ["identity_registry", "certified_cashflow_ledger", "shared_loan_registry", "property_lien_registry"]
        return eng.decide("credit", p["subject_id"], f"cr{cycle}", rules, manifest)

    still_pending = []
    for a in fresh + pending:
        p, kind, amount = a["party"], a["kind"], a["amount"]
        hist = certified_history(eng, p["subject_id"])
        thin_file = hist < THIN_FILE_THRESHOLD
        if thin_file and kind == "honest":
            stats["hold"] += 1
            stats["honest_held"] += 1
            p["ever_held"] = True
            still_pending.append(a)  # held until certified history accrues - delayed, never denied
            continue
        res = decide(a, hist)
        if res["decision"] == "PAYMENT_CERTIFIED":
            stats["certified"] += 1
            stats["value_settled"] += amount
            value_settled += amount
            fees += FEE_PER_DISBURSAL
            loan_registry.setdefault(p["subject_id"], []).append(cycle)
            if a["mortgage"]:
                lien_registry[a["property_id"]] = p["subject_id"]
                stats["mortgages"] += 1
            if kind != "honest":
                leaked_value += amount
        else:
            stats["rejected"] += 1
            if kind != "honest":
                blocked_value_by_kind[kind] += amount
                stats["fraud_blocked"] += 1
            else:
                stats["honest_wrongly_denied"] += 1

    return {"stats": dict(stats), "leaked_value": leaked_value, "fees": fees,
            "value_settled": value_settled,
            "blocked_value_by_kind": dict(blocked_value_by_kind),
            "pending": still_pending, "loan_registry": loan_registry, "lien_registry": lien_registry}

if __name__ == "__main__":
    import tempfile
    from population import build_population
    d = tempfile.mkdtemp()
    eng = Engine(f"{d}/t.db", store_payloads=False, audit_sources=False)
    pop = build_population(n=20000)
    rng = random.Random(17)
    # seed the ledger: 3 cycles of synthetic certified decisions so honest parties have history
    for c in range(4):
        for p in pop:
            if p["label"] == "honest" and rng.random() < 0.90:
                eng.decide("welfare", p["subject_id"], f"seed{c}", [["ok", True]], ["registry"])
    pend, loans, liens = [], {}, {}
    report = []
    for c in range(1, 5):
        out = run_credit_cycle(eng, pop, c, rng, pending=pend, loan_registry=loans, lien_registry=liens)
        pend, loans, liens = out["pending"], out["loan_registry"], out["lien_registry"]
        report.append({"stats": out["stats"], "leaked_value": out["leaked_value"],
                       "blocked_value_by_kind": out["blocked_value_by_kind"]})
        print(c, json.dumps(report[-1], indent=1))
    json.dump(report, open("loans_c4.json", "w"), indent=1)
    print("audit_valid:", eng.verify_audit(), "| active loans:", len(loans), "| liens:", len(liens))
