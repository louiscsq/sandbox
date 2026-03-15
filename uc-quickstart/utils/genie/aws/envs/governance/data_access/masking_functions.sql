-- ============================================================================
-- GENERATED MASKING FUNCTIONS (FIRST DRAFT)
-- ============================================================================
-- Target(s): dev_fin.finance, dev_clinical.clinical
-- Next: review generated/TUNING.md, tune if needed, then run this SQL.
-- ============================================================================

-- === dev_fin.finance functions ===
USE CATALOG dev_fin;
USE SCHEMA finance;

CREATE OR REPLACE FUNCTION mask_pii_partial(input STRING)
RETURNS STRING
COMMENT 'Masks middle characters, keeps first and last visible'
RETURN CASE 
  WHEN input IS NULL OR LENGTH(input) <= 2 THEN input
  WHEN LENGTH(input) = 3 THEN CONCAT(SUBSTRING(input, 1, 1), '*', SUBSTRING(input, 3, 1))
  ELSE CONCAT(SUBSTRING(input, 1, 1), REPEAT('*', LENGTH(input) - 2), SUBSTRING(input, -1, 1))
END;

CREATE OR REPLACE FUNCTION mask_ssn(ssn STRING)
RETURNS STRING
COMMENT 'Masks SSN showing only last 4 digits'
RETURN CASE 
  WHEN ssn IS NULL THEN NULL
  WHEN RLIKE(ssn, '^\\d{3}-\\d{2}-\\d{4}$') THEN CONCAT('***-**-', SUBSTRING(ssn, -4, 4))
  WHEN RLIKE(ssn, '^\\d{9}$') THEN CONCAT('*****', SUBSTRING(ssn, -4, 4))
  ELSE ssn
END;

CREATE OR REPLACE FUNCTION mask_email(email STRING)
RETURNS STRING
COMMENT 'Masks local part of email, keeps domain visible'
RETURN CASE 
  WHEN email IS NULL THEN NULL
  WHEN RLIKE(email, '^[^@]+@[^@]+\\.[^@]+$') THEN 
    CONCAT(REPEAT('*', LENGTH(SUBSTRING_INDEX(email, '@', 1))), '@', SUBSTRING_INDEX(email, '@', -1))
  ELSE email
END;

CREATE OR REPLACE FUNCTION mask_phone(phone STRING)
RETURNS STRING
COMMENT 'Masks phone number showing only last 4 digits'
RETURN CASE 
  WHEN phone IS NULL THEN NULL
  WHEN RLIKE(phone, '^\\(?\\d{3}\\)?[\\s.-]?\\d{3}[\\s.-]?\\d{4}$') THEN 
    CONCAT('***-***-', RIGHT(REGEXP_REPLACE(phone, '[^0-9]', ''), 4))
  ELSE phone
END;

CREATE OR REPLACE FUNCTION mask_date_to_year(dt DATE)
RETURNS DATE
COMMENT 'Rounds date to January 1st of the same year'
RETURN CASE 
  WHEN dt IS NULL THEN NULL
  ELSE DATE(CONCAT(YEAR(dt), '-01-01'))
END;

CREATE OR REPLACE FUNCTION mask_credit_card_full(card_number STRING)
RETURNS STRING
COMMENT 'Fully masks credit card number'
RETURN CASE 
  WHEN card_number IS NULL THEN NULL
  WHEN RLIKE(card_number, '^\\d{13,19}$') THEN REPEAT('*', LENGTH(card_number))
  ELSE '[REDACTED]'
END;

CREATE OR REPLACE FUNCTION mask_credit_card_last4(card_number STRING)
RETURNS STRING
COMMENT 'Masks credit card showing only last 4 digits'
RETURN CASE 
  WHEN card_number IS NULL THEN NULL
  WHEN RLIKE(card_number, '^\\d{13,19}$') THEN CONCAT(REPEAT('*', LENGTH(card_number) - 4), RIGHT(card_number, 4))
  ELSE '[REDACTED]'
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
COMMENT 'Rounds financial amounts to nearest 100'
RETURN CASE 
  WHEN amount IS NULL THEN NULL
  ELSE ROUND(amount, -2)
END;

CREATE OR REPLACE FUNCTION filter_aml_compliance_only()
RETURNS BOOLEAN
COMMENT 'Only members of AML_Compliance can see AML-flagged transactions'
RETURN is_account_group_member('AML_Compliance');

-- === dev_clinical.clinical functions ===
USE CATALOG dev_clinical;
USE SCHEMA clinical;

CREATE OR REPLACE FUNCTION mask_pii_partial(input STRING)
RETURNS STRING
COMMENT 'Masks middle characters, keeps first and last visible'
RETURN CASE 
  WHEN input IS NULL OR LENGTH(input) <= 2 THEN input
  WHEN LENGTH(input) = 3 THEN CONCAT(SUBSTRING(input, 1, 1), '*', SUBSTRING(input, 3, 1))
  ELSE CONCAT(SUBSTRING(input, 1, 1), REPEAT('*', LENGTH(input) - 2), SUBSTRING(input, -1, 1))
END;

CREATE OR REPLACE FUNCTION mask_ssn(ssn STRING)
RETURNS STRING
COMMENT 'Masks SSN showing only last 4 digits'
RETURN CASE 
  WHEN ssn IS NULL THEN NULL
  WHEN RLIKE(ssn, '^\\d{3}-\\d{2}-\\d{4}$') THEN CONCAT('***-**-', SUBSTRING(ssn, -4, 4))
  WHEN RLIKE(ssn, '^\\d{9}$') THEN CONCAT('*****', SUBSTRING(ssn, -4, 4))
  ELSE ssn
END;

CREATE OR REPLACE FUNCTION mask_email(email STRING)
RETURNS STRING
COMMENT 'Masks local part of email, keeps domain visible'
RETURN CASE 
  WHEN email IS NULL THEN NULL
  WHEN RLIKE(email, '^[^@]+@[^@]+\\.[^@]+$') THEN 
    CONCAT(REPEAT('*', LENGTH(SUBSTRING_INDEX(email, '@', 1))), '@', SUBSTRING_INDEX(email, '@', -1))
  ELSE email
END;

CREATE OR REPLACE FUNCTION mask_phone(phone STRING)
RETURNS STRING
COMMENT 'Masks phone number showing only last 4 digits'
RETURN CASE 
  WHEN phone IS NULL THEN NULL
  WHEN RLIKE(phone, '^\\(?\\d{3}\\)?[\\s.-]?\\d{3}[\\s.-]?\\d{4}$') THEN 
    CONCAT('***-***-', RIGHT(REGEXP_REPLACE(phone, '[^0-9]', ''), 4))
  ELSE phone
END;

CREATE OR REPLACE FUNCTION mask_date_to_year(dt DATE)
RETURNS DATE
COMMENT 'Rounds date to January 1st of the same year'
RETURN CASE 
  WHEN dt IS NULL THEN NULL
  ELSE DATE(CONCAT(YEAR(dt), '-01-01'))
END;

CREATE OR REPLACE FUNCTION mask_redact(input STRING)
RETURNS STRING
COMMENT 'Replaces input with [REDACTED]'
RETURN CASE 
  WHEN input IS NULL THEN NULL
  ELSE '[REDACTED]'
END;

CREATE OR REPLACE FUNCTION mask_diagnosis_code(code STRING)
RETURNS STRING
COMMENT 'Masks ICD-10 code to show only category (first 3 chars)'
RETURN CASE 
  WHEN code IS NULL THEN NULL
  WHEN RLIKE(code, '^[A-Z]\\d{2}') THEN CONCAT(SUBSTRING(code, 1, 3), '.*')
  ELSE '[REDACTED]'
END;
