"""1M-party scale test: one welfare cycle. Measures engine throughput and memory at 10x."""
import json, random, time, resource
from collections import Counter, defaultdict
from engine import Engine, sha
from population import build_population

t0 = time.time()
pop = build_population(n=1000000, seed=99)
t1 = time.time()
print(f"population build: {t1-t0:.1f}s", flush=True)
pop_index = {"by_true_identity": defaultdict(list), "by_account": defaultdict(list)}
for p in pop:
    pop_index["by_true_identity"][p["true_identity"]].append(p["subject_id"])
    pop_index["by_account"][p["account"]].append(p["subject_id"])
t2 = time.time()
print(f"index build: {t2-t1:.1f}s", flush=True)
import difflib
def name_sim(a, b): return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()
rng = random.Random(5)
eng = Engine("/tmp/econ/ensur-economy/economy_1m.db", store_payloads=False, audit_sources=False)
st = Counter()
for p in pop:
    if p["label"] == "deceased_closed": continue
    k = 0
    while rng.random() > p["genuine_auth_p"]: k += 1
    last_auth = 1 - k
    ev_alive = p["alive"] or rng.random() < 0.6
    reported = p["name"].replace("a", "e", 1) if p["alive"] and rng.random() < 0.004 else p["name"]
    evs = {
        "welfare_api": {"eligible": p["eligible"] and p["exists"], "scheme_status": "ACTIVE"},
        "registry_api": {"alive": ev_alive, "identity_active": p["exists"], "name": reported},
        "bank_api": {"account": p["account"], "account_holder_name": p["account_holder_name"], "account_active": True},
        "property_api": {"property_limit_pass": not p["property_over_ceiling"]},
        "trade_api": {"business_conflict": p["business_conflict"]},
        "activity_api": {"cycles_inactive": p["cycles_inactive"], "last_genuine_auth_cycle": last_auth},
    }
    manifest = []
    for conn, payload in evs.items():
        pl = {**payload, "subject_id": p["subject_id"], "cycle": 1}
        r = eng.submit_evidence("welfare", conn, p["subject_id"], pl)
        if r["status"] == "ACCEPTED": manifest.append({"connector": conn, "payload_hash": sha(pl)})
    hard = [
        ["welfare_eligible", evs["welfare_api"]["eligible"]],
        ["registry_valid", evs["registry_api"]["alive"] and evs["registry_api"]["identity_active"]],
        ["name_match", name_sim(evs["registry_api"]["name"], evs["bank_api"]["account_holder_name"]) >= 0.75],
        ["property_limit", evs["property_api"]["property_limit_pass"]],
        ["trade_conflict_clear", not evs["trade_api"]["business_conflict"]],
        ["account_concentration", len(pop_index["by_account"][p["account"]]) <= 2],
        ["identity_unique_on_rolls", len(pop_index["by_true_identity"][p["true_identity"]]) == 1],
        ["activity_current", evs["activity_api"]["cycles_inactive"] < 12],
    ]
    live = ["liveness_current", 1 - evs["activity_api"]["last_genuine_auth_cycle"] <= 3]
    hf = [r for r, ok in hard if not ok]
    decision = "PAYMENT_REJECTED" if hf else ("PAYMENT_HOLD" if not live[1] else "PAYMENT_CERTIFIED")
    eng.decide("welfare", p["subject_id"], "cycle-1", hard + [live], manifest)
    st[decision] += 1
eng.commit()
t3 = time.time()
print(f"1M decisions: {t3-t2:.1f}s ({1e6/(t3-t2):.0f}/s)", flush=True)
valid = eng.verify_audit()
t4 = time.time()
mem = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
print(json.dumps({"decisions": dict(st), "decision_seconds": round(t3-t2,1),
                  "decisions_per_sec": round(1e6/(t3-t2)), "audit_entries": 1000000,
                  "audit_valid": valid, "audit_verify_seconds": round(t4-t3,1),
                  "peak_rss_mb": round(mem)} , indent=2), flush=True)
