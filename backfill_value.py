"""One-time backfill: value metrics for months run before the value layer existed."""
import json
L = "econ_state/ledger.json"
led = json.load(open(L))
BASELINE_DAYS = {"welfare": 45, "hospital": 2, "merchant": 2, "trade": 7, "crop": 180}
BASELINE_COST = {"welfare": 300, "hospital": 150, "merchant": 5, "trade": 2000, "crop": 500}
ENGINE_COST = 0.02; COC = 0.12
STC, STV, SDC, SDV = 0.35, 0.15, 0.25, 0.10
tot = {}
for e in led["history"]:
    if "value" in e:
        for k, v in e["value"].items():
            if isinstance(v, (int, float)) and k != "settlement_days_avg": tot[k] = tot.get(k, 0) + v
        continue
    w, h, m, t = e["welfare"], e["hospital"], e["merchant"], e["trade"]
    c = e.get("crop")
    pdata = {"welfare": (w["certified"]*2000, w["certified"], w.get("hold",0)),
             "hospital": (h["certified"]*30000, h["certified"], h.get("hold",0)),
             "merchant": (m.get("value_settled",0), m.get("certified",0), m.get("hold",0)),
             "trade": (t.get("value_settled_lakh",0)*100000, t["certified"], 0),
             "crop": (c["certified"]*20000 if c else 0, c["certified"] if c else 0, 0)}
    val = {"capital_released":0.0,"cost_savings":0.0,"honest_delayed":0,"enabled_count":0,"enabled_value":0.0,"_n":0.0,"_d":0.0}
    for prod,(gpv,cert,hold) in pdata.items():
        val["capital_released"] += gpv*BASELINE_DAYS[prod]/365*COC
        val["cost_savings"] += cert*(BASELINE_COST[prod]-ENGINE_COST)
        val["honest_delayed"] += hold
        if gpv: val["_n"] += gpv*BASELINE_DAYS[prod]; val["_d"] += gpv
    val["enabled_count"] = int(pdata["merchant"][1]*STC + pdata["crop"][1] + pdata["trade"][1]*SDC)
    val["enabled_value"] = pdata["merchant"][0]*STV + pdata["crop"][0] + pdata["trade"][0]*SDV
    val["settlement_days_avg"] = round(val["_n"]/val["_d"],1) if val["_d"] else 0
    del val["_n"]; del val["_d"]
    e["value"] = val
    for k in ("capital_released","cost_savings","honest_delayed","enabled_count","enabled_value"):
        tot[k] = tot.get(k,0) + val[k]
led["value_totals"] = tot
json.dump(led, open(L,"w"))
print(json.dumps({k: round(v) for k,v in tot.items()}, indent=2))
