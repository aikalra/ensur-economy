"""Trade v3: customs-collusion adversary. Bribed filing makes phantom shipments look documented.
Product answer (v5 doctrine): the physical chain of custody starts BEFORE the documents -
container gate-in telemetry and vessel AIS can't be backdated by a customs clerk."""
import json, random
from collections import Counter, defaultdict
from engine import Engine, sha
from population import build_population

RULE_PACK = "trade-finance-v3"

def run_week(engine, pop, cycle, rng, collusion_rate=0.7):
    pop_index = {"by_true_identity": defaultdict(list), "by_account": defaultdict(list)}
    for q in pop:
        pop_index["by_true_identity"][q["true_identity"]].append(q["subject_id"])
        pop_index["by_account"][q["account"]].append(q["subject_id"])
    st = Counter(); blocked_value = Counter(); leaked = 0; miss_examples = []
    exporters = [p for p in pop if rng.random() < 0.005]
    for x in exporters:
        amount_lakh = rng.choice([12, 25, 48, 90, 240])
        fraud = None
        if x["label"] == "trade_conflict": fraud = "conflicted_party"
        elif x["label"] == "ghost": fraud = "phantom_exporter"
        elif rng.random() < 0.05: fraud = "customs_collusion"   # documented on paper, never shipped
        bol = f"BOL-{rng.randrange(10**8)}"
        real_shipment = fraud not in ("customs_collusion", "phantom_exporter")
        # physical chain: container gate-in at origin warehouse, then vessel load - exists only if real
        gate_in_day = rng.randint(1, 20) if real_shipment else None
        filing_day = (gate_in_day + rng.randint(1, 3)) if real_shipment else rng.randint(1, 23)
        ev = {
            "bol_api": {"bol": bol, "vessel": "MV SYNTH", "port_load": "INNSA1"},
            "customs_api": {"filing_exists": True, "filing_day": filing_day, "declared_value_lakh": amount_lakh},  # collusion: filing exists even for phantoms
            "invoice_api": {"amount_lakh": amount_lakh, "buyer": "BUYER-INTL-1"},
            "iot_api": {"container_gate_in_day": gate_in_day, "vessel_loaded": real_shipment,
                        "vessel_ais_at_port": real_shipment},
            "trade_registry_api": {"party_conflict": x["business_conflict"]},
            "registry_api": {"alive": x["alive"], "identity_active": x["exists"], "name": x["name"]},
        }
        manifest = []
        for conn, payload in ev.items():
            pl = {**payload, "subject_id": x["subject_id"], "cycle": cycle}
            r = engine.submit_evidence("trade", conn, x["subject_id"], pl)
            if r["status"] == "ACCEPTED":
                manifest.append({"connector": conn, "payload_hash": sha(pl)})
        physical_chain = (ev["iot_api"]["container_gate_in_day"] is not None
                          and ev["iot_api"]["vessel_loaded"] and ev["iot_api"]["vessel_ais_at_port"]
                          and ev["iot_api"]["container_gate_in_day"] <= ev["customs_api"]["filing_day"])
        rules = [
            ["shipment_filed_with_customs", ev["customs_api"]["filing_exists"]],
            ["invoice_matches_customs", ev["invoice_api"]["amount_lakh"] <= ev["customs_api"]["declared_value_lakh"] * 1.1],
            ["party_clear", not ev["trade_registry_api"]["party_conflict"]],
            ["party_real", ev["registry_api"]["identity_active"] and ev["registry_api"]["alive"]],
            ["identity_unique_on_rolls", len(pop_index["by_true_identity"][x["true_identity"]]) == 1],
            ["account_concentration", len(pop_index["by_account"][x["account"]]) <= 2],
            ["physical_chain_of_custody", physical_chain],
        ]
        failed = [r for r, ok in rules if not ok]
        if failed: decision = "PAYMENT_REJECTED"
        else: decision = "PAYMENT_CERTIFIED"
        engine.decide("trade", x["subject_id"], f"cycle-{cycle}", rules, manifest)
        truth_bad = (fraud is not None) or x["label"] in ("ghost", "deceased_on_rolls", "duplicate_identity", "account_mule")  # payee integrity applies to every contract
        if decision == "PAYMENT_CERTIFIED":
            st["certified"] += 1
            if truth_bad:
                st["missed_fraud"] += 1; leaked += amount_lakh * 100000
                if len(miss_examples) < 20: miss_examples.append({"exporter": x["subject_id"], "fraud": fraud})
            else:
                st["honest_paid"] += 1; st["value_settled_lakh"] += amount_lakh
        else:
            st["rejected"] += 1
            if truth_bad: st["fraud_blocked"] += 1; blocked_value[fraud] += amount_lakh * 100000
            else: st["false_reject"] += 1
    return {"rule_pack": RULE_PACK, "cycle": cycle, "shipments": len(exporters), "stats": dict(st),
            "blocked_value_by_kind": dict(blocked_value), "leaked_value": leaked, "miss_examples": miss_examples}

if __name__ == "__main__":
    rng = random.Random(37)
    pop = build_population()
    eng = Engine("/tmp/econ/ensur-economy/economy_tadv2.db", store_payloads=False, audit_sources=False)
    out = run_week(eng, pop, 1, rng)
    eng.commit()
    out["audit_valid"] = eng.verify_audit()
    print(json.dumps(out, indent=2))
    json.dump(out, open("/tmp/econ/ensur-economy/trade_adv_w2.json", "w"), indent=2)
