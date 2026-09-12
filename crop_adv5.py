"""Crop v5: independent physical channel (satellite vegetation) beats survey collusion.
Paper can lie; physics can't. Unproven (survey fail / satellite miss) -> HOLD, not reject."""
import json, random, difflib
from collections import Counter, defaultdict
from engine import Engine, sha
from population import build_population

SUM_INSURED = 20000
RULE_PACK = "crop-parametric-v5"

def name_sim(a, b):
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()

def run_season(engine, pop, cycle, season, rng, drought_districts, collusion_rate=0.6):
    pop_index = {"by_true_identity": defaultdict(list), "by_account": defaultdict(list)}
    for q in pop:
        pop_index["by_true_identity"][q["true_identity"]].append(q["subject_id"])
        pop_index["by_account"][q["account"]].append(q["subject_id"])
    farmers = [p for p in pop if p.get("is_farmer")]
    surveyors = {d: [f"SURV-{d[:3].upper()}-{i:02d}" for i in range(20)] for d in {p['district'] for p in farmers}}
    corrupt = {d: set(rng.sample(surveyors[d], 2)) for d in surveyors}
    st = Counter(); blocked_value = Counter(); leaked = 0; miss_examples = []; held = Counter()
    for p in farmers:
        if p["label"] == "deceased_closed" or p["district"] not in drought_districts:
            continue
        colluding = p["label"] in ("acreage_fraud", "ghost") and rng.random() < collusion_rate
        surv = rng.choice(list(corrupt[p["district"]])) if colluding else rng.choice(surveyors[p["district"]])
        claimed = p["farm_acres"] if p["label"] != "acreage_fraud" else p["farm_acres"] * rng.choice([2, 3])
        survey_verified = colluding or (p["label"] != "ghost" and rng.random() < 0.92)
        # satellite: independent. ghosts have no field; inflated acres measured at truth. 3% honest miss (cloud)
        if p["label"] == "ghost":
            sat_acres, sat_ok = 0.0, True
        elif p["label"] == "acreage_fraud":
            sat_acres, sat_ok = p["farm_acres"], True
        else:
            sat_ok = rng.random() < 0.97
            sat_acres = p["farm_acres"] if sat_ok else 0.0
        ev = {
            "rainfall_api": {"district": p["district"], "rainfall_index": rng.uniform(0.45, 0.68), "season": season},
            "land_api": {"subject_id": p["subject_id"], "sown_acres": claimed if colluding else p["farm_acres"],
                         "survey_verified": survey_verified, "surveyor": surv},
            "satellite_api": {"subject_id": p["subject_id"], "measured_acres": sat_acres, "reading_ok": sat_ok},
            "registry_api": {"alive": p["alive"], "identity_active": p["exists"], "name": p["name"]},
            "bank_api": {"account": p["account"], "account_holder_name": p["account_holder_name"], "account_active": True},
        }
        manifest = []
        for conn, payload in ev.items():
            pl = {**payload, "cycle": cycle}
            r = engine.submit_evidence("crop", conn, p["subject_id"], pl)
            if r["status"] == "ACCEPTED":
                manifest.append({"connector": conn, "payload_hash": sha(pl)})
        hard = [
            ["trigger_confirmed", ev["rainfall_api"]["rainfall_index"] < 0.70],
            ["payee_alive", ev["registry_api"]["alive"] and ev["registry_api"]["identity_active"]],
            ["name_match", name_sim(ev["registry_api"]["name"], ev["bank_api"]["account_holder_name"]) >= 0.75],
            ["identity_unique_on_rolls", len(pop_index["by_true_identity"][p["true_identity"]]) == 1],
            ["account_concentration", len(pop_index["by_account"][p["account"]]) <= 2],
        ]
        # physical corroboration: satellite must see the claimed acres (collusion-proof)
        sat = ["satellite_corroborates", ev["satellite_api"]["reading_ok"] and ev["satellite_api"]["measured_acres"] >= claimed / 1.15]
        hard_failed = [r for r, ok in hard if not ok]
        if hard_failed: decision = "PAYMENT_REJECTED"
        elif not sat[1]: decision = "PAYMENT_HOLD"     # unproven: re-fly / ground visit
        else: decision = "PAYMENT_CERTIFIED"
        engine.decide("crop", p["subject_id"], f"cycle-{cycle}", hard + [sat], manifest)
        truth_bad = p["label"] in ("ghost", "deceased_on_rolls", "acreage_fraud", "duplicate_identity", "account_mule")
        if decision == "PAYMENT_CERTIFIED":
            st["certified"] += 1
            if truth_bad:
                st["missed_fraud"] += 1; leaked += SUM_INSURED
                if len(miss_examples) < 20: miss_examples.append({"subject_id": p["subject_id"], "label": p["label"], "colluding": colluding})
            else: st["honest_paid"] += 1
        elif decision == "PAYMENT_HOLD":
            st["hold"] += 1
            if truth_bad: st["fraud_held"] += 1
            else: st["honest_held"] += 1
        else:
            st["rejected"] += 1
            if truth_bad: st["fraud_blocked"] += 1; blocked_value[p["label"]] += SUM_INSURED
            else: st["false_reject"] += 1
    return {"rule_pack": RULE_PACK, "season": season, "stats": dict(st),
            "blocked_value_by_label": dict(blocked_value), "leaked_value": leaked, "miss_examples": miss_examples}

if __name__ == "__main__":
    rng = random.Random(31)
    pop = build_population()
    for p in pop:
        p["is_farmer"] = rng.random() < 0.40
        p["farm_acres"] = round(rng.lognormvariate(1.0, 0.6), 1)
        if p["is_farmer"] and p["label"] == "honest" and rng.random() < 0.03:
            p["label"] = "acreage_fraud"
    eng = Engine("/tmp/econ/ensur-economy/economy_cadv5.db", store_payloads=False, audit_sources=False)
    out = run_season(eng, pop, 4, "kharif-2026", rng, ["Kalaburagi", "Ballari", "Raichur"])
    eng.commit()
    out["audit_valid"] = eng.verify_audit()
    print(json.dumps(out, indent=2))
    json.dump(out, open("/tmp/econ/ensur-economy/crop_adv5_s1.json", "w"), indent=2)
