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
}

tag_policies = [
  {
    key = "phi_level"
    description = "Protected Health Information sensitivity"
    values = ["public", "masked_diagnosis", "masked_notes", "restricted", "full_phi"]
  },
  {
    key = "pii_level"
    description = "Personal Identifiable Information sensitivity"
    values = ["public", "masked_name", "masked_ssn", "masked_email", "restricted", "highly_sensitive"]
  },
  {
    key = "pci_level"
    description = "Payment Card Industry data sensitivity"
    values = ["public", "masked_card_full", "masked_card_last4", "restricted"]
  },
  {
    key = "financial_level"
    description = "Financial data sensitivity for trading and compliance"
    values = ["public", "masked_account", "masked_amount", "restricted"]
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
    description = "Compliance and audit data sensitivity"
    values = ["public", "investigation_notes", "restricted"]
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
    description = "Anti-Money Laundering investigation sensitivity"
    values = ["public", "masked_amounts", "investigation_notes", "restricted"]
  },
  {
    key = "audit_level"
    description = "Audit and compliance data sensitivity"
    values = ["public", "restricted"]
  },
  {
    key = "trading_level"
    description = "Trading data for Chinese wall compliance"
    values = ["public", "restricted"]
  },
  {
    key = "data_region"
    description = "Data residency and regional access control"
    values = ["us", "eu", "global"]
  },
  {
    key = "financial_sensitivity"
    description = "Financial data sensitivity levels"
    values = ["public", "masked_account", "masked_amount", "restricted"]
  },
]
