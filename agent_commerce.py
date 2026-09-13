"""Agent-to-agent commerce verification (product 6, Phase 1).
Two synthetic agents transact: a machine-readable contract (spec hash) registered when the
escrow funds; the deliverable is verified by an INDEPENDENT runner (never the seller's claim);
milestone payment releases on certification, holds when unproven, rejects only contract-false.
Fraud classes: non_delivery, deliverable_substitution, spec_gaming, escrow_unfunded,
sybil_reputation, milestone_skip. Micro-contracts (sub-Rs 500) are the enabled-transaction story."""
import json, random
from collections import Counter
from engine import Engine, sha
from population import build_population

RULE_PACK = "agent-commerce-v1"
TICKETS = [49, 99, 199, 499, 999, 4999, 19999]

def run_window(engine, pop, cycle, rng, pending=None):
    st = Counter(); blocked_value = Counter(); leaked = 0; miss_examples = []
    new_pending = []
    for h in (pending or []):
        if h["disputed_later"]:
            st["held_then_blocked"] += 1; blocked_value[h["fraud"] or "honest"] += h["amount"]
        else:
            st["held_then_released"] += 1
            if h["fraud"]:
                st["missed_fraud"] += 1; leaked += h["amount"]
                if len(miss_examples) < 20: miss_examples.append({"seller": h["seller"], "fraud": h["fraud"], "amount": h["amount"], "via": "timeout_release"})
    deals = [p for p in pop if rng.random() < 0.03]
    for s in deals:
        buyer = rng.choice(pop)
        amount = rng.choice(TICKETS)
        fraud = None
        r = rng.random()
        if s["label"] == "ghost": fraud = "non_delivery"
        elif r < 0.020: fraud = "deliverable_substitution"
        elif r < 0.032: fraud = "spec_gaming"
        elif r < 0.037: fraud = "escrow_unfunded"
        elif r < 0.042: fraud = "sybil_reputation"
        elif r < 0.045: fraud = "milestone_skip"
        spec = {"task": f"task-{rng.randrange(10**6)}", "acceptance": "suite-v3", "spec_hash": sha({"s": s["subject_id"], "c": cycle})}
        delivered = fraud != "non_delivery"
        suite_true = fraud not in ("deliverable_substitution", "spec_gaming", "non_delivery")
        runner_pass = suite_true if delivered else False
        probe_catches = fraud == "spec_gaming" and rng.random() < 0.85
        escrow_funded = fraud != "escrow_unfunded"
        milestones_done = 3 if fraud != "milestone_skip" else 2
        buyer_funding = f"SRC-{s['true_identity']}" if fraud == "sybil_reputation" else f"SRC-{buyer['true_identity']}"
        buyer_silent = delivered and rng.random() < 0.06
        ev = {
            "contract_registry_api": {"spec_hash": spec["spec_hash"], "acceptance": spec["acceptance"], "registered": True},
            "escrow_api": {"funded": escrow_funded, "amount": amount, "milestones_contracted": 3, "milestones_completed": milestones_done},
            "deliverable_api": {"delivered": delivered, "artifact_hash": spec["spec_hash"] if fraud != "deliverable_substitution" else sha({"wrong": 1})},
            "runner_api": {"independent": True, "suite_pass": runner_pass, "quality_probe_pass": not probe_catches},
            "reputation_api": {"buyer_funding": buyer_funding, "buyer_prior_deals": rng.randint(0, 40)},
        }
        manifest = []
        for conn, payload in ev.items():
            pl = {**payload, "subject_id": s["subject_id"], "cycle": cycle}
            r2 = engine.submit_evidence("agent_commerce", conn, s["subject_id"], pl)
            if r2["status"] == "ACCEPTED":
                manifest.append({"connector": conn, "payload_hash": sha(pl)})
        rules = [
            ["spec_registered", ev["contract_registry_api"]["registered"]],
            ["escrow_funded_before_work", ev["escrow_api"]["funded"]],
            ["milestone_sequence_valid", ev["escrow_api"]["milestones_completed"] == ev["escrow_api"]["milestones_contracted"]],
            ["deliverable_matches_spec", not delivered or ev["deliverable_api"]["artifact_hash"] == spec["spec_hash"]],
            ["independent_suite_pass", ev["runner_api"]["suite_pass"]],
            ["quality_probe_pass", ev["runner_api"]["quality_probe_pass"]],
            ["counterparty_independent", ev["reputation_api"]["buyer_funding"] != f"SRC-{s['true_identity']}"],
        ]
        failed = [rn for rn, ok in rules if not ok]
        truth_bad = fraud is not None
        if failed: decision = "MILESTONE_REJECTED"
        elif buyer_silent: decision = "MILESTONE_HOLD"
        else: decision = "MILESTONE_CERTIFIED"
        engine.decide("agent_commerce", s["subject_id"], f"cycle-{cycle}", rules, manifest)
        if decision == "MILESTONE_CERTIFIED":
            st["certified"] += 1
            if truth_bad:
                st["missed_fraud"] += 1; leaked += amount
                if len(miss_examples) < 20: miss_examples.append({"seller": s["subject_id"], "fraud": fraud, "amount": amount})
            else:
                st["honest_paid"] += 1; st["value_settled"] += amount
                if amount < 500: st["micro_contracts"] += 1; st["micro_value"] += amount
        elif decision == "MILESTONE_HOLD":
            st["hold"] += 1
            new_pending.append({"seller": s["subject_id"], "fraud": fraud, "amount": amount,
                                "disputed_later": rng.random() < (0.15 if not truth_bad else 0.7)})
            if truth_bad: st["fraud_held"] += 1
            else: st["honest_held"] += 1
        else:
            st["rejected"] += 1
            if truth_bad: st["fraud_blocked"] += 1; blocked_value[fraud] += amount
            else: st["false_reject"] += 1
    return {"rule_pack": RULE_PACK, "cycle": cycle, "stats": dict(st),
            "blocked_value_by_kind": dict(blocked_value), "leaked_value": leaked,
            "miss_examples": miss_examples, "pending": new_pending}

if __name__ == "__main__":
    rng = random.Random(31)
    pop = build_population()
    eng = Engine("/tmp/econ/ensur-economy/economy_ac1.db", store_payloads=False, audit_sources=False)
    pend = []; windows = []
    for c in range(1, 4):
        out = run_window(eng, pop, c, rng, pending=pend)
        pend = out.pop("pending")
        windows.append(out); eng.commit()
        print(f"window {c}:", json.dumps(out["stats"]), "leaked:", out["leaked_value"], flush=True)
    tl = sum(w["leaked_value"] for w in windows); ts = sum(w["stats"].get("value_settled", 0) for w in windows)
    print(json.dumps({"windows": len(windows), "total_leaked": tl, "total_settled_honest": ts,
                      "leak_pct": round(100*tl/max(ts,1), 4), "audit_valid": eng.verify_audit()}, indent=2))
    json.dump(windows, open("/tmp/econ/ensur-economy/agent_commerce_w3.json", "w"), indent=2)
