# ============================================================================
# WORKSPACE-OWNED ABAC CONFIG
# ============================================================================
# Generated from the workspace draft for this environment only.
# Owns workspace lookups/ACLs and Genie config only.
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

genie_space_title = "Financial Services & Clinical Analytics"

genie_space_description = "Comprehensive analytics platform for banking transactions, AML compliance, trading positions, and clinical encounters. Designed for financial analysts, compliance officers, and healthcare professionals."

genie_sample_questions = ["What is the total transaction volume by region for completed transactions last quarter?", "Show me the top 10 customers by account balance with active status", "How many AML alerts are currently under review?", "What is the average risk score for customers in the US region?", "How many patient encounters occurred last month by encounter type?", "Which trading desks have the highest P&L this month?", "Show me credit card transactions over $10,000 that are flagged", "What percentage of customers have completed KYC verification?", "How many audit log entries were created for regulatory reviews?", "What is the distribution of diagnosis codes by facility region?"]

genie_instructions = "When asked about 'customers' without status qualifier, default to active customers (CustomerStatus = 'Active'). When asked about 'transactions' without specifying status, default to completed transactions (TransactionStatus = 'Completed'). When asked about 'accounts' without qualifier, default to active accounts (AccountStatus = 'Active'). When asked about 'alerts' without status, default to active investigations (InvestigationStatus IN ('New', 'Under Review', 'Escalated')). 'Last month' means the previous calendar month. Round monetary values to 2 decimal places. Patient identifiers and clinical notes are masked for non-clinical roles. AML investigation details are restricted to compliance officers. Trading data access is limited during market hours for Chinese wall compliance."

genie_benchmarks = [
  {
    question = "What is the total amount of completed transactions?"
    sql = "SELECT SUM(Amount) as total_amount FROM louis_sydney.finance.transactions WHERE TransactionStatus = 'Completed'"
  },
  {
    question = "How many patient encounters occurred last month?"
    sql = "SELECT COUNT(*) FROM louis_sydney.clinical.encounters WHERE EncounterDate >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL 1 MONTH) AND EncounterDate < DATE_TRUNC('month', CURRENT_DATE)"
  },
  {
    question = "What is the average risk score for active customers?"
    sql = "SELECT AVG(RiskScore) as avg_risk_score FROM louis_sydney.finance.customers WHERE CustomerStatus = 'Active'"
  },
  {
    question = "How many AML alerts are under investigation?"
    sql = "SELECT COUNT(*) FROM louis_sydney.finance.amlalerts WHERE InvestigationStatus IN ('New', 'Under Review', 'Escalated')"
  },
  {
    question = "What is the total credit limit across all active credit cards?"
    sql = "SELECT SUM(CreditLimit) as total_credit_limit FROM louis_sydney.finance.creditcards WHERE CardStatus = 'Active'"
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
    comment = "Only include active accounts"
    instruction = "Apply when the user asks about accounts without specifying a status"
  },
  {
    sql = "amlalerts.InvestigationStatus IN ('New', 'Under Review', 'Escalated')"
    display_name = "active investigations"
    comment = "Only include alerts currently under investigation"
    instruction = "Apply when the user asks about AML alerts without specifying investigation status"
  },
]

genie_sql_expressions = [
  {
    alias = "transaction_year"
    sql = "YEAR(transactions.TransactionDate)"
    display_name = "transaction year"
    comment = "Extracts year from transaction date"
    instruction = "Use for year-over-year transaction analysis"
  },
  {
    alias = "encounter_month"
    sql = "DATE_TRUNC('month', encounters.EncounterDate)"
    display_name = "encounter month"
    comment = "Truncates encounter date to month"
    instruction = "Use for monthly clinical volume analysis"
  },
  {
    alias = "customer_age_group"
    sql = "CASE WHEN DATEDIFF(CURRENT_DATE(), customers.DateOfBirth) / 365 < 30 THEN 'Under 30' WHEN DATEDIFF(CURRENT_DATE(), customers.DateOfBirth) / 365 < 50 THEN '30-49' WHEN DATEDIFF(CURRENT_DATE(), customers.DateOfBirth) / 365 < 65 THEN '50-64' ELSE '65+' END"
    display_name = "customer age group"
    comment = "Categorizes customers into age brackets"
    instruction = "Use for demographic analysis and age-based segmentation"
  },
  {
    alias = "high_risk_transaction"
    sql = "transactions.ExceedsHighRiskThreshold = TRUE OR transactions.IsInternational = TRUE"
    display_name = "high risk transaction flag"
    comment = "Identifies transactions requiring enhanced monitoring"
    instruction = "Use for AML and compliance risk analysis"
  },
]

genie_sql_measures = [
  {
    alias = "total_transaction_amount"
    sql = "SUM(transactions.Amount)"
    display_name = "total transaction amount"
    comment = "Sum of all transaction amounts"
    instruction = "Use for transaction volume, total amount, or revenue calculations"
  },
  {
    alias = "avg_risk_score"
    sql = "AVG(customers.RiskScore)"
    display_name = "average risk score"
    comment = "Average AML risk score across customers"
    instruction = "Use when asked about risk scores or risk averages"
  },
  {
    alias = "total_account_balance"
    sql = "SUM(accounts.Balance)"
    display_name = "total account balance"
    comment = "Sum of all account balances"
    instruction = "Use for total deposits, account value calculations"
  },
  {
    alias = "avg_credit_limit"
    sql = "AVG(creditcards.CreditLimit)"
    display_name = "average credit limit"
    comment = "Average credit limit across cards"
    instruction = "Use for credit analysis and limit calculations"
  },
  {
    alias = "total_pnl"
    sql = "SUM(tradingpositions.PnL)"
    display_name = "total profit and loss"
    comment = "Sum of P&L across trading positions"
    instruction = "Use for trading performance and profitability analysis"
  },
]

genie_join_specs = [
  {
    left_table = "louis_sydney.finance.transactions"
    left_alias = "transactions"
    right_table = "louis_sydney.finance.accounts"
    right_alias = "accounts"
    sql = "transactions.AccountID = accounts.AccountID"
    comment = "Join transactions to accounts on AccountID"
    instruction = "Use when you need account details for transaction queries"
  },
  {
    left_table = "louis_sydney.finance.accounts"
    left_alias = "accounts"
    right_table = "louis_sydney.finance.customers"
    right_alias = "customers"
    sql = "accounts.CustomerID = customers.CustomerID"
    comment = "Join accounts to customers on CustomerID"
    instruction = "Use when you need customer details for account queries"
  },
  {
    left_table = "louis_sydney.finance.amlalerts"
    left_alias = "amlalerts"
    right_table = "louis_sydney.finance.customers"
    right_alias = "customers"
    sql = "amlalerts.CustomerID = customers.CustomerID"
    comment = "Join AML alerts to customers on CustomerID"
    instruction = "Use when you need customer context for AML investigations"
  },
  {
    left_table = "louis_sydney.finance.creditcards"
    left_alias = "creditcards"
    right_table = "louis_sydney.finance.customers"
    right_alias = "customers"
    sql = "creditcards.CustomerID = customers.CustomerID"
    comment = "Join credit cards to customers on CustomerID"
    instruction = "Use when you need customer details for credit card analysis"
  },
  {
    left_table = "louis_sydney.finance.amlalerts"
    left_alias = "amlalerts"
    right_table = "louis_sydney.finance.transactions"
    right_alias = "transactions"
    sql = "amlalerts.TransactionID = transactions.TransactionID"
    comment = "Join AML alerts to transactions on TransactionID"
    instruction = "Use when you need transaction details for AML alert analysis"
  },
]
