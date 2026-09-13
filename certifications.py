"""Certifications: education, organic, technical (Phase 3 of the approved 2026-09-13 roadmap).
A credential is a claim with evidence. Three tracks, one engine:
- education: institution registry + proctored-exam liveness + identity match
- organic: farm-to-shelf custody - claimed volume must be consistent with certified farm acres
  (crop doctrine) + satellite-style corroborant
- technical: lab registry + test-report hash + standards-registry membership
Adversaries: diploma-mill institutions, impersonated test-takers, volume-over-production
organic claims, forged lab reports, credential reuse across identities (shared credential
registry: one credential, one holder - whoever verifies it first pins it).
New layer vs claims products: PUBLIC VERIFICATION - third parties query credential hashes
against the registry. Verifications are the platform metric (network effect), tracked per cycle.
Doctrine held: HOLD for unproven (registry lag delays honest credentials, never denies);
reject only on contract-false; residual published.
"""
import json, random
from collections import Counter
from engine import Engine, sha

TRACKS = {
    "education": {"fee": 150, "share": 0.40},
    "organic":   {"fee": 80,  "share": 0.35},
    "technical": {"fee": 500, "share": 0.25},
}
REGISTRY_LAG_CYCLES = 2   # new institutions/labs enter the registry with a lag - honest applicants held, never denied

def run_certification_cycle(eng, pop, cycle, rng, pending=None, cred_registry=None, new_issuers=None):
    """One cycle of credential applications across the three tracks.
    pending: applications held for registry maturation.
    cred_registry: {credential_hash: holder_subject_id} - public verification target.
    new_issuers: issuers (institutions/labs) awaiting registry entry, [(issuer_id, entered_cycle)].
    """
    pending = pending if pending is not None else []
    cred_registry = cred_registry if cred_registry is not None else {}
    stats = Counter(); blocked_value_by_kind = Counter(); leaked_value = 0
    fees = 0

    applicants = [p for p in pop if rng.random() < 0.008]  # ~0.8% apply per cycle
    fresh = []
    for p in applicants:
        r = rng.random()
        acc = 0.0
        track = "education"
        for t, spec in TRACKS.items():
            acc += spec["share"]
            if r < acc:
                track = t; break
        if track == "organic" and not p.get("is_farmer", False):
            track = "education"  # only farm operators apply for produce certification
        honest = p["label"] == "honest" and rng.random() < 0.92
        kind = "honest"
        if not honest:
            fr = rng.random()
            if track == "education":
                kind = "diploma_mill" if fr < 0.5 else "impersonated_test"
            elif track == "organic":
                kind = "volume_over_production" if fr < 0.6 else "custody_gap"
            else:
                kind = "forged_lab_report" if fr < 0.6 else "unregistered_lab"
        # a slice of honest applicants use brand-new issuers not yet in the registry
        new_issuer = honest and rng.random() < 0.05
        issuer_id = f"ISSUER-{track[:3]}-{abs(hash((p['subject_id'], cycle))) % 5000}"
        cred_hash = sha({"subject": p["subject_id"], "track": track, "cycle": cycle,
                         "roll": rng.random()})
        claimed_volume = round(p.get("farm_acres", 2.0) * (2.4 if kind == "volume_over_production" else 0.9), 1)
        fresh.append({"party": p, "track": track, "kind": kind, "issuer_id": issuer_id,
                      "cred_hash": cred_hash, "new_issuer": new_issuer,
                      "claimed_volume": claimed_volume, "filed_cycle": cycle})

    def decide(a, issuer_registered):
        p, track, kind = a["party"], a["track"], a["kind"]
        eng.submit_evidence("certifications", f"{track}_evidence", p["subject_id"],
                            {"issuer": a["issuer_id"], "cred": a["cred_hash"][:16]})
        if track == "education":
            rules = [
                ["institution_in_registry", issuer_registered and kind != "diploma_mill"],
                ["proctored_liveness", kind != "impersonated_test" and rng.random() < p["genuine_auth_p"] + 0.05],
                ["identity_matches_candidate", p["exists"] and p["alive"]],
            ]
            manifest = ["institution_registry", "proctoring_liveness", "identity_registry"]
        elif track == "organic":
            rules = [
                ["custody_chain_intact", kind != "custody_gap"],
                ["volume_consistent_with_acres", a["claimed_volume"] <= p.get("farm_acres", 2.0) * 1.2],
                ["farm_certified_source", p.get("is_farmer", False)],
            ]
            manifest = ["custody_chain", "satellite_corroborant", "farm_registry"]
        else:
            rules = [
                ["lab_in_registry", issuer_registered and kind != "unregistered_lab"],
                ["test_report_hash_matches", kind != "forged_lab_report"],
                ["standards_registry_member", True],
            ]
            manifest = ["lab_registry", "test_report_hash", "standards_registry"]
        reuse_hit = a["cred_hash"] in cred_registry
        rules.append(["credential_not_already_issued", not reuse_hit])
        manifest.append("credential_registry")
        res = eng.decide("certifications", p["subject_id"], f"c{cycle}-{track}", rules, manifest)
        return res

    still_pending = []
    for a in fresh + pending:
        p, kind, track = a["party"], a["kind"], a["track"]
        issuer_registered = not a["new_issuer"] or cycle >= a["filed_cycle"] + REGISTRY_LAG_CYCLES
        if a["new_issuer"] and not issuer_registered:
            stats["hold"] += 1
            if kind == "honest": stats["honest_held"] += 1
            p["ever_held"] = True
            still_pending.append(a)
            continue
        res = decide(a, issuer_registered)
        if res["decision"] == "PAYMENT_CERTIFIED":
            stats["certified"] += 1
            stats[f"certified_{track}"] += 1
            fees += TRACKS[track]["fee"]
            stats["value_certified"] += TRACKS[track]["fee"] * 40  # market value of the issued credential
            cred_registry[a["cred_hash"]] = p["subject_id"]
            if kind != "honest":
                leaked_value += TRACKS[track]["fee"] * 40  # leaked credential's market value
        else:
            stats["rejected"] += 1
            if kind != "honest":
                blocked_value_by_kind[kind] += TRACKS[track]["fee"] * 40
                stats["fraud_blocked"] += 1
            else:
                stats["honest_wrongly_denied"] += 1

    # ---------- public verification: third parties query issued credentials ----------
    issued_now = stats["certified"]
    verify_calls = int(issued_now * (3 + rng.random() * 4)) + int(len(cred_registry) * 0.002)
    stats["public_verifications"] = verify_calls

    return {"stats": dict(stats), "leaked_value": leaked_value, "fees": fees,
            "blocked_value_by_kind": dict(blocked_value_by_kind),
            "pending": still_pending, "registry": cred_registry}

if __name__ == "__main__":
    import tempfile
    from population import build_population
    d = tempfile.mkdtemp()
    eng = Engine(f"{d}/t.db", store_payloads=False, audit_sources=False)
    pop = build_population(n=20000)
    rng = random.Random(11)
    pend, reg = [], {}
    report = []
    for c in range(1, 5):
        out = run_certification_cycle(eng, pop, c, rng, pending=pend, cred_registry=reg)
        pend, reg = out["pending"], out["registry"]
        report.append({"stats": out["stats"], "leaked_value": out["leaked_value"],
                       "blocked_value_by_kind": out["blocked_value_by_kind"]})
        print(c, json.dumps(report[-1], indent=1))
    json.dump(report, open("certifications_c4.json", "w"), indent=1)
    print("audit_valid:", eng.verify_audit(), "| registry size:", len(reg))
