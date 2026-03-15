# ============================================================================
# DATA-ACCESS-OWNED ABAC CONFIG
# ============================================================================
# Generated from the workspace draft for this environment's governance layer.
# Owns group references, tag assignments, and FGAC policies.
# Tag policy definitions live in envs/account — not here.
# ============================================================================

groups = {
  Financial_Analyst = {
    description = "Standard financial analysts - can see masked PII and aggregated transaction data"
  }
  AML_Compliance = {
    description = "AML compliance officers - can see AML flags and risk scores without PII restrictions"
  }
  Finance_Admin = {
    description = "Finance administrators - full access to financial data except PCI-restricted fields"
  }
  Clinical_Staff = {
    description = "Healthcare providers - full access to PHI for patient care"
  }
  Clinical_Researcher = {
    description = "Clinical researchers - can see de-identified patient data"
  }
  Data_Governance_Admin = {
    description = "Data governance team - full administrative access across all domains"
  }
}

tag_assignments = [
  {
    entity_type = "columns"
    entity_name = "dev_fin.finance.customers.first_name"
    tag_key = "pii_level"
    tag_value = "masked_name"
  },
  {
    entity_type = "columns"
    entity_name = "dev_fin.finance.customers.last_name"
    tag_key = "pii_level"
    tag_value = "masked_name"
  },
  {
    entity_type = "columns"
    entity_name = "dev_fin.finance.customers.ssn"
    tag_key = "pii_level"
    tag_value = "masked_ssn"
  },
  {
    entity_type = "columns"
    entity_name = "dev_fin.finance.customers.date_of_birth"
    tag_key = "pii_level"
    tag_value = "masked_dob"
  },
  {
    entity_type = "columns"
    entity_name = "dev_fin.finance.customers.email"
    tag_key = "pii_level"
    tag_value = "masked_email"
  },
  {
    entity_type = "columns"
    entity_name = "dev_fin.finance.customers.phone"
    tag_key = "pii_level"
    tag_value = "masked_phone"
  },
  {
    entity_type = "columns"
    entity_name = "dev_fin.finance.customers.address"
    tag_key = "pii_level"
    tag_value = "masked_address"
  },
  {
    entity_type = "columns"
    entity_name = "dev_fin.finance.credit_cards.card_number"
    tag_key = "pci_level"
    tag_value = "redacted_card_full"
  },
  {
    entity_type = "columns"
    entity_name = "dev_fin.finance.credit_cards.cvv"
    tag_key = "pci_level"
    tag_value = "redacted_cvv"
  },
  {
    entity_type = "columns"
    entity_name = "dev_fin.finance.transactions.amount"
    tag_key = "financial_sensitivity"
    tag_value = "rounded_amounts"
  },
  {
    entity_type = "columns"
    entity_name = "dev_fin.finance.credit_cards.credit_limit"
    tag_key = "financial_sensitivity"
    tag_value = "rounded_amounts"
  },
  {
    entity_type = "columns"
    entity_name = "dev_fin.finance.credit_cards.current_balance"
    tag_key = "financial_sensitivity"
    tag_value = "rounded_amounts"
  },
  {
    entity_type = "tables"
    entity_name = "dev_fin.finance.transactions"
    tag_key = "compliance_scope"
    tag_value = "aml_restricted"
  },
  {
    entity_type = "columns"
    entity_name = "dev_clinical.clinical.patients.first_name"
    tag_key = "phi_level"
    tag_value = "masked_name_phi"
  },
  {
    entity_type = "columns"
    entity_name = "dev_clinical.clinical.patients.last_name"
    tag_key = "phi_level"
    tag_value = "masked_name_phi"
  },
  {
    entity_type = "columns"
    entity_name = "dev_clinical.clinical.patients.date_of_birth"
    tag_key = "phi_level"
    tag_value = "masked_dob_phi"
  },
  {
    entity_type = "columns"
    entity_name = "dev_clinical.clinical.patients.ssn"
    tag_key = "phi_level"
    tag_value = "masked_ssn_phi"
  },
  {
    entity_type = "columns"
    entity_name = "dev_clinical.clinical.patients.email"
    tag_key = "phi_level"
    tag_value = "masked_email_phi"
  },
  {
    entity_type = "columns"
    entity_name = "dev_clinical.clinical.patients.phone"
    tag_key = "phi_level"
    tag_value = "masked_phone_phi"
  },
  {
    entity_type = "columns"
    entity_name = "dev_clinical.clinical.patients.address"
    tag_key = "phi_level"
    tag_value = "masked_address_phi"
  },
  {
    entity_type = "columns"
    entity_name = "dev_clinical.clinical.patients.insurance_id"
    tag_key = "phi_level"
    tag_value = "masked_insurance"
  },
  {
    entity_type = "columns"
    entity_name = "dev_clinical.clinical.encounters.diagnosis_code"
    tag_key = "phi_level"
    tag_value = "masked_diagnosis"
  },
  {
    entity_type = "columns"
    entity_name = "dev_clinical.clinical.encounters.diagnosis_desc"
    tag_key = "phi_level"
    tag_value = "redacted_notes"
  },
  {
    entity_type = "columns"
    entity_name = "dev_clinical.clinical.encounters.treatment_notes"
    tag_key = "phi_level"
    tag_value = "redacted_notes"
  },
]

fgac_policies = [
  {
    name = "mask_pii_names"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "dev_fin"
    to_principals = ["Financial_Analyst"]
    comment = "Mask customer names for financial analysts"
    match_condition = "hasTagValue('pii_level', 'masked_name')"
    match_alias = "pii_masked_name"
    function_name = "mask_pii_partial"
    function_catalog = "dev_fin"
    function_schema = "finance"
  },
  {
    name = "mask_pii_ssn"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "dev_fin"
    to_principals = ["Financial_Analyst", "AML_Compliance"]
    comment = "Mask SSN for non-admin financial roles"
    match_condition = "hasTagValue('pii_level', 'masked_ssn')"
    match_alias = "pii_masked_ssn"
    function_name = "mask_ssn"
    function_catalog = "dev_fin"
    function_schema = "finance"
  },
  {
    name = "mask_pii_email"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "dev_fin"
    to_principals = ["Financial_Analyst"]
    comment = "Mask email addresses for financial analysts"
    match_condition = "hasTagValue('pii_level', 'masked_email')"
    match_alias = "pii_masked_email"
    function_name = "mask_email"
    function_catalog = "dev_fin"
    function_schema = "finance"
  },
  {
    name = "mask_pci_card_full"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "dev_fin"
    to_principals = ["account users"]
    except_principals = ["Data_Governance_Admin"]
    comment = "Fully redact credit card numbers for all users except data governance"
    match_condition = "hasTagValue('pci_level', 'redacted_card_full')"
    match_alias = "pci_card_full"
    function_name = "mask_credit_card_full"
    function_catalog = "dev_fin"
    function_schema = "finance"
  },
  {
    name = "mask_phi_names"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "dev_clinical"
    to_principals = ["Clinical_Researcher"]
    comment = "Mask patient names for clinical researchers"
    match_condition = "hasTagValue('phi_level', 'masked_name_phi')"
    match_alias = "phi_masked_name"
    function_name = "mask_pii_partial"
    function_catalog = "dev_clinical"
    function_schema = "clinical"
  },
  {
    name = "mask_phi_diagnosis"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "dev_clinical"
    to_principals = ["Clinical_Researcher"]
    comment = "Mask diagnosis codes to category level for researchers"
    match_condition = "hasTagValue('phi_level', 'masked_diagnosis')"
    match_alias = "phi_diagnosis_code"
    function_name = "mask_diagnosis_code"
    function_catalog = "dev_clinical"
    function_schema = "clinical"
  },
  {
    name = "redact_phi_notes"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "dev_clinical"
    to_principals = ["Clinical_Researcher"]
    comment = "Fully redact clinical notes and diagnosis descriptions for researchers"
    match_condition = "hasTagValue('phi_level', 'redacted_notes')"
    match_alias = "phi_redacted_notes"
    function_name = "mask_redact"
    function_catalog = "dev_clinical"
    function_schema = "clinical"
  },
  {
    name = "filter_aml_restricted"
    policy_type = "POLICY_TYPE_ROW_FILTER"
    catalog = "dev_fin"
    to_principals = ["account users"]
    except_principals = ["AML_Compliance", "Data_Governance_Admin"]
    comment = "Restrict AML-flagged transaction visibility to compliance officers only"
    when_condition = "hasTagValue('compliance_scope', 'aml_restricted')"
    function_name = "filter_aml_compliance_only"
    function_catalog = "dev_fin"
    function_schema = "finance"
  },
  {
    name = "auto_mask_dev_fin_pci_level_redacted_cvv"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "dev_fin"
    to_principals = ["account users"]
    except_principals = ["Data_Governance_Admin"]
    comment = "Auto-repaired coverage for dev_fin.finance.credit_cards.cvv (pci_level = 'redacted_cvv')"
    match_condition = "hasTagValue('pci_level', 'redacted_cvv')"
    match_alias = "pci_level_redacted_cvv"
    function_name = "mask_redact"
    function_catalog = "dev_fin"
    function_schema = "finance"
  },
  {
    name = "auto_mask_dev_clinical_phi_level_masked_ssn_phi"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "dev_clinical"
    to_principals = ["Clinical_Researcher"]
    comment = "Auto-repaired coverage for dev_clinical.clinical.patients.ssn (phi_level = 'masked_ssn_phi')"
    match_condition = "hasTagValue('phi_level', 'masked_ssn_phi')"
    match_alias = "phi_level_masked_ssn_phi"
    function_name = "mask_ssn"
    function_catalog = "dev_clinical"
    function_schema = "clinical"
  },
  {
    name = "auto_mask_dev_fin_financial_sensitivity_rounded_amounts"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "dev_fin"
    to_principals = ["Financial_Analyst"]
    comment = "Auto-repaired coverage for dev_fin.finance.credit_cards.credit_limit (financial_sensitivity = 'rounded_amounts')"
    match_condition = "hasTagValue('financial_sensitivity', 'rounded_amounts')"
    match_alias = "financial_sensitivity_rounded_amounts"
    function_name = "mask_pii_partial"
    function_catalog = "dev_fin"
    function_schema = "finance"
  },
  {
    name = "auto_mask_dev_fin_pii_level_masked_dob"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "dev_fin"
    to_principals = ["Financial_Analyst"]
    comment = "Auto-repaired coverage for dev_fin.finance.customers.date_of_birth (pii_level = 'masked_dob')"
    match_condition = "hasTagValue('pii_level', 'masked_dob')"
    match_alias = "pii_level_masked_dob"
    function_name = "mask_date_to_year"
    function_catalog = "dev_fin"
    function_schema = "finance"
  },
  {
    name = "auto_mask_dev_fin_pii_level_masked_address"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "dev_fin"
    to_principals = ["Financial_Analyst"]
    comment = "Auto-repaired coverage for dev_fin.finance.customers.address (pii_level = 'masked_address')"
    match_condition = "hasTagValue('pii_level', 'masked_address')"
    match_alias = "pii_level_masked_address"
    function_name = "mask_redact"
    function_catalog = "dev_fin"
    function_schema = "finance"
  },
  {
    name = "auto_mask_dev_clinical_phi_level_masked_dob_phi"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "dev_clinical"
    to_principals = ["Clinical_Researcher"]
    comment = "Auto-repaired coverage for dev_clinical.clinical.patients.date_of_birth (phi_level = 'masked_dob_phi')"
    match_condition = "hasTagValue('phi_level', 'masked_dob_phi')"
    match_alias = "phi_level_masked_dob_phi"
    function_name = "mask_date_to_year"
    function_catalog = "dev_clinical"
    function_schema = "clinical"
  },
  {
    name = "auto_mask_dev_clinical_phi_level_masked_address_phi"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "dev_clinical"
    to_principals = ["Clinical_Researcher"]
    comment = "Auto-repaired coverage for dev_clinical.clinical.patients.address (phi_level = 'masked_address_phi')"
    match_condition = "hasTagValue('phi_level', 'masked_address_phi')"
    match_alias = "phi_level_masked_address_phi"
    function_name = "mask_redact"
    function_catalog = "dev_clinical"
    function_schema = "clinical"
  },
  {
    name = "auto_mask_dev_fin_pii_level_masked_phone"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "dev_fin"
    to_principals = ["Financial_Analyst"]
    comment = "Auto-repaired coverage for dev_fin.finance.customers.phone (pii_level = 'masked_phone')"
    match_condition = "hasTagValue('pii_level', 'masked_phone')"
    match_alias = "pii_level_masked_phone"
    function_name = "mask_phone"
    function_catalog = "dev_fin"
    function_schema = "finance"
  },
  {
    name = "auto_mask_dev_clinical_phi_level_masked_email_phi"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "dev_clinical"
    to_principals = ["Clinical_Researcher"]
    comment = "Auto-repaired coverage for dev_clinical.clinical.patients.email (phi_level = 'masked_email_phi')"
    match_condition = "hasTagValue('phi_level', 'masked_email_phi')"
    match_alias = "phi_level_masked_email_phi"
    function_name = "mask_email"
    function_catalog = "dev_clinical"
    function_schema = "clinical"
  },
  {
    name = "auto_mask_dev_clinical_phi_level_masked_phone_phi"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "dev_clinical"
    to_principals = ["Clinical_Researcher"]
    comment = "Auto-repaired coverage for dev_clinical.clinical.patients.phone (phi_level = 'masked_phone_phi')"
    match_condition = "hasTagValue('phi_level', 'masked_phone_phi')"
    match_alias = "phi_level_masked_phone_phi"
    function_name = "mask_phone"
    function_catalog = "dev_clinical"
    function_schema = "clinical"
  },
  {
    name = "auto_mask_dev_clinical_phi_level_masked_insurance"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "dev_clinical"
    to_principals = ["Clinical_Researcher"]
    comment = "Auto-repaired coverage for dev_clinical.clinical.patients.insurance_id (phi_level = 'masked_insurance')"
    match_condition = "hasTagValue('phi_level', 'masked_insurance')"
    match_alias = "phi_level_masked_insurance"
    function_name = "mask_redact"
    function_catalog = "dev_clinical"
    function_schema = "clinical"
  },
]
