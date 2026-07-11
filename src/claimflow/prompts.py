PROMPT_VERSION = "2026-07-02"

HEALTH_EXTRACTION = (
    "Extract all fields from this CMS-1500 health insurance claim form. "
    "The form has numbered boxes — use the box numbers in field descriptions as anchors. "
    "For diagnosis codes extract only the code itself (e.g. J06.9), not descriptions. "
    "For dates use MMDDYYYY format as printed on the form. "
    "For boolean fields: 'X' or checked box = True, empty = False. "
    "Extract ID numbers (insurance ID, insured ID, tax ID, NPI) verbatim as printed, including "
    "any letter prefix — the value directly below the box 1a label 'INSURED'S I.D. NUMBER' is the "
    "full ID; a leading letter sequence there is part of the ID, not a separate label, so don't "
    "strip it. If that box is blank, return null — never invent an ID or reuse an example value."
)

PROPERTY_EXTRACTION = (
    "Extract all fields from this Xactimate property damage estimate. "
    "Line items each have a category, description, quantity, unit, unit cost, and total. "
    "RCV = total replacement cost value. actual_cash_value = RCV minus depreciation ONLY — "
    "some documents also print a separate deductible-adjusted figure (e.g. 'Net Actual Cash "
    "Value Payment'); that is a different, later-stage payout number, not actual_cash_value, "
    "even if it uses similar wording. Do not subtract the deductible. "
    "insured_name is the property owner the claim is filed for — not the adjuster, not the "
    "estimator, and not whoever signed the estimate. If the document identifies the insured only "
    "by a code or reference (not a person's name), extract that code rather than substituting a "
    "different name found elsewhere on the document. If no insured is identifiable, return null. "
    "adjuster_name is specifically an insurance company's claims adjuster — a contractor's own "
    "estimator or preparer is a different role; if only an estimator/preparer is named and no "
    "distinct adjuster appears, return null rather than using the estimator's name. "
    "For dates use MMDDYYYY format."
)

LOAN_EXTRACTION = (
    "Extract all fields from this SBA loan application or business loan form. "
    "Tax ID follows a 2-digit-dash-7-digit EIN pattern or a 3-2-4-digit SSN pattern — "
    "extract the actual digits printed on the form; if the tax ID field is blank, return null. "
    "Never output a placeholder or example pattern as if it were the extracted value. "
    "Extract dollar amounts as numbers without currency symbols. "
    "Signature on file is True only if an actual signature or mark is filled into the signature "
    "line — the line/label itself is always printed on the form whether or not it's signed, so its "
    "presence alone does not mean True; if the line is blank, signature_on_file is False. "
    "Applicant name is the first row of the 'OWNERSHIP OF APPLICANT COMPANY' table (the primary "
    "applicant, not a co-owner listed below); if that first row is blank, return null rather than "
    "using a different owner's name."
)

EOB_EXTRACTION = (
    "Extract all fields from this Explanation of Benefits (EOB) or Medicare Summary Notice (MSN). "
    "provider_charges is the amount the provider billed; allowed_charges is the payer's approved "
    "amount for the service (usually lower than provider_charges). plan_paid is what the insurer/"
    "Medicare paid; patient_responsibility is what the patient owes. "
    "is_bill is True only if the document explicitly presents itself as a bill/invoice requiring "
    "payment; if the document states 'This is not a bill' anywhere, is_bill must be False. "
    "If the document lists multiple service lines plus a 'Total' row, extract the dollar amounts "
    "(provider_charges, allowed_charges, plan_paid, patient_responsibility, deductible_amount, "
    "coinsurance_amount, copay_amount) from the Total row, not the first individual line — this "
    "schema has one set of amount fields per document, not per line. "
    "denial_or_remark_codes are the short alphanumeric codes printed next to a line item (e.g. "
    "CO-45, N130), not the plain-English remark description. "
    "For dates use MMDDYYYY format. Extract dollar amounts as numbers without currency symbols. "
    "If claim_number is blank, return null — never invent one or reuse an example value. "
    "If a name/ID field is printed as a redaction placeholder (e.g. a run of X's like 'XXXXXX'), "
    "return null for that field — a placeholder is not a real value, even though it isn't blank."
)

DECLARATIONS_PAGE_EXTRACTION = (
    "Extract all fields from this homeowners/property insurance declarations page. "
    "Coverage A is dwelling, Coverage B is other structures, Coverage C is personal property, "
    "Coverage D is loss of use — extract each coverage limit as printed, even if some are absent "
    "(return null for a coverage not listed on this policy). "
    "insured_name is the named insured on the policy, not the mortgagee or agent. "
    "For dates use MMDDYYYY format. Extract dollar amounts as numbers without currency symbols. "
    "If policy_number is blank, return null — never invent one or reuse an example value."
)

SBA_FORM_413_EXTRACTION = (
    "Extract all fields from this SBA Form 413 Personal Financial Statement. "
    "Each asset/liability line is a dollar amount as printed on the form; if a line is blank or "
    "shows only the printed label/format hint with no filled-in figure, return null for that field "
    "— never echo the form's own printed label (e.g. '$_____' or a section header) as if it were "
    "a value. total_assets, total_liabilities, and net_worth are the form's own printed totals, not "
    "values you should compute yourself. applicant_name is the person completing the statement — "
    "if only a business name is printed and no individual is named, return null for applicant_name "
    "rather than substituting the business name. For dates use MMDDYYYY format."
)

RETRIEVAL_SYNTHESIS = (
    "Answer the following question using only the policy excerpts below. "
    "Cite sources as [1], [2], [3].\n\n"
    "Question: {question}\n\nPolicy excerpts:\n{context}"
)
