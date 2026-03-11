# ============================================================================
# DATA-ACCESS-OWNED ABAC CONFIG
# ============================================================================
# Generated from the workspace draft for this environment's governance layer.
# Owns group references, tag assignments, and FGAC policies.
# Tag policy definitions live in envs/account — not here.
# ============================================================================

groups = {
  Finance_Analyst = {
    description = "Standard financial analysts - can see aggregated data with masked PII"
  }
  Compliance_Officer = {
    description = "AML/BSA compliance staff - can see flagged transactions and risk scores"
  }
  PCI_Admin = {
    description = "PCI-authorized personnel - can see last 4 digits of card numbers"
  }
  Clinical_Staff = {
    description = "Healthcare providers - full access to patient clinical data"
  }
  Billing_Admin = {
    description = "Healthcare billing - can see encounter amounts but masked PHI"
  }
  Data_Admin = {
    description = "System administrators - full access for operational purposes"
  }
}

tag_assignments = [
  {
    entity_type = "columns"
    entity_name = "prod_fin.finance.customers.first_name"
    tag_key = "pii_level"
    tag_value = "masked_name"
  },
  {
    entity_type = "columns"
    entity_name = "prod_fin.finance.customers.last_name"
    tag_key = "pii_level"
    tag_value = "masked_name"
  },
  {
    entity_type = "columns"
    entity_name = "prod_fin.finance.customers.ssn"
    tag_key = "pii_level"
    tag_value = "masked_ssn"
  },
  {
    entity_type = "columns"
    entity_name = "prod_fin.finance.customers.email"
    tag_key = "pii_level"
    tag_value = "masked_email"
  },
  {
    entity_type = "columns"
    entity_name = "prod_fin.finance.customers.phone"
    tag_key = "pii_level"
    tag_value = "masked_phone"
  },
  {
    entity_type = "columns"
    entity_name = "prod_fin.finance.customers.address"
    tag_key = "pii_level"
    tag_value = "masked_address"
  },
  {
    entity_type = "columns"
    entity_name = "prod_fin.finance.credit_cards.card_number"
    tag_key = "pci_level"
    tag_value = "masked_card_last4"
  },
  {
    entity_type = "columns"
    entity_name = "prod_fin.finance.credit_cards.cvv"
    tag_key = "pci_level"
    tag_value = "restricted"
  },
  {
    entity_type = "columns"
    entity_name = "prod_fin.finance.transactions.amount"
    tag_key = "financial_sensitivity"
    tag_value = "rounded_amounts"
  },
  {
    entity_type = "tables"
    entity_name = "prod_fin.finance.transactions"
    tag_key = "compliance_scope"
    tag_value = "aml_flagged"
  },
  {
    entity_type = "columns"
    entity_name = "prod_clinical.clinical.patients.first_name"
    tag_key = "phi_level"
    tag_value = "masked_name"
  },
  {
    entity_type = "columns"
    entity_name = "prod_clinical.clinical.patients.last_name"
    tag_key = "phi_level"
    tag_value = "masked_name"
  },
  {
    entity_type = "columns"
    entity_name = "prod_clinical.clinical.patients.ssn"
    tag_key = "phi_level"
    tag_value = "masked_ssn"
  },
  {
    entity_type = "columns"
    entity_name = "prod_clinical.clinical.patients.email"
    tag_key = "phi_level"
    tag_value = "masked_email"
  },
  {
    entity_type = "columns"
    entity_name = "prod_clinical.clinical.patients.phone"
    tag_key = "phi_level"
    tag_value = "masked_phone"
  },
  {
    entity_type = "columns"
    entity_name = "prod_clinical.clinical.patients.address"
    tag_key = "phi_level"
    tag_value = "masked_address"
  },
  {
    entity_type = "columns"
    entity_name = "prod_clinical.clinical.encounters.diagnosis_code"
    tag_key = "phi_level"
    tag_value = "masked_diagnosis"
  },
  {
    entity_type = "columns"
    entity_name = "prod_clinical.clinical.encounters.diagnosis_desc"
    tag_key = "phi_level"
    tag_value = "restricted_notes"
  },
  {
    entity_type = "columns"
    entity_name = "prod_clinical.clinical.encounters.treatment_notes"
    tag_key = "phi_level"
    tag_value = "restricted_notes"
  },
]

fgac_policies = [
  {
    name = "mask_customer_names_finance_analyst"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "prod_fin"
    to_principals = ["Finance_Analyst", "Billing_Admin"]
    comment = "Mask customer names for financial analysts"
    match_condition = "hasTagValue('pii_level', 'masked_name')"
    match_alias = "masked_name"
    function_name = "mask_pii_partial"
    function_catalog = "prod_fin"
    function_schema = "finance"
  },
  {
    name = "mask_customer_ssn_finance_analyst"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "prod_fin"
    to_principals = ["Finance_Analyst", "Billing_Admin"]
    comment = "Mask customer SSN for financial analysts"
    match_condition = "hasTagValue('pii_level', 'masked_ssn')"
    match_alias = "masked_ssn"
    function_name = "mask_ssn"
    function_catalog = "prod_fin"
    function_schema = "finance"
  },
  {
    name = "mask_customer_email_finance_analyst"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "prod_fin"
    to_principals = ["Finance_Analyst", "Billing_Admin"]
    comment = "Mask customer email for financial analysts"
    match_condition = "hasTagValue('pii_level', 'masked_email')"
    match_alias = "masked_email"
    function_name = "mask_email"
    function_catalog = "prod_fin"
    function_schema = "finance"
  },
  {
    name = "mask_customer_phone_finance_analyst"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "prod_fin"
    to_principals = ["Finance_Analyst", "Billing_Admin"]
    comment = "Mask customer phone for financial analysts"
    match_condition = "hasTagValue('pii_level', 'masked_phone')"
    match_alias = "masked_phone"
    function_name = "mask_phone"
    function_catalog = "prod_fin"
    function_schema = "finance"
  },
  {
    name = "mask_customer_address_finance_analyst"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "prod_fin"
    to_principals = ["Finance_Analyst", "Billing_Admin"]
    comment = "Mask customer address for financial analysts"
    match_condition = "hasTagValue('pii_level', 'masked_address')"
    match_alias = "masked_address"
    function_name = "mask_redact"
    function_catalog = "prod_fin"
    function_schema = "finance"
  },
  {
    name = "mask_card_number_last4"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "prod_fin"
    to_principals = ["Finance_Analyst", "Compliance_Officer"]
    comment = "Show last 4 digits of card numbers for authorized roles"
    match_condition = "hasTagValue('pci_level', 'masked_card_last4')"
    match_alias = "masked_card_last4"
    function_name = "mask_credit_card_last4"
    function_catalog = "prod_fin"
    function_schema = "finance"
  },
  {
    name = "mask_cvv_restricted"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "prod_fin"
    to_principals = ["Finance_Analyst", "Compliance_Officer", "Billing_Admin"]
    comment = "Fully redact CVV for all non-PCI roles"
    match_condition = "hasTagValue('pci_level', 'restricted')"
    match_alias = "pci_restricted"
    function_name = "mask_redact"
    function_catalog = "prod_fin"
    function_schema = "finance"
  },
  {
    name = "mask_transaction_amounts"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "prod_fin"
    to_principals = ["Finance_Analyst"]
    comment = "Round transaction amounts for privacy"
    match_condition = "hasTagValue('financial_sensitivity', 'rounded_amounts')"
    match_alias = "rounded_amounts"
    function_name = "mask_amount_rounded"
    function_catalog = "prod_fin"
    function_schema = "finance"
  },
  {
    name = "filter_aml_transactions"
    policy_type = "POLICY_TYPE_ROW_FILTER"
    catalog = "prod_fin"
    to_principals = ["Compliance_Officer"]
    comment = "Show AML-flagged transactions to compliance officers"
    when_condition = "hasTagValue('compliance_scope', 'aml_flagged')"
    function_name = "filter_aml_compliance"
    function_catalog = "prod_fin"
    function_schema = "finance"
  },
  {
    name = "mask_patient_names_billing"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "prod_clinical"
    to_principals = ["Billing_Admin"]
    comment = "Mask patient names for billing staff"
    match_condition = "hasTagValue('phi_level', 'masked_name')"
    match_alias = "phi_masked_name"
    function_name = "mask_pii_partial"
    function_catalog = "prod_clinical"
    function_schema = "clinical"
  },
  {
    name = "mask_patient_ssn_billing"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "prod_clinical"
    to_principals = ["Billing_Admin"]
    comment = "Mask patient SSN for billing staff"
    match_condition = "hasTagValue('phi_level', 'masked_ssn')"
    match_alias = "phi_masked_ssn"
    function_name = "mask_ssn"
    function_catalog = "prod_clinical"
    function_schema = "clinical"
  },
  {
    name = "mask_patient_email_billing"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "prod_clinical"
    to_principals = ["Billing_Admin"]
    comment = "Mask patient email for billing staff"
    match_condition = "hasTagValue('phi_level', 'masked_email')"
    match_alias = "phi_masked_email"
    function_name = "mask_email"
    function_catalog = "prod_clinical"
    function_schema = "clinical"
  },
  {
    name = "mask_patient_phone_billing"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "prod_clinical"
    to_principals = ["Billing_Admin"]
    comment = "Mask patient phone for billing staff"
    match_condition = "hasTagValue('phi_level', 'masked_phone')"
    match_alias = "phi_masked_phone"
    function_name = "mask_phone"
    function_catalog = "prod_clinical"
    function_schema = "clinical"
  },
  {
    name = "mask_patient_address_billing"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "prod_clinical"
    to_principals = ["Billing_Admin"]
    comment = "Mask patient address for billing staff"
    match_condition = "hasTagValue('phi_level', 'masked_address')"
    match_alias = "phi_masked_address"
    function_name = "mask_redact"
    function_catalog = "prod_clinical"
    function_schema = "clinical"
  },
  {
    name = "mask_diagnosis_codes_billing"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "prod_clinical"
    to_principals = ["Billing_Admin"]
    comment = "Show diagnosis category only for billing staff"
    match_condition = "hasTagValue('phi_level', 'masked_diagnosis')"
    match_alias = "phi_masked_diagnosis"
    function_name = "mask_diagnosis_code"
    function_catalog = "prod_clinical"
    function_schema = "clinical"
  },
  {
    name = "mask_clinical_notes_billing"
    policy_type = "POLICY_TYPE_COLUMN_MASK"
    catalog = "prod_clinical"
    to_principals = ["Billing_Admin"]
    comment = "Redact clinical notes for billing staff"
    match_condition = "hasTagValue('phi_level', 'restricted_notes')"
    match_alias = "phi_restricted_notes"
    function_name = "mask_redact"
    function_catalog = "prod_clinical"
    function_schema = "clinical"
  },
]
