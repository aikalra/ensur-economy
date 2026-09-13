"""Phase 5 - general verified workflows: the core doctrine generalized.
Any multi-step, multi-party process - company procurement, a freelance gig, a rental -
is a mini-business: a spec locked at funding, evidence-locked steps, escrow milestones,
an independent corroborant per step, HOLD-not-deny, and a P&L. The shared registries
learned 4x (insurance duplicates, credential reuse, loan stacking, double pledges)
appear here as the invoice registry: an invoice replayed at a second company dies
against the registry, the same lesson at workflow altitude."""
import json, random
from collections import Counter
from engine import Engine

FEE_BPS = 30            # 0.30% of settled milestone value - workflow-shaped pricing
MAX_OPEN_CYCLES = 6     # evidence deadline: undischarged steps die, escrow returns
ARCHETYPES = ("procurement", "freelance", "rental")

def _spec_hash(rng): return f"spec-{rng.getrandbits(48):012x}"

def run_workflows_cycle(eng, pop, cycle, rng, open_wf=None, invoice_registry=None):
    """open_wf: {wf_id: workflow} carried across cycles.
    invoice_registry: {invoice_id: wf_id} shared across ALL companies - the replay net."""
    open_wf = open_wf if open_wf is not None else {}
    invoice_registry = invoice_registry if invoice_registry is not None else {}
    stats = Counter(); blocked_value_by_kind = Counter()
    leaked_value = 0; value_settled = 0; fees = 0

    # --- new workflows initiated this cycle (~0.8% of parties start one) ---
    for p in pop:
        if rng.random() >= 0.008: continue
        arch = ARCHETYPES[rng.randrange(3)]
        honest = p["label"] == "honest" and rng.random() < 0.90
        kind = "honest"
        if not honest:
            fr = rng.random()
            if fr < 0.30: kind = "ghost_counterparty"      # sybil vendor/tenant controlled by initiator's ring
            elif fr < 0.55: kind = "invoice_replay"         # same invoice presented to a second payer
            elif fr < 0.80: kind = "fake_step_evidence"     # delivery note / damage claim fabricated
            else: kind = "spec_bait_switch"                 # deliverable doesn't match locked spec
        value = int({"procurement": 250000, "freelance": 60000, "rental": 90000}[arch] * (0.5 + rng.random()))
        wf_id = f"wf{cycle}-{p['subject_id'][-6:]}-{rng.randrange(9999)}"
        invoice_id = f"inv-{rng.getrandbits(40):010x}"
        if kind == "invoice_replay":
            if invoice_registry:
                invoice_id = rng.choice(list(invoice_registry.keys()))  # already paid elsewhere
            else:
                kind = "fake_step_evidence"  # no prior invoice exists yet - attacker's next-best play
        wf = {"wf_id": wf_id, "arch": arch, "initiator": p["subject_id"], "party": p,
              "kind": kind, "value": value, "spec": _spec_hash(rng),
              "steps_done": 0, "steps_total": {"procurement": 4, "freelance": 3, "rental": 3}[arch],
              "opened": cycle, "invoice_id": invoice_id}
        eng.submit_evidence("workflows", "spec_locked", p["subject_id"],
                            {"wf": wf_id, "arch": arch, "spec": wf["spec"], "value": value})
        open_wf[wf_id] = wf
        stats["opened"] += 1

    # --- advance open workflows one step each; decide at the paying step ---
    still_open = {}
    for wf_id, wf in open_wf.items():
        p, kind = wf["party"], wf["kind"]
        if cycle - wf["opened"] >= MAX_OPEN_CYCLES:
            stats["expired"] += 1
            if kind == "fake_step_evidence": stats["fraud_died_at_deadline"] += 1
            else: stats["honest_expired"] += 1
            continue  # staged evidence never discharged - escrow returns, nothing settles
        wf["steps_done"] += 1
        final = wf["steps_done"] >= wf["steps_total"]
        if not final:
            still_open[wf_id] = wf; continue

        # paying step: corroborant must be independent of the claimant's channel
        corroborant_independent = kind != "fake_step_evidence"
        rules = [
            ["identity_alive_real", p["alive"] and p["exists"] and kind != "ghost_counterparty"],
            ["spec_match_locked_hash", kind != "spec_bait_switch"],
            ["step_corroborated_independently", corroborant_independent],
            ["invoice_not_seen_before", wf["invoice_id"] not in invoice_registry],
        ]
        manifest = ["identity_registry", "locked_spec_hash", "independent_step_corroborant", "shared_invoice_registry"]
        res = eng.decide("workflows", p["subject_id"], wf_id, rules, manifest)
        if res["decision"] == "PAYMENT_CERTIFIED":
            stats["certified"] += 1; stats["value_settled"] += wf["value"]
            value_settled += wf["value"]; fees += wf["value"] * FEE_BPS // 10000
            invoice_registry[wf["invoice_id"]] = wf_id
            stats[f"certified_{wf['arch']}"] += 1
            if kind != "honest": leaked_value += wf["value"]
        else:
            stats["rejected"] += 1
            if kind != "honest":
                blocked_value_by_kind[kind] += wf["value"]; stats["fraud_blocked"] += 1
            else: stats["honest_wrongly_denied"] += 1
    return {"stats": dict(stats), "leaked_value": leaked_value, "fees": fees,
            "value_settled": value_settled, "blocked_value_by_kind": dict(blocked_value_by_kind),
            "open_wf": still_open, "invoice_registry": invoice_registry}

if __name__ == "__main__":
    import tempfile
    from population import build_population
    d = tempfile.mkdtemp()
    eng = Engine(f"{d}/t.db", store_payloads=False, audit_sources=False)
    pop = build_population(n=20000)
    rng = random.Random(23)
    open_wf, inv = {}, {}
    report = []
    for c in range(1, 5):
        out = run_workflows_cycle(eng, pop, c, rng, open_wf=open_wf, invoice_registry=inv)
        open_wf, inv = out["open_wf"], out["invoice_registry"]
        report.append({"stats": out["stats"], "leaked_value": out["leaked_value"],
                       "blocked_value_by_kind": out["blocked_value_by_kind"]})
        print(c, json.dumps(report[-1], indent=1))
    json.dump(report, open("workflows_c4.json", "w"), indent=1)
    print("audit_valid:", eng.verify_audit(), "| open workflows:", len(open_wf), "| invoices registered:", len(inv))
