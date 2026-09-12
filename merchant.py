"""Fourth commercial product: merchant settlement (ONDC/UPI-style).
The contract: the goods physically reached the buyer -> the merchant gets paid.
Delivery evidence (GPS trail + scan + geofence) is the trigger."""
import json, random, math
from collections import Counter
from engine import Engine, sha
from population import build_population

RULE_PACK = "merchant-settlement-v1"

def run_settlement_day(engine, pop, cycle, rng):
    st = Counter(); blocked_value = Counter(); leaked = 0; miss_examples = []
    merchants = [p for p in pop if rng.random() < 0.02]  # ~2k sellers ship today
    for m in merchants:
        buyer = rng.choice(pop)
        amount = rng.choice([499, 899, 1499, 2499, 4999])
        fraud_kind = None
        if m["label"] == "ghost": fraud_kind = "ghost_merchant"
        elif rng.random() < 0.03: fraud_kind = rng.choice(["gps_teleport", "wrong_geo", "no_delivery_claim"])
        dist_km = rng.uniform(5, 800); hours = dist_km / rng.uniform(25, 60)
        trail = {"distance_km": round(dist_km, 1), "elapsed_h": round(hours, 2)}
        if fraud_kind == "gps_teleport":
            trail = {"distance_km": 800.0, "elapsed_h": 0.5}  # physically impossible
        buyer_lat, buyer_lon = 12.97, 77.59
        drop_lat, drop_lon = buyer_lat + rng.uniform(-0.01, 0.01), buyer_lon + rng.uniform(-0.01, 0.01)
        if fraud_kind == "wrong_geo":
            drop_lat += 0.5  # delivered 50km away
        ev = {
            "order_api": {"order_id": f"ORD-{rng.randrange(10**9)}", "amount": amount, "merchant": m["subject_id"]},
            "logistics_api": {"trail": trail, "delivery_scan": fraud_kind != "no_delivery_claim",
                              "drop_lat": round(drop_lat, 4), "drop_lon": round(drop_lon, 4),
                              "buyer_lat": buyer_lat, "buyer_lon": buyer_lon},
            "merchant_registry_api": {"merchant": m["subject_id"], "kyb_verified": m["exists"]},
            "bank_api": {"account": m["account"], "account_holder_name": m["account_holder_name"], "account_active": True},
        }
        manifest = []
        for conn, payload in ev.items():
            pl = {**payload, "cycle": cycle}
            r = engine.submit_evidence("merchant", conn, m["subject_id"], pl)
            if r["status"] == "ACCEPTED":
                manifest.append({"connector": conn, "payload_hash": sha(pl)})
        speed = trail["distance_km"] / max(trail["elapsed_h"], 0.01)
        geo_err = math.hypot(ev["logistics_api"]["drop_lat"] - buyer_lat, ev["logistics_api"]["drop_lon"] - buyer_lon) * 111
        rules = [
            ["merchant_kyb", ev["merchant_registry_api"]["kyb_verified"]],
            ["delivery_scanned", ev["logistics_api"]["delivery_scan"]],
            ["route_physically_plausible", speed <= 120],
            ["delivered_at_buyer", geo_err <= 2.0],
        ]
        failed = [r for r, ok in rules if not ok]
        decision = "PAYMENT_CERTIFIED" if not failed else "PAYMENT_REJECTED"
        engine.decide("merchant", m["subject_id"], f"cycle-{cycle}", rules, manifest)
        truth_bad = fraud_kind is not None
        if decision == "PAYMENT_CERTIFIED":
            st["certified"] += 1
            if truth_bad:
                st["missed_fraud"] += 1; leaked += amount
                if len(miss_examples) < 20: miss_examples.append({"merchant": m["subject_id"], "fraud": fraud_kind, "amount": amount})
            else:
                st["honest_paid"] += 1; st["value_settled"] += amount
        else:
            st["rejected"] += 1
            if truth_bad:
                st["fraud_blocked"] += 1; blocked_value[fraud_kind] += amount
            else:
                st["false_reject"] += 1
    return {"rule_pack": RULE_PACK, "cycle": cycle, "shipments": len(merchants),
            "stats": dict(st), "blocked_value_by_kind": dict(blocked_value), "leaked_value": leaked,
            "miss_examples": miss_examples}

if __name__ == "__main__":
    rng = random.Random(17)
    pop = build_population()
    eng = Engine("/tmp/econ/ensur-economy/economy_merch.db", store_payloads=False, audit_sources=False)
    out = run_settlement_day(eng, pop, 1, rng)
    eng.commit()
    out["audit_valid"] = eng.verify_audit()
    print(json.dumps(out, indent=2))
    json.dump(out, open("/tmp/econ/ensur-economy/merch_day1.json", "w"), indent=2)
