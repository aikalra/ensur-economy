"""The ensur synthetic economy, consolidated: 100k parties, 12 monthly cycles,
all five commercial products in one engine, one audit chain.
Adversary adapts at cycle 4 (forgery rings: families held once start forging liveness at 50%).
Product answers at cycle 7 (welfare-v6: post-hold parties need same-cycle liveness).
Measures whether the product holds when the fraud learns."""
import json, random, difflib
from collections import Counter, defaultdict
from engine import Engine, sha
from population import build_population
from crop import run_crop_season
from hospital import run_admission_month
from merchant import run_settlement_day
from trade import run_trade_week

MONTHLY_BENEFIT = 2000
DEATH_RATE = 0.00065
FAMILY_DRAWS_P = 0.40
ADVERSARY_ADAPTS_AT = 4
PRODUCT_V6_AT = 7  # v7: stale-registry tightening replaces v6 at same cycle

def name_sim(a, b):
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()

def welfare_cycle(eng, pop, pop_index, cycle, rng, product_v6):
    st = Counter(); blocked = Counter(); leaked = 0
    for p in pop:
        if p["label"] == "deceased_closed":
            continue
        # adaptive adversary: held once -> forgery ring (forge at 50%/cycle)
        if not p["alive"] and p.get("ever_held") and cycle >= ADVERSARY_ADAPTS_AT:
            p["genuine_auth_p"] = 0.50
        ev_alive = p["alive"] or (cycle - p["died_cycle"]) <= p["registry_lag"]
        if rng.random() < p["genuine_auth_p"]:
            p["last_auth_cycle"] = cycle
        reported = p["name"]
        if p["alive"] and rng.random() < 0.004:
            reported = reported.replace("a", "e", 1)
        # registry records refresh periodically for the living; freeze at death until the death is reported
        if p["alive"] and rng.random() < 0.20:
            p["registry_updated_cycle"] = cycle
        record_age = cycle - p["registry_updated_cycle"]
        ev = {
            "welfare_api": {"eligible": p["eligible"] and p["exists"], "scheme_status": "ACTIVE"},
            "registry_api": {"alive": ev_alive, "identity_active": p["exists"], "name": reported, "record_age_cycles": record_age},
            "bank_api": {"account": p["account"], "account_holder_name": p["account_holder_name"], "account_active": True},
            "property_api": {"property_limit_pass": not p["property_over_ceiling"]},
            "trade_api": {"business_conflict": p["business_conflict"]},
            "activity_api": {"cycles_inactive": p["cycles_inactive"], "last_genuine_auth_cycle": p["last_auth_cycle"]},
        }
        manifest = []
        for conn, payload in ev.items():
            pl = {**payload, "subject_id": p["subject_id"], "cycle": cycle}
            r = eng.submit_evidence("welfare", conn, p["subject_id"], pl)
            if r["status"] == "ACCEPTED":
                manifest.append({"connector": conn, "payload_hash": sha(pl)})
        window = 1 if (product_v6 and (p.get("ever_held") or record_age > 6)) else 3  # v7: first-signal tightening
        hard = [
            ["welfare_eligible", ev["welfare_api"]["eligible"] and ev["welfare_api"]["scheme_status"] == "ACTIVE"],
            ["registry_valid", ev["registry_api"]["alive"] and ev["registry_api"]["identity_active"]],
            ["name_match", name_sim(ev["registry_api"]["name"], ev["bank_api"]["account_holder_name"]) >= 0.75],
            ["property_limit", ev["property_api"]["property_limit_pass"]],
            ["trade_conflict_clear", not ev["trade_api"]["business_conflict"]],
            ["account_concentration", len(pop_index["by_account"][p["account"]]) <= 2],
            ["identity_unique_on_rolls", len(pop_index["by_true_identity"][p["true_identity"]]) == 1],
            ["activity_current", ev["activity_api"]["cycles_inactive"] < 12],
        ]
        live = ["liveness_current", cycle - ev["activity_api"]["last_genuine_auth_cycle"] <= window]
        hard_failed = [r for r, ok in hard if not ok]
        if hard_failed: decision = "PAYMENT_REJECTED"
        elif not live[1]: decision = "PAYMENT_HOLD"
        else: decision = "PAYMENT_CERTIFIED"
        eng.decide("welfare", p["subject_id"], f"cycle-{cycle}", hard + [live], manifest)
        truth_bad = p["label"] not in ("honest", "acreage_fraud")  # acreage fraud is a crop-contract violation, not welfare
        if decision == "PAYMENT_CERTIFIED":
            st["certified"] += 1
            paid = MONTHLY_BENEFIT + p["held_amount"]; p["held_amount"] = 0
            if truth_bad:
                st["missed_fraud"] += 1; leaked += paid
            else:
                st["honest_paid"] += 1
        elif decision == "PAYMENT_HOLD":
            st["hold"] += 1; p["held_amount"] += MONTHLY_BENEFIT; p["ever_held"] = True
            if truth_bad: st["fraud_held"] += 1
            else: st["honest_held"] += 1
        else:
            st["rejected"] += 1
            if truth_bad: st["fraud_blocked"] += 1; blocked[p["label"]] += MONTHLY_BENEFIT
            else: st["false_reject"] += 1
    return st, blocked, leaked

def run():
    rng = random.Random(7)
    pop = build_population()
    for p in pop:
        k = 0
        while rng.random() > p["genuine_auth_p"]:
            k += 1
        p["last_auth_cycle"] = -k
        p["died_cycle"] = 0 if not p["alive"] else None
        p["registry_lag"] = rng.choice([1, 1, 2, 2, 3]) if not p["alive"] else 0
        p["held_amount"] = 0; p["ever_held"] = False
        p["registry_updated_cycle"] = -rng.randint(0, 5)
        p["is_farmer"] = rng.random() < 0.40
        p["farm_acres"] = round(rng.lognormvariate(1.0, 0.6), 1)
        if p["is_farmer"] and p["label"] == "honest" and rng.random() < 0.03:
            p["label"] = "acreage_fraud"
    pop_index = {"by_true_identity": defaultdict(list), "by_account": defaultdict(list)}
    for p in pop:
        pop_index["by_true_identity"][p["true_identity"]].append(p["subject_id"])
        pop_index["by_account"][p["account"]].append(p["subject_id"])
    eng = Engine("/tmp/econ/ensur-economy/economy_all_v7.db", store_payloads=False, audit_sources=False)
    ledger = {"cycles": [], "per_product": defaultdict(lambda: Counter()), "leaked_by_product": Counter(), "blocked_by_product": Counter()}
    droughts = ["Kalaburagi", "Ballari", "Raichur"]
    for cycle in range(1, 13):
        for p in pop:
            if p["alive"] and rng.random() < DEATH_RATE:
                p["alive"] = False; p["died_cycle"] = cycle; p["registry_lag"] = rng.choice([1, 1, 2, 2, 3])
                if rng.random() < FAMILY_DRAWS_P:
                    p["label"] = "deceased_on_rolls"; p["genuine_auth_p"] = 0.05
                else:
                    p["label"] = "deceased_closed"; p["genuine_auth_p"] = 0.0
        w, wb, wl = welfare_cycle(eng, pop, pop_index, cycle, rng, product_v6=(cycle >= PRODUCT_V6_AT))
        ledger["cycles"].append({"cycle": cycle, "welfare": dict(w)})
        ledger["leaked_by_product"]["welfare"] += wl
        for k2, v2 in wb.items(): ledger["blocked_by_product"][f"welfare:{k2}"] += v2
        for k2, v2 in w.items(): ledger["per_product"]["welfare"][k2] += v2
        if cycle in (4, 10):
            c = run_crop_season(eng, pop, cycle, f"season-{cycle}", rng, droughts)
            ledger["cycles"][-1]["crop"] = c["stats"]
            ledger["leaked_by_product"]["crop"] += c["leaked_value"]
            for k2, v2 in c["blocked_value_by_label"].items(): ledger["blocked_by_product"][f"crop:{k2}"] += v2
            for k2, v2 in c["stats"].items(): ledger["per_product"]["crop"][k2] += v2
        h = run_admission_month(eng, pop, cycle, rng)
        ledger["cycles"][-1]["hospital"] = h["stats"]
        ledger["leaked_by_product"]["hospital"] += h["leaked_value"]
        for k2, v2 in h["blocked_value_by_kind"].items(): ledger["blocked_by_product"][f"hospital:{k2}"] += v2
        for k2, v2 in h["stats"].items(): ledger["per_product"]["hospital"][k2] += v2
        m = run_settlement_day(eng, pop, cycle, rng)
        ledger["cycles"][-1]["merchant"] = m["stats"]
        ledger["leaked_by_product"]["merchant"] += m["leaked_value"]
        for k2, v2 in m["blocked_value_by_kind"].items(): ledger["blocked_by_product"][f"merchant:{k2}"] += v2
        for k2, v2 in m["stats"].items(): ledger["per_product"]["merchant"][k2] += v2
        t = run_trade_week(eng, pop, cycle, rng)
        ledger["cycles"][-1]["trade"] = t["stats"]
        ledger["leaked_by_product"]["trade"] += t["leaked_value"]
        for k2, v2 in t["blocked_value_by_kind"].items(): ledger["blocked_by_product"][f"trade:{k2}"] += v2
        for k2, v2 in t["stats"].items(): ledger["per_product"]["trade"][k2] += v2
        eng.commit()
        print(f"cycle {cycle}: welfare={dict(w)}", flush=True)
        eng.db.execute('DELETE FROM source_events')  # bound db growth; hashes live in the audit chain + manifests
        eng.commit()
    ledger["audit_valid"] = eng.verify_audit()
    ledger["per_product"] = {k: dict(v) for k, v in ledger["per_product"].items()}
    ledger["leaked_by_product"] = dict(ledger["leaked_by_product"])
    ledger["blocked_by_product"] = dict(ledger["blocked_by_product"])
    json.dump(ledger, open("/tmp/econ/ensur-economy/economy_v7_report.json", "w"), indent=2)
    print(json.dumps({k: ledger[k] for k in ("per_product", "leaked_by_product", "blocked_by_product", "audit_valid")}, indent=2))

if __name__ == "__main__":
    run()
