# ATM Transaction Logging & Management System (ATLS)

A monolithic DBMS mini-project built with **Python 3.12 (Flask)** and **PostgreSQL 16 (`atls_db`)** simulating both an active customer-facing ATM terminal and a back-end administrative bank portal running concurrently on independent ports.

---

## Architecture & Port Separation

A single execution of `python app.py` initializes two localized web servers on separate daemon threads:
- **Port 5001 (ATM Terminal Interface):** Customer-facing portal. Features an ATM switcher at the top, card validation, Werkzeug hashed PIN verification with a 3-attempt security lockout, a clean touchscreen-style 3-option menu (Cash Withdrawal, Cash Deposit, Balance Enquiry), dedicated money entering interfaces, and printable digital ATM receipts.
- **Port 5002 (Bank Admin & Audit Portal):** Employer/Auditor-facing dashboard. Handles account management, live balance distributions, real-time transaction ledger auditing, and an embedded administrative pseudo-terminal with external tabular report generation for direct SQL execution.

---

## Project Structure

```text
atm/
├── app.py                 # Multi-threaded dual-port server initiator (Ports 5001 & 5002)
├── db.py                  # psycopg v3 ConnectionPool manager & role segregation helper
├── schema.sql             # PostgreSQL DDL (Tables, Indexes, Views, Triggers, Stored Procedures)
├── seed.sql               # Seed dataset (10 Customers, 10 Accounts, 10 Branches, 10 Cards, 10 ATMs)
├── .env                   # Protected environmental configuration
├── .env.example           # Environment variables template
├── requirements.txt       # Dependencies (Flask, psycopg, psycopg-pool, python-dotenv, werkzeug)
├── static/
│   ├── css/
│   │   └── style.css      # Minimalist dark terminal stylesheet (#09090b / #18181b)
│   └── js/
│       ├── main.js        # Dynamic AJAX form handlers and modal controllers
│       └── terminal.js    # Web-based administrative CLI pseudo-terminal
└── templates/
    ├── atm/               # Port 5001 Templates
    │   ├── index.html     # Card insertion & PIN authentication screen
    │   └── dashboard.html # Authenticated customer banking dashboard & receipt modal
    └── bank/              # Port 5002 Templates
        ├── login.html     # Role-based Staff & Auditor Authentication Gateway
        ├── dashboard.html # Account Management Hub & KPI summary
        ├── audit.html     # Dedicated Transaction Logs Stream
        ├── reports.html   # DBMS Evaluation reports engine
        └── terminal.html  # Administrative pseudo-terminal CLI ($)
```

---

## Quick Start Guide

### 1. Prerequisites
Ensure PostgreSQL is active and running:
```bash
sudo systemctl status postgresql
```

### 2. Activate Virtual Environment
```bash
source .venv/bin/activate
```

### 3. Verify System Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the Dual-Port Application
```bash
python app.py
```

### 5. Access Interfaces in Your Browser
- **Customer ATM Terminal:** [http://localhost:5001](http://localhost:5001)
- **Bank Management & Audit Portal:** [http://localhost:5002](http://localhost:5002)

---

## Demo Test Cards (Port 5001)

All test cards use the universal demo PIN: `1234` (verified with `werkzeug.security`). 1-click test fill buttons are available directly on the login screen:

| Card Number | Customer Name | Account Type | Initial Balance | Status | Note |
|---|---|---|---|---|---|
| `4532012345678901` | Aarav Sharma | Savings | ₹45,000.00 | `ACTIVE` | Standard test card |
| `4532012345678902` | Priya Nair | Salary | ₹125,000.00 | `ACTIVE` | High balance card |
| `5241889911223344` | Rohan Verma | Current | ₹480,000.00 | `ACTIVE` | Credit card linked |
| `4532012345678908` | Suresh Raina | Savings | ₹0.00 | `BLOCKED` | Demonstrates lockout |

---

## Bank Portal Demo Logins & Access Control (Port 5002)

All unauthenticated traffic to Port 5002 is intercepted and redirected to `/login`. The login interface features 1-click quick-login buttons for evaluation and viva demonstrations:

| Role | Username | Password | Permissions & Scope | SQL Console (`/terminal`) Access |
|---|---|---|---|---|
| **DBA (Database Administrator)** | `dba` (or `admin`) | `dba123` (or `dba`) | Full administrative access, account management hub, transaction logs stream, and raw SQL console execution. | **YES (Full Access)** |
| **CLERK (Branch Operations)** | `clerk` | `clerk123` (or `clerk`) | Operational access: customer registration, new account opening, card issuance, card unblocking, transaction audits. | **NO (Access Denied / 403 Forbidden)** |

> **Security Invariant:** The SQL Console (`/terminal` and `POST /api/terminal/execute`) is strictly locked down to the `DBA` role. If a Clerk attempts to visit `/terminal`, they are automatically redirected to `/` with an `Access Denied` error alert. Any unauthorized API execution attempts return `403 Forbidden`.

---

## DBMS Syllabus Feature Mapping (Section 6)

### 1. Stored Procedures
- `sp_atm_withdraw_cash(p_card_id, p_terminal_code, p_amount)`: Validates withdrawal amount in multiples of ₹100, checks card and ATM status, acquires row-level lock (`FOR UPDATE`), updates balances, and logs ledger transaction.
- `sp_atm_deposit_cash(p_card_id, p_terminal_code, p_amount)`: Validates cash deposit amount, updates account balance, and increments ATM hardware cash vault.
- `sp_atm_balance_enquiry(p_card_id, p_terminal_code, INOUT p_balance)`: Retrieves available balance via procedure parameters.

### 2. Database Triggers
- `trg_set_customer_age`: Automatically computes customer age from `dob` before insertion or update.
- `trg_enforce_card_lockout`: Automatically transitions card status to `'BLOCKED'` when `failed_pin_attempts >= 3`.
- `trg_audit_balance_change`: Logs ledger records upon account balance changes.

### 3. Virtual Database Views
- `v_failed_security_audits`: Virtual analytical mirror surfacing cards with failed authentication attempts or locked accounts.
- `v_high_value_transfers`: Isolates transactions with amounts `₹10,000.00` and above.
- `v_account_overview`: Full 3NF relational join of `customer`, `account`, and `branch`.

### 4. Administrative SQL Console & Reporting (Port 5002 - `/terminal`)
- Restricted-access web CLI (`$`) for database administrators operating with `atm_dba` role privileges.
- **Generate Report Workflow**: Query execution is piped directly into a high-contrast tabular report rendered outside of the terminal window, displaying execution latency, returned tuple count, and clean column headers. When the result set contains wide or numerous attributes, the first two columns stay static/frozen while remaining columns slide smoothly underneath.
- **Quick Query Presets Dropdown**: Includes 12 pre-configured business analytical queries demonstrating core DBMS mechanics:
  1. *System-wide Total Accounts & Balance Summary* (Aggregates: `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`)
  2. *Branch-wise Total Accounts & Deposit Volume* (`GROUP BY` & aggregates)
  3. *High-Balance Account Categories (Avg Balance > ₹50,000)* (`HAVING` clause)
  4. *Customer Accounts Ranked by Highest Balance* (`ORDER BY` descending)
  5. *Distinct Transaction Types & Channels Used* (`DISTINCT`)
  6. *Accounts with Balance Above Bank Average* (Scalar subquery)
  7. *Customers with Blocked Cards (Account & Card Details)* (Subquery with `IN` returning account and card specifications)
  8. *Active Accounts with Customer & Linked Card Details* (Multi-table `INNER JOIN`)
  9. *All Bank Branches with Account Counts and Total Funds* (`LEFT OUTER JOIN`)
  10. *Unified Directory of All Bank Branches & ATM Locations* (`UNION` set operation)
  11. *Verified Active Accounts (Account Holder, Number & Type)* (`INTERSECT` set operation with account profile details)
  12. *Account Overview View (v_account_overview)* (Virtual analytical view)

### 5. Bank Management Dashboard Features (Port 5002 - `/`)
- **Live KPIs & Balance Trackers**: Live metrics on customer base, active accounts, total deposits, operational ATMs, and locked cards.
- **Account Management Hub**: Filter accounts by status (`ACTIVE`, `FROZEN`, `CLOSED`, etc.) or search by account number and customer name.
- **Searchable Customer Combobox**: In the *Open New Account* workflow, bank personnel can search customers dynamically by name, customer ID, email, or phone number with real-time dropdown suggestions.
- **Quick Customer Registration**: A dedicated `+ New Customer` modal (`POST /api/customer/create`) allows bank staff to register a new customer profile on the fly (with automatic age calculation via database trigger `trg_set_customer_age`) and immediately auto-selects them for opening an account.
- **Clickable Account Profile Inspector**: Clicking any account number in the Account Management Hub opens a comprehensive relational profile modal (`GET /api/account/<id>/details`) displaying:
  - Account Ledger Overview (Account number, type, live balance, date opened, status).
  - Customer Personal Identity (Name, age, date of birth, gender, phone, email, registered residential address).
  - Home Branch Specifications (Branch name, IFSC code, physical address, postal PIN code).
  - Linked Payment Cards (Card numbers, type, expiry date, security lockout counters, status badges).
  - Account Transaction Ledger (Chronological audit history of deposits, withdrawals, and balance checks).
- **Payment Card Issuance & Reactivation Engine**: Bank personnel can issue and link new Debit (Visa 4532) or Credit (Mastercard 5241) cards directly from the Account Profile modal (`POST /api/account/<id>/card/create`) with customizable 4-digit PIN (hashed via `werkzeug.security`). Blocked cards (due to 3 failed PIN attempts or security lockout) can be reactivated directly from the Account Profile with a single click (`POST /api/card/<card_id>/unblock`), resetting `failed_pin_attempts = 0` and transitioning `status = 'ACTIVE'`.
- **ATM Transaction Logs Section (`/audit`)**: Dedicated audit trail listing strictly transactions performed via ATM terminals. Includes:
  - Operation type filter (`WITHDRAWAL`, `DEPOSIT`, `BALANCE_INQUIRY`).
  - Small calendar datepicker widget for precise single-day transaction audits.
  - Multi-attribute sorting engine supporting `TX ID`, `Transaction Amount`, `Account ID`, and `Timestamp` in both ascending and descending sequences.



