"""Merchant adversary v3: two-device collusion rings (money loops back to operator)
and spoofs aimed at low-dispute buyers. Product v3: funding-source loop detection."""
import json, random, math
from collections import Counter
from engine import Engine, sha
from population import build_population

RULE_PACK = "merchant-settlement-v3"

def run_day(engine, pop, cycle, rng):
    st = Counter(); blocked_value = Counter(); leaked = 0; miss_examples = []
    merchants = [p for p in pop if rng.random() < 0.02]
    for m in merchants:
        buyer = rng.choice(pop)
        amount = rng.choice([499, 899, 1499, 2499, 4999])
        fraud = None
        r = rng.random()
        if m["label"] == "ghost": fraud = "ghost_merchant"
        elif r < 0.02: fraud = "gps_spoof_clean"
        elif r < 0.03: fraud = "collusion_2dev"     # ring with separate devices
        elif r < 0.035: fraud = "spoof_lowdispute"  # target buyers who rarely complain
        low_dispute_buyer = fraud == "spoof_lowdispute"
        dispute_p = 0.30 if low_dispute_buyer else 0.80
        dist_km = rng.uniform(5, 800); hours = dist_km / rng.uniform(25, 60)
        drop = (12.97 + rng.uniform(-0.005, 0.005), 77.59 + rng.uniform(-0.005, 0.005))
        delivered = fraud is None
        confirmed = (delivered and rng.random() < 0.95) or fraud == "collusion_2dev"
        disputed = (not delivered) and fraud != "collusion_2dev" and rng.random() < dispute_p
        # funding source: collusion buyer pays from an account funded by the merchant operator
        buyer_funding = f"SRC-{m['true_identity']}" if fraud == "collusion_2dev" else f"SRC-{buyer['true_identity']}"
        ev = {
            "order_api": {"order_id": f"ORD-{rng.randrange(10**9)}", "amount": amount, "merchant": m["subject_id"]},
            "logistics_api": {"trail": {"distance_km": round(dist_km,1), "elapsed_h": round(hours,2)},
                              "delivery_scan": True, "drop_lat": round(drop[0],4), "drop_lon": round(drop[1],4),
                              "buyer_lat": 12.97, "buyer_lon": 77.59},
            "merchant_registry_api": {"merchant": m["subject_id"], "kyb_verified": m["exists"]},
            "buyer_api": {"buyer": buyer["subject_id"], "confirmed": confirmed, "disputed": disputed,
                          "buyer_device": f"DEV-{buyer['true_identity']}",
                          "funding_source": buyer_funding},
        }
        manifest = []
        for conn, payload in ev.items():
            pl = {**payload, "subject_id": m["subject_id"], "cycle": cycle}
            r = engine.submit_evidence("merchant", conn, m["subject_id"], pl)
            if r["status"] == "ACCEPTED":
                manifest.append({"connector": conn, "payload_hash": sha(pl)})
        speed = ev["logistics_api"]["trail"]["distance_km"] / max(ev["logistics_api"]["trail"]["elapsed_h"], 0.01)
        geo_err = math.hypot(ev["logistics_api"]["drop_lat"] - 12.97, ev["logistics_api"]["drop_lon"] - 77.59) * 111
        rules = [
            ["merchant_kyb", ev["merchant_registry_api"]["kyb_verified"]],
            ["delivery_scanned", ev["logistics_api"]["delivery_scan"]],
            ["route_physically_plausible", speed <= 120],
            ["delivered_at_buyer", geo_err <= 2.0],
            ["no_buyer_dispute", not ev["buyer_api"]["disputed"]],
            ["counterparty_independent_device", ev["buyer_api"]["buyer_device"] != f"DEV-{m['true_identity']}"],
            ["no_money_loop", ev["buyer_api"]["funding_source"] != f"SRC-{m['true_identity']}"],
        ]
        failed = [r for r, ok in rules if not ok]
        buyer_silent = not ev["buyer_api"]["confirmed"] and not ev["buyer_api"]["disputed"]
        if failed: decision = "PAYMENT_REJECTED"
        elif buyer_silent: decision = "PAYMENT_HOLD"
        else: decision = "PAYMENT_CERTIFIED"
        engine.decide("merchant", m["subject_id"], f"cycle-{cycle}", rules, manifest)
        truth_bad = fraud is not None
        if decision == "PAYMENT_CERTIFIED":
            st["certified"] += 1
            if truth_bad:
                st["missed_fraud"] += 1; leaked += amount
                if len(miss_examples) < 20: miss_examples.append({"merchant": m["subject_id"], "fraud": fraud, "amount": amount})
            else:
                st["honest_paid"] += 1; st["value_settled"] += amount
        elif decision == "PAYMENT_HOLD":
            st["hold"] += 1
            if truth_bad: st["fraud_held"] += 1
            else: st["honest_held"] += 1
        else:
            st["rejected"] += 1
            if truth_bad: st["fraud_blocked"] += 1; blocked_value[fraud] += amount
            else: st["false_reject"] += 1
    return {"rule_pack": RULE_PACK, "cycle": cycle, "stats": dict(st),
            "blocked_value_by_kind": dict(blocked_value), "leaked_value": leaked, "miss_examples": miss_examples}

if __name__ == "__main__":
    rng = random.Random(29)
    pop = build_population()
    eng = Engine("/tmp/econ/ensur-economy/economy_madv3.db", store_payloads=False, audit_sources=False)
    out = run_day(eng, pop, 1, rng)
    eng.commit()
    out["audit_valid"] = eng.verify_audit()
    print(json.dumps(out, indent=2))
    json.dump(out, open("/tmp/econ/ensur-economy/merch_adv3_day1.json", "w"), indent=2)
