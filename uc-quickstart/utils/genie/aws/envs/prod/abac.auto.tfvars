# ============================================================================
# WORKSPACE-OWNED ABAC CONFIG
# ============================================================================
# Generated from the workspace draft for this environment only.
# Owns workspace lookups/ACLs and Genie config only.
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

genie_space_title = "Financial Services & Healthcare Analytics"

genie_space_description = "Comprehensive analytics platform for financial transactions, customer data, AML compliance, and patient encounter records. Designed for analysts, compliance officers, and clinical staff with appropriate data governance controls."

genie_sample_questions = ["What is the total transaction volume for active customers this quarter?", "Show me the top 10 accounts by balance for checking accounts", "How many AML alerts are currently under review?", "What is the average risk score for customers in the US region?", "Which credit card types have the highest utilization rates?", "How many patient encounters occurred last month by encounter type?", "What are the most common diagnosis codes in our clinical data?", "Show trading positions with the highest P&L for the equity desk", "Which customers have had the most interactions this year?", "What percentage of transactions are flagged as high-risk?"]

genie_instructions = "When asked about 'customers' without a status qualifier, default to active customers (CustomerStatus = 'Active'). When asked about 'transactions' without specifying status, default to completed transactions (TransactionStatus = 'Completed'). When asked about 'accounts' without status, default to active accounts (AccountStatus = 'Active'). When asked about 'AML alerts' without status, default to active investigations (InvestigationStatus IN ('New', 'Under Review', 'Escalated')). For trading positions, default to open positions (PositionStatus = 'Open') unless specified otherwise. 'Last month' means the previous calendar month. Round monetary values to 2 decimal places. Patient and customer names are masked for non-clinical/non-compliance roles. Queries about aggregate counts, dates, and non-PII fields are always allowed."

genie_benchmarks = [
  {
    question = "What is the total balance of all active checking accounts?"
    sql = "SELECT SUM(Balance) as total_balance FROM sydney_louis_prod.finance.accounts WHERE AccountStatus = 'Active' AND AccountType = 'Checking'"
  },
  {
    question = "How many completed transactions occurred last month?"
    sql = "SELECT COUNT(*) as transaction_count FROM sydney_louis_prod.finance.transactions WHERE TransactionStatus = 'Completed' AND TransactionDate >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL 1 MONTH) AND TransactionDate < DATE_TRUNC('month', CURRENT_DATE)"
  },
  {
    question = "What is the average risk score for active customers?"
    sql = "SELECT AVG(RiskScore) as avg_risk_score FROM sydney_louis_prod.finance.customers WHERE CustomerStatus = 'Active'"
  },
  {
    question = "How many patient encounters were inpatient visits this year?"
    sql = "SELECT COUNT(*) as inpatient_encounters FROM sydney_louis_prod.clinical.encounters WHERE EncounterType = 'INPATIENT' AND YEAR(EncounterDate) = YEAR(CURRENT_DATE)"
  },
  {
    question = "What is the total credit limit across all active credit cards?"
    sql = "SELECT SUM(CreditLimit) as total_credit_limit FROM sydney_louis_prod.finance.creditcards WHERE CardStatus = 'Active'"
  },
]

genie_sql_filters = [
  {
    sql = "customers.CustomerStatus = 'Active'"
    display_name = "active customers"
    comment = "Only include customers with Active status"
    instruction = "Apply when the user asks about customers without specifying a status"
  },
  {
    sql = "transactions.TransactionStatus = 'Completed'"
    display_name = "completed transactions"
    comment = "Only include completed transactions"
    instruction = "Apply when the user asks about transactions or amounts without specifying a status"
  },
  {
    sql = "accounts.AccountStatus = 'Active'"
    display_name = "active accounts"
    comment = "Only include accounts with Active status"
    instruction = "Apply when the user asks about accounts without specifying a status"
  },
  {
    sql = "amlalerts.InvestigationStatus IN ('New', 'Under Review', 'Escalated')"
    display_name = "active AML investigations"
    comment = "Only include AML alerts that are actively being investigated"
    instruction = "Apply when the user asks about AML alerts without specifying investigation status"
  },
  {
    sql = "tradingpositions.PositionStatus = 'Open'"
    display_name = "open trading positions"
    comment = "Only include currently open trading positions"
    instruction = "Apply when the user asks about trading positions without specifying position status"
  },
]

genie_sql_expressions = [
  {
    alias = "transaction_year"
    sql = "YEAR(transactions.TransactionDate)"
    display_name = "transaction year"
    comment = "Extracts year from transaction date"
    instruction = "Use for year-over-year analysis of transactions"
  },
  {
    alias = "transaction_month"
    sql = "DATE_TRUNC('month', transactions.TransactionDate)"
    display_name = "transaction month"
    comment = "Truncates transaction date to month"
    instruction = "Use for monthly transaction analysis"
  },
  {
    alias = "customer_region_group"
    sql = "CASE WHEN customers.CustomerRegion IN ('US') THEN 'Domestic' ELSE 'International' END"
    display_name = "customer region group"
    comment = "Groups customers into domestic vs international"
    instruction = "Use for domestic vs international customer analysis"
  },
  {
    alias = "high_risk_flag"
    sql = "CASE WHEN customers.RiskScore >= 70 THEN 'High Risk' WHEN customers.RiskScore >= 40 THEN 'Medium Risk' ELSE 'Low Risk' END"
    display_name = "risk category"
    comment = "Categorizes customers by risk level"
    instruction = "Use for risk-based customer segmentation"
  },
  {
    alias = "encounter_year"
    sql = "YEAR(encounters.EncounterDate)"
    display_name = "encounter year"
    comment = "Extracts year from encounter date"
    instruction = "Use for year-over-year analysis of patient encounters"
  },
]

genie_sql_measures = [
  {
    alias = "total_balance"
    sql = "SUM(accounts.Balance)"
    display_name = "total account balance"
    comment = "Sum of all account balances"
    instruction = "Use for total balance, account value, or portfolio calculations"
  },
  {
    alias = "total_transaction_amount"
    sql = "SUM(transactions.Amount)"
    display_name = "total transaction amount"
    comment = "Sum of all transaction amounts"
    instruction = "Use for transaction volume, total payments, or revenue calculations"
  },
  {
    alias = "avg_risk_score"
    sql = "AVG(customers.RiskScore)"
    display_name = "average risk score"
    comment = "Average AML risk score across customers"
    instruction = "Use when asked about risk scores or risk averages"
  },
  {
    alias = "total_credit_limit"
    sql = "SUM(creditcards.CreditLimit)"
    display_name = "total credit limit"
    comment = "Sum of all credit card limits"
    instruction = "Use for credit exposure or total available credit calculations"
  },
  {
    alias = "encounter_count"
    sql = "COUNT(encounters.EncounterID)"
    display_name = "encounter count"
    comment = "Count of patient encounters"
    instruction = "Use for patient volume or encounter frequency analysis"
  },
]

genie_join_specs = [
  {
    left_table = "sydney_louis_prod.finance.accounts"
    left_alias = "accounts"
    right_table = "sydney_louis_prod.finance.customers"
    right_alias = "customers"
    sql = "accounts.CustomerID = customers.CustomerID"
    comment = "Join accounts to customers on CustomerID"
    instruction = "Use when you need customer details for account queries"
  },
  {
    left_table = "sydney_louis_prod.finance.transactions"
    left_alias = "transactions"
    right_table = "sydney_louis_prod.finance.accounts"
    right_alias = "accounts"
    sql = "transactions.AccountID = accounts.AccountID"
    comment = "Join transactions to accounts on AccountID"
    instruction = "Use when you need account context for transactions"
  },
  {
    left_table = "sydney_louis_prod.finance.creditcards"
    left_alias = "creditcards"
    right_table = "sydney_louis_prod.finance.customers"
    right_alias = "customers"
    sql = "creditcards.CustomerID = customers.CustomerID"
    comment = "Join credit cards to customers on CustomerID"
    instruction = "Use when you need customer details for credit card queries"
  },
  {
    left_table = "sydney_louis_prod.finance.amlalerts"
    left_alias = "amlalerts"
    right_table = "sydney_louis_prod.finance.customers"
    right_alias = "customers"
    sql = "amlalerts.CustomerID = customers.CustomerID"
    comment = "Join AML alerts to customers on CustomerID"
    instruction = "Use when you need customer context for AML investigations"
  },
  {
    left_table = "sydney_louis_prod.finance.amlalerts"
    left_alias = "amlalerts"
    right_table = "sydney_louis_prod.finance.transactions"
    right_alias = "transactions"
    sql = "amlalerts.TransactionID = transactions.TransactionID"
    comment = "Join AML alerts to transactions on TransactionID"
    instruction = "Use when you need transaction details for AML alerts"
  },
  {
    left_table = "sydney_louis_prod.finance.customerinteractions"
    left_alias = "customerinteractions"
    right_table = "sydney_louis_prod.finance.customers"
    right_alias = "customers"
    sql = "customerinteractions.CustomerID = customers.CustomerID"
    comment = "Join customer interactions to customers on CustomerID"
    instruction = "Use when you need customer details for interaction analysis"
  },
]
