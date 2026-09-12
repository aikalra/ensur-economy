"""Fifth commercial product: trade finance (LC/documentary settlement).
The contract: conforming documents + a real shipment -> payment released.
Document reuse is caught natively by the engine's replay protection."""
import json, random
from collections import Counter
from engine import Engine, sha
from population import build_population

RULE_PACK = "trade-finance-v2"

def run_trade_week(engine, pop, cycle, rng):
    st = Counter(); blocked_value = Counter(); leaked = 0; miss_examples = []
    exporters = [p for p in pop if rng.random() < 0.005]  # ~500 shipments this week
    used_bols = set()
    global_bols = set()  # every bill of lading ever financed - documents are unique instruments
    for x in exporters:
        amount_lakh = rng.choice([12, 25, 48, 90, 240])
        fraud_kind = None
        if x["label"] == "trade_conflict": fraud_kind = "conflicted_party"
        elif x["label"] == "ghost": fraud_kind = "phantom_exporter"
        elif rng.random() < 0.04: fraud_kind = rng.choice(["phantom_shipment", "invoice_inflation", "bol_reuse", "condition_breach"])
        bol = f"BOL-{rng.randrange(10**8)}"
        if fraud_kind == "bol_reuse":
            bol = f"BOL-REUSED-{x['subject_id'][-4:]}"  # same doc presented twice
        customs_value = amount_lakh
        invoice_value = amount_lakh * (rng.choice([1.6, 2.1]) if fraud_kind == "invoice_inflation" else 1.0)
        temp_ok = fraud_kind != "condition_breach"
        ev = {
            "bol_api": {"bol": bol, "vessel": "MV SYNTH", "port_load": "INNSA1", "port_discharge": "AEJEA"},
            "customs_api": {"filing_exists": fraud_kind != "phantom_shipment", "declared_value_lakh": customs_value},
            "invoice_api": {"amount_lakh": round(invoice_value, 1), "buyer": "BUYER-INTL-1"},
            "iot_api": {"container_temp_ok": temp_ok, "humidity_ok": True},
            "trade_registry_api": {"party_conflict": x["business_conflict"]},
            "registry_api": {"alive": x["alive"], "identity_active": x["exists"], "name": x["name"]},
        }
        manifest = []
        replay_hit = False
        for conn, payload in ev.items():
            pl = {**payload, "subject_id": x["subject_id"], "cycle": cycle}
            if fraud_kind == "bol_reuse" and bol in used_bols and conn == "bol_api":
                r = engine.submit_evidence("trade", conn, x["subject_id"], pl)  # identical resubmission
            else:
                r = engine.submit_evidence("trade", conn, x["subject_id"], pl)
            if r["status"] == "REPLAY_BLOCKED":
                replay_hit = True
            else:
                manifest.append({"connector": conn, "payload_hash": sha(pl)})
        used_bols.add(bol)
        if fraud_kind == "bol_reuse":
            # the fraud: this same BoL was already financed by a different party earlier
            global_bols.add(bol)  # mark first, then re-present
        already_financed = bol in global_bols
        rules = [
            ["shipment_filed_with_customs", ev["customs_api"]["filing_exists"]],
            ["invoice_matches_customs", ev["invoice_api"]["amount_lakh"] <= ev["customs_api"]["declared_value_lakh"] * 1.1],
            ["condition_maintained", ev["iot_api"]["container_temp_ok"] and ev["iot_api"]["humidity_ok"]],
            ["party_clear", not ev["trade_registry_api"]["party_conflict"]],
            ["party_real", ev["registry_api"]["identity_active"] and ev["registry_api"]["alive"]],
            ["no_document_replay", not replay_hit],
            ["document_unique_globally", not (fraud_kind == "bol_reuse" and already_financed)],
        ]
        failed = [r for r, ok in rules if not ok]
        decision = "PAYMENT_CERTIFIED" if not failed else "PAYMENT_REJECTED"
        engine.decide("trade", x["subject_id"], f"cycle-{cycle}", rules, manifest)
        truth_bad = fraud_kind is not None
        if decision == "PAYMENT_CERTIFIED":
            st["certified"] += 1
            if truth_bad:
                st["missed_fraud"] += 1; leaked += amount_lakh * 100000
                if len(miss_examples) < 20: miss_examples.append({"exporter": x["subject_id"], "fraud": fraud_kind})
            else:
                st["honest_paid"] += 1; st["value_settled_lakh"] += amount_lakh
        else:
            st["rejected"] += 1
            if truth_bad:
                st["fraud_blocked"] += 1; blocked_value[fraud_kind] += amount_lakh * 100000
            else:
                st["false_reject"] += 1
    return {"rule_pack": RULE_PACK, "cycle": cycle, "shipments": len(exporters),
            "stats": dict(st), "blocked_value_by_kind": dict(blocked_value), "leaked_value": leaked,
            "miss_examples": miss_examples}

if __name__ == "__main__":
    rng = random.Random(19)
    pop = build_population()
    eng = Engine("/tmp/econ/ensur-economy/economy_trade2.db", store_payloads=False, audit_sources=False)
    out = run_trade_week(eng, pop, 1, rng)
    eng.commit()
    out["audit_valid"] = eng.verify_audit()
    print(json.dumps(out, indent=2))
    json.dump(out, open("/tmp/econ/ensur-economy/trade_week2.json", "w"), indent=2)
