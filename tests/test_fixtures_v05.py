import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from meridian.fixtures.generator_v04 import generate_fixtures_v04
from meridian.fixtures.generator_v05 import (
    TRUE_GROUPS,
    generate_fixtures_v05,
)
from tests.test_fixtures_v04 import _canonical_serializer


def test_t1_cross_process_determinism():
    script = (
        "import json\n"
        "from meridian.fixtures.generator_v05 import generate_fixtures_v05\n"
        "from tests.test_fixtures_v04 import _canonical_serializer as cs\n"
        "res = generate_fixtures_v05('seed_t1')\n"
        "print(json.dumps(res, default=cs, sort_keys=True, separators=(',', ':')))\n"
    )
    env1 = os.environ.copy()
    env1["PYTHONHASHSEED"] = "1"
    env1["PYTHONPATH"] = "src"
    out1 = subprocess.check_output([sys.executable, "-c", script], env=env1)

    env2 = os.environ.copy()
    env2["PYTHONHASHSEED"] = "2"
    env2["PYTHONPATH"] = "src"
    out2 = subprocess.check_output([sys.executable, "-c", script], env=env2)

    assert out1 == out2


def test_t2_additivity():
    script = (
        "import json\n"
        "import sys\n"
        "from meridian.fixtures.generator_v04 import generate_fixtures_v04\n"
        "from tests.test_fixtures_v04 import _canonical_serializer as cs\n"
        "seed = sys.argv[1]\n"
        "res = generate_fixtures_v04(seed)\n"
        "print(json.dumps(res, default=cs, sort_keys=True, separators=(',', ':')))\n"
    )

    for seed in ["default_seed", "er_corpus_v0.5_freeze", "another_seed"]:
        generate_fixtures_v04(seed)
        v05_local = generate_fixtures_v05(seed)

        env = os.environ.copy()
        env["PYTHONHASHSEED"] = "42"
        env["PYTHONPATH"] = "src"
        out_v04_sub = subprocess.check_output(
            [sys.executable, "-c", script, seed], env=env
        )
        v04_sub = json.loads(out_v04_sub.decode("utf-8"))

        def assert_byte_identical(obj1, obj2):
            j1 = json.dumps(
                obj1,
                default=_canonical_serializer,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            j2 = json.dumps(
                obj2,
                default=_canonical_serializer,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            assert j1 == j2

        assert_byte_identical(v05_local["accounts"], v04_sub["accounts"])
        assert_byte_identical(v05_local["transactions"], v04_sub["transactions"])
        assert_byte_identical(v05_local["beneficiaries"], v04_sub["beneficiaries"])
        assert_byte_identical(v05_local["entities"], v04_sub["entities"])
        assert_byte_identical(
            v05_local["graph_relationships"], v04_sub["graph_relationships"]
        )

        n04 = len(v04_sub["customers"])
        assert_byte_identical(v05_local["customers"][:n04], v04_sub["customers"])
        assert len(v05_local["customers"]) == n04 + 37

        assert_byte_identical(
            v05_local["manifest"]["fixtures"], v04_sub["manifest"]["fixtures"]
        )

        m_v05_stripped = v05_local["manifest"].copy()
        m_v05_stripped.pop("er_ground_truth", None)
        v_schema = m_v05_stripped.pop("manifest_schema_version")
        v_fixture = m_v05_stripped.pop("fixture_version")
        v_gen = m_v05_stripped.pop("generator_version")

        m_v04_stripped = v04_sub["manifest"].copy()
        m_v04_stripped.pop("manifest_schema_version", None)
        m_v04_stripped.pop("fixture_version", None)
        m_v04_stripped.pop("generator_version", None)

        assert_byte_identical(m_v05_stripped, m_v04_stripped)

        assert v_schema == "0.5"
        assert v_fixture == "0.5"
        assert v_gen == "0.5"


def test_t3_taxonomy_counts():
    v05 = generate_fixtures_v05("seed_t3")
    gt = v05["manifest"]["er_ground_truth"]

    assert sum(1 for c in gt["planted_customers"]) == 37
    assert len(gt["true_match_pairs"]) == 15
    assert sum(1 for c in gt["designed_negative_pairs"]) == 5

    # expected pair count per case
    case_counts = {}
    for g in TRUE_GROUPS:
        n = 1 + len(g["variants"])
        case_counts[g["case_id"]] = n * (n - 1) // 2

    actual_counts = {}
    for p in gt["true_match_pairs"]:
        c1 = p["customer_ids"][0]
        for c in gt["planted_customers"]:
            if c["customer_id"] == c1:
                id_group = c["identity_id"]
                break
        for i in gt["identities"]:
            if i["identity_id"] == id_group:
                case = i["case_id"]
                break
        actual_counts[case] = actual_counts.get(case, 0) + 1

    for k, v in case_counts.items():
        assert actual_counts.get(k, 0) == v


def test_t4_ground_truth_structure():
    v05 = generate_fixtures_v05("seed_t4")
    gt = v05["manifest"]["er_ground_truth"]

    customer_identities = {}
    for c in gt["planted_customers"]:
        assert c["customer_id"] not in customer_identities
        customer_identities[c["customer_id"]] = c["identity_id"]

    for c in gt["planted_customers"]:
        assert c["identity_id"] in [i["identity_id"] for i in gt["identities"]]

    id_groups = {}
    for cid, iid in customer_identities.items():
        id_groups.setdefault(iid, []).append(cid)

    expected_true_pairs = set()
    for iid, cids in id_groups.items():
        for i in range(len(cids)):
            for j in range(i + 1, len(cids)):
                pair = tuple(sorted([cids[i], cids[j]]))
                expected_true_pairs.add(pair)

    actual_true_pairs = set(tuple(p["customer_ids"]) for p in gt["true_match_pairs"])
    assert actual_true_pairs == expected_true_pairs

    actual_neg_pairs = set(
        tuple(p["customer_ids"]) for p in gt["designed_negative_pairs"]
    )
    assert not actual_neg_pairs.intersection(actual_true_pairs)

    for p in gt["designed_negative_pairs"]:
        id1 = customer_identities[p["customer_ids"][0]]
        id2 = customer_identities[p["customer_ids"][1]]
        assert id1 != id2

    for p in gt["true_match_pairs"]:
        assert len(p["variant_transforms"]) > 0
        assert "within_adr_v1_scope" in p

        c1 = p["customer_ids"][0]
        group = None
        for i in gt["identities"]:
            if i["identity_id"] == customer_identities[c1]:
                group = i["group"]
                break

        if group == "B" or group == "D":
            assert not p["within_adr_v1_scope"]
        elif group == "A":
            assert p["within_adr_v1_scope"]


def test_t5_literal_collision_integrity():
    v05 = generate_fixtures_v05("seed_t5")
    gt = v05["manifest"]["er_ground_truth"]

    planted_cids = set(c["customer_id"] for c in gt["planted_customers"])
    background_customers = [
        c for c in v05["customers"] if str(c["customer_id"]) not in planted_cids
    ]
    planted_customers = [
        c for c in v05["customers"] if str(c["customer_id"]) in planted_cids
    ]

    for p in planted_customers:
        for b in background_customers:
            assert p["full_name"] != b["full_name"]

    customer_identities = {
        c["customer_id"]: c["identity_id"] for c in gt["planted_customers"]
    }

    collisions = []
    for i in range(len(planted_customers)):
        for j in range(i + 1, len(planted_customers)):
            c1 = planted_customers[i]
            c2 = planted_customers[j]
            id1 = customer_identities[str(c1["customer_id"])]
            id2 = customer_identities[str(c2["customer_id"])]

            if id1 != id2:
                n1 = c1["full_name"]
                n2 = c2["full_name"]
                d1 = c1["date_of_birth"]
                d2 = c2["date_of_birth"]
                if n1 and n1.strip() and n1 == n2 and d1 and d1 == d2:
                    collisions.append(
                        tuple(sorted([str(c1["customer_id"]), str(c2["customer_id"])]))
                    )

    c3_pairs = []
    for p in gt["designed_negative_pairs"]:
        if p["category"] == "C3":
            c3_pairs.append(tuple(p["customer_ids"]))

    assert set(collisions) == set(c3_pairs)


def test_t6_independence():
    gen_file = Path("src/meridian/fixtures/generator_v05.py")
    tree = ast.parse(gen_file.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
            mod = (
                node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
            )
            assert mod is not None
            assert "entity_resolution" not in mod
            assert "er_" not in mod
            assert "unicodedata" not in mod

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in ("casefold", "normalize")


def test_t7_freeze():
    import hashlib

    seed = "er_corpus_v0.5_freeze"
    v05 = generate_fixtures_v05(seed)
    v04 = generate_fixtures_v04(seed)

    gt = v05["manifest"]["er_ground_truth"]
    gt_bytes = json.dumps(
        gt, default=_canonical_serializer, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    gt_hash = hashlib.sha256(gt_bytes).hexdigest()

    appended = v05["customers"][len(v04["customers"]) :]
    appended_bytes = json.dumps(
        appended, default=_canonical_serializer, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    appended_hash = hashlib.sha256(appended_bytes).hexdigest()

    ER_GROUND_TRUTH_SHA256 = (
        "99f7461140214e43c0e31806f83593616ebade04e0800e5969d04033e03811c8"
    )
    APPENDED_CUSTOMERS_SHA256 = (
        "684ed486a1317f17e8d306fcb8aae8998b536566cedd401419f27168ac2b0575"
    )

    assert gt_hash == ER_GROUND_TRUTH_SHA256
    assert appended_hash == APPENDED_CUSTOMERS_SHA256


def test_t8_db_round_trip(superuser_engine):
    import sqlalchemy as sa

    from meridian.loader.main import clear_data, insert_data

    clear_data(superuser_engine)
    v05 = generate_fixtures_v05("seed_t8")

    insert_data(superuser_engine, v05)

    with superuser_engine.connect() as conn:
        res = conn.execute(
            sa.text("SELECT customer_id, full_name, date_of_birth FROM customers")
        ).fetchall()

    db_customers = {str(r[0]): (r[1], r[2]) for r in res}
    for c in v05["customers"]:
        cid = str(c["customer_id"])
        assert cid in db_customers
        assert db_customers[cid][0] == c["full_name"]
        if c["date_of_birth"] is None:
            assert db_customers[cid][1] is None
        else:
            assert str(db_customers[cid][1]) == c["date_of_birth"]

    clear_data(superuser_engine)


def test_t9_forbidden_wording():
    v05 = generate_fixtures_v05("seed_t9")
    j = json.dumps(v05, default=_canonical_serializer).lower()

    # from v04
    forbidden = ["same person", "confirmed", "duplicate customer", "llm", "generative"]
    for f in forbidden:
        assert f not in j
