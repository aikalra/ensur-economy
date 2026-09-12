# ensur-economy

A running synthetic economy for the ensur commercial products. 100,000 labeled synthetic
parties use five certification products; every payment decision is made by the engine
(connector evidence -> rule pack -> PAYMENT_CERTIFIED / PAYMENT_HOLD / PAYMENT_REJECTED ->
SHA-256 certificate -> hash-chained audit), and every decision is scored against ground truth.
The miss ledger is published, not hidden.

## Products in the loop

- Welfare benefit (monthly cycles; Gruha Lakshmi-style)
- Parametric crop cover (rainfall trigger, satellite corroborant)
- Hospital benefit (per-admission, cross-facility overlap detection, readmission carve-out)
- Merchant settlement (delivery evidence, buyer confirmation, ring/money-loop detection)
- Trade finance (documentary, physical chain of custody vs customs collusion)

## Files

- `engine.py` - certification core (same semantics as ensur alpha v0.12.0, generalized per-product)
- `population.py` - 100k labeled parties (92k honest, 8k across seven fraud classes)
- `economy_all.py` - consolidated 12-cycle runner, all five products, adaptive adversaries
- `crop.py`, `hospital.py`, `merchant.py`, `trade.py` - product rule packs + adversary models
- `gen_dashboard.py` - renders `docs/index.html` from run ledgers
- `economy_all_report.json` - the consolidated year ledger
- `docs/index.html` - the economy dashboard (GitHub Pages)

## Current state (first simulated year)

- 1.2M decisions; Rs 310+ crore fraudulent value blocked; total leak 0.21% of certified value
- Zero honest parties wrongfully denied (HOLD = delayed, never denied)
- 1M-party single-cycle scale test: audit chain valid, 1M decisions
- Doctrine: HOLD for unproven; fraud is contract-relative; independent physical corroborants
  beat compromised channels; payee integrity is a shared core; residuals are structural -
  bound them, publish them.

All source data is synthetic. The economy does not move money.
