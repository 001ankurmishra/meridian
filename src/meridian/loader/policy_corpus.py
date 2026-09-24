# ruff: noqa: E501
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class PolicyDocumentSpec:
    title: str
    document_type: str
    version: str
    source_url_or_ref: str
    is_synthetic: bool
    text: str


DOC1_TEXT = """This document is an illustrative and synthetic internal policy provided for training and system testing purposes only. It does not represent the procedures of any real-world financial institution or regulatory body. The following procedures outline the steps analysts should take when an alert for a large_transaction occurs. It is essential to conduct a review to identify any unusual activity. The transaction may pose a financial crime risk and warrants review.

When a transaction exceeds typical thresholds or deviates significantly from a customer's historical baseline, an alert is generated. The primary objective is to determine if the activity aligns with the customer's known profile and stated purpose of the account. The analyst must inspect a variety of records to form a comprehensive understanding of the event. First, examine the customer's Know Your Customer (KYC) profile, focusing on their stated occupation, expected transaction volumes, and source of wealth. Compare these expected values against the actual alerted amount.

Next, review the transaction history for the preceding ninety days. Establish the baseline behavior. Is this large transfer an isolated event, or part of a newly emerging pattern? Contextual factors should be considered, such as recent life events, property purchases, or business expansions that might explain a sudden influx or outflow of funds. If the customer is a corporate entity, check if the counterparty is a known supplier or vendor in the same industry.

The analyst must document what evidence was found during this inspection. Evidence should include the transaction IDs, the dates of the transfers, the counterparty names, and any discrepancies found between the KYC profile and the observed activity. When comparisons or checks are performed, the rationale for why the activity is deemed expected or anomalous must be explicitly stated.

Analysts must record observations objectively. Avoid making unsupported leaps of logic. If a transaction appears out of character, note the specific attributes that make it so, such as a mismatch between the customer's salary and a sudden massive wire transfer from an unrelated third party.

Human review decisions must be documented clearly in the case management system. The final disposition should summarize the findings, detail the records inspected, and provide a clear justification for closing the alert or proceeding to further investigation. The documentation must be robust enough that an independent reviewer can follow the logic and arrive at the same conclusion based on the cited evidence.

This synthetic procedure ensures that all large transfers are evaluated with a consistent methodology, promoting rigorous examination and detailed record-keeping. The goal is to accurately distinguish between legitimate large-scale financial activities and those that require further scrutiny, maintaining the integrity of the review process.
 If missing context is encountered, the analyst should attempt to retrieve the expected source of funds from secondary internal records before marking the review disposition as incomplete. Missing documentation does not immediately mandate a closure but requires an explicit note detailing what information was unobtainable. When closing an alert as non-anomalous, the disposition narrative must reflect that all relevant customer profile checks were completed successfully, demonstrating that the observed transaction purpose aligns comprehensively with the known behavioral footprint. This final stage is critical to ensure the synthetic review process mimics the depth of a realistic investigation without introducing unverified assumptions. Proper recording ensures that future internal audits can trace the analyst's logic precisely back to the original source-of-funds context."""

DOC2_TEXT = """This document is an illustrative and synthetic internal policy provided for training and system testing purposes only. It does not represent the procedures of any real-world financial institution or regulatory body. The following procedures outline the steps analysts should take when an alert for a new_beneficiary occurs. It is essential to conduct a review to identify any unusual activity. The beneficiary addition may pose a financial crime risk and warrants review.

The addition of a new payee or beneficiary to an account can sometimes indicate an account takeover, unauthorized access, or the redirection of funds to unknown parties. Analysts are required to scrutinize the circumstances surrounding the addition of new beneficiaries, especially when followed immediately by transfers of funds.

The first step in the review process is to assess the beneficiary details. Analysts should inspect the name, country of residence, and the banking institution of the new payee. Compare these details against the customer's historical payment destinations. Has the customer ever sent money to this country or this type of institution before? Check for matching names. If the beneficiary shares a surname with the customer, it may indicate a familial transfer, which generally carries a different risk profile compared to transfers to unrelated corporate entities in high-risk jurisdictions.

Analysts must also verify the purpose of the transfer if such information is available in the payment references or memos. Contextual factors, such as the customer's industry or recent account updates, should be taken into account. Review the velocity of transactions following the beneficiary addition. A single small test transaction followed by a massive transfer is a pattern that requires careful documentation.

When documenting evidence, analysts should cite the specific dates the beneficiary was added, the IP address or device used if available in the fraud systems, and the chronological sequence of subsequent payments. Comparisons must be made between the new payee's profile and the customer's expected behavior.

Observations must be recorded meticulously. The analyst must note whether the addition aligns with the customer's profile. For example, a retail customer suddenly adding multiple overseas corporate beneficiaries within a 24-hour window should be documented as a significant deviation from expected behavior.

Human review decisions must be finalized by documenting the rationale in the system. The analyst must state clearly why the beneficiary addition is considered normal or anomalous. The narrative should lead logically to the conclusion, supported by the evidence gathered from the account history and payee details.

This synthetic policy is designed to enforce a structured approach to evaluating new payee additions, ensuring that analysts comprehensively review the contextual and historical data before making a determination.
 Specifically, the timing of the first payment following the addition of a new payee is a highly predictive signal that must be documented. If the customer context provides conflicting information—such as a sudden change in stated residence that contradicts the payee’s jurisdiction—the analyst must capture this evidence explicitly in the case notes. It is crucial to determine whether the customer’s historical destinations provide a plausible precedent for the newly added beneficiary. When evidence capture is complete, the final determination should address any inconsistencies directly rather than ignoring them. Handling conflicting information effectively requires that analysts weigh the timing of the payment against the verified customer context, ensuring the synthetic investigation reflects a comprehensive approach to newly added payee risks."""

DOC3_TEXT = """This document is an illustrative and synthetic internal policy provided for training and system testing purposes only. It does not represent the procedures of any real-world financial institution or regulatory body. The following procedures outline the steps analysts should take when an alert for a rapid_movement occurs. It is essential to conduct a review to identify any unusual activity. The rapid movement of funds may pose a financial crime risk and warrants review.

Rapid movement of funds, often characterized by funds being deposited and subsequently withdrawn or transferred out within a very short timeframe, can be indicative of pass-through activity or layering. Analysts must investigate these alerts to determine the economic rationale behind the swift sequence of transactions.

Upon receiving an alert for rapid movement, the analyst must first establish the timeline. Calculate the exact time elapsed between the incoming deposits and the outgoing transfers. Inspect the incoming sources and the outgoing destinations. Are the funds originating from cash deposits, wire transfers, or digital payment platforms? Are they being sent to cryptocurrency exchanges, overseas accounts, or withdrawn as cash?

A critical aspect of this review is assessing the economic rationale. Why would the customer use the account merely as a conduit? Contextual factors should be evaluated. For a business account, rapid turnover might be normal if the entity is a retail business paying suppliers immediately after receiving daily sales deposits. For a personal account, receiving large sums and wiring them out on the same day is generally atypical and requires scrutiny.

Analysts must document what evidence was reviewed. This includes retaining screenshots of linked accounts if the funds are being shuttled between related entities. The transaction amounts, timestamps, and counterparties must be cited directly from source records.

Comparisons should be drawn between the total volume of rapid movements and the customer's stated net worth or business revenue. If a student account exhibits rapid pass-through of hundreds of thousands of dollars, the analyst records this observation as a severe mismatch.

Human review decisions must be grounded in these observations. The documentation must clearly explain whether a valid business purpose was identified. If the activity lacks a reasonable economic purpose, the analyst must document the specific characteristics that render the activity anomalous.

This synthetic guideline mandates a thorough examination of the speed, source, and destination of funds. By systematically documenting the flow of money and analyzing the underlying rationale, analysts can effectively identify and evaluate unusual rapid movement patterns within customer accounts.
 The evaluation of transaction sequencing is paramount when reviewing rapid in-and-out transfers. Analysts should calculate the exact elapsed-time between the receipt of funds and their subsequent departure. When conducting a source/destination review, it is imperative to verify whether the business context and expected turnover justify the observed velocity. For example, a wholesale distribution business may naturally exhibit high velocity, whereas a dormant personal account doing the same is highly anomalous. If the expected turnover does not match the rapid sequence, the evidence must be captured clearly to support the final disposition. The human review must conclude whether the rapid sequence reflects a genuine operational need or an unexplained pass-through anomaly, ensuring the synthetic assessment captures the nuanced reality of swift financial flows."""

DOC4_TEXT = """This document is an illustrative and synthetic internal policy provided for training and system testing purposes only. It does not represent the procedures of any real-world financial institution or regulatory body. The following procedures outline the investigation evidence and documentation standards for all alert types. When an alert occurs, it is essential to conduct a review to identify any unusual activity. Evidence must be cited to source records. The analyst records the decision. Automated tooling does not freeze/close accounts. Automated tooling does not file reports. Escalation is a human decision.

The integrity of the review process relies heavily on the quality and accuracy of the documentation provided by the analyst. Every assertion made in a case file must be supported by empirical data. Analysts must ensure that all evidence is cited directly to source records, such as official bank statements, KYC profiles, or verified third-party data providers.

When conducting a review, the analyst must record observations in a structured and chronological manner. The narrative should begin with a summary of why the alert was triggered, followed by the specific records inspected. Contextual factors that influenced the decision must be detailed. For instance, if an alert was deemed normal due to a customer's recent change in employment, the source of that employment verification must be explicitly cited.

It is a strict requirement that automated tooling is used solely for the aggregation of data and the generation of alerts or preliminary insights. Analysts must understand the limitations of these systems. Automated tooling does not freeze/close accounts. Any action to restrict a customer's access to their funds requires a manual review and authorization from designated personnel. Furthermore, automated tooling does not file reports with external agencies. The drafting and submission of any formal external notices remain strictly manual processes.

Most importantly, escalation is a human decision. While an algorithm may score an alert as high priority, the determination to advance a case to a specialized investigation unit or to management rests entirely with the reviewing analyst. The rationale for this decision must be thoroughly documented, highlighting the specific evidence and policy deviations that necessitate further review.

Human review decisions must be comprehensive and self-contained. A subsequent reviewer or auditor should not need to conduct independent research to understand the primary analyst's logic. All comparisons, checks, and observed anomalies must be explicitly written in the final case disposition.

This synthetic policy establishes the foundational standards for evidence gathering and record-keeping, ensuring that all investigations are conducted with rigor, transparency, and full accountability.
 Establishing a clear chronology is vital for documentation completeness. The analyst must differentiate strictly between an observed fact, such as a mismatched address, and an interpretation, such as assuming the customer recently moved. The auditability of the investigation depends on this separation. If an auditor cannot reconstruct the timeline using only the cited sources, the documentation is considered incomplete. The boundaries of human review mean that analysts must not rely on unspoken assumptions or unrecorded conversations. Every piece of contextual evidence that influences the final disposition must be written down. This rigorous approach to source citation ensures that the synthetic review environment remains robust, providing a verifiable trail of evidence that clearly supports the outcome of every investigated alert."""

POLICY_CORPUS_V1: Tuple[PolicyDocumentSpec, ...] = (
    PolicyDocumentSpec(
        title="Synthetic Internal Policy — Large / unusual transaction review procedure",
        document_type="internal_policy",
        version="v1",
        source_url_or_ref="meridian-synthetic-policy-corpus-v1",
        is_synthetic=True,
        text=DOC1_TEXT,
    ),
    PolicyDocumentSpec(
        title="Synthetic Internal Policy — New beneficiary review procedure",
        document_type="internal_policy",
        version="v1",
        source_url_or_ref="meridian-synthetic-policy-corpus-v1",
        is_synthetic=True,
        text=DOC2_TEXT,
    ),
    PolicyDocumentSpec(
        title="Synthetic Internal Policy — Rapid movement of funds review procedure",
        document_type="internal_policy",
        version="v1",
        source_url_or_ref="meridian-synthetic-policy-corpus-v1",
        is_synthetic=True,
        text=DOC3_TEXT,
    ),
    PolicyDocumentSpec(
        title="Synthetic Internal Policy — Investigation evidence and documentation standards",
        document_type="internal_policy",
        version="v1",
        source_url_or_ref="meridian-synthetic-policy-corpus-v1",
        is_synthetic=True,
        text=DOC4_TEXT,
    ),
)
