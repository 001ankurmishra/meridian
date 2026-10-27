import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

from meridian.evaluation.external.ibm import parse_row, sha256_file
from meridian.evaluation.external.intelligence import receiver, sender
from meridian.evaluation.external.temporal import SELECTED, evidence_key

cache = Path("scratch/ai-v4/reserve/features.jsonl")
rows = [json.loads(s) for s in cache.read_text().splitlines()]
needed = {r["source_row"] for r in rows}
for r in rows:
    for ids in r["evidence"].values():
        needed.update(ids)
source = {}
with Path("scratch/ai-v2/validated-final/account-sample.csv").open(newline="") as f:
    reader = csv.reader(f)
    next(reader)
    for raw in reader:
        if int(raw[0]) in needed:
            source[int(raw[0])] = parse_row(raw[3:], int(raw[0]), allow_signed=True)
assert len(source) == len(needed)
lock_hash = sha256_file(Path("docs/evaluation/v4/final/reserve-lock.json"))
keys = set()
witness_count = 0
fanout = []
positives = []
for r in rows:
    t = source[r["source_row"]]
    a = tuple(r["account"])
    assert sender(t) == a
    assert t.timestamp == datetime.fromisoformat(r["timestamp"])
    for name in SELECTED:
        key = evidence_key(lock_hash, a, t.row_number, name)
        assert key == r["evidence_keys"][name] and key not in keys
        keys.add(key)
    inc = [source[i] for i in r["evidence"]["prior_24h_incoming_rows"]]
    week = [source[i] for i in r["evidence"]["prior_week_rows"]]
    day = [source[i] for i in r["evidence"]["current_24h_outgoing_rows"]]
    assert all(
        receiver(s) == a
        and sender(s) != a
        and t.timestamp - timedelta(days=1) <= s.timestamp < t.timestamp
        for s in inc
    )
    assert all(
        sender(s) == a
        and t.timestamp - timedelta(days=8)
        <= s.timestamp
        < t.timestamp - timedelta(days=1)
        for s in week
    )
    assert all(
        sender(s) == a and t.timestamp - timedelta(days=1) <= s.timestamp <= t.timestamp
        for s in day
    )
    assert r["amount_history_query"] == dict(
        account=r["account"],
        start=(t.timestamp - timedelta(days=90)).isoformat(),
        end_exclusive=t.timestamp.isoformat(),
    )
    if r["values"]["reciprocal_24h"] is not None:
        rev = [s for s in inc if sender(s) == receiver(t)]
        assert r["values"]["reciprocal_24h"] == float(bool(rev))
        assert r["values"]["fan_in_24h"] == len({sender(s) for s in inc})
        assert t.paid is not None and t.paid >= 0 and receiver(t) != a
        assert all(
            s.paid is not None
            and s.paid >= 0
            and s.received is not None
            and s.received >= 0
            for s in inc
        )
        witness_count += bool(rev)
        if rev and r["label"]:
            positives.append(
                dict(
                    target_source_row=t.row_number,
                    witness_source_rows=[s.row_number for s in rev],
                )
            )
    if all(s.paid is not None and s.paid >= 0 for s in day):
        fanout.append(len({receiver(s) for s in day if receiver(s) != a}))
result = dict(
    status="PASS",
    targets_checked=len(rows),
    source_rows_resolved=len(source),
    unique_scoped_evidence_keys=len(keys),
    reciprocal_witness_targets=witness_count,
    positive_witnesses=positives,
    checks=[
        "target account and timestamp",
        "strict incoming and prior-week bounds",
        "inclusive outgoing bounds",
        "no cross-account window contamination",
        "deterministic artifact keys unique by target and signal",
        "graph values reconstructed from source rows",
        "amount-history query exact reconstruction bounds",
    ],
    observed_fanout_diagnostic=dict(
        evaluable_targets=len(fanout),
        minimum=min(fanout),
        maximum=max(fanout),
        mean=sum(fanout) / len(fanout),
        scope=(
            "descriptive distinct outgoing counterparties in inclusive24h; "
            "no predictive feature added or measured"
        ),
    ),
    cache_sha256=sha256_file(cache),
    audit_script_sha256=sha256_file(Path(__file__)),
)
Path("docs/evaluation/v4/final/source-audit.json").write_text(
    json.dumps(result, indent=2) + "\n"
)
print(json.dumps(result, indent=2))
