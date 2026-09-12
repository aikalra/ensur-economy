"""The continuous ensur economy: one command = one more month, forever.
State persists (population, engine db, cumulative ledger); dashboard regenerates each cycle.
Includes the economy's own market metrics: GPV per product and certification-fee revenue."""
import json, os, random, sys, time
from collections import Counter, defaultdict
from engine import Engine, sha
from population import build_population
from crop import run_crop_season
from hospital import run_admission_month
from merchant_adv4 import run_day as merchant_day  # evolved pack: spoof/ring adversaries, timeout releases
from trade import run_trade_week
from economy_all import welfare_cycle, name_sim

STATE = "/tmp/econ/ensur-economy/econ_state"
DB = f"{STATE}/economy.db"
POP = f"{STATE}/population.json"
LEDGER = f"{STATE}/ledger.json"
MONTHLY_BENEFIT = 2000
FEE_RATE = 0.0025  # 0.25% certification fee on certified value - the economy's own revenue model

def init_state():
    os.makedirs(STATE, exist_ok=True)
    rng = random.Random(7)
    pop = build_population()
    for p in pop:
        k = 0
        while rng.random() > p["genuine_auth_p"]: k += 1
        p["last_auth_cycle"] = -k
        p["died_cycle"] = 0 if not p["alive"] else None
        p["registry_lag"] = rng.choice([1, 1, 2, 2, 3]) if not p["alive"] else 0
        p["held_amount"] = 0; p["ever_held"] = False
        p["registry_updated_cycle"] = -rng.randint(0, 5)
        p["is_farmer"] = rng.random() < 0.40
        p["farm_acres"] = round(rng.lognormvariate(1.0, 0.6), 1)
        if p["is_farmer"] and p["label"] == "honest" and rng.random() < 0.03:
            p["label"] = "acreage_fraud"
    json.dump(pop, open(POP, "w"))
    json.dump({"cycle": 0, "gpv_by_product": {}, "fees_by_product": {}, "leaked_by_product": {},
               "blocked_by_product": {}, "per_product": {}, "history": []}, open(LEDGER, "w"))

def load():
    pop = json.load(open(POP))
    ledger = json.load(open(LEDGER))
    return pop, ledger

def advance_cycle():
    pop, ledger = load()
    cycle = ledger["cycle"] + 1
    rng = random.Random(1000 + cycle)
    pop_index = {"by_true_identity": defaultdict(list), "by_account": defaultdict(list)}
    for p in pop:
        pop_index["by_true_identity"][p["true_identity"]].append(p["subject_id"])
        pop_index["by_account"][p["account"]].append(p["subject_id"])
    eng = Engine(DB, store_payloads=False, audit_sources=False)
    # mortality
    for p in pop:
        if p["alive"] and rng.random() < 0.00065:
            p["alive"] = False; p["died_cycle"] = cycle; p["registry_lag"] = rng.choice([1, 1, 2, 2, 3])
            if rng.random() < 0.40:
                p["label"] = "deceased_on_rolls"; p["genuine_auth_p"] = 0.05
            else:
                p["label"] = "deceased_closed"; p["genuine_auth_p"] = 0.0
    entry = {"cycle": cycle}
    w, wb, wl = welfare_cycle(eng, pop, pop_index, cycle, rng, product_v6=(cycle >= 4))
    entry["welfare"] = dict(w); w_gpv = w["certified"] * MONTHLY_BENEFIT
    h = run_admission_month(eng, pop, cycle, rng)
    entry["hospital"] = h["stats"]; h_gpv = h["stats"]["certified"] * 30000
    m = merchant_day(eng, pop, cycle, rng, pending=ledger.get("merchant_pending", []))
    ledger["merchant_pending"] = m.pop("pending")
    entry["merchant"] = m["stats"]; m_gpv = m["stats"].get("value_settled", 0)
    t = run_trade_week(eng, pop, cycle, rng)
    entry["trade"] = t["stats"]; t_gpv = t["stats"].get("value_settled_lakh", 0) * 100000
    c_out = None
    if cycle % 6 == 0:
        c_out = run_crop_season(eng, pop, cycle, f"season-{cycle}", rng, ["Kalaburagi", "Ballari", "Raichur"])
        entry["crop"] = c_out["stats"]; c_gpv = c_out["stats"]["certified"] * 20000
    else:
        c_gpv = 0
    eng.db.execute('DELETE FROM source_events'); eng.commit()
    def bump(d, k, v): d[k] = d.get(k, 0) + v
    # Workflow-shaped pricing (economy lesson, month 11): per-event where baseline delay is short
    # vs margin (merchant/trade/hospital), ad-valorem where certification replaces long waiting.
    # Levels = exemplar sustainable fee (value/3x ROI) normalized to per-event units.
    SHAPED_PER_EVENT = {"merchant": 2, "trade": 7000, "hospital": 55}   # Rs per settlement/deal/admission
    shaped = {"merchant": m["stats"].get("certified", 0) * SHAPED_PER_EVENT["merchant"],
              "trade": t["stats"]["certified"] * SHAPED_PER_EVENT["trade"],
              "hospital": h["stats"]["certified"] * SHAPED_PER_EVENT["hospital"],
              "welfare": w_gpv * FEE_RATE, "crop": c_gpv * FEE_RATE}
    entry["fees_shaped"] = {k: round(v) for k, v in shaped.items()}
    for k, v in shaped.items(): bump(ledger.setdefault("fees_shaped_by_product", {}), k, v)
    for prod, gpv, leak in (("welfare", w_gpv, wl), ("hospital", h_gpv, h["leaked_value"]),
                            ("merchant", m_gpv, m["leaked_value"]), ("trade", t_gpv, t["leaked_value"]),
                            ("crop", c_gpv, c_out["leaked_value"] if c_out else 0)):
        bump(ledger["gpv_by_product"], prod, gpv)
        bump(ledger["fees_by_product"], prod, gpv * FEE_RATE)
        bump(ledger["leaked_by_product"], prod, leak)
    for k2, v2 in wb.items(): bump(ledger["blocked_by_product"], f"welfare:{k2}", v2)
    for k2, v2 in h["blocked_value_by_kind"].items(): bump(ledger["blocked_by_product"], f"hospital:{k2}", v2)
    for k2, v2 in m["blocked_value_by_kind"].items(): bump(ledger["blocked_by_product"], f"merchant:{k2}", v2)
    for k2, v2 in t["blocked_value_by_kind"].items(): bump(ledger["blocked_by_product"], f"trade:{k2}", v2)
    if c_out:
        for k2, v2 in c_out["blocked_value_by_label"].items(): bump(ledger["blocked_by_product"], f"crop:{k2}", v2)
    # ---- Beyond fraud: what certification is worth (steering 2026-09-12 8:02 AM) ----
    # All baselines are modeling assumptions, labeled as such on the dashboard. Never present as measured fact.
    BASELINE_DAYS = {"welfare": 45, "hospital": 2, "merchant": 2, "trade": 7, "crop": 180}   # manual verification/settlement latency
    BASELINE_COST = {"welfare": 300, "hospital": 150, "merchant": 5, "trade": 2000, "crop": 500}  # Rs manual cost per decision
    ENGINE_COST = 0.02        # Rs compute per certified decision (measured: ~1,400 decisions/s on one core)
    COST_OF_CAPITAL = 0.12    # p.a. - value of money arriving earlier
    SMALL_TICKET_CNT, SMALL_TICKET_VAL = 0.35, 0.15   # merchant settlements below manual reconciliation break-even
    SMALL_DEAL_CNT, SMALL_DEAL_VAL = 0.25, 0.10       # trade deals too small for manual LC economics
    pdata = {"welfare": (w_gpv, w["certified"], w.get("hold", 0)),
             "hospital": (h_gpv, h["stats"]["certified"], h["stats"].get("hold", 0)),
             "merchant": (m_gpv, m["stats"].get("certified", 0), m["stats"].get("hold", 0)),
             "trade": (t_gpv, t["stats"]["certified"], 0),
             "crop": (c_gpv, c_out["stats"]["certified"] if c_out else 0, 0)}
    val = {"capital_released": 0.0, "cost_savings": 0.0, "honest_delayed": 0,
           "enabled_count": 0, "enabled_value": 0.0, "_days_num": 0.0, "_gpv_den": 0.0}
    for prod, (gpv, cert, hold) in pdata.items():
        val["capital_released"] += gpv * BASELINE_DAYS[prod] / 365 * COST_OF_CAPITAL
        val["cost_savings"] += cert * (BASELINE_COST[prod] - ENGINE_COST)
        val["honest_delayed"] += hold
        if gpv: val["_days_num"] += gpv * BASELINE_DAYS[prod]; val["_gpv_den"] += gpv
    val["enabled_count"] = int(pdata["merchant"][1] * SMALL_TICKET_CNT + pdata["crop"][1] + pdata["trade"][1] * SMALL_DEAL_CNT)
    val["enabled_value"] = pdata["merchant"][0] * SMALL_TICKET_VAL + pdata["crop"][0] + pdata["trade"][0] * SMALL_DEAL_VAL
    val["settlement_days_avg"] = round(val["_days_num"] / val["_gpv_den"], 1) if val["_gpv_den"] else 0
    del val["_days_num"]; del val["_gpv_den"]
    entry["value"] = val
    for k in ("capital_released", "cost_savings", "honest_delayed", "enabled_count", "enabled_value"):
        bump(ledger.setdefault("value_totals", {}), k, val[k])
    ledger["cycle"] = cycle
    ledger["history"].append(entry)
    ledger["audit_valid"] = eng.verify_audit()
    json.dump(pop, open(POP, "w"))
    json.dump(ledger, open(LEDGER, "w"))
    print(json.dumps({"cycle": cycle, "gpv_total": sum(ledger["gpv_by_product"].values()),
                      "fees_total": round(sum(ledger["fees_by_product"].values())),
                      "leaked_total": sum(ledger["leaked_by_product"].values()),
                      "audit_valid": ledger["audit_valid"]}, indent=2))

if __name__ == "__main__":
    if not os.path.exists(POP):
        init_state()
        print("state initialized")
    advance_cycle()
