# ============================================================================
# DATA-ACCESS-OWNED ABAC CONFIG
# ============================================================================
# Generated from the workspace draft for this environment's governance layer.
# Owns group references, tag assignments, and FGAC policies.
# Tag policy definitions live in envs/account — not here.
# ============================================================================

groups = {
  Junior_Analyst = {
    description = "Entry-level analysts with limited PII/PHI access"
  }
  Senior_Analyst = {
    description = "Experienced analysts with partial PII access for investigations"
  }
  Compliance_Officer = {
    description = "Full access to AML alerts and audit logs, masked PCI data"
  }
  Clinical_Staff = {
    description = "Healthcare workers with full PHI access"
  }
  Admin = {
    description = "System administrators with full data access"
  }
}

tag_assignments = [
  {
    entity_type = "tables"
    entity_name = "louis_sydney.clinical.encounters"
    tag_key = "data_region"
    tag_value = "us"
  },
  {
    entity_type = "columns"
    entity_name = "louis_sydney.clinical.encounters.PatientID"
    tag_key = "phi_level"
    tag_value = "restricted"
  },
  {
    entity_type = "columns"
    entity_name = "louis_sydney.clinical.encounters.DiagnosisCode"
    tag_key = "phi_level"
    tag_value = "masked_diagnosis"
  },
  {
    entity_type = "columns"
    entity_name = "louis_sydney.clinical.encounters.DiagnosisDesc"
    tag_key = "phi_level"
    tag_value = "masked_notes"
  },
  {
    entity_type = "columns"
    entity_name = "louis_sydney.clinical.encounters.TreatmentNotes"
    tag_key = "phi_level"
    tag_value = "masked_notes"
  },
  {
    entity_type = "columns"
    entity_name = "louis_sydney.clinical.encounters.AttendingDoc"
    tag_key = "pii_level"
    tag_value = "masked_name"
  },
  {
    entity_type = "tables"
    entity_name = "louis_sydney.finance.customers"
    tag_key = "data_region"
    tag_value = "global"
  },
  {
    entity_type = "tables"
    entity_name = "louis_sydney.finance.tradingpositions"
    tag_key = "trading_level"
    tag_value = "restricted"
  },
  {
    entity_type = "tables"
    entity_name = "louis_sydney.finance.auditlogs"
    tag_key = "audit_level"
    tag_value = "restricted"
  },
  {
    entity_type = "columns"
    entity_name = "louis_sydney.finance.customers.FirstName"
    tag_key = "pii_level"
    tag_value = "masked_name"
  },
  {
    entity_type = "columns"
    entity_name = "louis_sydney.finance.customers.LastName"
    tag_key = "pii_level"
    tag_value = "masked_name"
  },
  {
    entity_type = "columns"
    entity_name = "louis_sydney.finance.customers.Email"
    tag_key = "pii_level"
    tag_value = "masked_email"
  },
  {
    entity_type = "columns"
    entity_name = "louis_sydney.finance.customers.SSN"
    tag_key = "pii_level"
    tag_value = "masked_ssn"
  },
  {
    entity_type = "columns"
    entity_name = "louis_sydney.finance.customers.Address"
    tag_key = "pii_level"
    tag_value = "restricted"
  },
  {
    entity_type = "columns"
    entity_name = "louis_sydney.finance.customers.DateOfBirth"
    tag_key = "pii_level"
    tag_value = "restricted"
  },
  {
    entity_type = "columns"
    entity_name = "louis_sydney.finance.creditcards.CardNumber"
    tag_key = "pci_level"
    tag_value = "masked_card_full"
  },
  {
    entity_type = "columns"
    entity_name = "louis_sydney.finance.creditcards.CVV"
    tag_key = "pci_level"
    tag_value = "restricted"
  },
  {
    entity_type = "columns"
    entity_name = "louis_sydney.finance.accounts.AccountID"
    tag_key = "pii_level"
    tag_value = "masked_name"
  },
  {
    entity_type = "columns"
    entity_name = "louis_sydney.finance.amlalerts.InvestigationNotes"
    tag_key = "aml_level"
    tag_value = "investigation_notes"
  },
  {
    entity_type = "columns"
    entity_name = "louis_sydney.finance.amlalerts.AssignedInvestigator"
    tag_key = "pii_level"
    tag_value = "masked_name"
  },
  {
    entity_type = "columns"
    entity_name = "louis_sydney.finance.transactions.Amount"
    tag_key = "aml_level"
    tag_value = "masked_amounts"
  },
  {
    entity_type = "columns"
    entity_name = "louis_sydney.finance.accounts.Balance"
    tag_key = "aml_level"
    tag_value = "masked_amounts"
  },
  {
    entity_type = "columns"
    entity_name = "louis_sydney.finance.customerinteractions.InteractionNotes"
    tag_key = "pii_level"
    tag_value = "restricted"
  },
  {
    entity_type = "columns"
    entity_name = "louis_sydney.finance.customerinteractions.AgentID"
    tag_key = "pii_level"
    tag_value = "masked_name"
  },
]

fgac_policies = [
  {
    name = "mask_diagnosis_codes_junior"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "louis_sydney"
    to_principals = ["Junior_Analyst", "Senior_Analyst"]
    comment = "Mask diagnosis codes to category level for non-clinical staff"
    match_condition = "hasTagValue('phi_level', 'masked_diagnosis')"
    match_alias = "diagnosis"
    function_name = "mask_diagnosis_code"
    function_catalog = "louis_sydney"
    function_schema = "clinical"
  },
  {
    name = "mask_clinical_notes_junior"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "louis_sydney"
    to_principals = ["Junior_Analyst", "Senior_Analyst"]
    comment = "Redact clinical notes and descriptions for non-clinical staff"
    match_condition = "hasTagValue('phi_level', 'masked_notes')"
    match_alias = "notes"
    function_name = "mask_redact"
    function_catalog = "louis_sydney"
    function_schema = "clinical"
  },
  {
    name = "mask_phi_restricted_junior"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "louis_sydney"
    to_principals = ["Junior_Analyst", "Senior_Analyst", "Compliance_Officer"]
    comment = "Hide highly sensitive PHI from non-clinical roles"
    match_condition = "hasTagValue('phi_level', 'restricted')"
    match_alias = "phi_data"
    function_name = "mask_redact"
    function_catalog = "louis_sydney"
    function_schema = "clinical"
  },
  {
    name = "mask_names_junior"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "louis_sydney"
    to_principals = ["Junior_Analyst"]
    comment = "Partially mask names and identifiers for junior analysts"
    match_condition = "hasTagValue('pii_level', 'masked_name')"
    match_alias = "names"
    function_name = "mask_pii_partial"
    function_catalog = "louis_sydney"
    function_schema = "finance"
  },
  {
    name = "mask_ssn_non_compliance"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "louis_sydney"
    to_principals = ["Junior_Analyst", "Senior_Analyst"]
    comment = "Mask SSN for non-compliance roles"
    match_condition = "hasTagValue('pii_level', 'masked_ssn')"
    match_alias = "ssn"
    function_name = "mask_ssn"
    function_catalog = "louis_sydney"
    function_schema = "finance"
  },
  {
    name = "mask_email_junior"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "louis_sydney"
    to_principals = ["Junior_Analyst"]
    comment = "Mask email local parts for junior analysts"
    match_condition = "hasTagValue('pii_level', 'masked_email')"
    match_alias = "email"
    function_name = "mask_email"
    function_catalog = "louis_sydney"
    function_schema = "finance"
  },
  {
    name = "mask_pii_restricted_all"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "louis_sydney"
    to_principals = ["Junior_Analyst", "Senior_Analyst", "Clinical_Staff"]
    comment = "Hide highly sensitive PII from non-compliance roles"
    match_condition = "hasTagValue('pii_level', 'restricted')"
    match_alias = "pii_data"
    function_name = "mask_redact"
    function_catalog = "louis_sydney"
    function_schema = "finance"
  },
  {
    name = "mask_card_numbers_full"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "louis_sydney"
    to_principals = ["Junior_Analyst", "Senior_Analyst", "Compliance_Officer", "Clinical_Staff"]
    comment = "Fully mask credit card numbers for PCI-DSS compliance"
    match_condition = "hasTagValue('pci_level', 'masked_card_full')"
    match_alias = "card_full"
    function_name = "mask_credit_card_full"
    function_catalog = "louis_sydney"
    function_schema = "finance"
  },
  {
    name = "mask_pci_restricted"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "louis_sydney"
    to_principals = ["Junior_Analyst", "Senior_Analyst", "Compliance_Officer", "Clinical_Staff"]
    comment = "Hide CVV and other restricted PCI data"
    match_condition = "hasTagValue('pci_level', 'restricted')"
    match_alias = "pci_data"
    function_name = "mask_nullify"
    function_catalog = "louis_sydney"
    function_schema = "finance"
  },
  {
    name = "mask_amounts_junior"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "louis_sydney"
    to_principals = ["Junior_Analyst"]
    comment = "Round amounts for junior analysts to protect investigation details"
    match_condition = "hasTagValue('aml_level', 'masked_amounts')"
    match_alias = "amounts"
    function_name = "mask_amount_rounded"
    function_catalog = "louis_sydney"
    function_schema = "finance"
  },
  {
    name = "mask_investigation_notes"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "louis_sydney"
    to_principals = ["Junior_Analyst", "Senior_Analyst"]
    comment = "Hide AML investigation notes from non-compliance staff"
    match_condition = "hasTagValue('aml_level', 'investigation_notes')"
    match_alias = "investigation"
    function_name = "mask_redact"
    function_catalog = "louis_sydney"
    function_schema = "finance"
  },
  {
    name = "filter_trading_data_access"
    policy_type = "POLICY_TYPE_ROW_FILTER"
    catalog = "louis_sydney"
    to_principals = ["Junior_Analyst", "Senior_Analyst"]
    comment = "Restrict trading data access outside market hours for Chinese wall compliance"
    when_condition = "hasTagValue('trading_level', 'restricted')"
    function_name = "filter_trading_hours"
    function_catalog = "louis_sydney"
    function_schema = "finance"
  },
  {
    name = "filter_audit_data_access"
    policy_type = "POLICY_TYPE_ROW_FILTER"
    catalog = "louis_sydney"
    to_principals = ["Junior_Analyst", "Senior_Analyst"]
    comment = "Time-limited access to audit logs for SOX compliance"
    when_condition = "hasTagValue('audit_level', 'restricted')"
    function_name = "filter_audit_expiry"
    function_catalog = "louis_sydney"
    function_schema = "finance"
  },
]
