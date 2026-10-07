import json
import os
import uuid

import requests
import streamlit as st

st.set_page_config(page_title="Meridian Phase 1 UI", layout="wide")

API_BASE = os.environ.get("MERIDIAN_API_BASE_URL", "http://localhost:8000")

st.sidebar.header("Authentication")
api_token = st.sidebar.text_input(
    "API Bearer Token", type="password", key="api_token_input"
)

if not api_token:
    st.warning("Please enter an API token in the sidebar to continue.")
    st.stop()

headers = {"Authorization": f"Bearer {api_token}"}

st.title("Meridian: Phase 1 Human-Approval UI")

# --- CASE CREATION ---
st.header("1. Case Creation")
with st.form("case_create_form"):
    cust_id = st.text_input(
        "Customer ID (UUID)",
        value=str(uuid.uuid5(uuid.NAMESPACE_OID, "rahul_sharma")),
    )
    alert_type = st.text_input("Alert Type", value="suspicious_transfer")
    alert_reasons_str = st.text_area(
        "Alert Reasons (JSON)",
        value='{"reason": "High value transfer to new beneficiary"}',
    )
    txn_id = st.text_input("Transaction ID (UUID, optional)", value="")

    submitted = st.form_submit_button("Create Case")
    if submitted:
        try:
            parsed_reasons = json.loads(alert_reasons_str)
            payload = {
                "customer_id": cust_id,
                "alert_type": alert_type,
                "alert_reasons": parsed_reasons,
            }
            if txn_id.strip():
                payload["transaction_id"] = txn_id.strip()

            resp = requests.post(f"{API_BASE}/cases", json=payload, headers=headers)
            if resp.status_code == 201:
                data = resp.json()
                st.success("Case created successfully!")
                st.write(f"**alert_id**: `{data.get('alert_id')}`")
                st.write(f"**case_id**: `{data.get('case_id')}`")
                st.session_state["current_case_id"] = data.get("case_id")
            else:
                st.error(f"Failed to create case. HTTP {resp.status_code}: {resp.text}")
        except json.JSONDecodeError:
            st.error("Invalid JSON in Alert Reasons.")
        except requests.RequestException as e:
            st.error(f"API Connection Error: {e}")

st.divider()

current_case_id = st.session_state.get("current_case_id", "")
case_id_input = st.text_input(
    "Active Case ID", value=current_case_id, key="active_case_id"
)

if not case_id_input:
    st.info("Enter a Case ID or create a new case above.")
    st.stop()

# --- INVESTIGATION ---
st.header("2. Investigation")
if st.button("Investigate"):
    with st.spinner("Investigating..."):
        try:
            resp = requests.post(
                f"{API_BASE}/cases/{case_id_input}/investigate", headers=headers
            )
            if resp.status_code == 200:
                st.success(
                    f"Investigation complete. Status: {resp.json().get('status')}"
                )
            else:
                st.error(f"Investigation failed. HTTP {resp.status_code}: {resp.text}")
        except requests.RequestException as e:
            st.error(f"API Connection Error: {e}")

st.divider()

# --- REPORT ---
st.header("3. Report")
if st.button("Fetch Report"):
    try:
        resp = requests.get(f"{API_BASE}/cases/{case_id_input}/report", headers=headers)
        if resp.status_code == 200:
            report = resp.json()
            st.subheader("Summary")
            st.write(report.get("summary"))

            risk_level = report.get("risk_level")
            st.write(f"**Customer KYC risk rating (source data)**: {risk_level}")

            comp_status = report.get("evidence_completeness_status")
            st.write(f"**Evidence Completeness Status**: {comp_status}")
            st.write(f"**Confidence**: {report.get('confidence_text')}")

            st.subheader("Computed Risk Signals")
            risk_signals = report.get("risk_signals", [])
            if not risk_signals:
                st.write("No computed risk signals for this investigation run")
            else:
                for rs in risk_signals:
                    with st.container(border=True):
                        st.markdown(
                            "*PROTOTYPE — not a validated risk score "
                            "or AML determination*"
                        )
                        st.markdown(f"**Signal Type**: {rs.get('signal_type')}")
                        st.markdown(f"**Value**: {rs.get('value')}")
                        st.markdown(f"**Methodology**: {rs.get('methodology')}")
                        if rs.get("transaction_id"):
                            st.markdown(
                                f"**Related transaction:** {rs.get('transaction_id')}"
                            )

            st.subheader("Findings")
            for f in report.get("findings", []):
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

            st.subheader("Recommendations")
            for r in report.get("recommendations", []):
                st.write(f"- {r.get('text')}")

            st.subheader("Evidence References")
            for ev in report.get("evidence", []):
                e_type = ev.get("evidence_type")
                e_tbl = ev.get("reference_table")
                e_id = ev.get("reference_id")
                st.write(f"- {e_type} | {e_tbl} | {e_id}")

            st.subheader("Policy References")
            for p in report.get("applicable_policies", []):
                p_type = p.get("evidence_type")
                p_tbl = p.get("reference_table")
                p_id = p.get("reference_id")
                st.write(f"- {p_type} | {p_tbl} | {p_id}")

        elif resp.status_code == 422:
            st.error(
                "Report unavailable — insufficient evidence for this investigation run"
            )
        else:
            st.error(f"Failed to fetch report. HTTP {resp.status_code}: {resp.text}")
    except requests.RequestException as e:
        st.error(f"API Connection Error: {e}")

st.divider()

# --- AUDIT TRAIL ---
st.header("4. Audit Trail")
if st.button("Fetch Audit Trail"):
    try:
        resp = requests.get(
            f"{API_BASE}/cases/{case_id_input}/audit-trail", headers=headers
        )
        if resp.status_code == 200:
            trail = resp.json()

            st.subheader("Investigation Runs")
            for ir in trail.get("investigation_runs", []):
                with st.expander(
                    f"Run {ir.get('investigation_run_id')} ({ir.get('status')})"
                ):
                    start = ir.get("started_at")
                    end = ir.get("completed_at")
                    st.write(f"Started: {start} | Completed: {end}")

                    st.write("**Agent Runs:**")
                    st.json(ir.get("agent_runs", []))

                    st.write("**Evidence:**")
                    st.json(ir.get("evidence", []))

                    st.write("**Findings:**")
                    st.json(ir.get("findings", []))

            st.subheader("Audit Events")
            for ae in trail.get("audit_events", []):
                with st.container(border=True):
                    occurred = ae.get("occurred_at")
                    action = ae.get("action")
                    actor_t = ae.get("actor_type")
                    actor_i = ae.get("actor_id")
                    st.write(
                        f"**{occurred}** | Action: **{action}** "
                        f"| Actor: {actor_t} ({actor_i})"
                    )
                    st.write("Input:")
                    st.json(ae.get("input_summary") or {})
                    st.write("Output:")
                    st.json(ae.get("output_summary") or {})

        else:
            st.error(
                f"Failed to fetch audit trail. HTTP {resp.status_code}: {resp.text}"
            )
    except requests.RequestException as e:
        st.error(f"API Connection Error: {e}")

st.divider()

# --- HUMAN DECISION ---
st.header("5. Human Decision")
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
            payload = {
                "action": action,
            }
            if reason.strip():
                payload["reason"] = reason.strip()

            try:
                resp = requests.post(
                    f"{API_BASE}/cases/{case_id_input}/decision",
                    json=payload,
                    headers=headers,
                )
                if resp.status_code == 200:
                    st.success("Decision submitted successfully.")
                    st.write(f"**New Status**: {resp.json().get('new_status')}")
                elif resp.status_code in [422, 403]:
                    st.error(f"{resp.json().get('detail')}")
                else:
                    st.error(f"Decision failed. HTTP {resp.status_code}: {resp.text}")
            except requests.RequestException as e:
                st.error(f"API Connection Error: {e}")
