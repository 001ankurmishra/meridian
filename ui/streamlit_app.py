"""Meridian: Banking Investigation Review Workspace Shell.

Phase 1 Workspace Shell providing deep-blue navigation, theme styling,
session-state persistence isolated by case ID, readable report presentation,
and structured audit trail views while preserving 100% of API behaviors,
timeouts, role gates, and safety assertions.
"""

import json
import os
import uuid
from typing import Any

import requests
import streamlit as st

from ui.theme import inject_theme_css

st.set_page_config(page_title="Meridian Investigation Review", layout="wide")
inject_theme_css()

API_BASE: str = os.environ.get("MERIDIAN_API_BASE_URL", "http://localhost:8000")
REQUEST_TIMEOUT: tuple[int, int] = (5, 60)
INVESTIGATION_TIMEOUT: tuple[int, int] = (5, 120)

STATUS_DISPLAY_MAP: dict[str, str] = {
    "COMPLETE": "Complete",
    "INCOMPLETE_INSUFFICIENT_EVIDENCE": "Incomplete — insufficient evidence",
    "FAILED": "Failed",
    "IN_PROGRESS": "In progress",
    "OPEN": "Open",
    "CLOSED_APPROVED": "Closed (Approved)",
    "CLOSED_REJECTED": "Closed (Rejected)",
    "ESCALATED": "Escalated",
    "MORE_INFO_REQUESTED": "More information requested",
}


def show_request_failure(operation: str, response: requests.Response) -> None:
    """Render standardized API failure messages with HTTP status guidance."""
    st.error(f"{operation} could not be completed (HTTP {response.status_code}).")
    if response.status_code == 401:
        st.info("Credentials are missing, invalid, revoked or expired.")
    elif response.status_code == 403:
        st.info("Your role is not authorized for this action.")
    elif response.status_code == 404:
        st.info("The record is unavailable or you do not have access.")
    elif response.status_code == 422:
        st.info("Check the supplied values and the current case state.")
    request_id = response.headers.get("X-Request-ID")
    if request_id:
        st.text(f"Request ID: {request_id}")


def show_connection_failure() -> None:
    """Render standardized network timeout and connection failure advice."""
    st.error("The API did not respond within the request limits or is unavailable.")
    st.info(
        "A submitted operation may still finish. Check the audit trail before retrying."
    )


# --- SESSION STATE INITIALIZATION (ISOLATED BY CASE ID) ---
if "cases_data" not in st.session_state:
    st.session_state["cases_data"] = {}

if "session_progress" not in st.session_state:
    st.session_state["session_progress"] = {}


def get_case_store(case_id: str) -> dict[str, Any]:
    """Retrieve isolated state cache for a specific case ID."""
    if case_id not in st.session_state["cases_data"]:
        st.session_state["cases_data"][case_id] = {
            "investigation": None,
            "report": None,
            "copilot_draft": None,
            "audit_trail": None,
            "decision_result": None,
        }
    store: dict[str, Any] = st.session_state["cases_data"][case_id]
    return store


def get_case_progress(case_id: str) -> dict[str, bool]:
    """Retrieve session progress for a specific case ID."""
    if case_id not in st.session_state["session_progress"]:
        st.session_state["session_progress"][case_id] = {
            "case_created": False,
            "investigated": False,
            "report_fetched": False,
            "audit_viewed": False,
            "decision_submitted": False,
        }
    progress: dict[str, bool] = st.session_state["session_progress"][case_id]
    return progress


def record_session_action(case_id: str, action: str) -> None:
    """Record an action successfully executed in this session."""
    if not case_id:
        return
    progress = get_case_progress(case_id)
    progress[action] = True


# --- SIDEBAR NAVIGATION & AUTHENTICATION ---
st.sidebar.markdown("### MERIDIAN\n**Investigation Workspace**")

VIEW_OPTIONS: list[str] = [
    "Case Intake",
    "Investigation",
    "Report",
    "Audit Trail",
    "Human Decision",
]

if "view" not in st.session_state:
    st.session_state["view"] = "Case Intake"

current_view = st.sidebar.radio(
    "Navigation",
    VIEW_OPTIONS,
    key="view",
)

st.sidebar.markdown("---")
current_case_val = st.session_state.get("current_case_id", "")
case_id_input = st.sidebar.text_input(
    "Active Case ID",
    value=current_case_val,
    key="active_case_id",
    help="Case UUID for investigation, report, audit trail, and decision.",
)

st.sidebar.markdown("---")
st.sidebar.header("Authentication")
api_token = st.sidebar.text_input(
    "API Bearer Token", type="password", key="api_token_input"
)

if not api_token:
    st.warning("Please enter an API token in the sidebar to continue.")
    st.stop()

headers: dict[str, str] = {"Authorization": f"Bearer {api_token}"}

# --- HEADER BAND & WORKSPACE CONTEXT ---
st.title(f"Meridian: {current_view}")

# Permanent mandatory prototype warning
st.warning(
    "Synthetic prototype. Findings and recommendations require authorized human review."
)

# Active Case Badge & Session Progress Bar
if case_id_input:
    short_case = (
        f"{case_id_input[:8]}...{case_id_input[-4:]}"
        if len(case_id_input) > 12
        else case_id_input
    )
    col_hdr1, col_hdr2 = st.columns([1, 2])
    with col_hdr1:
        st.markdown(
            f"**Active Case:** <span class='meridian-case-badge'>{short_case}</span>",
            unsafe_allow_html=True,
        )
        st.caption(f"Full Case ID: `{case_id_input}`")
    with col_hdr2:
        case_prog = get_case_progress(case_id_input)
        steps_display = [
            ("Case Created", case_prog.get("case_created", False)),
            ("Investigated", case_prog.get("investigated", False)),
            ("Report Fetched", case_prog.get("report_fetched", False)),
            ("Audit Viewed", case_prog.get("audit_viewed", False)),
            ("Decision Submitted", case_prog.get("decision_submitted", False)),
        ]
        stepper_items = [
            f"<span style='color: {'#047857' if done else '#64748B'}; "
            f"font-weight: {'600' if done else 'normal'};'>"
            f"{'✓' if done else '○'} {name}</span>"
            for name, done in steps_display
        ]
        st.markdown(
            "**This session:** &nbsp;" + " &nbsp;→&nbsp; ".join(stepper_items),
            unsafe_allow_html=True,
        )
else:
    st.markdown(
        "**Active Case:** <span style='color: #64748B;'>No case selected</span>",
        unsafe_allow_html=True,
    )
    st.caption("Create a new case in Case Intake or enter a Case ID in the sidebar.")

st.markdown("<div class='meridian-header-band'></div>", unsafe_allow_html=True)


# ==============================================================================
# VIEW 1: CASE INTAKE
# ==============================================================================
if current_view == "Case Intake":
    st.header("1. Case Creation")
    st.info(
        "First demo: load the synthetic seed, use the senior analyst token, create "
        "the prefilled large_transaction case, then Investigate and Fetch Report. "
        "Review evidence and screening before submitting a decision."
    )
    st.caption(
        "Seeded customer: Rahul Sharma; transaction: INR 980,000 "
        "to Tech Solutions Inc. "
        "These identifiers require the repository's synthetic seed data."
    )
    st.info(
        "Creating a case registers the alert in Meridian. "
        "If a transaction ID is provided, "
        "transaction velocity and amount deviation evidence will be generated. "
        "The assigned analyst permissions govern subsequent actions."
    )

    with st.form("case_create_form"):
        cust_id = st.text_input(
            "Customer ID (UUID)",
            value=str(uuid.uuid5(uuid.NAMESPACE_OID, "rahul_sharma")),
        )
        alert_type = st.text_input("Alert Type", value="large_transaction")
        alert_reasons_str = st.text_area(
            "Alert Reasons (JSON)",
            value='{"reason": "High value transfer to new beneficiary"}',
        )
        txn_id = st.text_input(
            "Transaction ID (UUID; needed for transaction evidence)",
            value=str(uuid.uuid5(uuid.NAMESPACE_OID, "rahul_to_tech_sol_tx")),
            help=(
                "Leaving this empty skips transaction analysis and produces "
                "an incomplete investigation."
            ),
        )

        submitted = st.form_submit_button("Create Case")
        if submitted:
            try:
                parsed_reasons = json.loads(alert_reasons_str)
                payload: dict[str, Any] = {
                    "customer_id": cust_id,
                    "alert_type": alert_type,
                    "alert_reasons": parsed_reasons,
                }
                if txn_id.strip():
                    payload["transaction_id"] = txn_id.strip()

                if not txn_id.strip():
                    st.warning(
                        "No Transaction ID: transaction evidence will be missing. "
                        "This case cannot complete the seeded transaction "
                        "demonstration."
                    )
                resp = requests.post(
                    f"{API_BASE}/cases",
                    json=payload,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                )
                if resp.status_code == 201:
                    data = resp.json()
                    st.success("Case created successfully!")
                    st.write(f"**alert_id**: `{data.get('alert_id')}`")
                    new_case_id = str(data.get("case_id"))
                    st.write(f"**case_id**: `{new_case_id}`")
                    st.session_state["current_case_id"] = new_case_id
                    record_session_action(new_case_id, "case_created")
                    st.info("Case ID registered. You can now proceed to Investigation.")
                else:
                    show_request_failure("Case creation", resp)
            except json.JSONDecodeError:
                st.error("Invalid JSON in Alert Reasons.")
            except requests.RequestException:
                show_connection_failure()


# ==============================================================================
# VIEW 2: INVESTIGATION
# ==============================================================================
elif current_view == "Investigation":
    st.header("2. Investigation")
    if not case_id_input:
        st.info("Enter a Case ID in the sidebar or create a new case in Case Intake.")
        st.stop()

    case_store = get_case_store(case_id_input)
    st.markdown(
        "Trigger deterministic agents (Transaction, Graph, Sanctions, "
        "Policy, and Report) to assemble structured evidence, compute "
        "risk signals, and synthesize findings."
    )

    if st.button("Investigate"):
        with st.spinner("Investigating..."):
            try:
                resp = requests.post(
                    f"{API_BASE}/cases/{case_id_input}/investigate",
                    headers=headers,
                    timeout=INVESTIGATION_TIMEOUT,
                )
                if resp.status_code == 200:
                    inv_data = resp.json()
                    case_store["investigation"] = inv_data
                    record_session_action(case_id_input, "investigated")
                    investigation_status = inv_data.get("status")
                    if investigation_status == "COMPLETE":
                        st.success("Investigation complete. Human review is required.")
                    elif investigation_status == "INCOMPLETE_INSUFFICIENT_EVIDENCE":
                        st.warning("Investigation incomplete. Review missing evidence.")
                    elif investigation_status == "FAILED":
                        st.error("Investigation failed. Check the audit trail.")
                    else:
                        st.warning(
                            "Completion is not confirmed. Check the audit trail."
                        )
                else:
                    show_request_failure("Investigation", resp)
            except requests.RequestException:
                show_connection_failure()
    elif case_store.get("investigation"):
        inv_status = case_store["investigation"].get("status")
        plain_status = STATUS_DISPLAY_MAP.get(str(inv_status), str(inv_status))
        st.info(
            f"Last recorded investigation status in this session: **{plain_status}**"
        )


# ==============================================================================
# VIEW 3: REPORT
# ==============================================================================
elif current_view == "Report":
    st.header("3. Report")
    if not case_id_input:
        st.info("Enter a Case ID in the sidebar or create a new case in Case Intake.")
        st.stop()

    case_store = get_case_store(case_id_input)

    fetch_col, _ = st.columns([1, 4])
    with fetch_col:
        fetch_clicked = st.button("Fetch Report")

    if fetch_clicked:
        try:
            resp = requests.get(
                f"{API_BASE}/cases/{case_id_input}/report",
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 200:
                report_data = resp.json()
                case_store["report"] = report_data
                record_session_action(case_id_input, "report_fetched")

                # Fetch supplementary Copilot draft if run exists and eligible
                comp_status_val = report_data.get("evidence_completeness_status")
                run_id_val = report_data.get("investigation_run_id")
                if (
                    comp_status_val in ("COMPLETE", "INCOMPLETE_INSUFFICIENT_EVIDENCE")
                    and run_id_val
                ):
                    try:
                        d_resp = requests.get(
                            f"{API_BASE}/cases/{case_id_input}/investigations/{run_id_val}/copilot-draft",
                            headers=headers,
                            timeout=REQUEST_TIMEOUT,
                        )
                        if d_resp.status_code == 200:
                            case_store["copilot_draft"] = {
                                "status_code": 200,
                                "data": d_resp.json(),
                            }
                        else:
                            case_store["copilot_draft"] = {
                                "status_code": d_resp.status_code,
                                "response": d_resp,
                            }
                    except requests.RequestException:
                        case_store["copilot_draft"] = {"error": "timeout"}
                else:
                    case_store["copilot_draft"] = {"ineligible": True}

            elif resp.status_code == 422:
                st.error(
                    "Report unavailable — insufficient evidence "
                    "for this investigation run"
                )
            else:
                show_request_failure("Report retrieval", resp)
        except requests.RequestException:
            show_connection_failure()

    report = case_store.get("report")
    if not report:
        st.info(
            "No report loaded for this case. "
            "Click 'Fetch Report' to retrieve findings."
        )
    else:
        comp_status = str(report.get("evidence_completeness_status", ""))
        plain_comp_status = STATUS_DISPLAY_MAP.get(comp_status, comp_status)
        risk_level = str(report.get("risk_level", "Unknown"))
        screening = report.get("watchlist_screening") or {}
        screening_state = str(screening.get("state", "NOT_PERFORMED"))
        findings = report.get("findings", [])
        policies = report.get("applicable_policies", [])
        evidence = report.get("evidence", [])
        recommendations = report.get("recommendations", [])
        risk_signals = report.get("risk_signals", [])

        # --- 4 BORDERED KPI CARDS (NO RISK SCORES OR TRAFFIC LIGHTS) ---
        kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
        with kpi_col1:
            with st.container(border=True):
                st.markdown("**Evidence Completeness**")
                st.markdown(f"### {plain_comp_status}")
                st.caption(f"Raw status: `{comp_status}`")
        with kpi_col2:
            with st.container(border=True):
                st.markdown("**Customer KYC Rating**")
                st.markdown(f"### {risk_level}")
                st.caption(
                    "Customer baseline profile rating on file. "
                    "Not an investigation output."
                )
        with kpi_col3:
            with st.container(border=True):
                st.markdown("**Watchlist Screening**")
                st.markdown(f"### {screening_state}")
                st.caption("Exact-name match against synthetic watchlist.")
        with kpi_col4:
            with st.container(border=True):
                st.markdown("**Findings & Evidence**")
                st.markdown(f"### {len(findings)} Findings")
                st.caption(f"{len(policies)} Policies | {len(evidence)} Evidence Items")

        # --- SUMMARY ---
        st.subheader("Summary")
        st.write(report.get("summary"))

        st.write(f"**Customer KYC risk rating (source data)**: {risk_level}")
        st.write(f"**Evidence Completeness Status**: {comp_status}")
        st.write(f"**Confidence**: {report.get('confidence_text')}")

        if comp_status != "COMPLETE":
            st.warning("This report does not establish a complete investigation.")

        # --- WATCHLIST SCREENING (AUTHORITATIVE TEXT & NEUTRAL PRESENTATION) ---
        st.subheader("Watchlist Screening")
        if not isinstance(screening, dict) or not screening.get("rendered_text"):
            st.warning("Screening information unavailable. Not determined.")
        else:
            st.text(f"Screening state: {screening.get('state')}")
            st.write(screening["rendered_text"])
            st.caption(
                "Exact-name candidate screening on a synthetic watchlist. "
                "A candidate is not a confirmed identity. "
                "No candidate does not mean clearance."
            )
            with st.expander("Technical details (Screening)", expanded=False):
                cb = screening.get("classification_branch")
                rc = screening.get("reason_code")
                wl = screening.get("watchlist_name")
                wv = screening.get("watchlist_version")
                st.write(f"- Classification branch: `{cb}`")
                st.write(f"- Reason code: `{rc}`")
                st.write(f"- Watchlist: `{wl}` (v`{wv}`)")
                st.write(f"- Rule ID: `{screening.get('matching_rule_id')}`")
                st.write(
                    f"- Normalization: `{screening.get('normalization_version')}`"
                )

        # --- REASONING CHAIN LEGEND ---
        st.markdown(
            "<div class='meridian-chain-legend'>"
            "<strong>Analytical Reasoning Hierarchy:</strong> "
            "Observed Fact (verified in source records) &nbsp;→&nbsp; "
            "Derived Signal (computed metric) &nbsp;→&nbsp; "
            "Interpretation (domain meaning) &nbsp;→&nbsp; "
            "Recommendation (suggested action)"
            "</div>",
            unsafe_allow_html=True,
        )

        # --- FINDINGS (FACT -> SIGNAL -> INTERPRETATION) ---
        st.subheader("Findings")
        if not findings:
            st.info("No findings recorded for this investigation.")
        else:
            for f in findings:
                with st.container(border=True):
                    st.markdown(f"**Confidence**: {f.get('confidence')}")
                    st.markdown(
                        "**Observed Fact**\n<br>↓\n<br>**Derived Signal**"
                        "\n<br>↓\n<br>**Interpretation**",
                        unsafe_allow_html=True,
                    )
                    st.markdown(f"**Observed Fact**: {f.get('observed_fact')}")
                    st.markdown(f"**Derived Signal**: {f.get('derived_signal')}")
                    st.markdown(f"**Interpretation**: {f.get('interpretation')}")
                    with st.expander(
                        "Technical details (Finding references)", expanded=False
                    ):
                        st.write(f"- Finding ID: `{f.get('finding_id')}`")
                        ev_refs = f.get("evidence_ids", [])
                        ev_txt = ", ".join(ev_refs) if ev_refs else "None"
                        st.write(f"- Evidence references: `{ev_txt}`")

        # --- RISK SIGNALS ---
        st.subheader("Computed Risk Signals")
        if not risk_signals:
            st.write("No computed risk signals for this investigation run")
        else:
            st.markdown("*PROTOTYPE — not a validated risk score or AML determination*")
            for rs in risk_signals:
                with st.container(border=True):
                    st.markdown(
                        "*PROTOTYPE — not a validated risk score or AML determination*"
                    )
                    st.markdown(f"**Signal Type**: {rs.get('signal_type')}")
                    st.markdown(f"**Value**: {rs.get('value')}")
                    st.markdown(f"**Methodology**: {rs.get('methodology')}")
                    if rs.get("transaction_id"):
                        st.markdown(
                            f"**Related transaction:** {rs.get('transaction_id')}"
                        )

            # Card-style overview table
            rs_rows = [
                {
                    "Signal Type": rs.get("signal_type"),
                    "Value": str(rs.get("value")),
                    "Methodology": rs.get("methodology"),
                    "Transaction ID": str(rs.get("transaction_id") or "None"),
                }
                for rs in risk_signals
            ]
            st.dataframe(rs_rows, use_container_width=True)

        # --- RECOMMENDATIONS ---
        st.subheader("Recommendations")
        for r in recommendations:
            st.write(f"- {r.get('text')}")

        # --- EVIDENCE REFERENCES ---
        st.subheader("Evidence References")
        if evidence:
            ev_rows = [
                {
                    "Evidence Type": ev.get("evidence_type"),
                    "Reference Table": ev.get("reference_table"),
                    "Reference ID": str(ev.get("reference_id")),
                }
                for ev in evidence
            ]
            st.dataframe(ev_rows, use_container_width=True)
            for ev in evidence:
                st.write(
                    f"- {ev.get('evidence_type')} | "
                    f"{ev.get('reference_table')} | "
                    f"{ev.get('reference_id')}"
                )
        else:
            st.write("No evidence references recorded.")

        # --- POLICY REFERENCES ---
        st.subheader("Policy References")
        if policies:
            pol_rows = [
                {
                    "Policy Type": p.get("evidence_type"),
                    "Reference Table": p.get("reference_table"),
                    "Reference ID": str(p.get("reference_id")),
                }
                for p in policies
            ]
            st.dataframe(pol_rows, use_container_width=True)
            for p in policies:
                st.write(
                    f"- {p.get('evidence_type')} | "
                    f"{p.get('reference_table')} | "
                    f"{p.get('reference_id')}"
                )
        else:
            st.write("No policy references recorded.")

        # --- COPILOT INVESTIGATION DRAFT (SUPPLEMENTARY & NON-AUTHORITATIVE) ---
        with st.expander(
            "Copilot Investigation Draft — Supplementary, Non-Authoritative",
            expanded=False,
        ):
            st.warning(
                "NON-AUTHORITATIVE SUPPLEMENTARY DRAFT: This draft is generated "
                "by an offline deterministic model for review assistance only. "
                "It does NOT replace the authoritative investigation report or "
                "human analyst judgment."
            )

            run_id = report.get("investigation_run_id")
            if (
                comp_status not in ("COMPLETE", "INCOMPLETE_INSUFFICIENT_EVIDENCE")
                or not run_id
            ):
                copilot_ineligible_msg = (
                    "Copilot draft is unavailable because the "
                    "investigation run is not in a completed or "
                    "evaluated terminal state."
                )
                st.info(copilot_ineligible_msg)
            else:
                draft_entry = case_store.get("copilot_draft")
                if draft_entry:
                    if draft_entry.get("ineligible"):
                        copilot_ineligible_msg = (
                            "Copilot draft is unavailable because the "
                            "investigation run is not in a completed or "
                            "evaluated terminal state."
                        )
                        st.info(copilot_ineligible_msg)
                    elif draft_entry.get("error") == "timeout":
                        show_connection_failure()
                    elif draft_entry.get("status_code") == 200:
                        draft_data = draft_entry["data"]
                        d_status = draft_data.get("status")
                        reason = draft_data.get("reason", "")

                        st.write(f"**Draft Status**: {d_status}")
                        if d_status == "DRAFT":
                            m_id = draft_data.get("model_identifier")
                            p_ver = draft_data.get("prompt_version")
                            p_hash = draft_data.get("package_hash")
                            st.caption(
                                f"Model: `{m_id}` | "
                                f"Prompt Version: `{p_ver}` | "
                                f"Package Hash: `{p_hash}`"
                            )
                            draft_body = draft_data.get("draft") or {}

                            st.markdown("### Draft Summary Claims")
                            summary_claims = draft_body.get("summary", [])
                            if not summary_claims:
                                st.write("No summary claims provided.")
                            else:
                                for sc in summary_claims:
                                    with st.container(border=True):
                                        claim_txt = sc.get("text") or sc.get(
                                            "claim_text", ""
                                        )
                                        st.markdown(f"**Claim**: {claim_txt}")
                                        claim_k = sc.get("kind") or sc.get(
                                            "claim_type", ""
                                        )
                                        ev_ids = sc.get("evidence_ids") or sc.get(
                                            "evidence_references", []
                                        )
                                        ev_str = ", ".join(ev_ids) or "None"
                                        pid = sc.get("passage_id", "")
                                        st.caption(
                                            f"Kind: {claim_k} | "
                                            f"Passage: {pid} | "
                                            f"Evidence IDs: {ev_str}"
                                        )

                            st.markdown("### Draft Explanations")
                            explanation_claims = draft_body.get("explanations", [])
                            if not explanation_claims:
                                st.write("No explanation claims provided.")
                            else:
                                for ec in explanation_claims:
                                    with st.container(border=True):
                                        exp_txt = ec.get("text") or ec.get(
                                            "claim_text", ""
                                        )
                                        st.markdown(f"**Explanation**: {exp_txt}")
                                        exp_k = ec.get("kind") or ec.get(
                                            "claim_type", ""
                                        )
                                        ev_ids = ec.get("evidence_ids") or ec.get(
                                            "evidence_references", []
                                        )
                                        ev_str = ", ".join(ev_ids) or "None"
                                        pid = ec.get("passage_id", "")
                                        st.caption(
                                            f"Kind: {exp_k} | "
                                            f"Passage: {pid} | "
                                            f"Evidence IDs: {ev_str}"
                                        )

                            uncertainty = draft_body.get("uncertainty")
                            if uncertainty:
                                st.markdown(
                                    "**Uncertainty / Limitations Analysis**: "
                                    f"{uncertainty}"
                                )

                            prov = draft_data.get("policy_provenance")
                            if prov:
                                with st.container(border=True):
                                    st.markdown("**Policy Provenance**")
                                    reg_v = prov.get("registry_version")
                                    reg_h = prov.get("registry_hash")
                                    st.caption(
                                        f"Registry Version: `{reg_v}` | "
                                        f"Registry Hash: `{reg_h}`"
                                    )
                                    chunks = prov.get("chunks", [])
                                    if chunks:
                                        st.markdown("**Referenced Policy Chunks:**")
                                        for chk in chunks:
                                            title = chk.get(
                                                "document_title"
                                            ) or chk.get("title", "")
                                            cid = chk.get("chunk_id")
                                            st.write(f"- `{cid}` ({title})")

                            limitations = draft_data.get("limitations", [])
                            if limitations:
                                st.markdown("**Identified Limitations:**")
                                for lim in limitations:
                                    st.write(f"- {lim}")

                        elif d_status == "ABSTAIN":
                            st.info(
                                f"Copilot Abstained: {reason} — "
                                "No substantive claims were generated."
                            )
                            st.caption(
                                f"Package Hash: `{draft_data.get('package_hash')}`"
                            )
                            limitations = draft_data.get("limitations", [])
                            if limitations:
                                st.markdown("**Limitations:**")
                                for lim in limitations:
                                    st.write(f"- {lim}")

                        elif d_status == "UNAVAILABLE":
                            st.warning(f"Copilot draft unavailable: {reason}")
                        else:
                            st.warning(f"Unexpected copilot draft status: {d_status}")
                    elif "response" in draft_entry:
                        show_request_failure(
                            "Copilot draft retrieval", draft_entry["response"]
                        )


# ==============================================================================
# VIEW 4: AUDIT TRAIL
# ==============================================================================
elif current_view == "Audit Trail":
    st.header("4. Audit Trail")
    if not case_id_input:
        st.info("Enter a Case ID in the sidebar or create a new case in Case Intake.")
        st.stop()

    case_store = get_case_store(case_id_input)

    fetch_audit_col, _ = st.columns([1, 4])
    with fetch_audit_col:
        fetch_audit_clicked = st.button("Fetch Audit Trail")

    if fetch_audit_clicked:
        try:
            resp = requests.get(
                f"{API_BASE}/cases/{case_id_input}/audit-trail",
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 200:
                case_store["audit_trail"] = resp.json()
                record_session_action(case_id_input, "audit_viewed")
            else:
                show_request_failure("Audit retrieval", resp)
        except requests.RequestException:
            show_connection_failure()

    trail = case_store.get("audit_trail")
    if not trail:
        st.info(
            "No audit trail loaded for this case. "
            "Click 'Fetch Audit Trail' to view records."
        )
    else:
        st.subheader("Investigation Runs")
        inv_runs = trail.get("investigation_runs", [])
        if inv_runs:
            runs_table = [
                {
                    "Run ID": r.get("investigation_run_id"),
                    "Status": r.get("status"),
                    "Started At": r.get("started_at"),
                    "Completed At": r.get("completed_at"),
                }
                for r in inv_runs
            ]
            st.dataframe(runs_table, use_container_width=True)

            for ir in inv_runs:
                with st.expander(
                    f"Run {ir.get('investigation_run_id')} ({ir.get('status')})"
                ):
                    start = ir.get("started_at")
                    end = ir.get("completed_at")
                    st.write(f"Started: {start} | Completed: {end}")

                    agent_runs = ir.get("agent_runs", [])
                    if agent_runs:
                        st.write("**Agent Runs:**")
                        ag_table = [
                            {
                                "Agent": ar.get("agent_name"),
                                "Status": ar.get("status"),
                                "Started": ar.get("started_at"),
                                "Completed": ar.get("completed_at"),
                            }
                            for ar in agent_runs
                        ]
                        st.dataframe(ag_table, use_container_width=True)

                    with st.expander(
                        "Technical details (Raw Agent Runs JSON)", expanded=False
                    ):
                        st.json(agent_runs)

                    with st.expander(
                        "Technical details (Evidence JSON)", expanded=False
                    ):
                        st.json(ir.get("evidence", []))

                    with st.expander(
                        "Technical details (Screening Result JSON)", expanded=False
                    ):
                        st.json(ir.get("screening_result"))

                    with st.expander(
                        "Technical details (Recommendations JSON)", expanded=False
                    ):
                        st.json(ir.get("recommendations", []))

                    with st.expander(
                        "Technical details (Findings JSON)", expanded=False
                    ):
                        st.json(ir.get("findings", []))
        else:
            st.write("No investigation runs recorded.")

        st.subheader("Audit Events")
        audit_events = trail.get("audit_events", [])
        if audit_events:
            events_table = [
                {
                    "Occurred At": ae.get("occurred_at"),
                    "Action": ae.get("action"),
                    "Actor Type": ae.get("actor_type"),
                    "Actor ID": str(ae.get("actor_id")),
                    "Run ID": str(ae.get("investigation_run_id") or "None"),
                }
                for ae in audit_events
            ]
            st.dataframe(events_table, use_container_width=True)

            for ae in audit_events:
                with st.container(border=True):
                    occurred = ae.get("occurred_at")
                    action = ae.get("action")
                    actor_t = ae.get("actor_type")
                    actor_i = ae.get("actor_id")
                    st.write(
                        f"**{occurred}** | Action: **{action}** "
                        f"| Actor: {actor_t} ({actor_i})"
                    )
                    st.write(
                        f"Investigation run: {ae.get('investigation_run_id') or 'None'}"
                    )
                    with st.expander("Input Summary", expanded=False):
                        st.json(ae.get("input_summary") or {})
                    with st.expander("Output Summary", expanded=False):
                        st.json(ae.get("output_summary") or {})
        else:
            st.write("No audit events recorded.")


# ==============================================================================
# VIEW 5: HUMAN DECISION
# ==============================================================================
elif current_view == "Human Decision":
    st.header("5. Human Decision")
    if not case_id_input:
        st.info("Enter a Case ID in the sidebar or create a new case in Case Intake.")
        st.stop()

    case_store = get_case_store(case_id_input)

    st.caption(
        "APPROVE and REJECT require a COMPLETE investigation and a valid report "
        "with recommendations. Triage remains available for missing, incomplete "
        "or failed investigations under your role permissions. Wait for active runs."
    )
    st.info(
        "REQUEST_MORE_INFO is restricted to the assigned analyst; a senior analyst "
        "token alone does not permit it. Assignment administration is not available "
        "in this demo. Existing backend role checks govern every decision."
    )

    with st.form("decision_form"):
        action = st.selectbox(
            "Action",
            options=["APPROVE", "REJECT", "ESCALATE", "REQUEST_MORE_INFO"],
            key="action",
        )
        reason = st.text_input("Reason")

        decided = st.form_submit_button("Submit Decision", key="submit_decision_btn")
        if decided:
            if action in ["REJECT", "REQUEST_MORE_INFO"] and not reason.strip():
                st.error(f"A reason is required for {action}.")
            else:
                decision_payload: dict[str, Any] = {"action": action}
                if reason.strip():
                    decision_payload["reason"] = reason.strip()

                try:
                    resp = requests.post(
                        f"{API_BASE}/cases/{case_id_input}/decision",
                        json=decision_payload,
                        headers=headers,
                        timeout=REQUEST_TIMEOUT,
                    )
                    if resp.status_code == 200:
                        dec_data = resp.json()
                        case_store["decision_result"] = dec_data
                        record_session_action(case_id_input, "decision_submitted")
                        st.success("Decision submitted successfully.")
                        st.write(f"**New Status**: {dec_data.get('new_status')}")
                    elif resp.status_code in [422, 403]:
                        show_request_failure("Decision", resp)
                    else:
                        show_request_failure("Decision", resp)
                except requests.RequestException:
                    show_connection_failure()

    if case_store.get("decision_result"):
        last_dec = case_store["decision_result"]
        st.info(f"Recorded decision in this session: **{last_dec.get('new_status')}**")
