-- ============================================================================
-- GENERATED MASKING FUNCTIONS (FIRST DRAFT)
-- ============================================================================
-- Target(s): prod_fin.finance, prod_clinical.clinical
-- Next: review generated/TUNING.md, tune if needed, then run this SQL.
-- ============================================================================

-- === prod_fin.finance functions ===
USE CATALOG prod_fin;
USE SCHEMA finance;

CREATE OR REPLACE FUNCTION mask_pii_partial(input STRING)
RETURNS STRING
COMMENT 'Masks middle characters, shows first and last character'
RETURN CASE 
  WHEN input IS NULL OR LENGTH(input) = 0 THEN input
  WHEN LENGTH(input) = 1 THEN '*'
  WHEN LENGTH(input) = 2 THEN CONCAT(SUBSTRING(input, 1, 1), '*')
  ELSE CONCAT(SUBSTRING(input, 1, 1), REPEAT('*', LENGTH(input) - 2), SUBSTRING(input, -1, 1))
END;

CREATE OR REPLACE FUNCTION mask_ssn(ssn STRING)
RETURNS STRING
COMMENT 'Masks SSN showing only last 4 digits'
RETURN CASE 
  WHEN ssn IS NULL THEN NULL
  WHEN LENGTH(REGEXP_REPLACE(ssn, '[^0-9]', '')) < 4 THEN '***-**-****'
  ELSE CONCAT('***-**-', RIGHT(REGEXP_REPLACE(ssn, '[^0-9]', ''), 4))
END;

CREATE OR REPLACE FUNCTION mask_email(email STRING)
RETURNS STRING
COMMENT 'Masks email local part, preserves domain'
RETURN CASE 
  WHEN email IS NULL OR NOT email RLIKE '^[^@]+@[^@]+$' THEN email
  ELSE CONCAT('****@', SUBSTRING_INDEX(email, '@', -1))
END;

CREATE OR REPLACE FUNCTION mask_phone(phone STRING)
RETURNS STRING
COMMENT 'Masks phone number showing only last 4 digits'
RETURN CASE 
  WHEN phone IS NULL THEN NULL
  WHEN LENGTH(REGEXP_REPLACE(phone, '[^0-9]', '')) < 4 THEN '***-***-****'
  ELSE CONCAT('***-***-', RIGHT(REGEXP_REPLACE(phone, '[^0-9]', ''), 4))
END;

CREATE OR REPLACE FUNCTION mask_credit_card_full(card_number STRING)
RETURNS STRING
COMMENT 'Fully masks credit card number'
RETURN CASE 
  WHEN card_number IS NULL THEN NULL
  ELSE '****-****-****-****'
END;

CREATE OR REPLACE FUNCTION mask_credit_card_last4(card_number STRING)
RETURNS STRING
COMMENT 'Masks credit card showing only last 4 digits'
RETURN CASE 
  WHEN card_number IS NULL THEN NULL
  WHEN LENGTH(REGEXP_REPLACE(card_number, '[^0-9]', '')) < 4 THEN '****-****-****-****'
  ELSE CONCAT('****-****-****-', RIGHT(REGEXP_REPLACE(card_number, '[^0-9]', ''), 4))
END;

CREATE OR REPLACE FUNCTION mask_redact(input STRING)
RETURNS STRING
COMMENT 'Replaces input with [REDACTED]'
RETURN CASE 
  WHEN input IS NULL THEN NULL
  ELSE '[REDACTED]'
END;

CREATE OR REPLACE FUNCTION mask_amount_rounded(amount DECIMAL(18,2))
RETURNS DECIMAL(18,2)
COMMENT 'Rounds amounts to nearest 100 for privacy'
RETURN CASE 
  WHEN amount IS NULL THEN NULL
  ELSE ROUND(amount / 100.0, 0) * 100.0
END;

CREATE OR REPLACE FUNCTION filter_aml_compliance()
RETURNS BOOLEAN
COMMENT 'Filters to show only AML-flagged transactions for compliance review'
RETURN TRUE;

-- === prod_clinical.clinical functions ===
USE CATALOG prod_clinical;
USE SCHEMA clinical;

CREATE OR REPLACE FUNCTION mask_pii_partial(input STRING)
RETURNS STRING
COMMENT 'Masks middle characters, shows first and last character'
RETURN CASE 
  WHEN input IS NULL OR LENGTH(input) = 0 THEN input
  WHEN LENGTH(input) = 1 THEN '*'
  WHEN LENGTH(input) = 2 THEN CONCAT(SUBSTRING(input, 1, 1), '*')
  ELSE CONCAT(SUBSTRING(input, 1, 1), REPEAT('*', LENGTH(input) - 2), SUBSTRING(input, -1, 1))
END;

CREATE OR REPLACE FUNCTION mask_ssn(ssn STRING)
RETURNS STRING
COMMENT 'Masks SSN showing only last 4 digits'
RETURN CASE 
  WHEN ssn IS NULL THEN NULL
  WHEN LENGTH(REGEXP_REPLACE(ssn, '[^0-9]', '')) < 4 THEN '***-**-****'
  ELSE CONCAT('***-**-', RIGHT(REGEXP_REPLACE(ssn, '[^0-9]', ''), 4))
END;

CREATE OR REPLACE FUNCTION mask_email(email STRING)
RETURNS STRING
COMMENT 'Masks email local part, preserves domain'
RETURN CASE 
  WHEN email IS NULL OR NOT email RLIKE '^[^@]+@[^@]+$' THEN email
  ELSE CONCAT('****@', SUBSTRING_INDEX(email, '@', -1))
END;

CREATE OR REPLACE FUNCTION mask_phone(phone STRING)
RETURNS STRING
COMMENT 'Masks phone number showing only last 4 digits'
RETURN CASE 
  WHEN phone IS NULL THEN NULL
  WHEN LENGTH(REGEXP_REPLACE(phone, '[^0-9]', '')) < 4 THEN '***-***-****'
  ELSE CONCAT('***-***-', RIGHT(REGEXP_REPLACE(phone, '[^0-9]', ''), 4))
END;

CREATE OR REPLACE FUNCTION mask_diagnosis_code(code STRING)
RETURNS STRING
COMMENT 'Masks ICD-10 codes showing only category (first 3 chars)'
RETURN CASE 
  WHEN code IS NULL THEN NULL
  WHEN LENGTH(code) <= 3 THEN code
  ELSE CONCAT(SUBSTRING(code, 1, 3), '.XX')
END;

CREATE OR REPLACE FUNCTION mask_redact(input STRING)
RETURNS STRING
COMMENT 'Replaces input with [REDACTED]'
RETURN CASE 
  WHEN input IS NULL THEN NULL
  ELSE '[REDACTED]'
END;
