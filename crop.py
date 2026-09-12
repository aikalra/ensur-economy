"""Second commercial product in the loop: parametric crop cover (PMFBY-style).
The contract is data: district rainfall index below threshold -> payout, no proof-of-loss.
The engine's job: the payout goes only to a real farmer, on real sown land, once."""
import json, random, difflib
from collections import Counter, defaultdict
from engine import Engine, sha
from population import build_population

SUM_INSURED = 20000
RULE_PACK = "crop-parametric-v3"
DROUGHT_THRESHOLD = 0.70   # rainfall index vs long-period average

def name_sim(a, b):
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()

def run_crop_season(engine, pop, cycle, season, rng, drought_districts):
    pop_index = {"by_true_identity": defaultdict(list), "by_account": defaultdict(list)}
    for q in pop:
        pop_index["by_true_identity"][q["true_identity"]].append(q["subject_id"])
        pop_index["by_account"][q["account"]].append(q["subject_id"])
    farmers = [p for p in pop if p.get("is_farmer")]
    st = Counter(); blocked_value = Counter(); leaked = 0; miss_examples = []
    for p in farmers:
        if p["label"] == "deceased_closed":
            continue
        drought = p["district"] in drought_districts
        if not drought:
            continue  # no trigger, no claim - parametric: the data decides
        # ground truth for this claim
        land_sown = p["exists"] and p["label"] not in ("ghost",)
        acres = p["farm_acres"]
        claimed_acres = acres if p["label"] != "acreage_fraud" else acres * rng.choice([2, 3])
        ev = {
            "rainfall_api": {"district": p["district"], "rainfall_index": rng.uniform(0.45, 0.68), "season": season},
            "land_api": {"subject_id": p["subject_id"], "sown_acres": acres, "survey_verified": land_sown, "crop_sown": True},
            "registry_api": {"alive": p["alive"], "identity_active": p["exists"], "name": p["name"]},
            "bank_api": {"account": p["account"], "account_holder_name": p["account_holder_name"], "account_active": True},
        }
        manifest = []
        for conn, payload in ev.items():
            pl = {**payload, "cycle": cycle}
            r = engine.submit_evidence("crop", conn, p["subject_id"], pl)
            if r["status"] == "ACCEPTED":
                manifest.append({"connector": conn, "payload_hash": sha(pl)})
        rules = [
            ["trigger_confirmed", ev["rainfall_api"]["rainfall_index"] < DROUGHT_THRESHOLD],
            ["payee_alive", ev["registry_api"]["alive"] and ev["registry_api"]["identity_active"]],
            ["land_verified", ev["land_api"]["survey_verified"] and ev["land_api"]["crop_sown"]],
            ["acreage_consistent", claimed_acres <= ev["land_api"]["sown_acres"] * 1.15],
            ["name_match", name_sim(ev["registry_api"]["name"], ev["bank_api"]["account_holder_name"]) >= 0.75],
            ["identity_unique_on_rolls", len(pop_index["by_true_identity"][p["true_identity"]]) == 1],
            ["account_concentration", len(pop_index["by_account"][p["account"]]) <= 2],
        ]
        failed = [r for r, ok in rules if not ok]
        decision = "PAYMENT_CERTIFIED" if not failed else "PAYMENT_REJECTED"
        out = engine.decide("crop", p["subject_id"], f"cycle-{cycle}", rules, manifest)
        payout = int(SUM_INSURED * min(claimed_acres, ev["land_api"]["sown_acres"]) / max(acres, 0.1) * 1)
        payout = SUM_INSURED  # flat sum insured per farmer for v1
        truth_bad = p["label"] in ("ghost", "deceased_on_rolls", "acreage_fraud", "duplicate_identity", "account_mule")  # contract-relative: stale/property/trade are welfare-contract violations, not crop-contract violations
        if decision == "PAYMENT_CERTIFIED":
            st["certified"] += 1
            if truth_bad:
                st["missed_fraud"] += 1; leaked += payout
                if len(miss_examples) < 20:
                    miss_examples.append({"subject_id": p["subject_id"], "label": p["label"], "certificate": out["certificate"]})
            else:
                st["honest_paid"] += 1
        else:
            st["rejected"] += 1
            if truth_bad:
                st["fraud_blocked"] += 1; blocked_value[p["label"]] += payout
            else:
                st["false_reject"] += 1
    return {"rule_pack": RULE_PACK, "season": season, "cycle": cycle,
            "drought_districts": drought_districts, "claimants": st["certified"] + st["rejected"],
            "stats": dict(st), "blocked_value_by_label": dict(blocked_value), "leaked_value": leaked,
            "miss_examples": miss_examples}

if __name__ == "__main__":
    rng = random.Random(11)
    pop = build_population()
    # 40% of parties farm; farm size lognormal-ish; 3% of farmers inflate acreage when claiming
    for p in pop:
        p["is_farmer"] = rng.random() < 0.40
        p["farm_acres"] = round(rng.lognormvariate(1.0, 0.6), 1)
        if p["is_farmer"] and p["label"] == "honest" and rng.random() < 0.03:
            p["label"] = "acreage_fraud"
    eng = Engine("/tmp/econ/ensur-economy/economy_crop3.db", store_payloads=False, audit_sources=False)
    out = run_crop_season(eng, pop, 4, "kharif-2026", rng, drought_districts=["Kalaburagi", "Ballari", "Raichur"])
    eng.commit()
    out["audit_valid"] = eng.verify_audit()
    print(json.dumps(out, indent=2))
    json.dump(out, open("/tmp/econ/ensur-economy/crop_season3.json", "w"), indent=2)
