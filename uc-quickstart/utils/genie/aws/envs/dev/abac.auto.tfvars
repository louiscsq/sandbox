# ============================================================================
# WORKSPACE-OWNED ABAC CONFIG
# ============================================================================
# Generated from the workspace draft for this environment only.
# Owns workspace lookups/ACLs and Genie config only.
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

genie_space_title = "Financial Services & Healthcare Analytics"

genie_space_description = "Explore customer transactions, credit card data, patient encounters, and compliance metrics. Designed for financial analysts, compliance officers, clinical staff, and billing administrators with appropriate data masking."

genie_sample_questions = ["What is the total transaction volume for completed transactions last quarter?", "Show the top 10 customers by account tier and transaction count", "How many AML-flagged transactions occurred this month?", "What is the average credit limit by card type for active cards?", "How many patient encounters were there last month by encounter type?", "What is the total billed amount for outpatient encounters this year?", "Which facilities had the highest number of emergency encounters?", "What is the average length of stay for inpatient encounters?", "Show transaction patterns by merchant category for retail customers", "What is the distribution of risk scores across different account tiers?"]

genie_instructions = "When asked about 'transactions' without specifying status, default to completed transactions (status = 'COMPLETED'). When asked about 'customers' without qualifier, include all KYC-verified customers (kyc_status = 'VERIFIED'). When asked about 'cards' without status, default to active cards (status = 'ACTIVE'). When asked about 'encounters' without specifying type, include all encounter types. 'Last month' means the previous calendar month. 'This year' means current calendar year. Round monetary values to 2 decimal places. Patient names and other PHI are masked for non-clinical roles - queries about encounter counts, dates, and amounts are allowed. AML-flagged transaction details are restricted to compliance officers."

genie_benchmarks = [
  {
    question = "What is the total amount of completed transactions?"
    sql = "SELECT SUM(amount) as total_amount FROM dev_fin.finance.transactions WHERE status = 'COMPLETED'"
  },
  {
    question = "How many patient encounters occurred last month?"
    sql = "SELECT COUNT(*) FROM dev_clinical.clinical.encounters WHERE encounter_date >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL 1 MONTH) AND encounter_date < DATE_TRUNC('month', CURRENT_DATE)"
  },
  {
    question = "What is the average credit limit for active credit cards?"
    sql = "SELECT AVG(credit_limit) as avg_credit_limit FROM dev_fin.finance.credit_cards WHERE status = 'ACTIVE'"
  },
  {
    question = "How many verified customers are in the private banking tier?"
    sql = "SELECT COUNT(*) FROM dev_fin.finance.customers WHERE kyc_status = 'VERIFIED' AND account_tier = 'PRIVATE_BANKING'"
  },
  {
    question = "What is the total billed amount for emergency encounters this year?"
    sql = "SELECT SUM(billed_amount) FROM dev_clinical.clinical.encounters WHERE encounter_type = 'EMERGENCY' AND YEAR(encounter_date) = YEAR(CURRENT_DATE)"
  },
]

genie_sql_filters = [
  {
    sql = "transactions.status = 'COMPLETED'"
    display_name = "completed transactions"
    comment = "Only include completed transactions"
    instruction = "Apply when user asks about transactions or amounts without specifying status"
  },
  {
    sql = "customers.kyc_status = 'VERIFIED'"
    display_name = "verified customers"
    comment = "Only include KYC-verified customers"
    instruction = "Apply when user asks about customers without specifying KYC status"
  },
  {
    sql = "credit_cards.status = 'ACTIVE'"
    display_name = "active credit cards"
    comment = "Only include active credit cards"
    instruction = "Apply when user asks about credit cards without specifying status"
  },
  {
    sql = "transactions.aml_flag = false"
    display_name = "non-flagged transactions"
    comment = "Exclude AML-flagged transactions for non-compliance users"
    instruction = "Apply for general transaction analysis unless user is compliance officer"
  },
]

genie_sql_expressions = [
  {
    alias = "transaction_year"
    sql = "YEAR(transactions.transaction_date)"
    display_name = "transaction year"
    comment = "Extracts year from transaction date"
    instruction = "Use for year-over-year transaction analysis"
  },
  {
    alias = "encounter_month"
    sql = "DATE_TRUNC('month', encounters.encounter_date)"
    display_name = "encounter month"
    comment = "Truncates encounter date to month"
    instruction = "Use for monthly encounter trend analysis"
  },
  {
    alias = "account_tier_group"
    sql = "CASE WHEN customers.account_tier = 'INSTITUTIONAL' THEN 'High Value' WHEN customers.account_tier = 'PRIVATE_BANKING' THEN 'Premium' ELSE 'Standard' END"
    display_name = "account tier group"
    comment = "Groups account tiers into simplified categories"
    instruction = "Use when user asks about customer segments or tiers"
  },
  {
    alias = "risk_category"
    sql = "CASE WHEN transactions.risk_score >= 70 THEN 'High Risk' WHEN transactions.risk_score >= 30 THEN 'Medium Risk' ELSE 'Low Risk' END"
    display_name = "risk category"
    comment = "Categorizes transactions by risk score ranges"
    instruction = "Use for risk-based transaction analysis"
  },
]

genie_sql_measures = [
  {
    alias = "total_transaction_amount"
    sql = "SUM(transactions.amount)"
    display_name = "total transaction amount"
    comment = "Sum of all transaction amounts"
    instruction = "Use for revenue, total amount, or transaction volume calculations"
  },
  {
    alias = "avg_credit_limit"
    sql = "AVG(credit_cards.credit_limit)"
    display_name = "average credit limit"
    comment = "Average credit limit across cards"
    instruction = "Use when asked about credit limits or card capacity"
  },
  {
    alias = "total_billed_amount"
    sql = "SUM(encounters.billed_amount)"
    display_name = "total billed amount"
    comment = "Sum of all encounter billing amounts"
    instruction = "Use for healthcare revenue or billing calculations"
  },
  {
    alias = "avg_risk_score"
    sql = "AVG(transactions.risk_score)"
    display_name = "average risk score"
    comment = "Average AML risk score across transactions"
    instruction = "Use when asked about risk scores or risk analysis"
  },
  {
    alias = "avg_length_of_stay"
    sql = "AVG(encounters.length_of_stay_days)"
    display_name = "average length of stay"
    comment = "Average days for inpatient encounters"
    instruction = "Use for inpatient stay duration analysis"
  },
]

genie_join_specs = [
  {
    left_table = "dev_fin.finance.transactions"
    left_alias = "transactions"
    right_table = "dev_fin.finance.customers"
    right_alias = "customers"
    sql = "transactions.customer_id = customers.customer_id"
    comment = "Join transactions to customers on customer_id"
    instruction = "Use when you need customer details for transaction queries"
  },
  {
    left_table = "dev_fin.finance.credit_cards"
    left_alias = "credit_cards"
    right_table = "dev_fin.finance.customers"
    right_alias = "customers"
    sql = "credit_cards.customer_id = customers.customer_id"
    comment = "Join credit cards to customers on customer_id"
    instruction = "Use when you need customer context for credit card analysis"
  },
  {
    left_table = "dev_clinical.clinical.encounters"
    left_alias = "encounters"
    right_table = "dev_clinical.clinical.patients"
    right_alias = "patients"
    sql = "encounters.patient_id = patients.patient_id"
    comment = "Join encounters to patients on patient_id"
    instruction = "Use when you need patient demographics for encounter analysis"
  },
]
