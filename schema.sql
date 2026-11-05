-- Clean up existing tables if re-running (reverse order of dependencies)

-- DROP PROCEDURE IF EXISTS sp_atm_withdraw_cash;
-- DROP VIEW IF EXISTS v_failed_security_audits;
-- DROP VIEW IF EXISTS v_high_value_transfers;
-- DROP VIEW IF EXISTS v_account_overview;
-- DROP TABLE IF EXISTS transaction CASCADE;
-- DROP TABLE IF EXISTS card_security CASCADE;
-- DROP TABLE IF EXISTS card CASCADE;
-- DROP TABLE IF EXISTS account CASCADE;
-- DROP TABLE IF EXISTS services CASCADE;
-- DROP TABLE IF EXISTS address CASCADE;
-- DROP TABLE IF EXISTS atm CASCADE;
-- DROP TABLE IF EXISTS branch CASCADE;
-- DROP TABLE IF EXISTS customer CASCADE;


-- 1. CUSTOMER TABLE
CREATE TABLE customer (
    customer_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    firstname VARCHAR(50) NOT NULL,
    lastname VARCHAR(50),
    dob DATE NOT NULL,
    age INT NOT NULL DEFAULT 0,
    phone_number VARCHAR(15) NOT NULL,
    email VARCHAR(100) NOT NULL UNIQUE,
    gender VARCHAR(10) CHECK (gender IN ('Male', 'Female', 'Other'))
);

-- 2. ADDRESS TABLE (Multi-valued attribute decomposition)
CREATE TABLE address (
    customer_id BIGINT NOT NULL,
    address TEXT NOT NULL,
    CONSTRAINT pk_customer_address PRIMARY KEY (customer_id, address),
    CONSTRAINT fk_address_customer 
        FOREIGN KEY (customer_id)
        REFERENCES customer (customer_id)
        ON DELETE CASCADE
);

-- 3. BRANCH TABLE
CREATE TABLE branch (
    branch_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ifsc_code VARCHAR(11) NOT NULL UNIQUE,
    branch_name VARCHAR(100) NOT NULL,
    address TEXT NOT NULL,
    pin_code VARCHAR(10) NOT NULL
);

-- 4. SERVICES TABLE (M:N Relationship between Customer and Branch)
CREATE TABLE services (
    customer_id BIGINT NOT NULL,
    branch_id INT NOT NULL,
    CONSTRAINT pk_services PRIMARY KEY (customer_id, branch_id),
    CONSTRAINT fk_services_customer 
        FOREIGN KEY (customer_id) 
        REFERENCES customer (customer_id) 
        ON DELETE CASCADE,
    CONSTRAINT fk_services_branch 
        FOREIGN KEY (branch_id) 
        REFERENCES branch (branch_id) 
        ON DELETE CASCADE
);

-- 5. ACCOUNT TABLE
CREATE TABLE account (
    account_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_number VARCHAR(20) NOT NULL UNIQUE,
    account_type VARCHAR(20) NOT NULL CHECK (account_type IN ('SAVINGS', 'CURRENT', 'SALARY', 'FIXED_DEPOSIT')),
    balance NUMERIC(15, 2) NOT NULL DEFAULT 0.00 CHECK (balance >= 0.00),
    status VARCHAR(15) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE', 'DORMANT', 'FROZEN', 'CLOSED')),
    date_time TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    customer_id BIGINT NOT NULL,
    branch_id INT NOT NULL,
    CONSTRAINT fk_account_customer 
        FOREIGN KEY (customer_id) 
        REFERENCES customer (customer_id) 
        ON DELETE RESTRICT,
    CONSTRAINT fk_account_branch 
        FOREIGN KEY (branch_id) 
        REFERENCES branch (branch_id) 
        ON DELETE RESTRICT
);

-- 6. ATM TABLE
CREATE TABLE atm (
    atm_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    terminal_code VARCHAR(20) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'OPERATIONAL' CHECK (status IN ('OPERATIONAL', 'OUT_OF_SERVICE', 'MAINTENANCE')),
    current_balance NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (current_balance >= 0.00),
    atm_location TEXT NOT NULL
);

-- 7. CARD TABLE
CREATE TABLE card (
    card_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    card_number VARCHAR(19) NOT NULL UNIQUE,
    card_type VARCHAR(20) NOT NULL CHECK (card_type IN ('DEBIT', 'CREDIT')),
    status VARCHAR(15) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'BLOCKED', 'EXPIRED')),
    failed_pin_attempts INT NOT NULL DEFAULT 0 CHECK (failed_pin_attempts >= 0),
    expiry_date DATE NOT NULL,
    account_id BIGINT NOT NULL,
    CONSTRAINT fk_card_account 
        FOREIGN KEY (account_id) 
        REFERENCES account (account_id) 
        ON DELETE RESTRICT
);

-- 8. CARD_SECURITY TABLE (1:1 Relationship with CARD)
CREATE TABLE card_security (
    card_id BIGINT PRIMARY KEY,
    pin_hash VARCHAR(255) NOT NULL,
    CONSTRAINT fk_security_card 
        FOREIGN KEY (card_id) 
        REFERENCES card (card_id) 
        ON DELETE CASCADE
);

-- 9. TRANSACTION TABLE
CREATE TABLE transaction (
    transaction_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transaction_type VARCHAR(20) NOT NULL CHECK (transaction_type IN ('WITHDRAWAL', 'DEPOSIT', 'BALANCE_INQUIRY')),
    amount NUMERIC(12, 2) NOT NULL CHECK (amount >= 0.00),
    transaction_method VARCHAR(20) NOT NULL DEFAULT 'ATM' CHECK (transaction_method IN ('ATM', 'ONLINE', 'POS', 'BRANCH')),
    date_time TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    account_id BIGINT NOT NULL,
    card_id BIGINT,
    atm_id INT,
    CONSTRAINT fk_transaction_account 
        FOREIGN KEY (account_id) 
        REFERENCES account (account_id) 
        ON DELETE RESTRICT,
    CONSTRAINT fk_transaction_card 
        FOREIGN KEY (card_id) 
        REFERENCES card (card_id) 
        ON DELETE SET NULL,
    CONSTRAINT fk_transaction_atm 
        FOREIGN KEY (atm_id) 
        REFERENCES atm (atm_id) 
        ON DELETE SET NULL
);

-- PERFORMANCE INDEXES (Foreign Key & Query Targets)
CREATE INDEX idx_account_customer_id ON account (customer_id);
CREATE INDEX idx_account_branch_id ON account (branch_id);
CREATE INDEX idx_card_account_id ON card (account_id);
CREATE INDEX idx_transaction_account_id ON transaction (account_id);
CREATE INDEX idx_transaction_card_id ON transaction (card_id);
CREATE INDEX idx_transaction_atm_id ON transaction (atm_id);
CREATE INDEX idx_transaction_date_time ON transaction (date_time DESC);

--Trigger 1: trg_set_customer_age (age calculator)
CREATE OR REPLACE FUNCTION fn_set_customer_age()
RETURNS TRIGGER AS $$
BEGIN
    -- Built-in age() returns an interval; EXTRACT gets full years completed
    NEW.age := EXTRACT(YEAR FROM age(CURRENT_DATE, NEW.dob))::INT;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_set_customer_age
BEFORE INSERT OR UPDATE OF dob ON customer
FOR EACH ROW
EXECUTE FUNCTION fn_set_customer_age();

--Trigger 2: trg_audit_balance_change (Automated Ledger Logging)
CREATE OR REPLACE FUNCTION fn_audit_balance_change()
RETURNS TRIGGER AS $$
DECLARE
    v_diff NUMERIC(15, 2);
    v_tx_type VARCHAR(20);
    v_card_id BIGINT;
    v_atm_id INT;
BEGIN
    -- Only log when balance actually changes
    IF NEW.balance <> OLD.balance THEN
        v_diff := NEW.balance - OLD.balance;
        
        IF v_diff > 0 THEN
            v_tx_type := 'DEPOSIT';
        ELSE
            v_tx_type := 'WITHDRAWAL';
        END IF;

        -- 1. Lookup an ACTIVE card belonging to this account
        SELECT card_id INTO v_card_id
        FROM card
        WHERE account_id = NEW.account_id
        ORDER BY (status = 'ACTIVE') DESC, card_id ASC
        LIMIT 1;

        -- 2. Lookup an OPERATIONAL ATM terminal
        SELECT atm_id INTO v_atm_id
        FROM atm
        WHERE status = 'OPERATIONAL'
        ORDER BY atm_id ASC
        LIMIT 1;

        INSERT INTO transaction (
            transaction_type,
            amount,
            transaction_method,
            date_time,
            account_id,
            card_id,
            atm_id
        ) VALUES (
            v_tx_type,
            ABS(v_diff),
            'ATM',
            CURRENT_TIMESTAMP,
            NEW.account_id,
            COALESCE(v_card_id, 1),
            COALESCE(v_atm_id, 1)
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_audit_balance_change
AFTER UPDATE OF balance ON account
FOR EACH ROW
EXECUTE FUNCTION fn_audit_balance_change();

--Trigger 3: trg_enforce_card_lockout (Security Lockout Engine)
CREATE OR REPLACE FUNCTION fn_enforce_card_lockout()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.failed_pin_attempts >= 3 AND NEW.status <> 'BLOCKED' THEN
        NEW.status := 'BLOCKED';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_enforce_card_lockout
BEFORE UPDATE OF failed_pin_attempts ON card
FOR EACH ROW
EXECUTE FUNCTION fn_enforce_card_lockout();

--View 1: v_failed_security_audits
CREATE OR REPLACE VIEW v_failed_security_audits AS
SELECT 
    c.card_id,
    c.card_number,
    c.card_type,
    c.status AS card_status,
    c.failed_pin_attempts,
    c.expiry_date,
    a.account_id,
    a.account_number,
    a.status AS account_status,
    cust.customer_id,
    cust.firstname || ' ' || COALESCE(cust.lastname, '') AS customer_name,
    cust.phone_number,
    cust.email,
    b.branch_name,
    b.ifsc_code,
    b.pin_code AS branch_pincode
FROM card c
JOIN account a ON c.account_id = a.account_id
JOIN customer cust ON a.customer_id = cust.customer_id
JOIN branch b ON a.branch_id = b.branch_id
WHERE c.failed_pin_attempts > 0 OR c.status = 'BLOCKED';

--View 2: v_high_value_transfers
CREATE OR REPLACE VIEW v_high_value_transfers AS
SELECT 
    t.transaction_id,
    t.transaction_type,
    t.amount,
    t.transaction_method,
    t.date_time,
    a.account_id,
    a.account_number,
    a.account_type,
    cust.customer_id,
    cust.firstname || ' ' || COALESCE(cust.lastname, '') AS customer_name,
    cust.phone_number,
    cust.email,
    t.atm_id,
    atm.terminal_code,
    atm.atm_location
FROM transaction t
JOIN account a ON t.account_id = a.account_id
JOIN customer cust ON a.customer_id = cust.customer_id
LEFT JOIN atm ON t.atm_id = atm.atm_id
WHERE t.amount >= 10000.00;

--View 3: v_account_overview
CREATE OR REPLACE VIEW v_account_overview AS
SELECT 
    a.account_id,
    a.account_number,
    a.account_type,
    a.balance,
    a.status AS account_status,
    a.date_time AS account_opened_on,
    cust.customer_id,
    cust.firstname,
    cust.lastname,
    cust.age,
    cust.gender,
    cust.phone_number,
    cust.email,
    b.branch_id,
    b.branch_name,
    b.ifsc_code,
    b.address AS branch_address,
    b.pin_code AS branch_pincode
FROM account a
JOIN customer cust ON a.customer_id = cust.customer_id
JOIN branch b ON a.branch_id = b.branch_id;

--Procedure 1: sp_atm_withdraw_cash
CREATE OR REPLACE PROCEDURE sp_atm_withdraw_cash(
    p_card_id BIGINT,
    p_terminal_code VARCHAR(20),
    p_amount NUMERIC(12, 2)
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_account_id BIGINT;
    v_card_status VARCHAR(15);
    v_acc_status VARCHAR(15);
    v_acc_balance NUMERIC(15, 2);
    v_atm_id INT;
    v_atm_balance NUMERIC(12, 2);
    v_atm_status VARCHAR(20);
BEGIN
    -- 1. Validate withdrawal amount
    IF p_amount <= 0 OR (p_amount::INT % 100 <> 0) THEN
        RAISE EXCEPTION 'Dispense amount must be positive and in multiples of ₹100.';
    END IF;

    -- 2. Verify Card
    SELECT account_id, status INTO v_account_id, v_card_status
    FROM card WHERE card_id = p_card_id;

    IF v_card_status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'Card is not active (Current Status: %).', v_card_status;
    END IF;

    -- 3. Lock Account Row
    SELECT balance, status INTO v_acc_balance, v_acc_status
    FROM account WHERE account_id = v_account_id FOR UPDATE;

    IF v_acc_status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'Linked bank account is not active (Status: %).', v_acc_status;
    END IF;

    IF v_acc_balance < p_amount THEN
        RAISE EXCEPTION 'Insufficient customer account funds. Balance: ₹%', v_acc_balance;
    END IF;

    -- 4. Lock ATM Row
    SELECT atm_id, current_balance, status INTO v_atm_id, v_atm_balance, v_atm_status
    FROM atm WHERE terminal_code = p_terminal_code FOR UPDATE;

    IF v_atm_status <> 'OPERATIONAL' THEN
        RAISE EXCEPTION 'ATM Terminal % is currently out of service.', p_terminal_code;
    END IF;

    IF v_atm_balance < p_amount THEN
        RAISE EXCEPTION 'ATM does not have sufficient cash notes to fulfill request.';
    END IF;

    -- 5. Mutate Balances
    UPDATE account 
    SET balance = balance - p_amount 
    WHERE account_id = v_account_id;

    UPDATE atm 
    SET current_balance = current_balance - p_amount 
    WHERE atm_id = v_atm_id;


    RAISE NOTICE 'Withdrawal of ₹% completed successfully.', p_amount;
END;
$$;

--Procedure 2: sp_atm_deposit_cash
CREATE OR REPLACE PROCEDURE sp_atm_deposit_cash(
    p_card_id BIGINT,
    p_terminal_code VARCHAR(20),
    p_amount NUMERIC(12, 2)
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_account_id BIGINT;
    v_card_status VARCHAR(15);
    v_acc_status VARCHAR(15);
    v_atm_id INT;
    v_atm_status VARCHAR(20);
BEGIN
    -- 1. Validate deposit amount
    IF p_amount <= 0 OR (p_amount::INT % 100 <> 0) THEN
        RAISE EXCEPTION 'Deposit amount must be positive and in multiples of ₹100.';
    END IF;

    -- 2. Verify Card
    SELECT account_id, status INTO v_account_id, v_card_status
    FROM card WHERE card_id = p_card_id;

    IF v_card_status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'Card is not active (Current Status: %).', v_card_status;
    END IF;

    -- 3. Lock Account Row
    SELECT status INTO v_acc_status
    FROM account WHERE account_id = v_account_id FOR UPDATE;

    IF v_acc_status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'Linked bank account is not active (Status: %).', v_acc_status;
    END IF;

    -- 4. Lock ATM Row
    SELECT atm_id, status INTO v_atm_id, v_atm_status
    FROM atm WHERE terminal_code = p_terminal_code FOR UPDATE;

    IF v_atm_status <> 'OPERATIONAL' THEN
        RAISE EXCEPTION 'ATM Terminal % is currently out of service.', p_terminal_code;
    END IF;

    -- 5. Mutate Balances
    UPDATE account 
    SET balance = balance + p_amount 
    WHERE account_id = v_account_id;

    UPDATE atm 
    SET current_balance = current_balance + p_amount 
    WHERE atm_id = v_atm_id;

    RAISE NOTICE 'Deposit of ₹% completed successfully.', p_amount;
END;
$$;

--Procedure 3: sp_atm_balance_enquiry
CREATE OR REPLACE PROCEDURE sp_atm_balance_enquiry(
    p_card_id BIGINT,
    p_terminal_code VARCHAR(20),
    INOUT p_balance NUMERIC(15, 2) DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_account_id BIGINT;
    v_card_status VARCHAR(15);
    v_acc_status VARCHAR(15);
    v_atm_id INT;
    v_atm_status VARCHAR(20);
BEGIN
    -- 1. Verify Card
    SELECT account_id, status INTO v_account_id, v_card_status
    FROM card WHERE card_id = p_card_id;

    IF v_card_status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'Card is not active (Current Status: %).', v_card_status;
    END IF;

    -- 2. Verify ATM
    SELECT atm_id, status INTO v_atm_id, v_atm_status
    FROM atm WHERE terminal_code = p_terminal_code;

    IF v_atm_status <> 'OPERATIONAL' THEN
        RAISE EXCEPTION 'ATM Terminal % is currently out of service.', p_terminal_code;
    END IF;

    -- 3. Fetch Account Balance
    SELECT balance, status INTO p_balance, v_acc_status
    FROM account WHERE account_id = v_account_id;

    IF v_acc_status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'Linked bank account is not active (Status: %).', v_acc_status;
    END IF;

    RAISE NOTICE 'Balance inquiry completed. Available Balance: ₹%', p_balance;
END;
$$;

