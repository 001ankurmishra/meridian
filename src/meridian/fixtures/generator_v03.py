import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from meridian.loader.worked_example import generate_worked_example


def generate_fixtures_v03(seed: str = "default_seed") -> dict[str, Any]:
    """
    Generate v0.3 fixtures.

    Beneficiary quota assignment is used rather than independent per-fixture draws
    because groups of 4 need guaranteed representation of all three states.
    """
    MANIFEST_SCHEMA_VERSION = "0.3"
    FIXTURE_VERSION = "0.3"
    GENERATOR_VERSION = "0.3"
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

    def add_bene_hours(
        fix_id: str, b_key: str, c_id: uuid.UUID, a_id: uuid.UUID, hours_ago: float
    ) -> uuid.UUID:
        b_id = deterministic_uuid(seed, fix_id, b_key)
        beneficiaries.append(
            {
                "beneficiary_id": b_id,
                "customer_id": c_id,
                "account_id": a_id,
                "added_at": ANCHOR_TIMESTAMP - timedelta(hours=hours_ago),
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
                deterministic_float(seed, f"{fix_id}_hist_time_{i}") * 2000.0 + 26.0
            )
            add_tx(fix_id, f"hist_{suffix}_{i}", a_id, None, amt, time_ago)
            total_amt += amt
        return (total_amt / Decimal(num_hist)).quantize(Decimal("0.01"))

    def add_extra_outgoing(
        fix_id: str, a_id: uuid.UUID, extra_count: int, avg_hist: Decimal
    ) -> None:
        used_offsets = set()
        for i in range(extra_count):
            offset_mins = deterministic_int(seed, f"{fix_id}_extra_offset_{i}", 1, 1439)
            collision_attempt = 0
            while offset_mins in used_offsets:
                collision_attempt += 1
                offset_mins = deterministic_int(
                    seed, f"{fix_id}_extra_offset_{i}_col_{collision_attempt}", 1, 1439
                )
            used_offsets.add(offset_mins)

            time_ago_hrs = 2.0 + (offset_mins / 60.0)
            amt = avg_hist
            add_tx(fix_id, f"extra_{i}", a_id, None, amt, time_ago_hrs)

    def add_scenario(
        sc: str,
        st: str,
        gt: str | None,
        count: int,
        planted_patt: str,
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

            extra_count = 0
            if sc == "structuring":
                extra_count = deterministic_int(seed, f"{fix_id}_extra_count", 1, 5)
            elif sc == "clean_control":
                if st in ("typical", "large_legitimate"):
                    extra_count = deterministic_int(seed, f"{fix_id}_extra_count", 0, 1)
                elif st == "busy_legitimate":
                    extra_count = deterministic_int(seed, f"{fix_id}_extra_count", 1, 4)

            if extra_count > 0:
                add_extra_outgoing(fix_id, a1, extra_count, avg_hist)

            tx_ids = []
            target_dest_a = None
            if pattern_type == "structuring":
                c_dest, a_dest, _, _ = create_subject(fix_id, "dest")
                target_dest_a = str(a_dest)
                for i in range(4):
                    if i == 0:
                        tx_amt = target_amt
                    else:
                        noise = deterministic_amount(
                            seed, f"{fix_id}_noise_{i}", -50.0, 50.0
                        )
                        tx_amt = max(Decimal("0.01"), target_amt + noise)

                    tx_time_hrs = 2.0 - (i * 0.1)
                    tx_id, _ = add_tx(
                        fix_id, f"tx_{i}", a1, a_dest, tx_amt, tx_time_hrs
                    )
                    tx_ids.append(tx_id)
            elif pattern_type == "rapid_movement":
                c2, a2, _, _ = create_subject(fix_id, "s2")
                c3, a3, _, _ = create_subject(fix_id, "s3")
                target_dest_a = str(a2)

                add_bene_hours(fix_id, "b2", c2, a3, 24)

                tx1, _ = add_tx(fix_id, "tx_0", a1, a2, target_amt, 2.0)
                tx2, _ = add_tx(
                    fix_id, "tx_1", a2, a3, target_amt - Decimal("100.00"), 1.9
                )
                tx_ids = [tx1, tx2]
            elif pattern_type == "circular_transfer":
                c2, a2, _, _ = create_subject(fix_id, "s2")
                c3, a3, _, _ = create_subject(fix_id, "s3")
                target_dest_a = str(a2)
                tx1, _ = add_tx(fix_id, "tx_0", a1, a2, target_amt, 2.0)
                tx2, _ = add_tx(
                    fix_id, "tx_1", a2, a3, target_amt - Decimal("100.00"), 1.9
                )
                tx3, _ = add_tx(
                    fix_id, "tx_2", a3, a1, target_amt - Decimal("200.00"), 1.8
                )
                tx_ids = [tx1, tx2, tx3]
            elif pattern_type == "mule_account_chain":
                c2, a2, _, _ = create_subject(fix_id, "s2")
                c3, a3, _, _ = create_subject(fix_id, "s3")
                c4, a4, _, _ = create_subject(fix_id, "s4")
                target_dest_a = str(a2)
                tx1, _ = add_tx(fix_id, "tx_0", a1, a2, target_amt, 2.0)
                tx2, _ = add_tx(
                    fix_id, "tx_1", a2, a3, target_amt - Decimal("100.00"), 1.9
                )
                tx3, _ = add_tx(
                    fix_id, "tx_2", a3, a4, target_amt - Decimal("200.00"), 1.8
                )
                tx_ids = [tx1, tx2, tx3]
            elif pattern_type == "clean_control":
                c_dest, a_dest, _, _ = create_subject(fix_id, "dest")
                target_dest_a = str(a_dest)
                tx1, _ = add_tx(fix_id, "tx_0", a1, a_dest, target_amt, 2.0)
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
                        "alert_type": "temp",
                        "alert_reasons": {"reason": "System generated alert"},
                        "transaction_id": str(tx_ids[0]),
                    },
                    "evaluation_target": "temp",
                    "ground_truth": gt,
                    "planted_pattern": planted_patt,
                    "pattern_members": [str(t) for t in tx_ids],
                    "runtime_expectation": "COMPLETE",
                    "split_methodology": "stable sorted alternating",
                    "generation_params": {
                        "ratio": f"{ratio:.2f}",
                        "extra_recent_outgoing": extra_count,
                        "bene_state": None,
                        "bene_age_hours": None,
                        "_target_dest_a": target_dest_a,
                    },
                }
            )

    add_scenario(
        "structuring",
        "baseline",
        "AML_STRUCTURING",
        4,
        "4 deposits",
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
        4.00,
        15.00,
        "structuring",
    )

    add_scenario(
        "rapid_movement",
        "baseline",
        "AML_RAPID_MOVEMENT",
        4,
        "3 hops",
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
        4.00,
        15.00,
        "rapid_movement",
    )

    add_scenario(
        "circular_transfer",
        "baseline",
        "AML_CIRCULAR",
        4,
        "A->B->C->A",
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
        4.00,
        15.00,
        "circular_transfer",
    )

    add_scenario(
        "mule_account_chain",
        "baseline",
        "AML_MULE",
        4,
        "4-hop",
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
        4.00,
        15.00,
        "mule_account_chain",
    )

    add_scenario(
        "clean_control", "typical", "CLEAN", 8, "Routine", 0.50, 1.50, "clean_control"
    )
    add_scenario(
        "clean_control",
        "large_legitimate",
        "CLEAN",
        8,
        "Large routine",
        3.00,
        12.00,
        "clean_control",
    )
    add_scenario(
        "clean_control",
        "busy_legitimate",
        "CLEAN",
        8,
        "Busy routine",
        0.50,
        1.50,
        "clean_control",
    )

    fix_id = next_fix_id()
    c1, a1, e_c1, e_a1 = create_subject(fix_id, "s1", onboard_days=0)
    tx1, _ = add_tx(fix_id, "tx_0", a1, None, Decimal("10.00"), 0.1)

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
                "alert_type": "new_beneficiary",
                "alert_reasons": {"reason": "System generated alert"},
                "transaction_id": str(tx1),
            },
            "evaluation_target": "new_beneficiary",
            "ground_truth": None,
            "planted_pattern": "New account with no history",
            "pattern_members": [str(tx1)],
            "runtime_expectation": "INCOMPLETE_INSUFFICIENT_EVIDENCE",
            "split_methodology": "stable sorted alternating",
            "generation_params": {
                "ratio": "0.00",
                "extra_recent_outgoing": 0,
                "bene_state": None,
                "bene_age_hours": None,
                "_target_dest_a": None,
            },
        }
    )

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
                "alert_type": "large_transaction",
                "alert_reasons": {"reason": "System generated alert"},
                "transaction_id": suspicious_tx_id,
            },
            "evaluation_target": "large_transaction",
            "ground_truth": "AML_GENERAL",
            "planted_pattern": "Worked example reference",
            "pattern_members": [],
            "runtime_expectation": "COMPLETE",
            "split_methodology": "stable sorted alternating",
            "generation_params": {
                "ratio": "0.00",
                "extra_recent_outgoing": 0,
                "bene_state": None,
                "bene_age_hours": None,
                "_target_dest_a": None,
            },
        }
    )

    from collections import defaultdict

    groups = defaultdict(list)
    for fix in manifest_entries:
        groups[(fix["scenario_class"], fix.get("scenario_subtype", "none"))].append(fix)

    CONFIRMED_ALERT_TYPES = ["large_transaction", "new_beneficiary", "rapid_movement"]

    for (sc, st), group in sorted(groups.items()):
        group.sort(key=lambda x: x["fixture_id"])

        group_key = f"{sc}_{st}"
        alert_types = sorted(
            CONFIRMED_ALERT_TYPES,
            key=lambda at: hashlib.sha256(
                f"{seed}:{group_key}:{at}".encode("utf-8")
            ).hexdigest(),
        )

        applicable_bene = sc not in ("worked_example", "insufficient_history")

        states = []
        if applicable_bene:
            n = len(group)
            counts = {"absent": 0, "fresh": 0, "established": 0}
            fractions = {}
            for state, pct in [("absent", 20), ("fresh", 40), ("established", 40)]:
                val = n * pct / 100.0
                counts[state] = int(val)
                fractions[state] = val - int(val)

            rem = n - sum(counts.values())
            order = {"established": 0, "fresh": 1, "absent": 2}
            sorted_states = sorted(
                fractions.keys(), key=lambda s: (-fractions[s], order[s])
            )
            for s in sorted_states[:rem]:
                counts[s] += 1

            states = (
                ["absent"] * counts["absent"]
                + ["fresh"] * counts["fresh"]
                + ["established"] * counts["established"]
            )

            bene_order = sorted(
                group,
                key=lambda x: hashlib.sha256(
                    f"{seed}:{x['fixture_id']}:bene_state_order".encode("utf-8")
                ).hexdigest(),
            )
            for i, fix in enumerate(bene_order):
                fix["generation_params"]["bene_state"] = states[i]
                target_dest_a = fix["generation_params"]["_target_dest_a"]

                c1_uuid = uuid.UUID(fix["alert_spec"]["customer_id"])
                if target_dest_a:
                    target_a_uuid = uuid.UUID(target_dest_a)
                    if states[i] == "absent":
                        fix["generation_params"]["bene_age_hours"] = None
                    elif states[i] == "fresh":
                        age_hrs = deterministic_int(
                            seed, f"{fix['fixture_id']}_bene_age", 6, 72
                        )
                        fix["generation_params"]["bene_age_hours"] = age_hrs
                        b_id = add_bene_hours(
                            fix["fixture_id"],
                            "target_bene",
                            c1_uuid,
                            target_a_uuid,
                            age_hrs + 2.0,
                        )
                        fix["beneficiary_ids"].append(str(b_id))
                    elif states[i] == "established":
                        age_days = deterministic_int(
                            seed, f"{fix['fixture_id']}_bene_age", 30, 400
                        )
                        fix["generation_params"]["bene_age_hours"] = age_days * 24
                        b_id = add_bene_hours(
                            fix["fixture_id"],
                            "target_bene",
                            c1_uuid,
                            target_a_uuid,
                            (age_days * 24.0) + 2.0,
                        )
                        fix["beneficiary_ids"].append(str(b_id))

        group_hash = int(hashlib.sha256(f"{seed}_{group_key}".encode()).hexdigest(), 16)
        current_is_train = group_hash % 2 == 0

        for i, fix in enumerate(group):
            fix["split"] = "train" if current_is_train else "eval"
            current_is_train = not current_is_train

            if sc not in ("worked_example", "insufficient_history"):
                at = alert_types[i % len(alert_types)]
                fix["alert_spec"]["alert_type"] = at
                fix["evaluation_target"] = at

            if "_target_dest_a" in fix["generation_params"]:
                del fix["generation_params"]["_target_dest_a"]

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
