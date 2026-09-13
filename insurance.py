"""Insurance underwriting + claims (Phase 2 of the approved 2026-09-13 roadmap).
Generalizes the hospital/crop claims stacks into carrier-grade P&C:
UNDERWRITING certifies risk facts at bind time (identity registry, liveness, property
corroborant, prior-claims history); CLAIMS run the evidence stack plus cross-insurer
duplicate detection (trade's global-uniqueness pattern) against staged-loss, inflated,
duplicate, provider-collusion and ghost-policy adversaries.
Doctrine held: HOLD for unproven, reject only on contract-false; the corroborant is a
physical signal that PREDATES the claim; the corroborant lag is the published structural
residual (honest claimants delayed, never denied).
"""
import json, random, hashlib
from collections import Counter
from engine import Engine, sha

AVG_PREMIUM = 1200          # Rs per policy per quarter (synthetic market unit)
AVG_CLAIM = 45000           # Rs average certified payout
CORROBORANT_LAG_CYCLES = 2  # physical signal lands 1-2 cycles after the event

def run_quarter(eng, pop, cycle, rng, pending=None, registry=None):
    """One quarter of carrier activity: bind new policies, process claims.
    pending: claims held awaiting the corroborant (list of claim dicts).
    registry: shared cross-insurer loss-event registry {loss_hash: insurer_id} persisted
    in the ledger - one loss, one claim, whichever insurer sees it first."""
    pending = pending if pending is not None else []
    registry = registry if registry is not None else {}
    stats = Counter(); blocked_value_by_kind = Counter(); leaked_value = 0

    # ---------- underwriting: a slice of parties applies for cover ----------
    applicants = [p for p in pop if rng.random() < 0.012]  # ~1.2% shop per quarter
    policies = []
    for p in applicants:
        eng.submit_evidence("insurance", "identity_registry", p["subject_id"],
                            {"alive": p["alive"], "exists": p["exists"], "name": p["name"]})
        eng.submit_evidence("insurance", "liveness", p["subject_id"],
                            {"auth": rng.random() < p["genuine_auth_p"]})
        eng.submit_evidence("insurance", "property_registry", p["subject_id"],
                            {"over_ceiling": p["property_over_ceiling"]})
        rules = [
            ["identity_registered_alive", p["alive"] and p["exists"]],
            ["liveness_recent", p["cycles_inactive"] < 6],
            ["property_within_ceiling", not p["property_over_ceiling"]],
            ["no_business_conflict", not p["business_conflict"]],
        ]
        res = eng.decide("insurance", p["subject_id"], f"q{cycle}", rules,
                         ["identity_registry", "liveness", "property_registry"])
        if res["decision"] == "PAYMENT_CERTIFIED":
            stats["policies_bound"] += 1
            policies.append(p)
        else:
            # underwriting rejects at bind time are the product working (ghost/deceased
            # applicants never get paper) - count separately from claims decisions
            stats["applications_declined"] += 1
            if p["label"] in ("ghost", "deceased_on_rolls", "duplicate_identity"):
                blocked_value_by_kind["ghost_application"] += AVG_PREMIUM
            elif not p["alive"] or not p["exists"]:
                blocked_value_by_kind["ghost_application"] += AVG_PREMIUM
            else:
                stats["honest_application_declined"] += 1

    # ---------- claims: filed against bound policies ----------
    claims_open = []
    for p in policies:
        if rng.random() < 0.06:  # ~6% of new policies see a claim this quarter
            honest = p["label"] in ("honest", "acreage_fraud") and rng.random() < 0.90
            loss_id = sha({"event": "loss", "subject": p["subject_id"], "cycle": cycle,
                           "roll": rng.random()})
            kind = "honest"
            amount = AVG_CLAIM * (0.6 + rng.random())
            if not honest:
                r = rng.random()
                if r < 0.30: kind, amount = "staged_loss", AVG_CLAIM * (0.6 + rng.random())
                elif r < 0.55: kind, amount = "inflated_claim", AVG_CLAIM * (2.2 + rng.random())
                elif r < 0.75: kind = "duplicate_cross_insurer"
                elif r < 0.90: kind, amount = "provider_collusion", AVG_CLAIM * (1.4 + rng.random())
                else: kind = "staged_loss"
            real_event = kind != "staged_loss"  # a staged loss has no physical event
            claims_open.append({"party": p, "kind": kind, "amount": round(amount),
                                "loss_id": loss_id, "filed_cycle": cycle,
                                "real_event": real_event,
                                "corroborant_due": (cycle + (1 if rng.random() < 0.5 else 2)) if real_event else None})

    # ---------- decide claims: new filings + held claims whose corroborant landed ----------
    # Contract: a certifiable claim requires a physical corroborant for a REAL event.
    # Staged losses never corroborate; past the deadline (due + 1 grace cycle) a claim with
    # no physical signal is contract-false and is REJECTED - never paid on timeout.
    # Duplicate cross-insurer: the other carrier registered the same loss first.
    def decide_claim(c, corroborant_present, deadline_passed, dup_hit):
        p, amount = c["party"], c["amount"]
        eng.submit_evidence("insurance", "claim_dossier", p["subject_id"],
                            {"loss_id": c["loss_id"], "amount": amount})
        rules = [
            ["policy_in_force", True],  # filed against a policy bound this quarter
            ["physical_event_within_deadline", corroborant_present or not deadline_passed],
            ["amount_within_estimate_band", amount <= AVG_CLAIM * 2.0],
            ["not_duplicate_across_insurers", not dup_hit],
            ["provider_billing_consistent", c["kind"] != "provider_collusion"],
        ]
        res = eng.decide("insurance", p["subject_id"], f"q{cycle}-claim", rules,
                         ["claim_dossier", "physical_corroborant", "shared_loss_registry"])
        if res["decision"] == "PAYMENT_CERTIFIED" and not corroborant_present:
            # unproven is never paid: certification requires the corroborant itself
            return {"decision": "HOLD"}, dup_hit
        return res, dup_hit

    still_pending = []
    for c in claims_open + pending:
        if c["kind"] == "duplicate_cross_insurer" and c["loss_id"] not in registry:
            registry[c["loss_id"]] = "insurer-B"  # the other carrier saw it first
        corroborant_present = c["real_event"] and c["corroborant_due"] is not None and cycle >= c["corroborant_due"]
        deadline_passed = (not c["real_event"]) and cycle > c["filed_cycle"] + CORROBORANT_LAG_CYCLES
        dup_hit = c["loss_id"] in registry
        if not corroborant_present and not deadline_passed and not dup_hit:
            stats["hold"] += 1
            c["party"]["ever_held"] = True
            if c["kind"] == "honest":
                stats["honest_held"] += 1
            still_pending.append(c)
            continue
        res, dup_hit = decide_claim(c, corroborant_present, deadline_passed, dup_hit)
        kind, amount = c["kind"], c["amount"]
        if res["decision"] == "HOLD":
            stats["hold"] += 1
            c["party"]["ever_held"] = True
            if kind == "honest":
                stats["honest_held"] += 1
            still_pending.append(c)
        elif res["decision"] == "PAYMENT_CERTIFIED":
            stats["certified"] += 1
            stats["value_settled"] += amount
            registry.setdefault(c["loss_id"], "insurer-A")
            if kind != "honest":
                leaked_value += amount
        else:
            stats["rejected"] += 1
            if kind != "honest":
                blocked_value_by_kind[kind] += amount
                stats["fraud_blocked"] += 1
            else:
                stats["honest_wrongly_denied"] += 1

    return {"stats": dict(stats), "leaked_value": leaked_value,
            "blocked_value_by_kind": dict(blocked_value_by_kind),
            "pending": still_pending, "registry": registry}

if __name__ == "__main__":
    # self-test: 4 quarters on a scratch 20k population, fresh engine
    import os, tempfile
    from population import build_population
    d = tempfile.mkdtemp()
    eng = Engine(f"{d}/t.db", store_payloads=False, audit_sources=False)
    pop = build_population(n=20000)
    rng = random.Random(5)
    pend, reg = [], {}
    report = []
    for q in range(1, 5):
        out = run_quarter(eng, pop, q, rng, pending=pend, registry=reg)
        pend, reg = out["pending"], out["registry"]
        report.append({"stats": out["stats"], "leaked_value": out["leaked_value"],
                       "blocked_value_by_kind": out["blocked_value_by_kind"]})
        print(q, json.dumps(report[-1], indent=1))
    json.dump(report, open("insurance_q4.json", "w"), indent=1)
    print("audit_valid:", eng.verify_audit())
