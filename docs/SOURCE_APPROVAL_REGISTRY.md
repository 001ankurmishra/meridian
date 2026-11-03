# Policy Source-Approval Registry and Database Verifier (M1)

**Status:** IMPLEMENTED (Local Milestone M1).  
**Maintainer:** Ankur Mishra  
**Architect:** Claude  

---

## 1. Objective and Architectural Boundary

Project Meridian requires verifiable provenance and cryptographic integrity for policy text before any evidence-packaging component provides context to an LLM.

Milestone M1 establishes:
1. **A canonical byte framing and SHA-256 specification** for policy chunks, documents, and source texts.
2. **A deterministic registry generator** deriving chunks using the pinned tokenizer identity and chunking parameters.
3. **A committed canonical registry** (`src/meridian/registry/policy_registry_v1.json`) containing exactly the four synthetic documents in `POLICY_CORPUS_V1`.
4. **A read-only PostgreSQL verifier** (`verify_policy_database`) executing within an isolated `REPEATABLE READ, READ ONLY` transaction without runtime ML or tokenizer dependencies.
5. **A rigorous test suite** covering canonical hashing, serialization invariance, source-to-chunk token coverage, and PostgreSQL verification.

> **Important Boundary Notice:** Milestone M1 establishes the hashing contract, committed registry, and database verifier. It does **not** authorize deployment, public exposure, or wire runtime enforcement into application startup or package builders. Those integrations are explicitly reserved for subsequent milestones.

---

## 2. Canonical Byte Contract

Hashing across disparate environments requires strict framing to prevent length-extension and boundary-shifting collision attacks. Meridian enforces the following versioned contract:

### 2.1. Integer Encoding
- `U32(n)`: Unsigned 32-bit integer encoded as exactly 4 big-endian bytes (`struct.pack(">I", n)`).
- `U64(n)`: Unsigned 64-bit integer encoded as exactly 8 big-endian bytes (`struct.pack(">Q", n)`).
- **Invariants:** Rejects negative numbers, overflow values, non-integers, and booleans (`isinstance(b, bool)`). Never silently truncates or wraps.

### 2.2. String Framing
For string `s`:
$$\text{FRAME}(s) = \text{U32}(\text{len}(b)) \parallel b$$
where $b = s.\text{encode}(\text{"utf-8"}, \text{errors}=\text{"strict"})$.
- **Invariants:** Length is encoded byte count, not Unicode character count. Rejects lone surrogates and invalid strings. Performs no Unicode normalization, trimming, case folding, or newline conversion.

### 2.3. Optional Strings
- $\text{OPT}(\text{None}) = \mathtt{0x00}$
- $\text{OPT}(s) = \mathtt{0x01} \parallel \text{FRAME}(s)$ for non-NULL strings.

### 2.4. Boolean Encoding
- $\text{False} = \mathtt{0x00}$
- $\text{True} = \mathtt{0x01}$
- Non-boolean types are strictly rejected.

### 2.5. Hash Formulas and Domain Separation
All domain tags are ASCII strings terminated with a single zero byte (`\x00`):

1. **Chunk Hash:**
   $$\text{chunk\_hash}(i, \text{text}) = \text{SHA-256}\left(\mathtt{b"meridian.policy-chunk.v1\textbackslash x00"} \parallel \text{U32}(i) \parallel \text{FRAME}(\text{text})\right)$$

2. **Document Hash:**
   $$\text{doc\_hash} = \text{SHA-256}\left(
     \mathtt{b"meridian.policy-doc.v1\textbackslash x00"}
     \parallel \text{FRAME}(\text{title})
     \parallel \text{FRAME}(\text{document\_type})
     \parallel \text{FRAME}(\text{version})
     \parallel \text{OPT}(\text{source\_url\_or\_ref})
     \parallel \text{BYTE}(\text{is\_synthetic})
     \parallel \text{U32}(n_{\text{chunks}})
     \parallel d_0 \parallel \dots \parallel d_{n-1}
   \right)$$
   where each $d_i$ is the raw 32-byte chunk digest ($\text{compute\_chunk\_digest}(i, c_i)$).

3. **Source Text Hash:**
   $$\text{source\_text\_sha256} = \text{SHA-256}\left(\mathtt{b"meridian.policy-source.v1\textbackslash x00"} \parallel \text{FRAME}(\text{spec.text})\right)$$

---

## 3. Canonical Registry Format and Serialization

The committed registry is serialized canonically to JSON under strict rules:
- UTF-8 encoding without BOM.
- `ensure_ascii=False`.
- Lexicographically sorted object keys (`sort_keys=True`).
- Compact separators `(",", ":")` with zero whitespace around punctuation.
- `allow_nan=False` (rejects non-finite numbers).
- Exactly one trailing LF (`\n`).
- Documents sorted deterministically by identity tuple: `(title, document_type, version, source_url_or_ref)`.
- No timestamps, random UUIDs, or environment-dependent values. Byte-identical across processes regardless of `PYTHONHASHSEED`.

### Document Entry Schema
Each document contains:
```json
{
  "approved_for_public_deployment": true,
  "chunk_count": 2,
  "chunk_hashes": [
    "220cd694ed6a9bfc366499fae45338079923782f2f0d6198daf5f2f144c54261",
    "e200af40aa8a6d48d6b883dcbd391bc98845c9e34209921a84332300c44299f2"
  ],
  "doc_hash": "fe9cb3103e48ed6a3a033f345d8e61ff84db413954a07a4340a24207cd864c05",
  "document_type": "internal_policy",
  "is_synthetic": true,
  "source_text_sha256": "21f96da779e023645806d6dd4809a057bc65abc44e9c46b6187c4d2efd3e9fb8",
  "source_url_or_ref": "meridian-synthetic-policy-corpus-v1",
  "title": "Synthetic Internal Policy — Large / unusual transaction review procedure",
  "version": "v1"
}
```

---

## 4. Provenance Distinction: Build/CI vs Runtime

Meridian distinguishes two distinct provenance boundaries:

| Layer | Checked Hash | Scope and Guarantee |
|---|---|---|
| **Build & CI Provenance** | `source_text_sha256` | Verified at build and test time against `POLICY_CORPUS_V1`. Binds committed source text to emitted chunks. Original raw policy text is not persisted in the operational database. |
| **Operational DB Integrity** | `doc_hash` & `chunk_hashes` | Verified by `verify_policy_database` against PostgreSQL rows in `documents` and `document_chunks`. Guarantees database content was not tampered with, truncated, or modified. |

---

## 5. Read-Only PostgreSQL Verifier

The verifier (`meridian.registry.verifier.verify_policy_database`) enforces policy integrity at the database layer.

### Operational Characteristics:
- **Transaction Isolation:** Executes strictly within a single `REPEATABLE READ, READ ONLY` transaction.
- **Runtime Model Independence:** Requires **zero** ML or tokenizer dependencies. Operates entirely on cryptographic primitives and string comparisons.
- **Fail Closed:** Any unexpected exception, connection error, or schema discrepancy immediately rejects verification.
- **Sanitized Diagnostics:** Failure messages return bounded reason codes and generic explanations. They **never** leak policy text, document titles, tokens, passwords, or hashes.

### Verification Sequence and Precedence:
1. **Validate registry structure:** Validate JSON structure and required keys. If malformed $\rightarrow$ `REGISTRY_INVALID`.
2. **Detect duplicate identities:**
   - In registry $\rightarrow$ `DUPLICATE_IDENTITY`.
   - In database rows $\rightarrow$ `DUPLICATE_IDENTITY`.
3. **Detect unregistered database documents:** Require every database document to match a registry entry. If a database row has no registry match $\rightarrow$ `UNREGISTERED_DOCUMENT`.
4. **Detect missing database documents:** Require every registry document to exist in the database. If absent $\rightarrow$ `MISSING_DOCUMENT`.
5. **Verify deployment approval:** If `approved_for_public_deployment` is false $\rightarrow$ `NOT_APPROVED`.
6. **Verify provenance metadata:** If `is_synthetic` does not match or is false in release-1 $\rightarrow$ `PROVENANCE_MISMATCH`.
7. **Verify chunk structure:** Check that chunk indices are strictly $[0, \dots, n-1]$ with no missing, extra, or duplicate indices $\rightarrow$ `CHUNK_SET_MISMATCH`.
8. **Verify chunk hashes:** Recompute $\text{chunk\_hash}(i, c_i)$ for every chunk. If any digest differs $\rightarrow$ `CHUNK_HASH_MISMATCH`.
9. **Verify document composite hash:** Recompute $\text{doc\_hash}$ from raw chunk digests and metadata. If it differs $\rightarrow$ `DOC_HASH_MISMATCH`.

### Identity Precedence Note
When an identity is modified (e.g., an altered title or version), it simultaneously creates an unrecognized database row and an unfulfilled registry entry. Meridian enforces deterministic precedence: `UNREGISTERED_DOCUMENT` is evaluated and reported prior to `MISSING_DOCUMENT`.

---

## 6. Source-to-Chunk Token Integrity

A source hash alone does not prove chunking fidelity. The chunking algorithm preserves the following invariants verified in CI:
1. **Ordered Paragraph Traversal:** Source blocks split by paragraph breaks are processed sequentially without reordering.
2. **Complete Source Token Coverage:** Every token emitted by the pinned tokenizer across source paragraphs is represented in the emitted chunk token sequences.
3. **Overlap Soundness:** The overlap window carries forward exactly the tail tokens of the preceding chunk without dropping or repeating intermediate source tokens.
4. **Token-to-String Fidelity:** The public chunk strings correspond byte-for-byte to `tokenizer.decode(tokens)` from the canonical token sequence.

---

## 7. Milestone M1 Limitations and Deferred Items

The following components are intentionally deferred to future milestones:
- Wiring the database verifier into application startup or API request lifecycles.
- Evidence builder and package builder integration (`package_hash`).
- Ingestion of non-synthetic external regulatory guidance.
- Migrations or database schema alterations.
- Additional database roles or permissions beyond existing `app_role` (SELECT) and `loader_role` (SELECT, INSERT).

