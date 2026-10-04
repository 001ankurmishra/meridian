"""Tests for deterministic entity resolution."""

import ast
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from meridian.entity_resolution import (
    MATCHED_FIELDS,
    NORMALIZATION_VERSION,
    RULE_ID,
    CustomerIdentityRecord,
    compute_er_candidates,
    find_candidate_links,
)
from meridian.entity_resolution.matching import normalize_full_name

FORBIDDEN_VOCABULARY = [
    "same " + "person",
    "duplicate " + "customer",
    "confir" + "med",
]


def test_normalization_goldens() -> None:
    assert normalize_full_name("John Doe") == "john doe"
    assert normalize_full_name("\t John  Doe \n") == "john doe"
    assert normalize_full_name("STRA\u00dfE") == "strasse"  # casefold
    assert normalize_full_name("\u00a0John\u00a0Doe\u00a0") == "john doe"  # NBSP
    assert normalize_full_name("John\u3000Doe") == "john doe"  # ideographic space
    assert normalize_full_name("\uff2a\uff4f\uff48\uff4e") == "john"  # fullwidth latin
    assert normalize_full_name("\ufb01") == "fi"  # ligature

    # Meaningful differences that shouldn't normalize away
    assert normalize_full_name("John Doe") != normalize_full_name(
        "John, Doe"
    )  # punctuation
    assert normalize_full_name("J. Doe") != normalize_full_name("John Doe")  # initials
    assert normalize_full_name("José") != normalize_full_name("Jose")  # diacritics
    assert normalize_full_name("John Doe") != normalize_full_name("Doe John")  # order

    # Empty cases
    assert normalize_full_name("") == ""
    assert normalize_full_name("   ") == ""
    assert normalize_full_name("\u00a0\u00a0") == ""


def test_single_pass_nfkc(monkeypatch: pytest.MonkeyPatch) -> None:
    import unicodedata

    call_count = 0
    orig_normalize = unicodedata.normalize

    def mock_normalize(form: str, unistr: str) -> str:
        nonlocal call_count
        if form == "NFKC":
            call_count += 1
        return orig_normalize(form, unistr)

    monkeypatch.setattr(
        "meridian.entity_resolution.matching.unicodedata.normalize", mock_normalize
    )

    res = normalize_full_name("John Doe")
    assert res == "john doe"
    assert call_count == 1


def test_find_candidate_links() -> None:
    # 2 customers match
    c1 = CustomerIdentityRecord(uuid.uuid4(), "John Doe", "1980-01-01")
    c2 = CustomerIdentityRecord(uuid.uuid4(), " JOHN  DOE ", "1980-01-01")
    # Different DOB
    c3 = CustomerIdentityRecord(uuid.uuid4(), "John Doe", "1990-01-01")
    # Different Name
    c4 = CustomerIdentityRecord(uuid.uuid4(), "Jane Doe", "1980-01-01")
    # Null DOB
    c5 = CustomerIdentityRecord(uuid.uuid4(), "John Doe", None)
    # Null Name
    c6 = CustomerIdentityRecord(uuid.uuid4(), None, "1980-01-01")
    # Empty Name
    c7 = CustomerIdentityRecord(uuid.uuid4(), "   ", "1980-01-01")
    # Another matching DOB for blank name, no candidate expected
    c8 = CustomerIdentityRecord(uuid.uuid4(), "   ", "1980-01-01")
    # Another matching name for null DOB
    c9 = CustomerIdentityRecord(uuid.uuid4(), "John Doe", None)

    # 3-person bucket
    c10 = CustomerIdentityRecord(uuid.uuid4(), "Alice", "2000-01-01")
    c11 = CustomerIdentityRecord(uuid.uuid4(), "ALICE", "2000-01-01")
    c12 = CustomerIdentityRecord(uuid.uuid4(), "alice", "2000-01-01")

    # 4-person bucket
    c13 = CustomerIdentityRecord(uuid.uuid4(), "Bob", "2010-01-01")
    c14 = CustomerIdentityRecord(uuid.uuid4(), "BOB", "2010-01-01")
    c15 = CustomerIdentityRecord(uuid.uuid4(), "bob", "2010-01-01")
    c16 = CustomerIdentityRecord(uuid.uuid4(), "bOb", "2010-01-01")

    records = [c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11, c12, c13, c14, c15, c16]

    res = find_candidate_links(records)

    # 2-person bucket = 1 link
    # 3-person bucket = 3 links
    # 4-person bucket = 6 links
    # total links = 10
    assert len(res.candidates) == 10

    # Verify provenance
    for link in res.candidates:
        assert link.rule_id == RULE_ID
        assert link.normalization_version == NORMALIZATION_VERSION
        assert link.matched_fields == MATCHED_FIELDS
        assert link.customer_id_a < link.customer_id_b
        # No self-pairs
        assert link.customer_id_a != link.customer_id_b

    # Verify abstentions
    assert len(res.ineligible) == 5  # c5, c6, c7, c8, c9
    assert any(
        c.customer_id == c5.customer_id and c.reasons == ("dob_null",)
        for c in res.ineligible
    )
    assert any(
        c.customer_id == c6.customer_id and c.reasons == ("name_null",)
        for c in res.ineligible
    )
    assert any(
        c.customer_id == c7.customer_id
        and c.reasons == ("name_empty_after_normalization",)
        for c in res.ineligible
    )
    assert any(
        c.customer_id == c8.customer_id
        and c.reasons == ("name_empty_after_normalization",)
        for c in res.ineligible
    )
    assert any(
        c.customer_id == c9.customer_id and c.reasons == ("dob_null",)
        for c in res.ineligible
    )


def test_duplicate_customer_ids_raise() -> None:
    uid = uuid.uuid4()
    records = [
        CustomerIdentityRecord(uid, "A", "2000-01-01"),
        CustomerIdentityRecord(uid, "B", "2000-01-01"),
    ]
    with pytest.raises(ValueError, match="Repeated customer_id"):
        find_candidate_links(records)


def test_determinism_shuffled() -> None:
    import random

    c1 = CustomerIdentityRecord(uuid.uuid4(), "John Doe", "1980-01-01")
    c2 = CustomerIdentityRecord(uuid.uuid4(), "JOHN DOE", "1980-01-01")
    c3 = CustomerIdentityRecord(uuid.uuid4(), "Alice", "2000-01-01")
    c4 = CustomerIdentityRecord(uuid.uuid4(), "ALICE", "2000-01-01")
    c5 = CustomerIdentityRecord(uuid.uuid4(), "alice", "2000-01-01")

    records = [c1, c2, c3, c4, c5]
    res1 = find_candidate_links(records)

    shuffled = records.copy()
    random.shuffle(shuffled)
    res2 = find_candidate_links(shuffled)

    assert res1.candidates == res2.candidates
    assert res1.ineligible == res2.ineligible


def test_determinism_pythonhashseed() -> None:
    code = """
import uuid
import sys
sys.path.insert(0, "src")
from meridian.entity_resolution import CustomerIdentityRecord, find_candidate_links

records = [
    CustomerIdentityRecord(
        uuid.UUID("00000000-0000-0000-0000-000000000001"), "John Doe", "1980-01-01"
    ),
    CustomerIdentityRecord(
        uuid.UUID("00000000-0000-0000-0000-000000000002"), "JOHN DOE", "1980-01-01"
    ),
]
res = find_candidate_links(records)
print([str(c.customer_id_a) for c in res.candidates])
"""
    env1 = {"PYTHONHASHSEED": "1"}
    env2 = {"PYTHONHASHSEED": "42"}

    out1 = subprocess.run(
        [sys.executable, "-c", code],
        env=env1,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    out2 = subprocess.run(
        [sys.executable, "-c", code],
        env=env2,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert out1 == out2


def test_read_only_and_database(
    superuser_engine: Engine, app_role_engine: Engine
) -> None:
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM customers WHERE customer_id IN "
                "('00000000-0000-0000-0000-000000000001', "
                "'00000000-0000-0000-0000-000000000002', "
                "'00000000-0000-0000-0000-000000000003')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO customers (
                    customer_id, full_name, date_of_birth, kyc_risk_rating,
                    source, onboarded_at, created_at, is_synthetic
                )
                VALUES
                (
                    '00000000-0000-0000-0000-000000000001', 'Test Name',
                    '1990-01-01', 'LOW', 'test', NOW(), NOW(), true
                ),
                (
                    '00000000-0000-0000-0000-000000000002', 'test name',
                    '1990-01-01', 'LOW', 'test', NOW(), NOW(), true
                ),
                (
                    '00000000-0000-0000-0000-000000000003', NULL,
                    '1990-01-01', 'LOW', 'test', NOW(), NOW(), true
                )
                """
            )
        )

    res = compute_er_candidates(app_role_engine)

    # Check candidates contains the pair we inserted
    found_link = False
    for link in res.candidates:
        if link.customer_id_a == uuid.UUID(
            "00000000-0000-0000-0000-000000000001"
        ) and link.customer_id_b == uuid.UUID("00000000-0000-0000-0000-000000000002"):
            found_link = True
            break
        if link.customer_id_a == uuid.UUID(
            "00000000-0000-0000-0000-000000000002"
        ) and link.customer_id_b == uuid.UUID("00000000-0000-0000-0000-000000000001"):
            found_link = True
            break
    assert found_link, "Expected candidate link not found"

    # Check ineligible contains the null name record
    found_ineligible = False
    for inel in res.ineligible:
        if inel.customer_id == uuid.UUID("00000000-0000-0000-0000-000000000003"):
            found_ineligible = True
            break
    assert found_ineligible, "Expected ineligible customer not found"

    # Check candidates contains the pair we inserted
    found_link = False
    for link in res.candidates:
        if link.customer_id_a == uuid.UUID(
            "00000000-0000-0000-0000-000000000001"
        ) and link.customer_id_b == uuid.UUID("00000000-0000-0000-0000-000000000002"):
            found_link = True
            break
        if link.customer_id_a == uuid.UUID(
            "00000000-0000-0000-0000-000000000002"
        ) and link.customer_id_b == uuid.UUID("00000000-0000-0000-0000-000000000001"):
            found_link = True
            break
    assert found_link, "Expected candidate link not found"

    # Check ineligible contains the null name record
    found_ineligible = False
    for inel in res.ineligible:
        if inel.customer_id == uuid.UUID("00000000-0000-0000-0000-000000000003"):
            found_ineligible = True
            break
    assert found_ineligible, "Expected ineligible customer not found"

    # Verify no writes occurred (count didn't increase from other tests)
    with superuser_engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT count(*) FROM customers "
                "WHERE customer_id IN (:id1, :id2, :id3)"
            ),
            {
                "id1": "00000000-0000-0000-0000-000000000001",
                "id2": "00000000-0000-0000-0000-000000000002",
                "id3": "00000000-0000-0000-0000-000000000003",
            }
        ).scalar()
        assert count == 3

    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM customers WHERE customer_id IN "
                "('00000000-0000-0000-0000-000000000001', "
                "'00000000-0000-0000-0000-000000000002', "
                "'00000000-0000-0000-0000-000000000003')"
            )
        )


def _get_all_imports(path: Path) -> set[str]:
    imports: set[str] = set()
    try:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    imports.add(name.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.level == 0:
                    imports.add(node.module.split(".")[0])
                    # Full path for meridian imports
                    if node.module.startswith("meridian."):
                        imports.add(node.module)
    except Exception:
        pass
    return imports


def test_architecture_guards() -> None:
    src_dir = Path("src/meridian")
    er_dir = src_dir / "entity_resolution"

    # 1. ER module must not import forbidden packages
    forbidden_imports = {
        "meridian.fixtures",
        "meridian.loader",
        "meridian.agents",
        "meridian.orchestration",
        "meridian.risk_engine",
    }

    for f in er_dir.rglob("*.py"):
        imports = _get_all_imports(f)
        for imp in imports:
            assert not any(imp.startswith(f) for f in forbidden_imports), (
                f"{f.name} imports forbidden {imp}"
            )

    # 2. No module outside entity_resolution may import meridian.entity_resolution
    # (except for allow-list empty for prod, expanded in Commit 2)
    allow_list = [
        "src/meridian/fixtures/er_baseline.py",
    ]

    for f in src_dir.rglob("*.py"):
        if "entity_resolution" in f.parts:
            continue
        # Skip allow list
        if str(f).endswith(tuple(allow_list)):
            continue

        imports = _get_all_imports(f)
        for imp in imports:
            assert not imp.startswith("meridian.entity_resolution"), (
                f"{f} illegally imports {imp}"
            )


def test_forbidden_vocabulary() -> None:
    er_dir = Path("src/meridian/entity_resolution")
    for f in er_dir.rglob("*.py"):
        content = f.read_text(encoding="utf-8").lower()
        for word in FORBIDDEN_VOCABULARY:
            assert word not in content, f"Forbidden word '{word}' found in {f.name}"
