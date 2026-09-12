"""Third commercial product: hospital benefit (Ayushman/JSY-style per-admission payment).
The contract: a real patient, really admitted, at an empanelled hospital, for the treatment billed.
Paid on discharge when the evidence chain is true."""
import json, random, difflib
from collections import Counter, defaultdict
from engine import Engine, sha
from population import build_population

BENEFIT = 30000
RULE_PACK = "hospital-benefit-v3"
HOSPITALS = [f"HOSP-{i:02d}" for i in range(1, 9)]
UNEMPANELLED = ["HOSP-X1", "HOSP-X2"]

def name_sim(a, b):
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()

def run_admission_month(engine, pop, cycle, rng):
    st = Counter(); blocked_value = Counter(); leaked = 0; miss_examples = []
    admissions = []
    for p in pop:
        if p["label"] == "deceased_closed":
            continue
        if rng.random() < 0.03:  # ~3% monthly admission rate
            hosp = rng.choice(HOSPITALS)
            day = rng.randint(1, 28)
            los = rng.randint(1, 6)
            fraud_kind = None
            if p["label"] == "ghost": fraud_kind = "ghost_admission"
            elif p["label"] == "deceased_on_rolls" and rng.random() < 0.5: fraud_kind = "deceased_billing"
            elif rng.random() < 0.02: fraud_kind = "upcoding"
            admissions.append({"p": p, "hosp": hosp, "admit_day": day, "discharge_day": min(28, day + los),
                               "treatment": "c_section" if fraud_kind == "upcoding" else "normal_delivery",
                               "fraud_kind": fraud_kind})
        # duplicate cross-hospital billing: same patient billed at two hospitals, overlapping days
        if p["label"] == "duplicate_identity" and rng.random() < 0.10:
            day = rng.randint(1, 20)
            admissions.append({"p": p, "hosp": rng.choice(HOSPITALS), "admit_day": day,
                               "discharge_day": day + 3, "treatment": "normal_delivery",
                               "fraud_kind": "cross_hospital_double_bill"})
            admissions.append({"p": p, "hosp": rng.choice(HOSPITALS), "admit_day": day + 1,
                               "discharge_day": day + 4, "treatment": "normal_delivery",
                               "fraud_kind": "cross_hospital_double_bill"})
    # non-empanelled hospital claims
    for p in rng.sample(pop, 40):
        admissions.append({"p": p, "hosp": rng.choice(UNEMPANELLED), "admit_day": rng.randint(1, 25),
                           "discharge_day": 28, "treatment": "normal_delivery", "fraud_kind": "non_empanelled"})
    # genuine readmissions: 0.8% of admitted honest patients get readmitted same hospital, different treatment
    honest_admitted = [a for a in admissions if a["fraud_kind"] is None and a["p"]["label"] == "honest"]
    for a in rng.sample(honest_admitted, min(len(honest_admitted), int(0.008 * len(admissions)))):
        day = a["admit_day"] + 1
        admissions.append({"p": a["p"], "hosp": a["hosp"], "admit_day": min(day, 26),
                           "discharge_day": min(day + 2, 28), "treatment": "physiotherapy",
                           "fraud_kind": None})
    # cross-hospital overlap index from CLAIMED evidence (what the engine can see)
    claimed = defaultdict(list)
    for a in admissions:
        claimed[a["p"]["subject_id"]].append((a["admit_day"], a["discharge_day"]))
    claimed_detail = defaultdict(list)
    for a in admissions:
        claimed_detail[a["p"]["subject_id"]].append((a["admit_day"], a["discharge_day"], a["hosp"], a["treatment"]))
    def overlap_kind(sid, admit, discharge, hosp, treatment):
        for (s, e, h, t) in claimed_detail[sid]:
            if s == admit and e == discharge and h == hosp:
                continue  # self
            if s <= discharge and admit <= e:
                if h != hosp: return "cross_hospital"
                if t == treatment: return "same_hosp_same_treatment"
                return "same_hosp_diff_treatment"
        return None
    for a in admissions:
        p = a["p"]
        ev = {
            "hmis_api": {"hospital": a["hosp"], "admission_ts": a["admit_day"], "discharge_ts": a["discharge_day"],
                         "treatment_billed": a["treatment"], "treatment_recorded": "normal_delivery"},
            "hospital_registry_api": {"hospital": a["hosp"], "empanelled": a["hosp"] in HOSPITALS},
            "registry_api": {"alive": p["alive"] if a["fraud_kind"] != "deceased_billing" else True,
                             "identity_active": p["exists"], "name": p["name"]},
            "activity_api": {"last_genuine_auth_cycle": cycle if rng.random() < p["genuine_auth_p"] else cycle - 6},
        }
        manifest = []
        for conn, payload in ev.items():
            pl = {**payload, "subject_id": p["subject_id"], "cycle": cycle}
            r = engine.submit_evidence("hospital", conn, p["subject_id"], pl)
            if r["status"] == "ACCEPTED":
                manifest.append({"connector": conn, "payload_hash": sha(pl)})
        rules = [
            ["empanelled_hospital", ev["hospital_registry_api"]["empanelled"]],
            ["patient_real", ev["registry_api"]["identity_active"]],
            ["patient_alive", ev["registry_api"]["alive"]],
            ["billing_matches_record", ev["hmis_api"]["treatment_billed"] == ev["hmis_api"]["treatment_recorded"]],
            ["no_concurrent_admission", overlap_kind(p["subject_id"], a["admit_day"], a["discharge_day"], a["hosp"], a["treatment"]) is None],
            ["liveness_recent", cycle - ev["activity_api"]["last_genuine_auth_cycle"] <= 3],
        ]
        okind = overlap_kind(p["subject_id"], a["admit_day"], a["discharge_day"], a["hosp"], a["treatment"])
        failed = [r for r, ok in rules if not ok]
        hard_failed = [f for f in failed if f not in ("liveness_recent", "no_concurrent_admission")]
        if hard_failed or okind in ("cross_hospital", "same_hosp_same_treatment"):
            decision = "PAYMENT_REJECTED"
        elif failed or okind == "same_hosp_diff_treatment":
            decision = "PAYMENT_HOLD"  # liveness gap or genuine readmission -> review, not denial
        else:
            decision = "PAYMENT_CERTIFIED"
        engine.decide("hospital", p["subject_id"], f"cycle-{cycle}", rules, manifest)
        truth_bad = a["fraud_kind"] is not None
        if decision == "PAYMENT_CERTIFIED":
            st["certified"] += 1
            if truth_bad:
                st["missed_fraud"] += 1; leaked += BENEFIT
                if len(miss_examples) < 20:
                    miss_examples.append({"subject_id": p["subject_id"], "fraud": a["fraud_kind"]})
            else:
                st["honest_paid"] += 1
        elif decision == "PAYMENT_HOLD":
            st["hold"] += 1
            if truth_bad: st["fraud_held"] += 1
            else: st["honest_held"] += 1
        else:
            st["rejected"] += 1
            if truth_bad:
                st["fraud_blocked"] += 1; blocked_value[a["fraud_kind"]] += BENEFIT
            else:
                st["false_reject"] += 1
    return {"rule_pack": RULE_PACK, "cycle": cycle, "admissions": len(admissions),
            "stats": dict(st), "blocked_value_by_kind": dict(blocked_value), "leaked_value": leaked,
            "miss_examples": miss_examples}

if __name__ == "__main__":
    rng = random.Random(13)
    pop = build_population()
    eng = Engine("/tmp/econ/ensur-economy/economy_hosp3.db", store_payloads=False, audit_sources=False)
    out = run_admission_month(eng, pop, 1, rng)
    eng.commit()
    out["audit_valid"] = eng.verify_audit()
    print(json.dumps(out, indent=2))
    json.dump(out, open("/tmp/econ/ensur-economy/hosp_month3.json", "w"), indent=2)
