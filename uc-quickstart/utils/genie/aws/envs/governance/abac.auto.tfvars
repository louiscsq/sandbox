# ============================================================================
# WORKSPACE-OWNED ABAC CONFIG
# ============================================================================
# Generated from the workspace draft for this environment only.
# Owns workspace lookups/ACLs and Genie config only.
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
