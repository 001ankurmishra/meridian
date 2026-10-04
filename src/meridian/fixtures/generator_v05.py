"""
ER Evaluation Corpus v0.5.
Planted identities for structural fidelity ground truth.
No entity resolution code exists here.
Note: Names and DOBs come from hand-written literal tables.
The random seed affects UUID generation only.
"""

import copy
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from meridian.fixtures.generator_v04 import generate_fixtures_v04


def deterministic_uuid(seed: str, namespace: str, key: str) -> uuid.UUID:
    """Generate a deterministic UUID."""
    h = hashlib.sha256(f"{seed}:{namespace}:{key}".encode("utf-8")).hexdigest()
    return uuid.uuid5(uuid.NAMESPACE_OID, h)


TRANSFORM_SCOPES = {
    "case_variant": {"within_adr_v1_scope": True, "scope_note": "A1: case variant"},
    "whitespace_variant": {"within_adr_v1_scope": True, "scope_note": "A2: whitespace variant"},
    "nfkc_variant": {"within_adr_v1_scope": True, "scope_note": "A3: NFKC compatibility variant"},
    "casefold_variant": {"within_adr_v1_scope": True, "scope_note": "A4: casefold-only variant"},
    "punctuation_variant": {"within_adr_v1_scope": False, "scope_note": "B1: punctuation"},
    "diacritic_variant": {"within_adr_v1_scope": False, "scope_note": "B2: diacritic"},
    "token_reorder_variant": {"within_adr_v1_scope": False, "scope_note": "B3: token reorder"},
    "abbreviation_variant": {"within_adr_v1_scope": False, "scope_note": "B4: initial/abbreviation"},
    "nickname_variant": {"within_adr_v1_scope": False, "scope_note": "B5: nickname"},
    "typo_variant": {"within_adr_v1_scope": False, "scope_note": "B6: one-character typo"},
    "name_null": {"within_adr_v1_scope": False, "scope_note": "D1: name NULL"},
    "dob_null": {"within_adr_v1_scope": False, "scope_note": "D4: DOB NULL"},
}

# 13 true identity groups
TRUE_GROUPS = [
    {"group": "A", "case_id": "A1", "base_name": "Synthetic John Doe", "base_dob": "1980-01-01", "variants": [{"name": "SYNTHETIC JOHN DOE", "dob": "1980-01-01", "transform": "case_variant"}]},
    {"group": "A", "case_id": "A2", "base_name": "Synthetic Jane Doe", "base_dob": "1980-01-01", "variants": [{"name": "\t Synthetic  Jane\u00a0Doe \n", "dob": "1980-01-01", "transform": "whitespace_variant"}]},
    {"group": "A", "case_id": "A3", "base_name": "Synthetic Bob", "base_dob": "1980-01-01", "variants": [{"name": "Ｓｙｎｔｈｅｔｉｃ Ｂｏｂ", "dob": "1980-01-01", "transform": "nfkc_variant"}]},
    {"group": "A", "case_id": "A4", "base_name": "Synthetic Strauß", "base_dob": "1980-01-01", "variants": [{"name": "Synthetic STRAUSS", "dob": "1980-01-01", "transform": "casefold_variant"}]},
    {"group": "A", "case_id": "A5", "base_name": "Synthetic Triple", "base_dob": "1980-01-01", "variants": [{"name": "SYNTHETIC TRIPLE", "dob": "1980-01-01", "transform": "case_variant"}, {"name": "Synthetic   Triple", "dob": "1980-01-01", "transform": "whitespace_variant"}]},
    {"group": "B", "case_id": "B1", "base_name": "Synthetic O'Connor", "base_dob": "1980-01-01", "variants": [{"name": "Synthetic OConnor", "dob": "1980-01-01", "transform": "punctuation_variant"}]},
    {"group": "B", "case_id": "B2", "base_name": "Synthetic Renée", "base_dob": "1980-01-01", "variants": [{"name": "Synthetic Renee", "dob": "1980-01-01", "transform": "diacritic_variant"}]},
    {"group": "B", "case_id": "B3", "base_name": "Synthetic John Smith", "base_dob": "1980-01-01", "variants": [{"name": "Synthetic Smith John", "dob": "1980-01-01", "transform": "token_reorder_variant"}]},
    {"group": "B", "case_id": "B4", "base_name": "Synthetic William Jones", "base_dob": "1980-01-01", "variants": [{"name": "Synthetic W. Jones", "dob": "1980-01-01", "transform": "abbreviation_variant"}]},
    {"group": "B", "case_id": "B5", "base_name": "Synthetic Robert Black", "base_dob": "1980-01-01", "variants": [{"name": "Synthetic Bob Black", "dob": "1980-01-01", "transform": "nickname_variant"}]},
    {"group": "B", "case_id": "B6", "base_name": "Synthetic Typos", "base_dob": "1980-01-01", "variants": [{"name": "Synthetic Typso", "dob": "1980-01-01", "transform": "typo_variant"}]},
    {"group": "D", "case_id": "D1", "base_name": "Synthetic NullName", "base_dob": "1980-01-01", "variants": [{"name": None, "dob": "1980-01-01", "transform": "name_null", "field_state": "name_null"}]},
    {"group": "D", "case_id": "D4", "base_name": "Synthetic NullDob", "base_dob": "1980-01-01", "variants": [{"name": "Synthetic NullDob", "dob": None, "transform": "dob_null", "field_state": "dob_null"}]},
]

# 5 designed negative categories
NEGATIVES_GROUPS = [
    {"category": "C1", "c1": {"name": "Synthetic SameName", "dob": "1980-01-01"}, "c2": {"name": "Synthetic SameName", "dob": "1980-01-02"}},
    {"category": "C2", "c1": {"name": "Synthetic DiffCharA", "dob": "1980-01-01"}, "c2": {"name": "Synthetic DiffCharB", "dob": "1980-01-01"}},
    {"category": "C3", "c1": {"name": "Synthetic Homonym", "dob": "1980-01-01"}, "c2": {"name": "Synthetic Homonym", "dob": "1980-01-01"}},
    {"category": "D2", "c1": {"name": "", "dob": "1980-01-01", "field_state": "name_empty"}, "c2": {"name": "\u00a0 \t", "dob": "1980-01-01", "field_state": "name_whitespace_only"}},
    {"category": "D3", "c1": {"name": "Synthetic NullDobBoth", "dob": None, "field_state": "dob_null"}, "c2": {"name": "Synthetic NullDobBoth", "dob": None, "field_state": "dob_null"}},
]

def generate_fixtures_v05(seed: str = "default_seed") -> dict[str, Any]:
    res = generate_fixtures_v04(seed)
    res = copy.deepcopy(res)

    res["manifest"]["manifest_schema_version"] = "0.5"
    res["manifest"]["fixture_version"] = "0.5"
    res["manifest"]["generator_version"] = "0.5"

    ANCHOR_TIMESTAMP = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    identities = []
    planted_customers = []
    true_match_pairs = []
    designed_negative_pairs = []

    # True Groups
    for t_idx, tg in enumerate(TRUE_GROUPS):
        identity_id = str(deterministic_uuid(seed, "id_true", tg["case_id"]))
        identities.append({
            "identity_id": identity_id,
            "group": tg["group"],
            "case_id": tg["case_id"],
        })
        
        c_base_id = str(deterministic_uuid(seed, "cust_true", f"{tg['case_id']}_base"))
        res["customers"].append({
            "customer_id": uuid.UUID(c_base_id),
            "full_name": tg["base_name"],
            "date_of_birth": tg["base_dob"],
            "kyc_risk_rating": "MEDIUM",
            "onboarded_at": ANCHOR_TIMESTAMP,
            "source": "er_corpus_v0.5",
            "created_at": ANCHOR_TIMESTAMP,
            "is_synthetic": True,
        })
        planted_customers.append({
            "customer_id": c_base_id,
            "identity_id": identity_id,
            "role": "base",
            "variant_transform": None,
            "field_state": "complete",
        })

        var_custs = []
        for v_idx, v in enumerate(tg["variants"]):
            c_var_id = str(deterministic_uuid(seed, "cust_true", f"{tg['case_id']}_var_{v_idx}"))
            res["customers"].append({
                "customer_id": uuid.UUID(c_var_id),
                "full_name": v["name"],
                "date_of_birth": v["dob"],
                "kyc_risk_rating": "MEDIUM",
                "onboarded_at": ANCHOR_TIMESTAMP,
                "source": "er_corpus_v0.5",
                "created_at": ANCHOR_TIMESTAMP,
                "is_synthetic": True,
            })
            planted_customers.append({
                "customer_id": c_var_id,
                "identity_id": identity_id,
                "role": "variant",
                "variant_transform": v["transform"],
                "field_state": v.get("field_state", "complete"),
            })
            var_custs.append((c_var_id, v["transform"]))
        
        # Build pairs
        group_custs = [(c_base_id, None)] + var_custs
        for i in range(len(group_custs)):
            for j in range(i + 1, len(group_custs)):
                cid1, t1 = group_custs[i]
                cid2, t2 = group_custs[j]
                
                ordered_ids = sorted([cid1, cid2])
                transforms = sorted([t for t in (t1, t2) if t is not None])
                
                within_scope = True
                for t in transforms:
                    if not TRANSFORM_SCOPES[t]["within_adr_v1_scope"]:
                        within_scope = False
                        break
                
                true_match_pairs.append({
                    "customer_ids": ordered_ids,
                    "variant_transforms": transforms,
                    "within_adr_v1_scope": within_scope,
                })

    # Negatives
    for n_idx, ng in enumerate(NEGATIVES_GROUPS):
        c1 = ng["c1"]
        c2 = ng["c2"]
        cat = ng["category"]

        id1 = str(deterministic_uuid(seed, "id_neg", f"{cat}_1"))
        id2 = str(deterministic_uuid(seed, "id_neg", f"{cat}_2"))
        
        identities.append({"identity_id": id1, "group": cat[0], "case_id": cat})
        identities.append({"identity_id": id2, "group": cat[0], "case_id": cat})
        
        cid1 = str(deterministic_uuid(seed, "cust_neg", f"{cat}_1"))
        cid2 = str(deterministic_uuid(seed, "cust_neg", f"{cat}_2"))
        
        res["customers"].append({
            "customer_id": uuid.UUID(cid1),
            "full_name": c1["name"],
            "date_of_birth": c1["dob"],
            "kyc_risk_rating": "MEDIUM",
            "onboarded_at": ANCHOR_TIMESTAMP,
            "source": "er_corpus_v0.5",
            "created_at": ANCHOR_TIMESTAMP,
            "is_synthetic": True,
        })
        planted_customers.append({
            "customer_id": cid1,
            "identity_id": id1,
            "role": "base",
            "variant_transform": None,
            "field_state": c1.get("field_state", "complete"),
        })

        res["customers"].append({
            "customer_id": uuid.UUID(cid2),
            "full_name": c2["name"],
            "date_of_birth": c2["dob"],
            "kyc_risk_rating": "MEDIUM",
            "onboarded_at": ANCHOR_TIMESTAMP,
            "source": "er_corpus_v0.5",
            "created_at": ANCHOR_TIMESTAMP,
            "is_synthetic": True,
        })
        planted_customers.append({
            "customer_id": cid2,
            "identity_id": id2,
            "role": "base",
            "variant_transform": None,
            "field_state": c2.get("field_state", "complete"),
        })

        ordered_ids = sorted([cid1, cid2])
        designed_negative_pairs.append({
            "customer_ids": ordered_ids,
            "category": cat,
        })
    
    # Sort for canonical output
    true_match_pairs.sort(key=lambda x: x["customer_ids"])
    designed_negative_pairs.sort(key=lambda x: x["customer_ids"])

    res["manifest"]["er_ground_truth"] = {
        "taxonomy_version": "0.5",
        "identities": identities,
        "planted_customers": planted_customers,
        "true_match_pairs": true_match_pairs,
        "designed_negative_pairs": designed_negative_pairs,
        "transform_scopes": copy.deepcopy(TRANSFORM_SCOPES),
        "note": "generator-defined ground truth for structural fidelity, not real-world ER performance, and not an identity determination",
    }

    return res
