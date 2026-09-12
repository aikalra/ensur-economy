"""ensur economy engine: deterministic certification core.
Same semantics as the preserved alpha v0.12.0 (connectors -> rules -> certificate -> hash-chained audit),
generalized so any product rule pack can plug in. Batched: one commit per cycle, last audit hash cached.
The alpha itself is untouched."""
import hashlib, hmac, json, sqlite3
from datetime import datetime, timezone

KEY = b"ensur-economy-synthetic-key"
def canon(x): return json.dumps(x, sort_keys=True, separators=(",", ":"))
def sha(x): return hashlib.sha256(canon(x).encode()).hexdigest()
def sign(x): return hmac.new(KEY, canon(x).encode(), hashlib.sha256).hexdigest()

class Engine:
    def __init__(self, path, store_payloads=True, audit_sources=True):
        self.store_payloads = store_payloads
        self.audit_sources = audit_sources
        self.db = sqlite3.connect(path); self.db.row_factory = sqlite3.Row
        self.db.executescript('''PRAGMA journal_mode=WAL; PRAGMA synchronous=OFF;
CREATE TABLE IF NOT EXISTS source_events(event_key TEXT PRIMARY KEY, product TEXT, connector TEXT, subject_id TEXT, payload TEXT, payload_hash TEXT, signature TEXT, ingested_at TEXT);
CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY AUTOINCREMENT, product TEXT, subject_id TEXT, cycle TEXT, decision TEXT, rules TEXT, certificate TEXT, source_manifest TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, subject_id TEXT, body TEXT, previous_hash TEXT, entry_hash TEXT, created_at TEXT);''')
        self.db.commit()
        r = self.db.execute('SELECT entry_hash FROM audit ORDER BY seq DESC LIMIT 1').fetchone()
        self._last_hash = r[0] if r else '0'*64

    def commit(self):
        self.db.commit()

    def _audit(self, event_type, sid, body, now):
        prev = self._last_hash
        base = {"event_type": event_type, "subject_id": sid, "body": body, "previous_hash": prev, "created_at": now}
        eh = sha(base)
        self.db.execute('INSERT INTO audit(event_type,subject_id,body,previous_hash,entry_hash,created_at) VALUES(?,?,?,?,?,?)',
                        (event_type, sid, canon(body), prev, eh, now))
        self._last_hash = eh

    def submit_evidence(self, product, connector, subject_id, payload):
        ph = sha(payload); ek = sha({"product": product, "connector": connector, "subject_id": subject_id, "payload_hash": ph})
        now = datetime.now(timezone.utc).isoformat()
        envelope = {"product": product, "connector": connector, "subject_id": subject_id, "payload": payload, "payload_hash": ph}
        try:
            self.db.execute('INSERT INTO source_events VALUES(?,?,?,?,?,?,?,?)',
                            (ek, product, connector, subject_id,
                             canon(payload) if self.store_payloads else '', ph, sign(envelope), now))
        except sqlite3.IntegrityError:
            self._audit('REPLAY_BLOCKED', subject_id, {"event_key": ek, "product": product}, now)
            return {"status": "REPLAY_BLOCKED", "event_key": ek}
        if self.audit_sources:
            self._audit('SOURCE_ACCEPTED', subject_id, {"product": product, "connector": connector, "event_key": ek, "payload_hash": ph}, now)
        return {"status": "ACCEPTED", "event_key": ek}

    def decide(self, product, subject_id, cycle, rule_results, manifest):
        failed = [r for r, ok in rule_results if not ok]
        decision = 'PAYMENT_CERTIFIED' if not failed else 'PAYMENT_REJECTED'
        cert = sha({"product": product, "subject_id": subject_id, "cycle": cycle,
                    "decision": decision, "rules": rule_results, "source_manifest": manifest})
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute('INSERT INTO decisions(product,subject_id,cycle,decision,rules,certificate,source_manifest,created_at) VALUES(?,?,?,?,?,?,?,?)',
                        (product, subject_id, cycle, decision, canon(rule_results), cert, canon(manifest), now))
        self._audit('DECISION_RECORDED', subject_id, {"product": product, "cycle": cycle, "decision": decision,
                    "failed_rules": failed, "certificate": cert}, now)
        return {"decision": decision, "failed_rules": failed, "certificate": cert}

    def verify_audit(self):
        prev = '0'*64
        for r in self.db.execute('SELECT * FROM audit ORDER BY seq'):
            base = {"event_type": r['event_type'], "subject_id": r['subject_id'], "body": json.loads(r['body']),
                    "previous_hash": r['previous_hash'], "created_at": r['created_at']}
            if r['previous_hash'] != prev or sha(base) != r['entry_hash']: return False
            prev = r['entry_hash']
        return True
