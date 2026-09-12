"""Synthetic population: 100,000 labeled parties for the ensur economy.
v2: mule rings share one operator-controlled account; every party has a name
(name-match and liveness are real evidence, not booleans)."""
import random, json

FRAUD_MIX = [
    ("honest",               0.920),
    ("deceased_on_rolls",    0.020),
    ("duplicate_identity",   0.015),
    ("ghost",                0.010),
    ("account_mule",         0.015),
    ("stale_activity",       0.010),
    ("property_violation",   0.005),
    ("trade_conflict",       0.005),
]
DISTRICTS = ["Bengaluru Urban", "Mysuru", "Belagavi", "Kalaburagi", "Tumakuru", "Ballari", "Hassan", "Dharwad"]
FIRST = ["Asha", "Lakshmi", "Meena", "Ravi", "Suresh", "Anita", "Kiran", "Manju", "Ramesh", "Geeta", "Nagaraj", "Parvati"]
LAST = ["Gowda", "Shetty", "Patil", "Reddy", "Kulkarni", "Hegde", "Rao", "Naik", "Desai", "Kuruba"]

def build_population(n=100000, seed=42):
    rng = random.Random(seed)
    parties = []
    labels = []
    for label, share in FRAUD_MIX:
        labels += [label] * int(round(share * n))
    labels += ["honest"] * (n - len(labels))
    rng.shuffle(labels)
    acct_seq = 1000000
    # build mule rings first: 3-6 identities per ring, one account in the first member's name
    mule_idx = [i for i, l in enumerate(labels) if l == "account_mule"]
    ring_of = {}
    pos = 0
    while pos < len(mule_idx):
        ring_size = rng.randint(3, 6)
        members = mule_idx[pos:pos + ring_size]
        acct_seq += 1
        for i in members:
            ring_of[i] = (f"ACCT-{acct_seq}", members)
        pos += ring_size
    for i in range(n):
        sid = f"SYN-{i+1:06d}"
        label = labels[i]
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        age = int(min(95, max(18, rng.gauss(46, 17))))
        if label == "account_mule":
            account, members = ring_of[i]
        else:
            acct_seq += 1; account = f"ACCT-{acct_seq}"; members = [i]
        p = {
            "subject_id": sid, "true_identity": f"P-{i+1:06d}", "label": label,
            "name": name, "age": age, "district": rng.choice(DISTRICTS),
            "account": account, "ring": [f"SYN-{m+1:06d}" for m in members],
            "alive": label != "deceased_on_rolls",
            "exists": label != "ghost",
            "eligible": label not in ("ghost", "property_violation", "trade_conflict"),
            "qualifying_activity": label != "stale_activity",
            "property_over_ceiling": label == "property_violation",
            "business_conflict": label == "trade_conflict",
            "cycles_inactive": 14 if label == "stale_activity" else rng.randint(0, 2),
            # liveness behavior: honest parties genuinely authenticate ~95% of cycles;
            # families of deceased forge a liveness event ~5% of cycles
            "genuine_auth_p": 0.95 if label != "deceased_on_rolls" else 0.05,
        }
        parties.append(p)
    # account holder name: for mule rings, the FIRST member's name (operator uses own KYC)
    by_id = {p["subject_id"]: p for p in parties}
    for p in parties:
        if p["label"] == "account_mule":
            p["account_holder_name"] = by_id[p["ring"][0]]["name"]
        else:
            p["account_holder_name"] = p["name"]
    dups = [p for p in parties if p["label"] == "duplicate_identity"]
    for j in range(0, len(dups) - 1, 2):
        dups[j+1]["true_identity"] = dups[j]["true_identity"]
        dups[j+1]["name"] = dups[j]["name"]  # same person, same name
    return parties

if __name__ == "__main__":
    pop = build_population()
    from collections import Counter
    print(json.dumps({"parties": len(pop), "labels": dict(Counter(p["label"] for p in pop))}, indent=2))
