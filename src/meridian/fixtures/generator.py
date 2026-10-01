import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from meridian.loader.worked_example import generate_worked_example

MANIFEST_SCHEMA_VERSION = "0.1"
FIXTURE_VERSION = "0.1"
GENERATOR_VERSION = "0.1"

ANCHOR_TIMESTAMP = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def deterministic_uuid(seed: str, namespace: str, key: str) -> uuid.UUID:
    h = hashlib.sha256(f"{seed}:{namespace}:{key}".encode("utf-8")).hexdigest()
    return uuid.uuid5(uuid.NAMESPACE_OID, h)


def _get_split(seed: str, fix_id: str) -> str:
    val = int(hashlib.md5(f"{seed}_{fix_id}".encode()).hexdigest(), 16)
    return "train" if val % 2 == 0 else "eval"


def generate_fixtures(seed: str = "default_seed") -> dict[str, Any]:
    customers = []
    accounts = []
    transactions = []
    beneficiaries = []
    entities = []
    graph_relationships = []
    manifest_entries: list[dict[str, Any]] = []

    def add_entity(
        e_id: uuid.UUID, e_type: str, r_id: uuid.UUID, created_at: datetime
    ) -> None:
        entities.append(
            {
                "entity_id": e_id,
                "entity_type": e_type,
                "reference_id": r_id,
                "created_at": created_at,
            }
        )

    def add_rel(
        s_id: uuid.UUID,
        t_id: uuid.UUID,
        r_type: str,
        w: float,
        first: datetime,
        last: datetime,
    ) -> None:
        rel_id = deterministic_uuid(
            seed, "rel", f"{s_id}_{t_id}_{r_type}_{first.isoformat()}"
        )
        graph_relationships.append(
            {
                "relationship_id": rel_id,
                "source_entity_id": s_id,
                "target_entity_id": t_id,
                "relationship_type": r_type,
                "weight": w,
                "first_observed_at": first,
                "last_observed_at": last,
                "created_at": ANCHOR_TIMESTAMP,
            }
        )

    fix_counter = 1

    def next_fix_id() -> str:
        nonlocal fix_counter
        fid = f"fx-{fix_counter:04d}"
        fix_counter += 1
        return fid

    def create_subject(
        fix_id: str,
        suffix: str,
        onboard_days: int = 365,
        acct_type: str = "SAVINGS",
        has_history: bool = True,
    ) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
        c_id = deterministic_uuid(seed, fix_id, f"cust_{suffix}")
        a_id = deterministic_uuid(seed, fix_id, f"acct_{suffix}")
        source = f"fixture:{fix_id}"
        c_time = ANCHOR_TIMESTAMP - timedelta(days=onboard_days)

        customers.append(
            {
                "customer_id": c_id,
                "full_name": f"Synthetic {suffix} {fix_id}",
                "date_of_birth": "1980-01-01",
                "kyc_risk_rating": "LOW",
                "onboarded_at": c_time,
                "source": source,
                "created_at": ANCHOR_TIMESTAMP,
                "is_synthetic": True,
            }
        )

        accounts.append(
            {
                "account_id": a_id,
                "customer_id": c_id,
                "account_type": acct_type,
                "opened_at": c_time,
                "status": "active",
                "created_at": ANCHOR_TIMESTAMP,
            }
        )

        e_c_id = deterministic_uuid(seed, fix_id, f"ent_c_{suffix}")
        e_a_id = deterministic_uuid(seed, fix_id, f"ent_a_{suffix}")

        add_entity(e_c_id, "customer", c_id, ANCHOR_TIMESTAMP)
        add_entity(e_a_id, "account", a_id, ANCHOR_TIMESTAMP)
        add_rel(e_c_id, e_a_id, "OWNS", 1.0, c_time, ANCHOR_TIMESTAMP)

        if has_history:
            # Provide 1 qualifying historical outgoing transaction 30 days ago
            # so the AmountDeviation agent can compute a baseline and return COMPLETE
            add_tx(fix_id, f"hist_{suffix}", a_id, None, 1000.0, 24 * 30)

        return c_id, a_id, e_c_id, e_a_id

    def add_tx(
        fix_id: str,
        tx_key: str,
        src_a: uuid.UUID,
        dst_a: uuid.UUID | None,
        amt: float,
        time_ago_hrs: float,
    ) -> tuple[uuid.UUID, dict[str, Any]]:
        tx_id = deterministic_uuid(seed, fix_id, tx_key)
        tx_time = ANCHOR_TIMESTAMP - timedelta(hours=time_ago_hrs)
        tx = {
            "transaction_id": tx_id,
            "source_account_id": src_a,
            "destination_account_id": dst_a,
            "amount": amt,
            "currency": "INR",
            "transaction_type": "TRANSFER",
            "occurred_at": tx_time,
            "counterparty_external_ref": None,
            "source": f"fixture:{fix_id}",
            "created_at": ANCHOR_TIMESTAMP,
        }
        transactions.append(tx)
        return tx_id, tx

    def add_bene(
        fix_id: str, b_key: str, c_id: uuid.UUID, a_id: uuid.UUID, days_ago: int
    ) -> uuid.UUID:
        b_id = deterministic_uuid(seed, fix_id, b_key)
        beneficiaries.append(
            {
                "beneficiary_id": b_id,
                "customer_id": c_id,
                "account_id": a_id,
                "added_at": ANCHOR_TIMESTAMP - timedelta(days=days_ago),
                "created_at": ANCHOR_TIMESTAMP,
            }
        )
        return b_id

    # 1. Structuring (3 instances)
    for _ in range(3):
        fix_id = next_fix_id()
        c_id, a_id, e_c, e_a = create_subject(fix_id, "subject")
        tx_ids = []
        for i in range(4):
            tx_id, _ = add_tx(fix_id, f"tx_{i}", a_id, None, 9500.0, 24.0 - i)
            tx_ids.append(tx_id)

        manifest_entries.append(
            {
                "fixture_id": fix_id,
                "scenario_class": "structuring",
                "taxonomy": "structuring",
                "split": _get_split(seed, fix_id),
                "customer_id": str(c_id),
                "account_ids": [str(a_id)],
                "transaction_ids": [str(tid) for tid in tx_ids],
                "beneficiary_ids": [],
                "alert_spec": {
                    "customer_id": str(c_id),
                    "alert_type": "AML_STRUCTURING",
                    "alert_reasons": {
                        "reason": (
                            "Multiple cash deposits just under reporting threshold"
                        )
                    },
                    "transaction_id": str(tx_ids[-1]),
                },
                "evaluation_target": "AML_STRUCTURING",
                "ground_truth": "AML_STRUCTURING",
                "planted_pattern": "4 deposits of 9500 in 24 hours",
                "pattern_members": [str(tid) for tid in tx_ids],
                "runtime_expectation": "COMPLETE",
            }
        )

    # 2. Rapid movement (3 instances)
    for _ in range(3):
        fix_id = next_fix_id()
        c1, a1, e_c1, e_a1 = create_subject(fix_id, "s1")
        c2, a2, e_c2, e_a2 = create_subject(fix_id, "s2")
        c3, a3, e_c3, e_a3 = create_subject(fix_id, "s3")

        b1 = add_bene(fix_id, "b1", c1, a2, 1)
        b2 = add_bene(fix_id, "b2", c2, a3, 1)

        tx1, _ = add_tx(fix_id, "tx1", a1, a2, 50000.0, 2.0)
        tx2, _ = add_tx(fix_id, "tx2", a2, a3, 49900.0, 1.9)

        add_rel(e_a1, e_a2, "TRANSACTED_WITH", 1.0, ANCHOR_TIMESTAMP, ANCHOR_TIMESTAMP)
        add_rel(e_a2, e_a3, "TRANSACTED_WITH", 1.0, ANCHOR_TIMESTAMP, ANCHOR_TIMESTAMP)

        manifest_entries.append(
            {
                "fixture_id": fix_id,
                "scenario_class": "rapid_movement",
                "taxonomy": "rapid_movement",
                "split": _get_split(seed, fix_id),
                "customer_id": str(c1),
                "account_ids": [str(a1), str(a2), str(a3)],
                "transaction_ids": [str(tx1), str(tx2)],
                "beneficiary_ids": [str(b1), str(b2)],
                "alert_spec": {
                    "customer_id": str(c1),
                    "alert_type": "AML_RAPID_MOVEMENT",
                    "alert_reasons": {
                        "reason": "Funds transferred and immediately forwarded"
                    },
                    "transaction_id": str(tx1),
                },
                "evaluation_target": "AML_RAPID_MOVEMENT",
                "ground_truth": "AML_RAPID_MOVEMENT",
                "planted_pattern": "Funds moved through 3 accounts in 6 minutes",
                "pattern_members": [str(tx1), str(tx2)],
                "runtime_expectation": "COMPLETE",
            }
        )

    # 3. Circular transfer (3 instances)
    for _ in range(3):
        fix_id = next_fix_id()
        c1, a1, e_c1, e_a1 = create_subject(fix_id, "s1")
        c2, a2, e_c2, e_a2 = create_subject(fix_id, "s2")
        c3, a3, e_c3, e_a3 = create_subject(fix_id, "s3")

        tx1, _ = add_tx(fix_id, "tx1", a1, a2, 10000.0, 3.0)
        tx2, _ = add_tx(fix_id, "tx2", a2, a3, 9900.0, 2.0)
        tx3, _ = add_tx(fix_id, "tx3", a3, a1, 9800.0, 1.0)

        add_rel(e_a1, e_a2, "TRANSACTED_WITH", 1.0, ANCHOR_TIMESTAMP, ANCHOR_TIMESTAMP)
        add_rel(e_a2, e_a3, "TRANSACTED_WITH", 1.0, ANCHOR_TIMESTAMP, ANCHOR_TIMESTAMP)
        add_rel(e_a3, e_a1, "TRANSACTED_WITH", 1.0, ANCHOR_TIMESTAMP, ANCHOR_TIMESTAMP)

        manifest_entries.append(
            {
                "fixture_id": fix_id,
                "scenario_class": "circular_transfer",
                "taxonomy": "circular_transfer",
                "split": _get_split(seed, fix_id),
                "customer_id": str(c1),
                "account_ids": [str(a1), str(a2), str(a3)],
                "transaction_ids": [str(tx1), str(tx2), str(tx3)],
                "beneficiary_ids": [],
                "alert_spec": {
                    "customer_id": str(c1),
                    "alert_type": "AML_CIRCULAR",
                    "alert_reasons": {"reason": "Circular flow of funds"},
                    "transaction_id": str(tx3),
                },
                "evaluation_target": "AML_CIRCULAR",
                "ground_truth": "AML_CIRCULAR",
                "planted_pattern": "A->B->C->A cycle",
                "pattern_members": [str(tx1), str(tx2), str(tx3)],
                "runtime_expectation": "COMPLETE",
            }
        )

    # 4. Mule account chain (3 instances)
    for _ in range(3):
        fix_id = next_fix_id()
        c1, a1, e_c1, e_a1 = create_subject(fix_id, "s1")
        c2, a2, e_c2, e_a2 = create_subject(fix_id, "s2")
        c3, a3, e_c3, e_a3 = create_subject(fix_id, "s3")
        c4, a4, e_c4, e_a4 = create_subject(fix_id, "s4")

        tx1, _ = add_tx(fix_id, "tx1", a1, a2, 5000.0, 4.0)
        tx2, _ = add_tx(fix_id, "tx2", a2, a3, 4900.0, 3.0)
        tx3, _ = add_tx(fix_id, "tx3", a3, a4, 4800.0, 2.0)

        add_rel(e_a1, e_a2, "TRANSACTED_WITH", 1.0, ANCHOR_TIMESTAMP, ANCHOR_TIMESTAMP)
        add_rel(e_a2, e_a3, "TRANSACTED_WITH", 1.0, ANCHOR_TIMESTAMP, ANCHOR_TIMESTAMP)
        add_rel(e_a3, e_a4, "TRANSACTED_WITH", 1.0, ANCHOR_TIMESTAMP, ANCHOR_TIMESTAMP)

        manifest_entries.append(
            {
                "fixture_id": fix_id,
                "scenario_class": "mule_account_chain",
                "taxonomy": "mule_account_chain",
                "split": _get_split(seed, fix_id),
                "customer_id": str(c1),
                "account_ids": [str(a1), str(a2), str(a3), str(a4)],
                "transaction_ids": [str(tx1), str(tx2), str(tx3)],
                "beneficiary_ids": [],
                "alert_spec": {
                    "customer_id": str(c1),
                    "alert_type": "AML_MULE",
                    "alert_reasons": {"reason": "Mule chain identified"},
                    "transaction_id": str(tx1),
                },
                "evaluation_target": "AML_MULE",
                "ground_truth": "AML_MULE",
                "planted_pattern": "4-hop mule chain",
                "pattern_members": [str(tx1), str(tx2), str(tx3)],
                "runtime_expectation": "COMPLETE",
            }
        )

    # 5. Clean control (6 instances)
    for _ in range(6):
        fix_id = next_fix_id()
        c1, a1, e_c1, e_a1 = create_subject(fix_id, "s1")

        tx1, _ = add_tx(fix_id, "tx1", a1, None, 100.0, 24.0)
        tx2, _ = add_tx(fix_id, "tx2", a1, None, 50.0, 12.0)

        manifest_entries.append(
            {
                "fixture_id": fix_id,
                "scenario_class": "clean_control",
                "taxonomy": "clean_control",
                "split": _get_split(seed, fix_id),
                "customer_id": str(c1),
                "account_ids": [str(a1)],
                "transaction_ids": [str(tx1), str(tx2)],
                "beneficiary_ids": [],
                "alert_spec": {
                    "customer_id": str(c1),
                    "alert_type": "AML_GENERAL",
                    "alert_reasons": {"reason": "Routine screening"},
                    "transaction_id": str(tx2),
                },
                "evaluation_target": "AML_GENERAL",
                "ground_truth": "CLEAN",
                "planted_pattern": "Normal retail spending",
                "pattern_members": [str(tx1), str(tx2)],
                "runtime_expectation": "COMPLETE",
            }
        )

    # 6. Runtime edge case: Insufficient history (1 instance)
    fix_id = next_fix_id()
    c1, a1, e_c1, e_a1 = create_subject(fix_id, "s1", onboard_days=0, has_history=False)
    tx1, _ = add_tx(fix_id, "tx1", a1, None, 10.0, 0.1)

    manifest_entries.append(
        {
            "fixture_id": fix_id,
            "scenario_class": "insufficient_history",
            "taxonomy": "runtime_edge_case",
            "split": _get_split(seed, fix_id),
            "customer_id": str(c1),
            "account_ids": [str(a1)],
            "transaction_ids": [str(tx1)],
            "beneficiary_ids": [],
            "alert_spec": {
                "customer_id": str(c1),
                "alert_type": "AML_GENERAL",
                "alert_reasons": {"reason": "New account first transaction"},
                "transaction_id": str(tx1),
            },
            "evaluation_target": "AML_GENERAL",
            "ground_truth": None,
            "planted_pattern": "New account with no history",
            "pattern_members": [str(tx1)],
            "runtime_expectation": "INCOMPLETE_INSUFFICIENT_EVIDENCE",
        }
    )

    # Include worked example reference
    import unittest.mock

    class MockDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> "MockDatetime":
            return cls(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    with unittest.mock.patch("meridian.loader.worked_example.datetime", MockDatetime):
        we_data = generate_worked_example()
    customers.extend(we_data["customers"])
    accounts.extend(we_data["accounts"])
    transactions.extend(we_data["transactions"])
    beneficiaries.extend(we_data["beneficiaries"])
    entities.extend(we_data["entities"])
    graph_relationships.extend(we_data["graph_relationships"])

    rahul_id = str(uuid.uuid5(uuid.NAMESPACE_OID, "rahul_sharma"))
    suspicious_tx_id = str(uuid.uuid5(uuid.NAMESPACE_OID, "rahul_to_tech_sol_tx"))

    manifest_entries.append(
        {
            "fixture_id": "worked_example",
            "scenario_class": "worked_example",
            "taxonomy": "reference",
            "split": "train",
            "customer_id": rahul_id,
            "account_ids": [],
            "transaction_ids": [],
            "beneficiary_ids": [],
            "alert_spec": {
                "customer_id": rahul_id,
                "alert_type": "AML_GENERAL",
                "alert_reasons": {"reason": "Worked example manual trigger"},
                "transaction_id": suspicious_tx_id,
            },
            "evaluation_target": "AML_GENERAL",
            "ground_truth": "AML_GENERAL",
            "planted_pattern": "Worked example reference",
            "pattern_members": [],
            "runtime_expectation": "COMPLETE",
        }
    )

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "fixture_version": FIXTURE_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "anchor_timestamp": ANCHOR_TIMESTAMP.isoformat(),
        "fixtures": manifest_entries,
    }

    return {
        "manifest": manifest,
        "customers": customers,
        "accounts": accounts,
        "transactions": transactions,
        "beneficiaries": beneficiaries,
        "entities": entities,
        "graph_relationships": graph_relationships,
    }


def generate_fixtures_v02(seed: str = "default_seed") -> dict[str, Any]:
    import hashlib
    import uuid
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal

    from meridian.loader.worked_example import generate_worked_example

    MANIFEST_SCHEMA_VERSION = "0.2"
    FIXTURE_VERSION = "0.2"
    GENERATOR_VERSION = "0.2"
    ANCHOR_TIMESTAMP = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    customers = []
    accounts = []
    transactions = []
    beneficiaries = []
    entities: list[dict[str, Any]] = []
    graph_relationships: list[dict[str, Any]] = []
    manifest_entries: list[dict[str, Any]] = []

    def deterministic_uuid(seed: str, namespace: str, key: str) -> uuid.UUID:
        h = hashlib.sha256(f"{seed}:{namespace}:{key}".encode("utf-8")).hexdigest()
        return uuid.uuid5(uuid.NAMESPACE_OID, h)

    def deterministic_float(seed: str, key: str) -> float:
        h = int(hashlib.sha256(f"{seed}:{key}".encode("utf-8")).hexdigest(), 16)
        return h / float(2**256 - 1)

    def deterministic_int(seed: str, key: str, min_val: int, max_val: int) -> int:
        h = int(hashlib.sha256(f"{seed}:{key}".encode("utf-8")).hexdigest(), 16)
        range_val = max_val - min_val
        return min_val + (h % (range_val + 1))

    def deterministic_amount(
        seed: str, key: str, min_amt: float, max_amt: float
    ) -> Decimal:
        h = int(hashlib.sha256(f"{seed}:{key}".encode("utf-8")).hexdigest(), 16)
        min_cents = int(Decimal(str(min_amt)) * 100)
        max_cents = int(Decimal(str(max_amt)) * 100)
        range_cents = max_cents - min_cents
        val_cents = min_cents + (h % (range_cents + 1))
        return Decimal(val_cents) / Decimal("100.00")

    def add_entity(
        e_id: uuid.UUID, e_type: str, r_id: uuid.UUID, created_at: datetime
    ) -> None:
        entities.append(
            {
                "entity_id": e_id,
                "entity_type": e_type,
                "reference_id": r_id,
                "created_at": created_at,
            }
        )

    def add_rel(
        s_id: uuid.UUID,
        t_id: uuid.UUID,
        r_type: str,
        w: float,
        first: datetime,
        last: datetime,
    ) -> None:
        rel_id = deterministic_uuid(
            seed, "rel", f"{s_id}_{t_id}_{r_type}_{first.isoformat()}"
        )
        graph_relationships.append(
            {
                "relationship_id": rel_id,
                "source_entity_id": s_id,
                "target_entity_id": t_id,
                "relationship_type": r_type,
                "weight": w,
                "first_observed_at": first,
                "last_observed_at": last,
                "created_at": ANCHOR_TIMESTAMP,
            }
        )

    fix_counter = 1

    def next_fix_id() -> str:
        nonlocal fix_counter
        fid = f"fx-{fix_counter:04d}"
        fix_counter += 1
        return fid

    def create_subject(
        fix_id: str, suffix: str, onboard_days: int = 365, acct_type: str = "SAVINGS"
    ) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
        c_id = deterministic_uuid(seed, fix_id, f"cust_{suffix}")
        a_id = deterministic_uuid(seed, fix_id, f"acct_{suffix}")
        source = f"fixture:{fix_id}"
        c_time = ANCHOR_TIMESTAMP - timedelta(days=onboard_days)

        customers.append(
            {
                "customer_id": c_id,
                "full_name": f"Synthetic {suffix} {fix_id}",
                "date_of_birth": "1980-01-01",
                "kyc_risk_rating": "LOW",
                "onboarded_at": c_time,
                "source": source,
                "created_at": ANCHOR_TIMESTAMP,
                "is_synthetic": True,
            }
        )

        accounts.append(
            {
                "account_id": a_id,
                "customer_id": c_id,
                "account_type": acct_type,
                "opened_at": c_time,
                "status": "active",
                "created_at": ANCHOR_TIMESTAMP,
            }
        )

        e_c_id = deterministic_uuid(seed, fix_id, f"ent_c_{suffix}")
        e_a_id = deterministic_uuid(seed, fix_id, f"ent_a_{suffix}")

        add_entity(e_c_id, "customer", c_id, ANCHOR_TIMESTAMP)
        add_entity(e_a_id, "account", a_id, ANCHOR_TIMESTAMP)
        add_rel(e_c_id, e_a_id, "OWNS", 1.0, c_time, ANCHOR_TIMESTAMP)

        return c_id, a_id, e_c_id, e_a_id

    def add_tx(
        fix_id: str,
        tx_key: str,
        src_a: uuid.UUID,
        dst_a: uuid.UUID | None,
        amt: Decimal,
        time_ago_hrs: float,
    ) -> tuple[uuid.UUID, dict[str, Any]]:
        tx_id = deterministic_uuid(seed, fix_id, tx_key)
        tx_time = ANCHOR_TIMESTAMP - timedelta(hours=time_ago_hrs)
        tx = {
            "transaction_id": tx_id,
            "source_account_id": src_a,
            "destination_account_id": dst_a,
            "amount": float(amt),
            "currency": "INR",
            "transaction_type": "TRANSFER",
            "occurred_at": tx_time,
            "counterparty_external_ref": None,
            "source": f"fixture:{fix_id}",
            "created_at": ANCHOR_TIMESTAMP,
        }
        transactions.append(tx)
        return tx_id, tx

    def add_bene(
        fix_id: str, b_key: str, c_id: uuid.UUID, a_id: uuid.UUID, days_ago: int
    ) -> uuid.UUID:
        b_id = deterministic_uuid(seed, fix_id, b_key)
        beneficiaries.append(
            {
                "beneficiary_id": b_id,
                "customer_id": c_id,
                "account_id": a_id,
                "added_at": ANCHOR_TIMESTAMP - timedelta(days=days_ago),
                "created_at": ANCHOR_TIMESTAMP,
            }
        )
        return b_id

    def generate_history(fix_id: str, a_id: uuid.UUID, suffix: str) -> Decimal:
        num_hist = deterministic_int(seed, f"{fix_id}_num_hist", 3, 8)
        total_amt = Decimal("0.00")
        for i in range(num_hist):
            amt = deterministic_amount(seed, f"{fix_id}_hist_amt_{i}", 100.0, 5000.0)
            time_ago = (
                deterministic_float(seed, f"{fix_id}_hist_time_{i}") * 2000.0 + 24.0
            )  # 1 to 84 days ago
            add_tx(fix_id, f"hist_{suffix}_{i}", a_id, None, amt, time_ago)
            total_amt += amt
        return (total_amt / Decimal(num_hist)).quantize(Decimal("0.01"))

    # Helpers for scenarios
    def add_scenario(
        sc: str,
        st: str,
        gt: str | None,
        count: int,
        planted_patt: str,
        eval_target: str,
        ratio_min: float,
        ratio_max: float,
        pattern_type: str,
    ) -> None:
        for _ in range(count):
            fix_id = next_fix_id()
            c1, a1, _, _ = create_subject(fix_id, "s1")

            avg_hist = generate_history(fix_id, a1, "s1")
            ratio = deterministic_amount(seed, f"{fix_id}_ratio", ratio_min, ratio_max)
            target_amt = (avg_hist * ratio).quantize(Decimal("0.01"))

            tx_ids = []
            if pattern_type == "structuring":
                for i in range(4):
                    if i == 3:
                        tx_amt = target_amt
                    else:
                        noise = deterministic_amount(
                            seed, f"{fix_id}_noise_{i}", -50.0, 50.0
                        )
                        tx_amt = max(Decimal("0.01"), target_amt + noise)
                    tx_id, _ = add_tx(fix_id, f"tx_{i}", a1, None, tx_amt, 24.0 - i)
                    tx_ids.append(tx_id)
            elif pattern_type == "rapid_movement":
                c2, a2, _, _ = create_subject(fix_id, "s2")
                c3, a3, _, _ = create_subject(fix_id, "s3")
                add_bene(fix_id, "b1", c1, a2, 1)
                add_bene(fix_id, "b2", c2, a3, 1)
                tx1, _ = add_tx(fix_id, "tx1", a1, a2, target_amt, 2.0)
                tx2, _ = add_tx(
                    fix_id, "tx2", a2, a3, target_amt - Decimal("100.00"), 1.9
                )
                tx_ids = [tx1, tx2]
            elif pattern_type == "circular_transfer":
                c2, a2, _, _ = create_subject(fix_id, "s2")
                c3, a3, _, _ = create_subject(fix_id, "s3")
                tx1, _ = add_tx(fix_id, "tx1", a1, a2, target_amt, 3.0)
                tx2, _ = add_tx(
                    fix_id, "tx2", a2, a3, target_amt - Decimal("100.00"), 2.0
                )
                tx3, _ = add_tx(
                    fix_id, "tx3", a3, a1, target_amt - Decimal("200.00"), 1.0
                )
                tx_ids = [tx1, tx2, tx3]
            elif pattern_type == "mule_account_chain":
                c2, a2, _, _ = create_subject(fix_id, "s2")
                c3, a3, _, _ = create_subject(fix_id, "s3")
                c4, a4, _, _ = create_subject(fix_id, "s4")
                tx1, _ = add_tx(fix_id, "tx1", a1, a2, target_amt, 4.0)
                tx2, _ = add_tx(
                    fix_id, "tx2", a2, a3, target_amt - Decimal("100.00"), 3.0
                )
                tx3, _ = add_tx(
                    fix_id, "tx3", a3, a4, target_amt - Decimal("200.00"), 2.0
                )
                tx_ids = [tx1, tx2, tx3]
            elif pattern_type == "clean_control":
                tx1, _ = add_tx(fix_id, "tx1", a1, None, target_amt, 12.0)
                tx_ids = [tx1]

            manifest_entries.append(
                {
                    "fixture_id": fix_id,
                    "scenario_class": sc,
                    "scenario_subtype": st,
                    "taxonomy": sc,
                    "split": "temp",
                    "customer_id": str(c1),
                    "account_ids": [str(a1)],
                    "transaction_ids": [str(t) for t in tx_ids],
                    "beneficiary_ids": [],
                    "alert_spec": {
                        "customer_id": str(c1),
                        "alert_type": eval_target,
                        "alert_reasons": {"reason": f"{st} scenario"},
                        "transaction_id": str(tx_ids[-1]),
                    },
                    "evaluation_target": eval_target,
                    "ground_truth": gt,
                    "planted_pattern": planted_patt,
                    "pattern_members": [str(t) for t in tx_ids],
                    "runtime_expectation": "COMPLETE",
                    "split_methodology": "stable sorted alternating",
                }
            )

    # 1. Structuring (8 instances: 4 baseline, 4 elevated)
    add_scenario(
        "structuring",
        "baseline",
        "AML_STRUCTURING",
        4,
        "4 deposits",
        "AML_STRUCTURING",
        0.60,
        2.00,
        "structuring",
    )
    add_scenario(
        "structuring",
        "elevated",
        "AML_STRUCTURING",
        4,
        "4 deposits",
        "AML_STRUCTURING",
        4.00,
        15.00,
        "structuring",
    )

    # 2. Rapid movement (8 instances: 4 baseline, 4 elevated)
    add_scenario(
        "rapid_movement",
        "baseline",
        "AML_RAPID_MOVEMENT",
        4,
        "3 hops",
        "AML_RAPID_MOVEMENT",
        0.60,
        2.00,
        "rapid_movement",
    )
    add_scenario(
        "rapid_movement",
        "elevated",
        "AML_RAPID_MOVEMENT",
        4,
        "3 hops",
        "AML_RAPID_MOVEMENT",
        4.00,
        15.00,
        "rapid_movement",
    )

    # 3. Circular transfer (8 instances: 4 baseline, 4 elevated)
    add_scenario(
        "circular_transfer",
        "baseline",
        "AML_CIRCULAR",
        4,
        "A->B->C->A",
        "AML_CIRCULAR",
        0.60,
        2.00,
        "circular_transfer",
    )
    add_scenario(
        "circular_transfer",
        "elevated",
        "AML_CIRCULAR",
        4,
        "A->B->C->A",
        "AML_CIRCULAR",
        4.00,
        15.00,
        "circular_transfer",
    )

    # 4. Mule account chain (8 instances: 4 baseline, 4 elevated)
    add_scenario(
        "mule_account_chain",
        "baseline",
        "AML_MULE",
        4,
        "4-hop",
        "AML_MULE",
        0.60,
        2.00,
        "mule_account_chain",
    )
    add_scenario(
        "mule_account_chain",
        "elevated",
        "AML_MULE",
        4,
        "4-hop",
        "AML_MULE",
        4.00,
        15.00,
        "mule_account_chain",
    )

    # 5. Clean control (24 instances: 12 typical, 12 large_legitimate)
    add_scenario(
        "clean_control",
        "typical",
        "CLEAN",
        12,
        "Routine",
        "AML_GENERAL",
        0.50,
        1.50,
        "clean_control",
    )
    add_scenario(
        "clean_control",
        "large_legitimate",
        "CLEAN",
        12,
        "Large routine",
        "AML_GENERAL",
        3.00,
        12.00,
        "clean_control",
    )

    # 6. Insufficient history (1 instance)
    fix_id = next_fix_id()
    c1, a1, e_c1, e_a1 = create_subject(fix_id, "s1", onboard_days=0)
    tx1, _ = add_tx(fix_id, "tx1", a1, None, Decimal("10.00"), 0.1)

    manifest_entries.append(
        {
            "fixture_id": fix_id,
            "scenario_class": "insufficient_history",
            "scenario_subtype": "baseline",
            "taxonomy": "runtime_edge_case",
            "split": "temp",
            "customer_id": str(c1),
            "account_ids": [str(a1)],
            "transaction_ids": [str(tx1)],
            "beneficiary_ids": [],
            "alert_spec": {
                "customer_id": str(c1),
                "alert_type": "AML_GENERAL",
                "alert_reasons": {"reason": "New account first transaction"},
                "transaction_id": str(tx1),
            },
            "evaluation_target": "AML_GENERAL",
            "ground_truth": None,
            "planted_pattern": "New account with no history",
            "pattern_members": [str(tx1)],
            "runtime_expectation": "INCOMPLETE_INSUFFICIENT_EVIDENCE",
            "split_methodology": "stable sorted alternating",
        }
    )

    # Worked example
    import unittest.mock

    class MockDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> "MockDatetime":
            return cls(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    with unittest.mock.patch("meridian.loader.worked_example.datetime", MockDatetime):
        we_data = generate_worked_example()
    customers.extend(we_data["customers"])
    accounts.extend(we_data["accounts"])
    transactions.extend(we_data["transactions"])
    beneficiaries.extend(we_data["beneficiaries"])
    entities.extend(we_data["entities"])
    graph_relationships.extend(we_data["graph_relationships"])

    rahul_id = str(uuid.uuid5(uuid.NAMESPACE_OID, "rahul_sharma"))
    suspicious_tx_id = str(uuid.uuid5(uuid.NAMESPACE_OID, "rahul_to_tech_sol_tx"))

    manifest_entries.append(
        {
            "fixture_id": "worked_example",
            "scenario_class": "worked_example",
            "scenario_subtype": "baseline",
            "taxonomy": "reference",
            "split": "train",
            "customer_id": rahul_id,
            "account_ids": [],
            "transaction_ids": [],
            "beneficiary_ids": [],
            "alert_spec": {
                "customer_id": rahul_id,
                "alert_type": "AML_GENERAL",
                "alert_reasons": {"reason": "Worked example manual trigger"},
                "transaction_id": suspicious_tx_id,
            },
            "evaluation_target": "AML_GENERAL",
            "ground_truth": "AML_GENERAL",
            "planted_pattern": "Worked example reference",
            "pattern_members": [],
            "runtime_expectation": "COMPLETE",
            "split_methodology": "stable sorted alternating",
        }
    )

    from collections import defaultdict
    groups = defaultdict(list)
    for fix in manifest_entries:
        groups[(fix["scenario_class"], fix.get("scenario_subtype", "none"))].append(fix)

    for (sc, st), group in sorted(groups.items()):
        group.sort(key=lambda x: x["fixture_id"])
        group_hash = int(hashlib.sha256(f"{seed}_{sc}_{st}".encode()).hexdigest(), 16)
        current_is_train = (group_hash % 2 == 0)
        for fix in group:
            fix["split"] = "train" if current_is_train else "eval"
            current_is_train = not current_is_train

    manifest: dict[str, Any] = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "fixture_version": FIXTURE_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "split_methodology": "stable sorted alternating",
        "anchor_timestamp": ANCHOR_TIMESTAMP.isoformat(),
        "fixtures": manifest_entries,
    }

    return {
        "manifest": manifest,
        "customers": customers,
        "accounts": accounts,
        "transactions": transactions,
        "beneficiaries": beneficiaries,
        "entities": entities,
        "graph_relationships": graph_relationships,
    }
