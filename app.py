"""
ATM Transaction Logging & Management System - Multi-Port Monolithic Initiator.

Initializes two concurrent WSGI Flask servers on independent ports:
- Port 5001: Customer ATM Terminal Interface (atm_service role)
- Port 5002: Bank Admin & Auditor Portal (clerk_service and atm_dba roles)
"""

import os
import re
import sys
import time
import logging
import threading
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

import db

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("app")

load_dotenv()

# Environmental configuration
ATM_SECRET_KEY = os.getenv("ATM_SECRET_KEY", "atm_session_secret_5001")
BANK_SECRET_KEY = os.getenv("BANK_SECRET_KEY", "bank_session_secret_5002")
ATM_TERMINAL_CODE = os.getenv("ATM_TERMINAL_CODE", "ATM-BLR-042")
MAX_PIN_ATTEMPTS = int(os.getenv("MAX_PIN_ATTEMPTS", "3"))


# ============================================================================
# FACTORY: PORT 5001 - ATM TERMINAL APPLICATION
# ============================================================================
def create_atm_app() -> Flask:
    """
    Construct and configure the Port 5001 customer-facing ATM Flask application.
    Enforces least-privilege operations via the 'atm_service' database role.
    """
    atm_app = Flask(__name__, template_folder="templates")
    atm_app.secret_key = ATM_SECRET_KEY

    def get_all_atms() -> List[Dict[str, Any]]:
        """Fetch all ATM terminals from the database."""
        return db.execute_query(
            "SELECT atm_id, terminal_code, status, current_balance, atm_location FROM atm ORDER BY atm_id",
            role="atm",
            fetch="all",
        ) or []

    def get_terminal_info() -> Dict[str, Any]:
        """Fetch current ATM terminal hardware telemetry from database."""
        selected_code = session.get("terminal_code", ATM_TERMINAL_CODE)
        row = db.execute_query(
            "SELECT atm_id, terminal_code, status, current_balance, atm_location FROM atm WHERE terminal_code = %s",
            (selected_code,),
            role="atm",
            fetch="one",
        )
        if not row:
            # Fallback to first available terminal if configured terminal code is not found
            row = db.execute_query(
                "SELECT atm_id, terminal_code, status, current_balance, atm_location FROM atm LIMIT 1",
                role="atm",
                fetch="one",
            )
        return row or {
            "atm_id": 1,
            "terminal_code": selected_code,
            "status": "OPERATIONAL",
            "current_balance": Decimal("500000.00"),
            "atm_location": "Main Terminal Concourse",
        }

    @atm_app.route("/change-atm", methods=["POST"])
    def change_atm():
        """
        Switch current active ATM terminal (only permitted prior to card authentication).
        :return: Redirect response to index or dashboard.
        """
        if "card_id" in session:
            # Switching ATM is prohibited once card authentication has passed
            session["dash_error"] = "ATM terminal switching is only permitted before card authentication."
            return redirect(url_for("dashboard"))

        new_code = request.form.get("terminal_code", "").strip()
        if new_code:
            atm_exists = db.execute_query(
                "SELECT terminal_code, status FROM atm WHERE terminal_code = %s",
                (new_code,),
                role="atm",
                fetch="one",
            )
            if atm_exists:
                session["terminal_code"] = new_code
                status = (atm_exists.get("status") or "OPERATIONAL").upper()
                if status == "MAINTENANCE":
                    session["login_error"] = (
                        f"Terminal Notice: ATM {new_code} is currently UNDER MAINTENANCE. "
                        "Transactions cannot be processed at this time."
                    )
                    return redirect(url_for("index"))
                elif status == "OUT_OF_SERVICE":
                    session["login_error"] = (
                        f"Terminal Notice: ATM {new_code} is currently OUT OF SERVICE. "
                        "Please use another ATM terminal."
                    )
                    return redirect(url_for("index"))
                elif status != "OPERATIONAL":
                    session["login_error"] = (
                        f"Terminal Notice: ATM {new_code} is currently {status.replace('_', ' ')}. "
                        "Transactions cannot be processed."
                    )
                    return redirect(url_for("index"))
                session["login_success"] = f"Switched to ATM Terminal: {new_code}"
        return redirect(url_for("index"))

    @atm_app.route("/")
    def index():
        """
        Render ATM card insertion and PIN authentication surface.
        :return: HTML template (templates/atm/index.html), HTTP 200.
        """
        if "card_id" in session:
            return redirect(url_for("dashboard"))

        atm_info = get_terminal_info()
        all_atms = get_all_atms()
        return render_template(
            "atm/index.html",
            terminal_code=atm_info["terminal_code"],
            atm_status=atm_info["status"],
            atm_cash=float(atm_info["current_balance"]),
            atm_location=atm_info["atm_location"],
            all_atms=all_atms,
            error=session.pop("login_error", None),
            success=session.pop("login_success", None),
        )

    @atm_app.route("/login", methods=["POST"])
    def login():
        """
        Authenticate card number and 4-digit hashed PIN with consecutive failure tracking.
        Enforces security lockout when failed attempts reach MAX_PIN_ATTEMPTS.
        :return: Redirect response to dashboard or login with error.
        """
        card_number = request.form.get("card_number", "").strip().replace(" ", "")
        pin = request.form.get("pin", "").strip()
        form_term = request.form.get("terminal_code", "").strip()
        if form_term:
            session["terminal_code"] = form_term

        if not card_number or not pin:
            session["login_error"] = "Card Number and 4-Digit PIN are required."
            return redirect(url_for("index"))

        # Verify active ATM hardware operational status before allowing authentication
        atm_info = get_terminal_info()
        atm_status = (atm_info.get("status") or "OPERATIONAL").upper()

        if atm_status == "MAINTENANCE":
            session["login_error"] = (
                f"Terminal Notice: ATM {atm_info['terminal_code']} is currently UNDER MAINTENANCE. "
                "Transactions cannot be processed at this time."
            )
            return redirect(url_for("index"))

        if atm_status == "OUT_OF_SERVICE":
            session["login_error"] = (
                f"Terminal Notice: ATM {atm_info['terminal_code']} is currently OUT OF SERVICE. "
                "Please use another ATM terminal."
            )
            return redirect(url_for("index"))

        if atm_status != "OPERATIONAL":
            session["login_error"] = (
                f"Terminal Notice: ATM {atm_info['terminal_code']} is currently {atm_status.replace('_', ' ')}. "
                "Transactions cannot be processed."
            )
            return redirect(url_for("index"))

        # Look up card record
        card = db.execute_query(
            """
            SELECT card_id, card_number, card_type, status, failed_pin_attempts, account_id
            FROM card
            WHERE card_number = %s
            """,
            (card_number,),
            role="atm",
            fetch="one",
        )

        if not card:
            session["login_error"] = "Invalid card number. Terminal could not locate account profile."
            return redirect(url_for("index"))

        # Verify card status
        if card["status"] == "BLOCKED":
            session["login_error"] = "Security Alert: This card is BLOCKED due to security lockout."
            return redirect(url_for("index"))

        if card["status"] == "EXPIRED":
            session["login_error"] = "Transaction Rejected: Card has reached its expiration date."
            return redirect(url_for("index"))

        # Verify PIN hash against card_security table
        sec = db.execute_query(
            "SELECT pin_hash FROM card_security WHERE card_id = %s",
            (card["card_id"],),
            role="atm",
            fetch="one",
        )

        pin_valid = False
        if sec and sec.get("pin_hash"):
            try:
                pin_valid = check_password_hash(sec["pin_hash"], pin)
            except Exception as e:
                logger.error(f"PIN validation error: {e}")
                pin_valid = False

        if not pin_valid:
            # Increment failed attempts
            new_attempts = card["failed_pin_attempts"] + 1
            if new_attempts >= MAX_PIN_ATTEMPTS:
                # Lockout trigger: Transition status to BLOCKED
                db.execute_query(
                    "UPDATE card SET failed_pin_attempts = %s, status = 'BLOCKED' WHERE card_id = %s",
                    (new_attempts, card["card_id"]),
                    role="atm",
                    fetch="none",
                )
                session["login_error"] = f"Card LOCKED OUT! 3 consecutive failed attempts detected."
            else:
                db.execute_query(
                    "UPDATE card SET failed_pin_attempts = %s WHERE card_id = %s",
                    (new_attempts, card["card_id"]),
                    role="atm",
                    fetch="none",
                )
                remaining = MAX_PIN_ATTEMPTS - new_attempts
                session["login_error"] = f"Incorrect PIN. {remaining} attempt(s) remaining before permanent lockout."
            return redirect(url_for("index"))

        # Authentication successful: Reset failed attempts counter
        db.execute_query(
            "UPDATE card SET failed_pin_attempts = 0 WHERE card_id = %s",
            (card["card_id"],),
            role="atm",
            fetch="none",
        )

        # Establish customer session
        session["card_id"] = card["card_id"]
        session["account_id"] = card["account_id"]
        session["login_success"] = "Card authenticated successfully."
        return redirect(url_for("dashboard"))

    @atm_app.route("/dashboard")
    def dashboard():
        """
        Display customer authenticated dashboard with account balance and operational options.
        :return: HTML template (templates/atm/dashboard.html), HTTP 200.
        """
        if "card_id" not in session:
            return redirect(url_for("index"))

        atm_info = get_terminal_info()
        atm_status = (atm_info.get("status") or "OPERATIONAL").upper()
        if atm_status != "OPERATIONAL":
            session.pop("card_id", None)
            session.pop("account_id", None)
            status_text = "UNDER MAINTENANCE" if atm_status == "MAINTENANCE" else "OUT OF SERVICE"
            session["login_error"] = f"Terminal Notice: ATM {atm_info.get('terminal_code', '')} is currently {status_text}. Session terminated."
            return redirect(url_for("index"))

        card_id = session["card_id"]
        account_id = session["account_id"]

        # Fetch Card, Account, Customer, and Branch details
        account_data = db.execute_query(
            """
            SELECT 
                a.account_id, a.account_number, a.account_type, a.balance, a.status,
                c.customer_id, c.firstname, c.lastname, c.phone_number, c.email,
                b.branch_id, b.branch_name, b.ifsc_code, b.pin_code
            FROM account a
            JOIN customer c ON a.customer_id = c.customer_id
            JOIN branch b ON a.branch_id = b.branch_id
            WHERE a.account_id = %s
            """,
            (account_id,),
            role="atm",
            fetch="one",
        )

        card_data = db.execute_query(
            "SELECT card_id, card_number, card_type, status FROM card WHERE card_id = %s",
            (card_id,),
            role="atm",
            fetch="one",
        )

        # Fetch mini-statement recent transactions
        transactions = db.execute_query(
            """
            SELECT transaction_id, transaction_type, amount, transaction_method, date_time
            FROM transaction
            WHERE account_id = %s
            ORDER BY date_time DESC
            LIMIT 5
            """,
            (account_id,),
            role="atm",
            fetch="all",
        )

        receipt = session.pop("recent_receipt", None)
        error = session.pop("dash_error", None)
        success = session.pop("dash_success", None)

        return render_template(
            "atm/dashboard.html",
            terminal_code=atm_info["terminal_code"],
            atm=atm_info,
            all_atms=get_all_atms(),
            account=account_data,
            card=card_data,
            customer=account_data,
            branch=account_data,
            transactions=transactions or [],
            receipt=receipt,
            error=error,
            success=success,
        )

    @atm_app.route("/balance-inquiry", methods=["POST"])
    def balance_inquiry():
        """
        Trigger balance validation inquiry and generate digital ATM slip.
        :return: Redirect to dashboard.
        """
        if "card_id" not in session:
            return redirect(url_for("index"))

        card_id = session["card_id"]
        account_id = session["account_id"]
        atm_info = get_terminal_info()

        try:
            # Query current balance
            acc = db.execute_query(
                "SELECT account_number, balance FROM account WHERE account_id = %s",
                (account_id,),
                role="atm",
                fetch="one",
            )
            card = db.execute_query(
                "SELECT card_number FROM card WHERE card_id = %s",
                (card_id,),
                role="atm",
                fetch="one",
            )

            # Record inquiry transaction in transaction ledger
            # Acquire transaction connection with commit
            db.execute_query(
                """
                INSERT INTO transaction (
                    transaction_type, amount, transaction_method, date_time, account_id, card_id, atm_id
                ) VALUES ('BALANCE_INQUIRY', 0.00, 'ATM', CURRENT_TIMESTAMP, %s, %s, %s)
                """,
                (account_id, card_id, atm_info["atm_id"]),
                role="atm",
                fetch="none",
            )

            session["recent_receipt"] = {
                "type": "BALANCE INQUIRY",
                "account_number": acc["account_number"],
                "card_last4": card["card_number"][-4:],
                "amount": 0.00,
                "new_balance": float(acc["balance"]),
                "status": "APPROVED",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            session["dash_success"] = f"Balance Inquiry Processed. Available Funds: ₹{acc['balance']:,.2f}"
        except Exception as e:
            logger.error(f"Balance inquiry failed: {e}")
            session["dash_error"] = f"Inquiry Failed: {str(e)}"

        return redirect(url_for("dashboard"))

    @atm_app.route("/withdraw", methods=["POST"])
    def withdraw():
        """
        Process customer cash withdrawal executing PostgreSQL stored procedure sp_atm_withdraw_cash.
        :return: Redirect to dashboard.
        """
        if "card_id" not in session:
            return redirect(url_for("index"))

        card_id = session["card_id"]
        account_id = session["account_id"]
        atm_info = get_terminal_info()

        try:
            amount = float(request.form.get("amount", "0"))
            if amount <= 0 or amount % 100 != 0:
                session["dash_error"] = "Withdrawal amount must be in multiples of ₹100."
                return redirect(url_for("dashboard"))

            # Execute PostgreSQL Stored Procedure sp_atm_withdraw_cash
            db.execute_procedure(
                "sp_atm_withdraw_cash",
                [card_id, atm_info["terminal_code"], amount],
                types=["BIGINT", "VARCHAR", "NUMERIC"],
                role="atm",
            )

            # Retrieve updated balance for receipt
            acc = db.execute_query(
                "SELECT account_number, balance FROM account WHERE account_id = %s",
                (account_id,),
                role="atm",
                fetch="one",
            )
            card = db.execute_query(
                "SELECT card_number FROM card WHERE card_id = %s",
                (card_id,),
                role="atm",
                fetch="one",
            )

            session["recent_receipt"] = {
                "type": "CASH WITHDRAWAL",
                "account_number": acc["account_number"],
                "card_last4": card["card_number"][-4:],
                "amount": amount,
                "new_balance": float(acc["balance"]),
                "status": "APPROVED",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            session["dash_success"] = f"Successfully withdrawn ₹{amount:,.2f}. Please collect your cash."
        except Exception as e:
            logger.error(f"Withdrawal failed: {e}")
            session["dash_error"] = f"Transaction Declined: {str(e)}"

        return redirect(url_for("dashboard"))

    @atm_app.route("/deposit", methods=["POST"])
    def deposit():
        """
        Process cash deposit executing PostgreSQL stored procedure sp_atm_deposit_cash.
        :return: Redirect to dashboard.
        """
        if "card_id" not in session:
            return redirect(url_for("index"))

        card_id = session["card_id"]
        account_id = session["account_id"]
        atm_info = get_terminal_info()

        try:
            amount = float(request.form.get("amount", "0"))
            if amount <= 0 or amount % 100 != 0:
                session["dash_error"] = "Deposit amount must be in multiples of ₹100."
                return redirect(url_for("dashboard"))

            # Execute PostgreSQL Stored Procedure sp_atm_deposit_cash
            db.execute_procedure(
                "sp_atm_deposit_cash",
                [card_id, atm_info["terminal_code"], amount],
                types=["BIGINT", "VARCHAR", "NUMERIC"],
                role="atm",
            )

            # Retrieve updated balance for receipt
            acc = db.execute_query(
                "SELECT account_number, balance FROM account WHERE account_id = %s",
                (account_id,),
                role="atm",
                fetch="one",
            )
            card = db.execute_query(
                "SELECT card_number FROM card WHERE card_id = %s",
                (card_id,),
                role="atm",
                fetch="one",
            )

            session["recent_receipt"] = {
                "type": "CASH DEPOSIT",
                "account_number": acc["account_number"],
                "card_last4": card["card_number"][-4:],
                "amount": amount,
                "new_balance": float(acc["balance"]),
                "status": "APPROVED",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            session["dash_success"] = f"Cash deposit of ₹{amount:,.2f} completed successfully."
        except Exception as e:
            logger.error(f"Deposit failed: {e}")
            session["dash_error"] = f"Deposit Failed: {str(e)}"

        return redirect(url_for("dashboard"))

    @atm_app.route("/transfer", methods=["POST"])
    def transfer():
        """
        Process atomic inter-account fund transfer with row-level locks (FOR UPDATE).
        :return: Redirect to dashboard.
        """
        if "card_id" not in session:
            return redirect(url_for("index"))

        card_id = session["card_id"]
        source_acc_id = session["account_id"]
        atm_info = get_terminal_info()

        target_acc_num = request.form.get("target_account_number", "").strip()
        try:
            amount = float(request.form.get("amount", "0"))
            if amount <= 0:
                session["dash_error"] = "Transfer amount must be positive."
                return redirect(url_for("dashboard"))

            # Atomic transaction block with row-level locks
            with db.get_db_connection("atm") as conn:
                with conn.cursor() as cur:
                    # Look up target account
                    cur.execute(
                        "SELECT account_id, status FROM account WHERE account_number = %s",
                        (target_acc_num,),
                    )
                    target = cur.fetchone()
                    if not target:
                        raise ValueError(f"Beneficiary account '{target_acc_num}' not found.")
                    if target["status"] != "ACTIVE":
                        raise ValueError(f"Target account is not active (Status: {target['status']}).")

                    target_acc_id = target["account_id"]
                    if source_acc_id == target_acc_id:
                        raise ValueError("Source and destination accounts cannot be identical.")

                    # Order lock acquisition by account ID to prevent relational deadlocks
                    first_lock = min(source_acc_id, target_acc_id)
                    second_lock = max(source_acc_id, target_acc_id)
                    cur.execute("SELECT balance, status FROM account WHERE account_id = %s FOR UPDATE", (first_lock,))
                    cur.execute("SELECT balance, status FROM account WHERE account_id = %s FOR UPDATE", (second_lock,))

                    # Re-verify source balance
                    cur.execute("SELECT balance, account_number FROM account WHERE account_id = %s", (source_acc_id,))
                    src_acc = cur.fetchone()
                    if src_acc["balance"] < amount:
                        raise ValueError(f"Insufficient balance (Available: ₹{src_acc['balance']:,.2f}).")

                    # Mutate balances atomically
                    cur.execute("UPDATE account SET balance = balance - %s WHERE account_id = %s", (amount, source_acc_id))
                    cur.execute("UPDATE account SET balance = balance + %s WHERE account_id = %s", (amount, target_acc_id))

                    # Insert transfer transaction record
                    cur.execute(
                        """
                        INSERT INTO transaction (
                            transaction_type, amount, transaction_method, date_time, account_id, card_id, atm_id
                        ) VALUES ('TRANSFER', %s, 'ATM', CURRENT_TIMESTAMP, %s, %s, %s)
                        """,
                        (amount, source_acc_id, card_id, atm_info["atm_id"]),
                    )

                conn.commit()

            # Retrieve updated balance
            acc = db.execute_query(
                "SELECT account_number, balance FROM account WHERE account_id = %s",
                (source_acc_id,),
                role="atm",
                fetch="one",
            )
            card = db.execute_query(
                "SELECT card_number FROM card WHERE card_id = %s",
                (card_id,),
                role="atm",
                fetch="one",
            )

            session["recent_receipt"] = {
                "type": "FUND TRANSFER",
                "account_number": acc["account_number"],
                "card_last4": card["card_number"][-4:],
                "amount": amount,
                "new_balance": float(acc["balance"]),
                "status": f"SENT TO {target_acc_num}",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            session["dash_success"] = f"Transferred ₹{amount:,.2f} to {target_acc_num} successfully."
        except Exception as e:
            logger.error(f"Transfer failed: {e}")
            session["dash_error"] = f"Transfer Declined: {str(e)}"

        return redirect(url_for("dashboard"))

    @atm_app.route("/logout")
    def logout():
        """Eject card and clear current customer terminal session."""
        session.clear()
        return redirect(url_for("index"))

    return atm_app


# ============================================================================
# FACTORY: PORT 5002 - BANK MANAGEMENT & AUDIT PORTAL
# ============================================================================
def create_bank_app() -> Flask:
    """
    Construct and configure the Port 5002 Bank Administrator and Audit Portal.
    Operates via clerk_service and atm_dba for reports and raw terminal commands.
    """
    bank_app = Flask(__name__, template_folder="templates")
    bank_app.secret_key = BANK_SECRET_KEY

    # Demo user registry with role-based access control
    BANK_USERS = {
        "dba": {
            "username": "dba",
            "name": "Database Administrator",
            "role": "DBA",
            "allowed_passwords": ["dba", "dba123", "admin", "admin123"],
            "password_hash": generate_password_hash("dba123"),
        },
        "clerk": {
            "username": "clerk",
            "name": "Branch Operations Clerk",
            "role": "CLERK",
            "allowed_passwords": ["clerk", "clerk123"],
            "password_hash": generate_password_hash("clerk123"),
        },
    }

    @bank_app.before_request
    def check_bank_auth():
        """
        Enforce role-based session authentication for Port 5002 Bank Portal routes.
        Redirect unauthenticated sessions to /login or return 401 for JSON endpoints.
        """
        # Allow static files and public authentication endpoints
        if request.path.startswith("/static") or request.path in ["/login", "/logout"]:
            return None

        if "bank_user" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required. Please login."}), 401
            return redirect(url_for("bank_login"))
        return None

    @bank_app.route("/login", methods=["GET", "POST"])
    def bank_login():
        """
        Authenticate bank personnel (DBA or Clerk) or process 1-click demo logins.
        :return: Rendered login page or redirect to dashboard.
        """
        if request.method == "GET":
            if "bank_user" in session:
                return redirect(url_for("dashboard"))
            return render_template(
                "bank/login.html",
                error=session.pop("bank_error", None),
                message=session.pop("bank_message", None),
            )

        # 1-Click Demo Login handler
        demo_role = request.form.get("demo_role", "").strip().lower()
        if demo_role in BANK_USERS:
            user_data = BANK_USERS[demo_role]
            session["bank_user"] = {
                "username": user_data["username"],
                "name": user_data["name"],
                "role": user_data["role"],
            }
            session["bank_message"] = f"Logged in successfully as {user_data['name']} ({user_data['role']})."
            return redirect(url_for("dashboard"))

        # Standard username/password login handler
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "").strip()

        # Alias 'admin' to 'dba'
        if username == "admin":
            username = "dba"

        user_data = BANK_USERS.get(username)
        if user_data:
            pw_match = (password in user_data["allowed_passwords"]) or check_password_hash(user_data["password_hash"], password)
            if pw_match:
                session["bank_user"] = {
                    "username": user_data["username"],
                    "name": user_data["name"],
                    "role": user_data["role"],
                }
                session["bank_message"] = f"Welcome, {user_data['name']}! Authenticated as {user_data['role']}."
                return redirect(url_for("dashboard"))

        return render_template(
            "bank/login.html",
            error="Invalid credentials. Use demo logins: 'dba / dba123' or 'clerk / clerk123'.",
            message=None,
        )

    @bank_app.route("/logout")
    def bank_logout():
        """
        Terminate bank employee session and redirect to login gateway.
        :return: Redirect to /login.
        """
        session.pop("bank_user", None)
        session["bank_message"] = "Logged out successfully."
        return redirect(url_for("bank_login"))

    @bank_app.route("/")
    def dashboard():
        """
        Bank administrator workspace with live KPIs, Account Management Hub, and Audit Stream.
        :return: HTML template (templates/bank/dashboard.html), HTTP 200.
        """
        search = request.args.get("search", "").strip()
        status_filter = request.args.get("status", "").strip()

        # 1. System KPI Aggregates
        kpi = {}
        row = db.execute_query("SELECT COUNT(*) AS total FROM customer", role="clerk", fetch="one")
        kpi["total_customers"] = row["total"] if row else 0

        row = db.execute_query("SELECT COUNT(*) AS total, COALESCE(SUM(balance), 0) AS sum_bal FROM account WHERE status = 'ACTIVE'", role="clerk", fetch="one")
        kpi["active_accounts"] = row["total"] if row else 0
        kpi["total_deposits"] = float(row["sum_bal"]) if row else 0.0

        row = db.execute_query("SELECT COUNT(*) AS total, COALESCE(SUM(current_balance), 0) AS total_cash FROM atm WHERE status = 'OPERATIONAL'", role="clerk", fetch="one")
        kpi["operational_atms"] = row["total"] if row else 0
        kpi["total_atm_cash"] = float(row["total_cash"]) if row else 0.0

        row = db.execute_query("SELECT COUNT(*) AS total FROM card WHERE status = 'BLOCKED' OR failed_pin_attempts >= 3", role="clerk", fetch="one")
        kpi["blocked_cards"] = row["total"] if row else 0

        # 2. Account Management Hub Query
        acc_sql = """
            SELECT 
                a.account_id, a.account_number, a.account_type, a.balance, a.status,
                c.firstname || ' ' || COALESCE(c.lastname, '') AS customer_name,
                c.phone_number,
                b.branch_name
            FROM account a
            JOIN customer c ON a.customer_id = c.customer_id
            JOIN branch b ON a.branch_id = b.branch_id
            WHERE 1=1
        """
        params = []
        if search:
            acc_sql += " AND (a.account_number ILIKE %s OR c.firstname ILIKE %s OR c.lastname ILIKE %s)"
            search_param = f"%{search}%"
            params.extend([search_param, search_param, search_param])
        if status_filter:
            acc_sql += " AND a.status = %s"
            params.append(status_filter)

        acc_sql += " ORDER BY a.account_id ASC LIMIT 25"
        accounts = db.execute_query(acc_sql, params, role="clerk", fetch="all") or []

        # 3. Transaction Audit Stream Query
        audit_sql = """
            SELECT 
                t.transaction_id, t.transaction_type, t.amount, t.transaction_method, t.date_time,
                a.account_number,
                c.firstname || ' ' || COALESCE(c.lastname, '') AS customer_name,
                atm.atm_location
            FROM transaction t
            JOIN account a ON t.account_id = a.account_id
            JOIN customer c ON a.customer_id = c.customer_id
            LEFT JOIN atm ON t.atm_id = atm.atm_id
            ORDER BY t.date_time DESC
            LIMIT 20
        """
        audit_logs = db.execute_query(audit_sql, role="clerk", fetch="all") or []

        # 4. Reference data for new account modal
        customers = db.execute_query("SELECT customer_id, firstname, lastname, email, phone_number FROM customer ORDER BY customer_id ASC", role="clerk", fetch="all") or []
        branches = db.execute_query("SELECT branch_id, branch_name, ifsc_code FROM branch ORDER BY branch_id ASC", role="clerk", fetch="all") or []

        return render_template(
            "bank/dashboard.html",
            kpi=kpi,
            accounts=accounts,
            audit_logs=audit_logs,
            customers=customers,
            branches=branches,
            search=search,
            status=status_filter,
            message=session.pop("bank_message", None),
            error=session.pop("bank_error", None),
        )

    @bank_app.route("/account/status", methods=["POST"])
    def update_account_status():
        """
        Update bank account lifecycle status (Soft delete / Freeze / Reactivate).
        Never physically deletes records (enforces soft-delete invariant).
        """
        account_id = request.form.get("account_id")
        new_status = request.form.get("new_status")

        if new_status not in ["ACTIVE", "FROZEN", "CLOSED", "INACTIVE"]:
            session["bank_error"] = "Invalid account status transition."
            return redirect(url_for("dashboard"))

        try:
            db.execute_query(
                "UPDATE account SET status = %s WHERE account_id = %s",
                (new_status, account_id),
                role="clerk",
                fetch="none",
            )
            session["bank_message"] = f"Account #{account_id} transitioned to {new_status}."
        except Exception as e:
            session["bank_error"] = f"Failed to update status: {str(e)}"

        return redirect(url_for("dashboard"))

    @bank_app.route("/account/create", methods=["POST"])
    def create_account():
        """
        Open a new customer bank account with assigned branch and initial ledger balance.
        Associates with existing customer profile without modifying the customer table.
        """
        try:
            customer_id = int(request.form.get("customer_id"))
            branch_id = int(request.form.get("branch_id"))
            account_type = request.form.get("account_type", "SAVINGS")
            initial_balance = float(request.form.get("initial_balance", "1000"))

            # Verify customer exists in customer table
            cust = db.execute_query(
                "SELECT customer_id, firstname, lastname FROM customer WHERE customer_id = %s",
                (customer_id,),
                role="clerk",
                fetch="one",
            )
            if not cust:
                session["bank_error"] = f"Account creation rejected: Customer ID #{customer_id} does not exist."
                return redirect(url_for("dashboard"))

            # 1. Determine next sequential account_id: strictly MAX(account_id) + 1
            max_id_row = db.execute_query(
                "SELECT COALESCE(MAX(account_id), 0) AS max_id FROM account",
                role="clerk",
                fetch="one",
            )
            next_account_id = (max_id_row["max_id"] if max_id_row else 0) + 1

            # 2. Generate structured account number in same sequential order as existing accounts (e.g. SB-10029384XX)
            account_config = {
                "SAVINGS": {"prefix": "SB", "base": "10029384"},
                "CURRENT": {"prefix": "CA", "base": "20093847"},
                "SALARY": {"prefix": "SA", "base": "10029384"},
                "FIXED_DEPOSIT": {"prefix": "FD", "base": "30019283"},
            }
            cfg = account_config.get(account_type, {"prefix": "SB", "base": "10029384"})
            prefix = cfg["prefix"]
            base = cfg["base"]

            # Query existing accounts to determine the next sequential order
            existing_accs = db.execute_query(
                "SELECT account_number FROM account",
                role="clerk",
                fetch="all",
            )
            max_seq = 0
            for acc in (existing_accs or []):
                num_val = acc.get("account_number", "")
                match = re.search(r"^[A-Z]{2}-\d{8}(\d+)$", num_val)
                if match:
                    try:
                        s_val = int(match.group(1))
                        if s_val > max_seq:
                            max_seq = s_val
                    except ValueError:
                        pass

            next_seq = max(max_seq + 1, next_account_id)

            # Ensure candidate account number is unique and increments cleanly
            while True:
                candidate_acc_num = f"{prefix}-{base}{next_seq:02d}"
                exists = db.execute_query(
                    "SELECT 1 FROM account WHERE account_number = %s",
                    (candidate_acc_num,),
                    role="clerk",
                    fetch="one",
                )
                if not exists:
                    acc_num = candidate_acc_num
                    break
                next_seq += 1

            # 3. Insert new account with explicit incrementing account_id
            db.execute_query(
                """
                INSERT INTO account (account_id, account_number, account_type, balance, status, date_time, customer_id, branch_id)
                OVERRIDING SYSTEM VALUE
                VALUES (%s, %s, %s, %s, 'ACTIVE', CURRENT_TIMESTAMP, %s, %s)
                """,
                (next_account_id, acc_num, account_type, initial_balance, customer_id, branch_id),
                role="clerk",
                fetch="none",
            )

            # 4. Synchronize the PostgreSQL identity sequence to maintain alignment
            try:
                db.execute_query(
                    "SELECT setval(pg_get_serial_sequence('account', 'account_id'), %s)",
                    (next_account_id,),
                    role="clerk",
                    fetch="one",
                )
            except Exception as seq_err:
                logger.warning(f"Could not update account_account_id_seq: {seq_err}")

            cust_name = f"{cust['firstname']} {cust['lastname'] or ''}".strip()
            session["bank_message"] = f"Successfully opened account #{next_account_id} ({acc_num}) for customer '{cust_name}' with ₹{initial_balance:,.2f}."
        except Exception as e:
            session["bank_error"] = f"Account creation failed: {str(e)}"

        return redirect(url_for("dashboard"))

    @bank_app.route("/api/customer/create", methods=["POST"])
    def api_create_customer():
        """
        Register a new bank customer profile or reuse existing customer if already present.
        Ensures duplicate customers are NEVER added to the customer table.
        Accepts JSON or form data and returns structured JSON payload.
        """
        data = request.get_json(silent=True) or request.form.to_dict()
        firstname = data.get("firstname", "").strip()
        lastname = data.get("lastname", "").strip()
        dob = data.get("dob", "").strip()
        gender = data.get("gender", "Other").strip()
        phone_number = data.get("phone_number", "").strip()
        email = data.get("email", "").strip()
        address_text = data.get("address", "").strip()

        if not firstname or not dob or not phone_number or not email:
            return jsonify({"error": "First Name, Date of Birth, Phone Number, and Email are required."}), 400

        try:
            # Check if customer already exists by email, phone, or exact full name
            existing = db.execute_query(
                """
                SELECT customer_id, firstname, lastname, email, phone_number 
                FROM customer 
                WHERE LOWER(email) = LOWER(%s)
                   OR phone_number = %s
                   OR (LOWER(TRIM(firstname)) = LOWER(TRIM(%s)) AND LOWER(COALESCE(TRIM(lastname), '')) = LOWER(COALESCE(TRIM(%s), '')))
                LIMIT 1
                """,
                (email, phone_number, firstname, lastname),
                role="clerk",
                fetch="one",
            )
            if existing:
                full_name = f"{existing['firstname']} {existing['lastname'] or ''}".strip()
                return jsonify({
                    "success": True,
                    "already_exists": True,
                    "message": f"Customer '{full_name}' already exists (ID #{existing['customer_id']}). Reusing existing profile.",
                    "customer": {
                        "customer_id": existing["customer_id"],
                        "firstname": existing["firstname"],
                        "lastname": existing["lastname"] or "",
                        "email": existing["email"],
                        "phone_number": existing["phone_number"],
                    }
                }), 200

            # Only insert if customer does not already exist
            with db.get_db_connection("clerk") as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO customer (firstname, lastname, dob, phone_number, email, gender)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING customer_id, firstname, lastname, email, phone_number
                        """,
                        (firstname, lastname or None, dob, phone_number, email, gender),
                    )
                    new_cust = cur.fetchone()
                    new_id = new_cust["customer_id"]

                    if address_text:
                        cur.execute(
                            "INSERT INTO address (customer_id, address) VALUES (%s, %s)",
                            (new_id, address_text),
                        )
                conn.commit()

            return jsonify({
                "success": True,
                "already_exists": False,
                "message": f"Customer '{firstname} {lastname}' created successfully.",
                "customer": {
                    "customer_id": new_cust["customer_id"],
                    "firstname": new_cust["firstname"],
                    "lastname": new_cust["lastname"] or "",
                    "email": new_cust["email"],
                    "phone_number": new_cust["phone_number"],
                }
            }), 201
        except Exception as e:
            logger.error(f"Customer creation failed: {e}")
            return jsonify({"error": f"Failed to register customer: {str(e)}"}), 500

    @bank_app.route("/customer/create", methods=["POST"])
    def form_create_customer():
        """Standard form POST endpoint for customer creation."""
        res = api_create_customer()
        resp_obj, status_code = (res if isinstance(res, tuple) else (res, 200))
        data = resp_obj.get_json() if hasattr(resp_obj, "get_json") else {}
        if status_code in [200, 201]:
            session["bank_message"] = data.get("message", "Customer registered successfully.")
        else:
            session["bank_error"] = data.get("error", "Customer creation failed.")
        return redirect(url_for("dashboard"))

    @bank_app.route("/api/account/<int:account_id>/details")
    def api_account_details(account_id):
        """
        Fetch full comprehensive profile for a given account:
        customer details (including age, dob, phone, email, address),
        account details, home branch, linked cards, and transaction records.
        """
        try:
            sql = """
                SELECT 
                    a.account_id, a.account_number, a.account_type, a.balance, a.status, a.date_time AS account_created_at,
                    c.customer_id, c.firstname, c.lastname, c.dob, c.age, c.gender, c.phone_number, c.email,
                    COALESCE(addr.address, 'No address registered') AS customer_address,
                    b.branch_id, b.branch_name, b.ifsc_code, b.address AS branch_address, b.pin_code
                FROM account a
                JOIN customer c ON a.customer_id = c.customer_id
                JOIN branch b ON a.branch_id = b.branch_id
                LEFT JOIN address addr ON c.customer_id = addr.customer_id
                WHERE a.account_id = %s
            """
            row = db.execute_query(sql, (account_id,), role="clerk", fetch="one")
            if not row:
                return jsonify({"error": f"Account #{account_id} not found."}), 404

            cards_sql = """
                SELECT 
                    card_id, card_number, card_type, status, failed_pin_attempts, expiry_date
                FROM card
                WHERE account_id = %s
                ORDER BY card_id ASC
            """
            cards = db.execute_query(cards_sql, (account_id,), role="clerk", fetch="all") or []

            tx_sql = """
                SELECT 
                    t.transaction_id, t.transaction_type, t.amount, t.transaction_method, t.date_time,
                    COALESCE(atm.atm_location, 'Branch / Internal') AS atm_location,
                    c.card_number
                FROM transaction t
                LEFT JOIN atm ON t.atm_id = atm.atm_id
                LEFT JOIN card c ON t.card_id = c.card_id
                WHERE t.account_id = %s
                ORDER BY t.date_time DESC
                LIMIT 25
            """
            transactions = db.execute_query(tx_sql, (account_id,), role="clerk", fetch="all") or []

            account_data = {
                "account_id": row["account_id"],
                "account_number": row["account_number"],
                "account_type": row["account_type"],
                "balance": float(row["balance"]),
                "status": row["status"],
                "created_at": row["account_created_at"].strftime("%Y-%m-%d %H:%M:%S") if row["account_created_at"] else "N/A"
            }
            customer_data = {
                "customer_id": row["customer_id"],
                "firstname": row["firstname"],
                "lastname": row["lastname"] or "",
                "full_name": f"{row['firstname']} {row['lastname'] or ''}".strip(),
                "dob": str(row["dob"]) if row["dob"] else "N/A",
                "age": row["age"],
                "gender": row["gender"],
                "phone_number": row["phone_number"],
                "email": row["email"],
                "address": row["customer_address"],
            }
            branch_data = {
                "branch_id": row["branch_id"],
                "branch_name": row["branch_name"],
                "ifsc_code": row["ifsc_code"],
                "address": row["branch_address"],
                "pin_code": row["pin_code"],
            }
            formatted_cards = []
            for c in cards:
                formatted_cards.append({
                    "card_id": c["card_id"],
                    "card_number": c["card_number"],
                    "card_type": c["card_type"],
                    "status": c["status"],
                    "failed_pin_attempts": c["failed_pin_attempts"],
                    "expiry_date": str(c["expiry_date"]) if c["expiry_date"] else "N/A"
                })

            formatted_txs = []
            for t in transactions:
                formatted_txs.append({
                    "transaction_id": t["transaction_id"],
                    "transaction_type": t["transaction_type"],
                    "amount": float(t["amount"]),
                    "transaction_method": t["transaction_method"],
                    "date_time": t["date_time"].strftime("%Y-%m-%d %H:%M:%S") if t["date_time"] else "N/A",
                    "atm_location": t["atm_location"],
                    "card_number": t["card_number"][-4:] if t.get("card_number") else "N/A"
                })

            return jsonify({
                "success": True,
                "account": account_data,
                "customer": customer_data,
                "branch": branch_data,
                "cards": formatted_cards,
                "transactions": formatted_txs,
            }), 200
        except Exception as e:
            logger.error(f"Error fetching account details: {e}")
            return jsonify({"error": f"Failed to retrieve account details: {str(e)}"}), 500

    @bank_app.route("/api/account/<int:account_id>/card/create", methods=["POST"])
    def api_create_card(account_id):
        """
        Issue and link a new card to the specified bank account.
        Generates a unique 16-digit card number and securely hashes the 4-digit PIN via werkzeug.
        """
        try:
            data = request.get_json(silent=True) or request.form.to_dict()
            card_type = (data.get("card_type") or "DEBIT").upper().strip()
            pin = (data.get("pin") or "1234").strip()
            validity_years = int(data.get("validity_years") or 5)

            if card_type not in ["DEBIT", "CREDIT"]:
                return jsonify({"error": "Card type must be either 'DEBIT' or 'CREDIT'."}), 400

            if not pin.isdigit() or len(pin) != 4:
                return jsonify({"error": "PIN must be exactly 4 numeric digits."}), 400

            # Verify account exists and is not CLOSED
            acc = db.execute_query(
                "SELECT account_id, status, account_number FROM account WHERE account_id = %s",
                (account_id,),
                role="clerk",
                fetch="one",
            )
            if not acc:
                return jsonify({"error": f"Account #{account_id} not found."}), 404
            if acc["status"] == "CLOSED":
                return jsonify({"error": "Cannot issue cards for a CLOSED account."}), 400

            # Generate unique 16-digit card number
            prefix = "4532" if card_type == "DEBIT" else "5241"
            import random
            while True:
                random_digits = "".join([str(random.randint(0, 9)) for _ in range(12)])
                candidate_number = f"{prefix}{random_digits}"
                existing_card = db.execute_query(
                    "SELECT card_id FROM card WHERE card_number = %s",
                    (candidate_number,),
                    role="clerk",
                    fetch="one",
                )
                if not existing_card:
                    break

            # Hash the PIN via Werkzeug
            pin_hash = generate_password_hash(pin)

            # Insert card & card_security within a transaction
            with db.get_db_connection("clerk") as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO card (card_number, card_type, status, failed_pin_attempts, expiry_date, account_id)
                        VALUES (%s, %s, 'ACTIVE', 0, CURRENT_DATE + (%s || ' years')::INTERVAL, %s)
                        RETURNING card_id, card_number, card_type, status, expiry_date
                        """,
                        (candidate_number, card_type, validity_years, account_id),
                    )
                    new_card = cur.fetchone()
                    new_card_id = new_card["card_id"]

                    cur.execute(
                        "INSERT INTO card_security (card_id, pin_hash) VALUES (%s, %s)",
                        (new_card_id, pin_hash),
                    )
                conn.commit()

            return jsonify({
                "success": True,
                "message": f"Successfully issued new {card_type} card {candidate_number} with PIN {pin}.",
                "card": {
                    "card_id": new_card["card_id"],
                    "card_number": new_card["card_number"],
                    "card_type": new_card["card_type"],
                    "status": new_card["status"],
                    "failed_pin_attempts": 0,
                    "expiry_date": str(new_card["expiry_date"]),
                }
            }), 201
        except Exception as e:
            logger.error(f"Card issuance failed: {e}")
            return jsonify({"error": f"Failed to issue card: {str(e)}"}), 500

    @bank_app.route("/api/card/<int:card_id>/unblock", methods=["POST"])
    def api_unblock_card(card_id):
        """
        Unblock and reactivate a blocked payment card.
        Resets failed_pin_attempts to 0 and transitions status to 'ACTIVE'.
        """
        try:
            card = db.execute_query(
                """
                SELECT c.card_id, c.card_number, c.status, a.status AS account_status, a.account_number
                FROM card c
                JOIN account a ON c.account_id = a.account_id
                WHERE c.card_id = %s
                """,
                (card_id,),
                role="clerk",
                fetch="one",
            )
            if not card:
                return jsonify({"error": f"Card #{card_id} not found."}), 404

            if card["account_status"] == "CLOSED":
                return jsonify({"error": "Cannot reactivate card: Linked bank account is CLOSED."}), 400

            db.execute_query(
                """
                UPDATE card 
                SET status = 'ACTIVE', failed_pin_attempts = 0 
                WHERE card_id = %s
                """,
                (card_id,),
                role="clerk",
                fetch="none",
            )

            card_num = card["card_number"]
            formatted_card = f"•••• {card_num[-4:]}"
            return jsonify({
                "success": True,
                "message": f"Card {formatted_card} successfully unblocked and reactivated with 0 failed attempts.",
                "card_id": card_id,
                "status": "ACTIVE",
                "failed_pin_attempts": 0,
            }), 200
        except Exception as e:
            logger.error(f"Failed to unblock card: {e}")
            return jsonify({"error": f"Failed to unblock card: {str(e)}"}), 500

    @bank_app.route("/api/card/<int:card_id>/status", methods=["POST"])
    def api_update_card_status(card_id):
        """
        Update status of a payment card (ACTIVE or BLOCKED).
        """
        try:
            data = request.get_json(silent=True) or request.form.to_dict()
            new_status = (data.get("status") or "ACTIVE").upper().strip()

            if new_status not in ["ACTIVE", "BLOCKED"]:
                return jsonify({"error": "Status must be either 'ACTIVE' or 'BLOCKED'."}), 400

            card = db.execute_query(
                """
                SELECT c.card_id, c.card_number, a.status AS account_status
                FROM card c
                JOIN account a ON c.account_id = a.account_id
                WHERE c.card_id = %s
                """,
                (card_id,),
                role="clerk",
                fetch="one",
            )
            if not card:
                return jsonify({"error": f"Card #{card_id} not found."}), 404

            if new_status == "ACTIVE" and card["account_status"] == "CLOSED":
                return jsonify({"error": "Cannot activate card for a CLOSED bank account."}), 400

            attempts = 0 if new_status == "ACTIVE" else 3
            db.execute_query(
                """
                UPDATE card 
                SET status = %s, failed_pin_attempts = %s 
                WHERE card_id = %s
                """,
                (new_status, attempts, card_id),
                role="clerk",
                fetch="none",
            )

            card_last4 = card["card_number"][-4:]
            return jsonify({
                "success": True,
                "message": f"Card •••• {card_last4} status updated to {new_status}.",
                "card_id": card_id,
                "status": new_status,
                "failed_pin_attempts": attempts,
            }), 200
        except Exception as e:
            logger.error(f"Failed to update card status: {e}")
            return jsonify({"error": f"Failed to update card status: {str(e)}"}), 500

    @bank_app.route("/audit")
    def audit_ledger():
        """
        Dedicated Transaction Audit Ledger Section: Renders ATM transaction history
        with multi-field search, operation type filter, calendar date filter, and multi-field sorting.
        :return: HTML template (templates/bank/audit.html), HTTP 200.
        """
        search = request.args.get("search", "").strip()
        tx_type = request.args.get("type", "").strip()
        date_filter = request.args.get("date", "").strip()
        sort_by = request.args.get("sort_by", "").strip() or request.args.get("sort", "timestamp_desc").strip()

        # Aggregate Statistics strictly for ATM transactions
        stats = {}
        row = db.execute_query(
            """
            SELECT 
                COUNT(*) AS total_count,
                COALESCE(SUM(amount), 0) AS total_volume,
                COALESCE(SUM(CASE WHEN transaction_type = 'WITHDRAWAL' THEN amount ELSE 0 END), 0) AS withdrawal_volume,
                COALESCE(COUNT(CASE WHEN transaction_type = 'WITHDRAWAL' THEN 1 END), 0) AS withdrawal_count,
                COALESCE(SUM(CASE WHEN transaction_type = 'DEPOSIT' THEN amount ELSE 0 END), 0) AS deposit_volume,
                COALESCE(COUNT(CASE WHEN transaction_type = 'DEPOSIT' THEN 1 END), 0) AS deposit_count
            FROM transaction
            WHERE transaction_method = 'ATM'
            """,
            role="clerk",
            fetch="one",
        )
        if row:
            stats["total_count"] = row["total_count"]
            stats["total_volume"] = float(row["total_volume"])
            stats["withdrawal_volume"] = float(row["withdrawal_volume"])
            stats["withdrawal_count"] = row["withdrawal_count"]
            stats["deposit_volume"] = float(row["deposit_volume"])
            stats["deposit_count"] = row["deposit_count"]
        else:
            stats = {"total_count": 0, "total_volume": 0.0, "withdrawal_volume": 0.0, "withdrawal_count": 0, "deposit_volume": 0.0, "deposit_count": 0}

        # Filtered Relational Query - strictly only transactions done through ATM
        sql = """
            SELECT 
                t.transaction_id,
                t.transaction_type,
                t.amount,
                t.transaction_method,
                t.date_time,
                a.account_id,
                a.account_number,
                c.firstname || ' ' || COALESCE(c.lastname, '') AS customer_name,
                c.phone_number,
                b.branch_name,
                b.ifsc_code,
                atm.terminal_code,
                atm.atm_location,
                cd.card_number,
                cd.card_type
            FROM transaction t
            JOIN account a ON t.account_id = a.account_id
            JOIN customer c ON a.customer_id = c.customer_id
            JOIN branch b ON a.branch_id = b.branch_id
            LEFT JOIN atm ON t.atm_id = atm.atm_id
            LEFT JOIN card cd ON t.card_id = cd.card_id
            WHERE t.transaction_method = 'ATM'
        """
        params = []
        if search:
            sql += " AND (a.account_number ILIKE %s OR CAST(a.account_id AS TEXT) ILIKE %s OR CAST(t.transaction_id AS TEXT) ILIKE %s OR c.firstname ILIKE %s OR c.lastname ILIKE %s OR c.phone_number ILIKE %s OR atm.terminal_code ILIKE %s OR atm.atm_location ILIKE %s)"
            sp = f"%{search}%"
            params.extend([sp, sp, sp, sp, sp, sp, sp, sp])
        if tx_type:
            sql += " AND t.transaction_type = %s"
            params.append(tx_type)
        if date_filter:
            sql += " AND DATE(t.date_time) = %s"
            params.append(date_filter)

        # Multi-attribute sorting
        if sort_by in ["tx_id_asc", "tx_id"]:
            sql += " ORDER BY t.transaction_id ASC"
        elif sort_by == "tx_id_desc":
            sql += " ORDER BY t.transaction_id DESC"
        elif sort_by in ["amount_asc", "lowest"]:
            sql += " ORDER BY t.amount ASC, t.transaction_id ASC"
        elif sort_by in ["amount_desc", "highest"]:
            sql += " ORDER BY t.amount DESC, t.transaction_id DESC"
        elif sort_by in ["account_id_asc", "account_id"]:
            sql += " ORDER BY a.account_id ASC, t.transaction_id DESC"
        elif sort_by == "account_id_desc":
            sql += " ORDER BY a.account_id DESC, t.transaction_id DESC"
        elif sort_by in ["timestamp_asc", "oldest"]:
            sql += " ORDER BY t.date_time ASC, t.transaction_id ASC"
        else:  # default timestamp_desc / newest
            sort_by = "timestamp_desc"
            sql += " ORDER BY t.date_time DESC, t.transaction_id DESC"

        sql += " LIMIT 100"
        logs = db.execute_query(sql, params, role="clerk", fetch="all") or []

        return render_template(
            "bank/audit.html",
            stats=stats,
            logs=logs,
            search=search,
            tx_type=tx_type,
            date_filter=date_filter,
            sort_by=sort_by,
        )

    @bank_app.route("/reports")
    def reports_view():
        """
        Display DBMS Syllabus Evaluation analytical reports and presets engine.
        :return: HTML template (templates/bank/reports.html)
        """
        return render_template("bank/reports.html")

    @bank_app.route("/terminal")
    def terminal_view():
        """
        Display restricted administrative pseudo-terminal CLI console.
        Strictly restricted to DBA role.
        :return: HTML template (templates/bank/terminal.html) or redirect to dashboard.
        """
        user = session.get("bank_user", {})
        if user.get("role") != "DBA":
            session["bank_error"] = "Access Denied: SQL Console is strictly restricted to DBA users."
            return redirect(url_for("dashboard"))
        return render_template("bank/terminal.html")

    @bank_app.route("/api/terminal/execute", methods=["POST"])
    def terminal_execute():
        """
        API endpoint for executing raw SQL statements from the web CLI console.
        Uses the 'atm_dba' database role to allow schema inspections.
        Strictly restricted to DBA role.
        :return: JSON payload with columns, rows, execution time, or error description.
        """
        user = session.get("bank_user", {})
        if user.get("role") != "DBA":
            return jsonify({"error": "Unauthorized: SQL Console execution is strictly restricted to DBA role."}), 403

        data = request.get_json(silent=True) or {}
        cmd = data.get("query", "").strip()

        if not cmd:
            return jsonify({"error": "Empty command submitted."}), 400

        # Support psql metacommand shortcuts
        if cmd == r"\dt":
            cmd = "SELECT schemaname, tablename, tableowner FROM pg_tables WHERE schemaname = 'public';"
        elif cmd == r"\dv":
            cmd = "SELECT table_name, view_definition FROM information_schema.views WHERE table_schema = 'public';"

        start_time = time.time()
        try:
            with db.get_db_connection("admin") as conn:
                with conn.cursor() as cur:
                    cur.execute(cmd)
                    if cur.description:
                        rows = cur.fetchall()
                        columns = [desc[0] for desc in cur.description]
                        exec_time = round((time.time() - start_time) * 1000, 2)
                        return jsonify({
                            "columns": columns,
                            "rows": rows,
                            "execution_time": exec_time,
                        })
                    else:
                        conn.commit()
                        exec_time = round((time.time() - start_time) * 1000, 2)
                        return jsonify({
                            "message": f"Statement executed successfully. (Time: {exec_time}ms)",
                            "execution_time": exec_time,
                        })
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    return bank_app


# ============================================================================
# DUAL-PORT MULTI-THREADED SERVER RUNNER
# ============================================================================
def run_atm_server(atm_app: Flask) -> None:
    """Run Port 5001 server in isolated worker thread."""
    logger.info("Initializing ATM Customer Interface on http://localhost:5001")
    atm_app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False)


def run_bank_server(bank_app: Flask) -> None:
    """Run Port 5002 server in isolated worker thread."""
    logger.info("Initializing Bank Management & Audit Portal on http://localhost:5002")
    bank_app.run(host="0.0.0.0", port=5002, debug=False, use_reloader=False)


def main():
    """
    Entry point for the application. Initializes database connection pools
    and launches both localized web servers on separate daemon threads.
    """
    print("=" * 72)
    print(" ATM TRANSACTION LOGGING & MANAGEMENT SYSTEM (DBMS MINI-PROJECT)")
    print("=" * 72)

    # Initialize PostgreSQL connection pools
    try:
        db.init_pools()
    except Exception as e:
        logger.error(f"Failed to connect to database atls_db: {e}")
        sys.exit(1)

    atm_app = create_atm_app()
    bank_app = create_bank_app()

    # Launch Port 5001 (ATM Terminal) thread
    t1 = threading.Thread(target=run_atm_server, args=(atm_app,), daemon=True)
    t1.start()

    # Launch Port 5002 (Bank Admin Portal) thread
    t2 = threading.Thread(target=run_bank_server, args=(bank_app,), daemon=True)
    t2.start()

    print("\n[+] Port 5001: ATM Terminal Interface    --> http://localhost:5001")
    print("[+] Port 5002: Bank Management & Reports --> http://localhost:5002")
    print("\nPress Ctrl+C to terminate both servers.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[!] Shutting down ATM & Bank servers...")


if __name__ == "__main__":
    main()
