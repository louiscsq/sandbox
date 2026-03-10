# ============================================================================
# DATA-ACCESS-OWNED ABAC CONFIG
# ============================================================================
# Generated from the workspace draft for this environment's governance layer.
# Owns group references, tag assignments, and FGAC policies.
# Tag policy definitions live in envs/account — not here.
# ============================================================================

groups = {
  Junior_Analyst = {
    description = "Entry-level analysts with basic access to aggregated data"
  }
  Senior_Analyst = {
    description = "Experienced analysts with access to detailed financial data but masked PII"
  }
  Compliance_Officer = {
    description = "Compliance team with access to AML alerts and audit logs"
  }
  Clinical_Staff = {
    description = "Healthcare professionals with access to patient encounter data"
  }
  Admin = {
    description = "System administrators with full access to all data"
  }
}

tag_assignments = [
  {
    entity_type = "tables"
    entity_name = "sydney_louis_prod.clinical.encounters"
    tag_key = "data_region"
    tag_value = "us"
  },
  {
    entity_type = "columns"
    entity_name = "sydney_louis_prod.clinical.encounters.DiagnosisCode"
    tag_key = "phi_level"
    tag_value = "masked_diagnosis"
  },
  {
    entity_type = "columns"
    entity_name = "sydney_louis_prod.clinical.encounters.DiagnosisDesc"
    tag_key = "phi_level"
    tag_value = "masked_notes"
  },
  {
    entity_type = "columns"
    entity_name = "sydney_louis_prod.clinical.encounters.TreatmentNotes"
    tag_key = "phi_level"
    tag_value = "masked_notes"
  },
  {
    entity_type = "columns"
    entity_name = "sydney_louis_prod.clinical.encounters.AttendingDoc"
    tag_key = "pii_level"
    tag_value = "masked_partial"
  },
  {
    entity_type = "tables"
    entity_name = "sydney_louis_prod.finance.tradingpositions"
    tag_key = "trading_restriction"
    tag_value = "non_market_hours"
  },
  {
    entity_type = "tables"
    entity_name = "sydney_louis_prod.finance.auditlogs"
    tag_key = "audit_access"
    tag_value = "time_limited"
  },
  {
    entity_type = "columns"
    entity_name = "sydney_louis_prod.finance.customers.FirstName"
    tag_key = "pii_level"
    tag_value = "masked_partial"
  },
  {
    entity_type = "columns"
    entity_name = "sydney_louis_prod.finance.customers.LastName"
    tag_key = "pii_level"
    tag_value = "masked_partial"
  },
  {
    entity_type = "columns"
    entity_name = "sydney_louis_prod.finance.customers.Email"
    tag_key = "pii_level"
    tag_value = "masked_email"
  },
  {
    entity_type = "columns"
    entity_name = "sydney_louis_prod.finance.customers.SSN"
    tag_key = "pii_level"
    tag_value = "masked_ssn"
  },
  {
    entity_type = "columns"
    entity_name = "sydney_louis_prod.finance.customers.Address"
    tag_key = "pii_level"
    tag_value = "restricted"
  },
  {
    entity_type = "columns"
    entity_name = "sydney_louis_prod.finance.creditcards.CardNumber"
    tag_key = "pci_level"
    tag_value = "masked_last4"
  },
  {
    entity_type = "columns"
    entity_name = "sydney_louis_prod.finance.creditcards.CVV"
    tag_key = "pci_level"
    tag_value = "masked_full"
  },
  {
    entity_type = "columns"
    entity_name = "sydney_louis_prod.finance.accounts.AccountID"
    tag_key = "financial_sensitivity"
    tag_value = "masked_account"
  },
  {
    entity_type = "columns"
    entity_name = "sydney_louis_prod.finance.accounts.Balance"
    tag_key = "financial_sensitivity"
    tag_value = "masked_amount"
  },
  {
    entity_type = "columns"
    entity_name = "sydney_louis_prod.finance.transactions.Amount"
    tag_key = "financial_sensitivity"
    tag_value = "masked_amount"
  },
  {
    entity_type = "columns"
    entity_name = "sydney_louis_prod.finance.amlalerts.InvestigationNotes"
    tag_key = "compliance_level"
    tag_value = "investigation_notes"
  },
  {
    entity_type = "columns"
    entity_name = "sydney_louis_prod.finance.customerinteractions.InteractionNotes"
    tag_key = "compliance_level"
    tag_value = "investigation_notes"
  },
]

fgac_policies = [
  {
    name = "mask_diagnosis_codes_junior"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "sydney_louis_prod"
    to_principals = ["Junior_Analyst", "Senior_Analyst"]
    comment = "Mask specific diagnosis details for non-clinical staff"
    match_condition = "hasTagValue('phi_level', 'masked_diagnosis')"
    match_alias = "diagnosis_code"
    function_name = "mask_diagnosis_code"
    function_catalog = "sydney_louis_prod"
    function_schema = "clinical"
  },
  {
    name = "mask_clinical_notes_junior"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "sydney_louis_prod"
    to_principals = ["Junior_Analyst", "Senior_Analyst"]
    comment = "Redact clinical notes for non-clinical staff"
    match_condition = "hasTagValue('phi_level', 'masked_notes')"
    match_alias = "clinical_notes"
    function_name = "mask_redact"
    function_catalog = "sydney_louis_prod"
    function_schema = "clinical"
  },
  {
    name = "mask_names_junior"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "sydney_louis_prod"
    to_principals = ["Junior_Analyst"]
    comment = "Partially mask names for junior analysts"
    match_condition = "hasTagValue('pii_level', 'masked_partial')"
    match_alias = "partial_pii"
    function_name = "mask_pii_partial"
    function_catalog = "sydney_louis_prod"
    function_schema = "finance"
  },
  {
    name = "mask_emails_junior"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "sydney_louis_prod"
    to_principals = ["Junior_Analyst"]
    comment = "Mask email local parts for junior analysts"
    match_condition = "hasTagValue('pii_level', 'masked_email')"
    match_alias = "email_pii"
    function_name = "mask_email"
    function_catalog = "sydney_louis_prod"
    function_schema = "finance"
  },
  {
    name = "mask_ssn_non_compliance"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "sydney_louis_prod"
    to_principals = ["Junior_Analyst", "Senior_Analyst"]
    comment = "Show only last 4 digits of SSN for non-compliance roles"
    match_condition = "hasTagValue('pii_level', 'masked_ssn')"
    match_alias = "ssn_pii"
    function_name = "mask_ssn"
    function_catalog = "sydney_louis_prod"
    function_schema = "finance"
  },
  {
    name = "nullify_restricted_pii"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "sydney_louis_prod"
    to_principals = ["Junior_Analyst", "Senior_Analyst"]
    comment = "Completely hide highly sensitive PII"
    match_condition = "hasTagValue('pii_level', 'restricted')"
    match_alias = "restricted_pii"
    function_name = "mask_nullify"
    function_catalog = "sydney_louis_prod"
    function_schema = "finance"
  },
  {
    name = "mask_card_last4_analysts"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "sydney_louis_prod"
    to_principals = ["Senior_Analyst"]
    comment = "Show last 4 digits of card numbers for senior analysts"
    match_condition = "hasTagValue('pci_level', 'masked_last4')"
    match_alias = "card_last4"
    function_name = "mask_credit_card_last4"
    function_catalog = "sydney_louis_prod"
    function_schema = "finance"
  },
  {
    name = "mask_card_full_junior"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "sydney_louis_prod"
    to_principals = ["Junior_Analyst"]
    comment = "Completely mask card numbers for junior analysts"
    match_condition = "hasTagValue('pci_level', 'masked_last4')"
    match_alias = "card_full"
    function_name = "mask_credit_card_full"
    function_catalog = "sydney_louis_prod"
    function_schema = "finance"
  },
  {
    name = "mask_cvv_all"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "sydney_louis_prod"
    to_principals = ["Junior_Analyst", "Senior_Analyst", "Compliance_Officer"]
    comment = "Completely mask CVV for all non-admin users"
    match_condition = "hasTagValue('pci_level', 'masked_full')"
    match_alias = "cvv_full"
    function_name = "mask_credit_card_full"
    function_catalog = "sydney_louis_prod"
    function_schema = "finance"
  },
  {
    name = "mask_account_ids_junior"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "sydney_louis_prod"
    to_principals = ["Junior_Analyst"]
    comment = "Hash account IDs for junior analysts"
    match_condition = "hasTagValue('financial_sensitivity', 'masked_account')"
    match_alias = "account_hash"
    function_name = "mask_account_number"
    function_catalog = "sydney_louis_prod"
    function_schema = "finance"
  },
  {
    name = "mask_amounts_junior"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "sydney_louis_prod"
    to_principals = ["Junior_Analyst"]
    comment = "Round amounts to nearest 100 for junior analysts"
    match_condition = "hasTagValue('financial_sensitivity', 'masked_amount')"
    match_alias = "rounded_amount"
    function_name = "mask_amount_rounded"
    function_catalog = "sydney_louis_prod"
    function_schema = "finance"
  },
  {
    name = "mask_investigation_notes"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "sydney_louis_prod"
    to_principals = ["Junior_Analyst", "Senior_Analyst"]
    comment = "Redact investigation notes for non-compliance staff"
    match_condition = "hasTagValue('compliance_level', 'investigation_notes')"
    match_alias = "investigation_redacted"
    function_name = "mask_redact"
    function_catalog = "sydney_louis_prod"
    function_schema = "finance"
  },
  {
    name = "filter_trading_non_market_hours"
    policy_type = "POLICY_TYPE_ROW_FILTER"
    catalog = "sydney_louis_prod"
    to_principals = ["Junior_Analyst", "Senior_Analyst"]
    comment = "Restrict trading data access to non-market hours"
    when_condition = "hasTagValue('trading_restriction', 'non_market_hours')"
    function_name = "filter_trading_hours"
    function_catalog = "sydney_louis_prod"
    function_schema = "finance"
  },
  {
    name = "filter_audit_time_limited"
    policy_type = "POLICY_TYPE_ROW_FILTER"
    catalog = "sydney_louis_prod"
    to_principals = ["Junior_Analyst", "Senior_Analyst"]
    comment = "Time-limited access to audit logs"
    when_condition = "hasTagValue('audit_access', 'time_limited')"
    function_name = "filter_audit_expiry"
    function_catalog = "sydney_louis_prod"
    function_schema = "finance"
  },
  {
    name = "filter_clinical_us_region"
    policy_type = "POLICY_TYPE_ROW_FILTER"
    catalog = "sydney_louis_prod"
    to_principals = ["Junior_Analyst", "Senior_Analyst"]
    comment = "Restrict clinical data to US region"
    when_condition = "hasTagValue('data_region', 'us')"
    function_name = "filter_by_region_us"
    function_catalog = "sydney_louis_prod"
    function_schema = "clinical"
  },
]
