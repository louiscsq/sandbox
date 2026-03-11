# ============================================================================
# ACCOUNT-OWNED ABAC CONFIG
# ============================================================================
# Generated from the workspace draft and merged into shared account state.
# Owns groups, optional group membership, and tag policy definitions.
# Tag policies are account-scoped and shared across all workspace environments.
# ============================================================================

groups = {
  Clinical_Staff = {
    description = "Healthcare providers with access to patient data and clinical notes"
  }
  Clinical_Analysts = {
    description = "Clinical data analysts with limited access to masked patient information"
  }
  Finance_Analysts = {
    description = "Financial analysts with access to transaction data and customer insights"
  }
  Compliance_Officers = {
    description = "AML/KYC compliance team with full access to investigation data"
  }
  Auditors = {
    description = "External auditors with time-limited access to audit logs and financial data"
  }
  Traders = {
    description = "Trading desk staff with restricted access based on information barriers"
  }
  Customer_Service = {
    description = "Customer service representatives with limited PII access"
  }
  Junior_Analyst = {
    description = "Entry-level analysts with limited access to masked PII and basic financial data"
  }
  Senior_Analyst = {
    description = "Experienced analysts with access to detailed financial data and partial PII"
  }
  Compliance_Officer = {
    description = "Full access to AML, audit logs, and investigation data for regulatory compliance"
  }
  Admin = {
    description = "System administrators with unrestricted access to all data"
  }
  Finance_Admin = {
    description = "Finance administrators with full PCI/PII access for operations"
  }
  Finance_Analyst = {
    description = "Standard financial analysts - can see aggregated data with masked PII"
  }
  PCI_Admin = {
    description = "PCI-authorized personnel - can see last 4 digits of card numbers"
  }
  Billing_Admin = {
    description = "Healthcare billing - can see encounter amounts but masked PHI"
  }
  Data_Admin = {
    description = "System administrators - full access for operational purposes"
  }
}

tag_policies = [
  {
    key = "phi_level"
    description = "Protected health information sensitivity"
    values = ["public", "masked_name", "masked_ssn", "masked_email", "masked_phone", "masked_address", "masked_diagnosis", "restricted_notes", "full_phi"]
  },
  {
    key = "pii_level"
    description = "Personal information sensitivity"
    values = ["public", "masked_name", "masked_ssn", "masked_email", "masked_phone", "masked_address", "highly_sensitive"]
  },
  {
    key = "pci_level"
    description = "Payment card industry sensitivity"
    values = ["public", "masked_card_full", "masked_card_last4", "restricted"]
  },
  {
    key = "financial_level"
    description = "Financial data sensitivity"
    values = ["public", "masked_amounts", "masked_accounts", "restricted"]
  },
  {
    key = "regional_access"
    description = "Geographic data access controls"
    values = ["global", "us_only", "eu_only", "apac_only"]
  },
  {
    key = "audit_scope"
    description = "Audit and compliance data access levels"
    values = ["public", "audit_logs", "time_restricted"]
  },
  {
    key = "compliance_level"
    description = "Regulatory compliance sensitivity"
    values = ["public", "audit_restricted", "investigation_notes", "restricted"]
  },
  {
    key = "region_access"
    description = "Regional data access control"
    values = ["us_only", "eu_only", "global"]
  },
  {
    key = "trading_restriction"
    description = "Trading data access restrictions"
    values = ["public", "non_market_hours", "restricted"]
  },
  {
    key = "audit_access"
    description = "Audit log access control"
    values = ["public", "time_limited", "restricted"]
  },
  {
    key = "aml_level"
    description = "Anti-Money Laundering data sensitivity"
    values = ["public", "masked_amounts", "redacted", "restricted"]
  },
  {
    key = "audit_level"
    description = "Audit and compliance data sensitivity"
    values = ["public", "time_limited", "restricted"]
  },
  {
    key = "trading_level"
    description = "Trading data sensitivity for Chinese walls"
    values = ["public", "trading_restricted", "restricted"]
  },
  {
    key = "data_region"
    description = "Data residency and regional access control"
    values = ["global", "us_only", "eu_only"]
  },
  {
    key = "financial_sensitivity"
    description = "Financial data sensitivity"
    values = ["public", "rounded_amounts", "restricted"]
  },
  {
    key = "data_residency"
    description = "Data residency and regional filtering"
    values = ["global", "us_only", "eu_only"]
  },
  {
    key = "compliance_scope"
    description = "Regulatory compliance requirements"
    values = ["public", "aml_flagged", "pci_restricted", "phi_restricted"]
  },
]
