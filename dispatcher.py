"""Retention event dispatcher.

policy -> decision -> experiment arm -> signed webhook event -> outbox log.

Design rules (deliberate):
  * No claim of uplift anywhere: actions are EXPERIMENTS. A deterministic holdout arm is
    withheld so the effect can be measured later against the same 180-day outcome.
  * Missing data never triggers an action (a customer with unknown features gets no event).
  * Real HTTP only when a URL is configured; otherwise DRY-RUN (events are logged, nothing is sent).
  * Events are signed (HMAC-SHA256) and carry an idempotency key; successful sends are never repeated.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

DEFAULT_POLICY = {
    "experiment": "retention-v1",
    "holdout_pct": 20,                       # % of eligible customers withheld as control
    "service_recovery": {"max_csat": 2.0, "min_transit_days": 21.0, "voucher_amount_brl": None},
    "nurture": {"enabled": False, "required_band": "High", "min_csat": 4.0},   # off by default: v2 bands showed no out-of-time support
}

# Order-risk experiment (v3 model). Separate experiment name, randomised per ORDER, 50/50 while testing.
DEFAULT_ORDER_POLICY = {
    "experiment": "order-risk-v1",
    "holdout_pct": 50,
    "target": "went_wrong",
    "bands": ["High"],
}

QUEUES = {
    "service_recovery": "retention.service_recovery.requested",
    "nurture": "retention.nurture.requested",
    "order_proactive_care": "order_risk.proactive_care.requested",
}


# ----------------------------------------------------------------------------- decisions
def decide_frame(df: pd.DataFrame, policy: dict) -> pd.DataFrame:
    """Vectorised policy. Adds `queue` (None = no action) and `reasons`. NaN inputs never trigger."""
    sr, nu = policy["service_recovery"], policy["nurture"]
    csat, transit = df["first_order_csat"], df["transit_days"]
    bad_csat = csat.le(sr["max_csat"]).fillna(False)
    slow = transit.gt(sr["min_transit_days"]).fillna(False)
    recovery = bad_csat | slow
    nurture = (~recovery) & df["risk_band"].eq(nu["required_band"]) & csat.ge(nu["min_csat"]).fillna(False)
    if not nu.get("enabled", True):
        nurture = pd.Series(False, index=df.index)

    out = df.copy()
    out["queue"] = np.select([recovery, nurture], ["service_recovery", "nurture"], default=None)
    why_csat = "review score <= %s" % sr["max_csat"]
    why_slow = "transit > %s days" % sr["min_transit_days"]
    why_nurt = ["model band == %s" % nu["required_band"], "review score >= %s" % nu["min_csat"]]
    out["reasons"] = [
        ([why_csat] if c else []) + ([why_slow] if s else []) if r else (why_nurt if n else [])
        for r, c, s, n in zip(recovery, bad_csat, slow, nurture)
    ]
    return out


def assign_arm(customer_id: str, experiment: str, holdout_pct: float) -> str:
    """Deterministic arm from a hash, so reruns and other systems agree."""
    h = int(hashlib.sha256(f"{experiment}:{customer_id}".encode()).hexdigest(), 16) % 10000
    return "holdout" if h < holdout_pct * 100 else "treatment"


# ----------------------------------------------------------------------------- events
def build_event(row, policy: dict, model_version: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    queue = row["queue"]
    cid = str(row["customer_unique_id"])
    arm = assign_arm(cid, policy["experiment"], policy["holdout_pct"])
    event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{policy['experiment']}|{cid}|{queue}|{model_version}"))
    data = {
        "reasons": list(row["reasons"]),
        "p_repeat_180d": round(float(row["p_repeat"]), 5),
        "risk_band": row["risk_band"],
        "order_id": str(row.get("order_id", "")),
        "template_id": f"{queue}_v1",
    }
    voucher = policy["service_recovery"].get("voucher_amount_brl")
    if queue == "service_recovery" and voucher:
        data["offer"] = {"voucher_amount_brl": float(voucher)}
    return {
        "event_id": event_id,
        "event_type": QUEUES[queue],
        "created_at": now.isoformat(timespec="seconds"),
        "customer_unique_id": cid,
        "experiment": policy["experiment"],
        "arm": arm,
        "model_version": model_version,
        "data": data,
    }


def build_order_event(row, policy: dict, model_version: str, now: datetime | None = None) -> dict:
    """Order-risk event (v3). The arm is hashed on the ORDER id: the unit of the experiment is the order."""
    now = now or datetime.now(timezone.utc)
    oid, cid = str(row["order_id"]), str(row["customer_unique_id"])
    arm = assign_arm(oid, policy["experiment"], policy["holdout_pct"])
    event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{policy['experiment']}|{oid}|order_proactive_care|{model_version}"))
    ctx = {k: (None if pd.isna(row.get(k)) else round(float(row.get(k)), 4))
           for k in ("distance_km", "promised_days", "seller_prior_late_rate", "n_sellers", "total_weight_kg") if k in row}
    return {
        "event_id": event_id,
        "event_type": QUEUES["order_proactive_care"],
        "created_at": now.isoformat(timespec="seconds"),
        "customer_unique_id": cid,
        "order_id": oid,
        "seller_id": str(row.get("seller_id", "")),
        "experiment": policy["experiment"],
        "arm": arm,
        "model_version": model_version,
        "data": {"target": policy["target"], "p_risk": round(float(row["p"]), 5), "risk_band": row["band"],
                 "context": ctx, "template_id": "order_proactive_care_v1"},
    }


def build_care_event(order_id, customer_id, experiment: str, holdout_pct: float, model_version: str, action_id: str,
                     data: dict, now: datetime | None = None) -> dict:
    """Generic order-care event (any dataset package). One decision per order per experiment; arm hashed on the order id."""
    now = now or datetime.now(timezone.utc)
    oid = str(order_id)
    return {
        "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{experiment}|{oid}|care")),
        "event_type": f"order_care.{action_id}.requested",
        "created_at": now.isoformat(timespec="seconds"),
        "customer_unique_id": str(customer_id),
        "order_id": oid,
        "experiment": experiment,
        "arm": assign_arm(oid, experiment, holdout_pct),
        "model_version": model_version,
        "data": data,
    }


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign(secret, timestamp, body), signature)


# ----------------------------------------------------------------------------- dispatcher
class WebhookDispatcher:
    def __init__(self, url: str | None = None, secret: str | None = None, outbox: str | Path = "outbox.jsonl",
                 max_retries: int = 3, timeout: float = 5.0, backoff: float = 0.5):
        self.url = (url or "").strip() or None
        self.secret = secret or os.environ.get("WEBHOOK_SECRET")
        self.outbox = Path(outbox)
        self.max_retries, self.timeout, self.backoff = max_retries, timeout, backoff
        if self.url and not self.secret:
            raise ValueError("A webhook URL is set but no secret was given (set WEBHOOK_SECRET). Refusing to send unsigned events.")
        if self.url and requests is None:
            raise RuntimeError("`requests` is required for live dispatch: pip install requests")

    @property
    def mode(self) -> str:
        return "LIVE" if self.url else "DRY-RUN"

    def _sent_ids(self) -> set:
        """Events already decided for real. A DRY-RUN holdout record must NOT block the live run,
        otherwise the live experiment ends up with no holdout records of its own."""
        if not self.outbox.exists():
            return set()
        ids = set()
        for line in self.outbox.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            same_mode = rec.get("mode", "LIVE") == self.mode
            if rec.get("status") == "sent" or (rec.get("status") in ("withheld_holdout", "skipped_by_user") and same_mode):
                ids.add(rec["event_id"])
        return ids

    def _log(self, event: dict, status: str, **extra) -> dict:
        rec = {"logged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event_id": event["event_id"],
               "event_type": event["event_type"], "experiment": event.get("experiment"),
               "customer_unique_id": event["customer_unique_id"], "order_id": event.get("order_id") or event.get("data", {}).get("order_id"),
               "arm": event["arm"], "status": status, "mode": self.mode, **extra}
        if self._ids is not None and status in ("sent", "withheld_holdout"):
            self._ids.add(event["event_id"])
        with self.outbox.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        return rec

    _ids = None   # cached decided ids during dispatch_many

    def dispatch(self, event: dict) -> dict:
        decided = self._ids if self._ids is not None else self._sent_ids()
        if event["event_id"] in decided:
            return {"event_id": event["event_id"], "status": "duplicate_skipped"}
        if event["arm"] == "holdout":
            return self._log(event, "withheld_holdout")
        if not self.url:
            return self._log(event, "dry_run", payload=event)

        body = json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
        last_err, status_code, attempt = None, None, 0
        for attempt in range(1, self.max_retries + 1):
            ts = str(int(time.time()))
            headers = {"Content-Type": "application/json", "X-Idempotency-Key": event["event_id"],
                       "X-Timestamp": ts, "X-Signature": sign(self.secret, ts, body)}
            try:
                resp = requests.post(self.url, data=body, headers=headers, timeout=self.timeout)
                status_code = resp.status_code
                if 200 <= status_code < 300:
                    return self._log(event, "sent", http_status=status_code, attempts=attempt)
                last_err = f"HTTP {status_code}"
                if status_code < 500 and status_code != 429:
                    break                                  # client error: retrying will not help
            except requests.RequestException as e:
                last_err = type(e).__name__ + ": " + str(e)[:200]
            if attempt < self.max_retries:
                time.sleep(self.backoff * 2 ** (attempt - 1))
        return self._log(event, "failed", http_status=status_code, attempts=attempt, error=last_err)

    def decided_ids(self) -> set:
        return self._sent_ids()

    def record_skip(self, event: dict, reason: str = "") -> dict:
        """The person reviewing chose not to act. Logged so the experiment stays intention-to-treat and the
        learning loop can later see which suggestions people reject and why."""
        if event["event_id"] in self._sent_ids():
            return {"event_id": event["event_id"], "status": "duplicate_skipped"}
        return self._log(event, "skipped_by_user", reason=reason)

    def dispatch_many(self, events: list[dict]) -> pd.DataFrame:
        self._ids = self._sent_ids()          # read the outbox once per batch, not once per event
        try:
            return pd.DataFrame([self.dispatch(e) for e in events])
        finally:
            self._ids = None
