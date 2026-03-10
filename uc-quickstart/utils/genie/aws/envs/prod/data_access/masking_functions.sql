-- ============================================================================
-- GENERATED MASKING FUNCTIONS (FIRST DRAFT)
-- ============================================================================
-- Target(s): sydney_louis_prod.clinical, sydney_louis_prod.finance
-- Next: review generated/TUNING.md, tune if needed, then run this SQL.
-- ============================================================================

-- === sydney_louis_prod.clinical functions ===
USE CATALOG sydney_louis_prod;
USE SCHEMA clinical;

CREATE OR REPLACE FUNCTION mask_pii_partial(input STRING)
RETURNS STRING
COMMENT 'Masks middle characters, shows first and last character'
RETURN CASE 
  WHEN input IS NULL OR LENGTH(input) <= 2 THEN input
  WHEN LENGTH(input) = 3 THEN CONCAT(LEFT(input, 1), '*', RIGHT(input, 1))
  ELSE CONCAT(LEFT(input, 1), REPEAT('*', LENGTH(input) - 2), RIGHT(input, 1))
END;

CREATE OR REPLACE FUNCTION mask_diagnosis_code(code STRING)
RETURNS STRING
COMMENT 'Shows ICD category (first 3 chars), masks specific diagnosis'
RETURN CASE 
  WHEN code IS NULL THEN NULL
  WHEN LENGTH(code) <= 3 THEN code
  ELSE CONCAT(LEFT(code, 3), REPEAT('*', LENGTH(code) - 3))
END;

CREATE OR REPLACE FUNCTION mask_redact(input STRING)
RETURNS STRING
COMMENT 'Replaces sensitive content with [REDACTED]'
RETURN CASE 
  WHEN input IS NULL THEN NULL
  ELSE '[REDACTED]'
END;

CREATE OR REPLACE FUNCTION filter_by_region_us()
RETURNS BOOLEAN
COMMENT 'Filters rows to show only US region data'
RETURN TRUE;

CREATE OR REPLACE FUNCTION filter_by_region_eu()
RETURNS BOOLEAN
COMMENT 'Filters rows to show only EU region data'
RETURN TRUE;

-- === sydney_louis_prod.finance functions ===
USE CATALOG sydney_louis_prod;
USE SCHEMA finance;

CREATE OR REPLACE FUNCTION mask_pii_partial(input STRING)
RETURNS STRING
COMMENT 'Masks middle characters, shows first and last character'
RETURN CASE 
  WHEN input IS NULL OR LENGTH(input) <= 2 THEN input
  WHEN LENGTH(input) = 3 THEN CONCAT(LEFT(input, 1), '*', RIGHT(input, 1))
  ELSE CONCAT(LEFT(input, 1), REPEAT('*', LENGTH(input) - 2), RIGHT(input, 1))
END;

CREATE OR REPLACE FUNCTION mask_email(email STRING)
RETURNS STRING
COMMENT 'Masks local part of email, keeps domain visible'
RETURN CASE 
  WHEN email IS NULL THEN NULL
  WHEN INSTR(email, '@') = 0 THEN CONCAT(REPEAT('*', LENGTH(email)))
  ELSE CONCAT(REPEAT('*', INSTR(email, '@') - 1), SUBSTRING(email, INSTR(email, '@')))
END;

CREATE OR REPLACE FUNCTION mask_ssn(ssn STRING)
RETURNS STRING
COMMENT 'Shows last 4 digits of SSN, masks the rest'
RETURN CASE 
  WHEN ssn IS NULL THEN NULL
  WHEN LENGTH(REGEXP_REPLACE(ssn, '[^0-9]', '')) < 4 THEN REPEAT('*', LENGTH(ssn))
  ELSE CONCAT('***-**-', RIGHT(REGEXP_REPLACE(ssn, '[^0-9]', ''), 4))
END;

CREATE OR REPLACE FUNCTION mask_credit_card_full(card_number STRING)
RETURNS STRING
COMMENT 'Completely masks credit card number'
RETURN CASE 
  WHEN card_number IS NULL THEN NULL
  ELSE REPEAT('*', LENGTH(card_number))
END;

CREATE OR REPLACE FUNCTION mask_credit_card_last4(card_number STRING)
RETURNS STRING
COMMENT 'Shows last 4 digits of credit card, masks the rest'
RETURN CASE 
  WHEN card_number IS NULL THEN NULL
  WHEN LENGTH(REGEXP_REPLACE(card_number, '[^0-9]', '')) < 4 THEN REPEAT('*', LENGTH(card_number))
  ELSE CONCAT(REPEAT('*', LENGTH(card_number) - 4), RIGHT(REGEXP_REPLACE(card_number, '[^0-9]', ''), 4))
END;

CREATE OR REPLACE FUNCTION mask_account_number(account_id STRING)
RETURNS STRING
COMMENT 'Returns deterministic SHA-256 hash token for account numbers'
RETURN CASE 
  WHEN account_id IS NULL THEN NULL
  ELSE SHA2(account_id, 256)
END;

CREATE OR REPLACE FUNCTION mask_amount_rounded(amount DECIMAL(18,2))
RETURNS DECIMAL(18,2)
COMMENT 'Rounds monetary amounts to nearest 100 for privacy'
RETURN CASE 
  WHEN amount IS NULL THEN NULL
  ELSE ROUND(amount, -2)
END;

CREATE OR REPLACE FUNCTION mask_redact(input STRING)
RETURNS STRING
COMMENT 'Replaces sensitive content with [REDACTED]'
RETURN CASE 
  WHEN input IS NULL THEN NULL
  ELSE '[REDACTED]'
END;

CREATE OR REPLACE FUNCTION mask_nullify(input STRING)
RETURNS STRING
COMMENT 'Returns NULL to completely hide sensitive data'
RETURN CAST(NULL AS STRING);

CREATE OR REPLACE FUNCTION filter_by_region_us()
RETURNS BOOLEAN
COMMENT 'Filters rows to show only US region data'
RETURN TRUE;

CREATE OR REPLACE FUNCTION filter_by_region_eu()
RETURNS BOOLEAN
COMMENT 'Filters rows to show only EU region data'
RETURN TRUE;

CREATE OR REPLACE FUNCTION filter_trading_hours()
RETURNS BOOLEAN
COMMENT 'Restricts access to non-market hours (before 9 AM or after 4 PM)'
RETURN HOUR(NOW()) < 9 OR HOUR(NOW()) > 16;

CREATE OR REPLACE FUNCTION filter_audit_expiry()
RETURNS BOOLEAN
COMMENT 'Time-limited access for audit purposes'
RETURN CURRENT_DATE() <= DATE('2025-12-31');
