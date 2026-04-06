from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from datetime import datetime
import time
from db import get_conn, log_activity
from modules.core.utils import login_required, admin_required

baddebt_bp = Blueprint("baddebt", __name__)



@baddebt_bp.route("/")
@login_required
@admin_required
def dashboard():
    """Display all bad debt write-offs"""
    conn = get_conn()
    cur = conn.cursor()

    # Get all write-offs with related invoice and student details
    cur.execute("""
        SELECT
            bw.id,
            bw.invoice_id,
            bw.amount_written_off,
            bw.paid_amount,
            bw.reason,
            bw.student_status_at_writeoff,
            bw.writeoff_date,
            bw.notes,
            i.invoice_no,
            i.status AS invoice_status,
            i.total_amount,
            s.full_name AS student_name,
            s.student_code,
            s.status AS student_status,
            u.full_name AS authorized_by,
            bw.created_at
        FROM bad_debt_writeoffs bw
        JOIN invoices i ON bw.invoice_id = i.id
        JOIN students s ON i.student_id = s.id
        LEFT JOIN users u ON bw.authorized_by = u.id
        ORDER BY bw.writeoff_date DESC
    """)
    write_offs = cur.fetchall()

    # Calculate totals
    total_written_off = sum(float(row["amount_written_off"] or 0) for row in write_offs)
    count = len(write_offs)

    conn.close()

    return render_template(
        "baddebt/dashboard.html",
        write_offs=write_offs,
        total_written_off=total_written_off,
        count=count
    )


@baddebt_bp.route("/create", methods=["GET", "POST"])
@login_required
@admin_required
def create():
    """Create a new bad debt write-off"""
    if request.method == "POST":
        invoice_id = request.form.get("invoice_id", "").strip()
        amount_written_off = request.form.get("amount_written_off", "").strip()
        reason = request.form.get("reason", "").strip()
        student_status = request.form.get("student_status", "").strip()
        notes = request.form.get("notes", "").strip()

        # Validation
        if not invoice_id or not amount_written_off or not reason:
            flash("Please fill in all required fields", "error")
            return redirect(url_for("baddebt.create"))

        try:
            amount_written_off = float(amount_written_off)
        except ValueError:
            flash("Invalid amount entered", "error")
            return redirect(url_for("baddebt.create"))

        if amount_written_off <= 0:
            flash("Amount must be greater than 0", "error")
            return redirect(url_for("baddebt.create"))

        conn = get_conn()
        cur = conn.cursor()

        # Get invoice details
        cur.execute("""
            SELECT
                i.id,
                i.invoice_no,
                i.total_amount,
                i.student_id,
                i.branch_id,
                s.student_code,
                s.status AS student_status,
                (SELECT IFNULL(SUM(amount_received), 0) FROM receipts WHERE invoice_id = i.id) AS paid_amount
            FROM invoices i
            JOIN students s ON i.student_id = s.id
            WHERE i.id = ?
        """, (invoice_id,))
        invoice = cur.fetchone()

        if not invoice:
            flash("Invoice not found", "error")
            conn.close()
            return redirect(url_for("baddebt.create"))

        invoice_id = invoice["id"]
        paid_amount = float(invoice["paid_amount"] or 0)
        total_amount = float(invoice["total_amount"] or 0)
        balance = total_amount - paid_amount

        if amount_written_off > balance:
            flash(f"Write-off amount (₹{amount_written_off}) cannot exceed balance (₹{balance})", "error")
            conn.close()
            return redirect(url_for("baddebt.create"))

        # Close the initial connection to avoid locking issues
        conn.close()

        try:
            conn = get_conn()
            conn.isolation_level = None  # Autocommit mode
            cur = conn.cursor()

            try:
                now = datetime.now().isoformat(timespec="seconds")
                user_id = session.get("user_id")
                branch_id = invoice["branch_id"]

                # Start explicit transaction
                cur.execute("BEGIN IMMEDIATE")

                # Insert write-off record
                cur.execute("""
                    INSERT INTO bad_debt_writeoffs (
                        invoice_id,
                        amount_written_off,
                        paid_amount,
                        reason,
                        student_status_at_writeoff,
                        authorized_by,
                        writeoff_date,
                        notes,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    invoice_id,
                    amount_written_off,
                    paid_amount,
                    reason,
                    student_status or invoice["student_status"],
                    user_id,
                    datetime.now().date().isoformat(),
                    notes,
                    now,
                    now
                ))

                write_off_id = cur.lastrowid

                # Get expense category
                cur.execute("""
                    SELECT id FROM expense_categories WHERE category_name = 'Uncollectible Receivables'
                """)
                category = cur.fetchone()

                if category:
                    category_id = category["id"]
                    expense_description = (
                        f"Bad Debt Write-off - Invoice {invoice['invoice_no']} - "
                        f"Student: {invoice['student_code']} - Reason: {reason}"
                    )

                    cur.execute("""
                        INSERT INTO expenses (
                            expense_date,
                            branch_id,
                            category_id,
                            title,
                            amount,
                            payment_mode,
                            reference_no,
                            notes,
                            created_by,
                            created_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        datetime.now().date().isoformat(),
                        branch_id,
                        category_id,
                        f"Bad Debt Write-off - {invoice['invoice_no']}",
                        amount_written_off,
                        "cash",
                        f"WO-{write_off_id}",
                        expense_description,
                        user_id,
                        now,
                        now
                    ))

                # Update invoice status
                if round(balance - amount_written_off, 2) <= 0:
                    new_status = "write_off"
                else:
                    new_status = "partially_written_off"

                cur.execute("""
                    UPDATE invoices
                    SET status = ?, updated_at = ?
                    WHERE id = ?
                """, (new_status, now, invoice_id))

                # Mark all unpaid installment_plans for this invoice as written_off
                # so they no longer appear in receivables
                cur.execute("""
                    UPDATE installment_plans
                    SET status = 'paid', amount_paid = amount_due,
                        remarks = 'Written off', updated_at = ?
                    WHERE invoice_id = ? AND status != 'paid'
                """, (now, invoice_id))

                # Commit transaction
                cur.execute("COMMIT")
                conn.close()

                # Log activity after transaction is committed
                log_activity(
                    user_id,
                    branch_id,
                    "create",
                    "Bad Debt Write-off",
                    write_off_id,
                    f"Created write-off of ₹{amount_written_off} for Invoice {invoice['invoice_no']} - Reason: {reason}"
                )

                flash(f"Bad debt write-off of ₹{amount_written_off} created successfully", "success")
                return redirect(url_for("baddebt.dashboard"))

            except Exception as e:
                cur.execute("ROLLBACK")
                conn.close()
                raise

        except Exception as e:
            flash(f"Error creating write-off: {str(e)}", "error")
            return redirect(url_for("baddebt.create"))

    # GET request - show form
    conn = get_conn()
    cur = conn.cursor()

    # Get pre-selected invoice if passed from invoice view
    pre_selected_invoice = None
    invoice_id_param = request.args.get("invoice_id", "").strip()
    if invoice_id_param:
        try:
            cur.execute("""
                SELECT
                    i.id,
                    i.invoice_no,
                    i.total_amount,
                    s.full_name AS student_name,
                    s.student_code,
                    s.status AS student_status,
                    (SELECT IFNULL(SUM(amount_received), 0) FROM receipts WHERE invoice_id = i.id) AS paid_amount,
                    i.branch_id
                FROM invoices i
                JOIN students s ON i.student_id = s.id
                WHERE i.id = ? AND i.status IN ('unpaid', 'partially_paid')
            """, (invoice_id_param,))
            pre_selected_invoice = cur.fetchone()
        except:
            pass

    # Get invoices with pending balance
    cur.execute("""
        SELECT
            i.id,
            i.invoice_no,
            i.total_amount,
            s.full_name AS student_name,
            s.student_code,
            s.status AS student_status,
            (SELECT IFNULL(SUM(amount_received), 0) FROM receipts WHERE invoice_id = i.id) AS paid_amount,
            i.branch_id
        FROM invoices i
        JOIN students s ON i.student_id = s.id
        WHERE i.status IN ('unpaid', 'partially_paid')
        ORDER BY i.invoice_no DESC
    """)
    invoices = cur.fetchall()

    conn.close()

    return render_template("baddebt/create.html", invoices=invoices, pre_selected_invoice=pre_selected_invoice)


@baddebt_bp.route("/view/<int:writeoff_id>")
@login_required
@admin_required
def view(writeoff_id):
    """View details of a bad debt write-off"""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            bw.id,
            bw.invoice_id,
            bw.amount_written_off,
            bw.paid_amount,
            bw.reason,
            bw.student_status_at_writeoff,
            bw.writeoff_date,
            bw.notes,
            i.invoice_no,
            i.status AS invoice_status,
            i.total_amount,
            i.invoice_date,
            s.full_name AS student_name,
            s.student_code,
            s.phone,
            s.status AS student_status,
            u.full_name AS authorized_by,
            u.id AS authorized_by_id,
            bw.created_at,
            b.branch_name
        FROM bad_debt_writeoffs bw
        JOIN invoices i ON bw.invoice_id = i.id
        JOIN students s ON i.student_id = s.id
        LEFT JOIN users u ON bw.authorized_by = u.id
        LEFT JOIN branches b ON i.branch_id = b.id
        WHERE bw.id = ?
    """, (writeoff_id,))
    write_off = cur.fetchone()

    if not write_off:
        flash("Write-off record not found", "error")
        conn.close()
        return redirect(url_for("baddebt.dashboard"))

    # Get related expense record
    cur.execute("""
        SELECT
            id,
            expense_date,
            amount,
            reference_no,
            notes
        FROM expenses
        WHERE reference_no = ?
    """, (f"WO-{writeoff_id}",))
    expense = cur.fetchone()

    conn.close()

    return render_template(
        "baddebt/view.html",
        write_off=write_off,
        expense=expense
    )


@baddebt_bp.route("/api/get-invoice/<int:invoice_id>")
@login_required
@admin_required
def get_invoice_details(invoice_id):
    """API endpoint to get invoice details for form"""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            i.id,
            i.invoice_no,
            i.total_amount,
            s.full_name AS student_name,
            s.student_code,
            s.status AS student_status,
            (SELECT IFNULL(SUM(amount_received), 0) FROM receipts WHERE invoice_id = i.id) AS paid_amount
        FROM invoices i
        JOIN students s ON i.student_id = s.id
        WHERE i.id = ?
    """, (invoice_id,))
    invoice = cur.fetchone()

    conn.close()

    if not invoice:
        return jsonify({"error": "Invoice not found"}), 404

    paid_amount = float(invoice["paid_amount"] or 0)
    balance = float(invoice["total_amount"] or 0) - paid_amount

    return jsonify({
        "invoice_no": invoice["invoice_no"],
        "student_name": invoice["student_name"],
        "student_code": invoice["student_code"],
        "student_status": invoice["student_status"],
        "total_amount": float(invoice["total_amount"] or 0),
        "paid_amount": paid_amount,
        "balance": balance
    })


@baddebt_bp.route("/delete/<int:writeoff_id>", methods=["POST"])
@login_required
@admin_required
def delete(writeoff_id):
    """Delete a bad debt write-off"""
    conn = get_conn()
    conn.isolation_level = None  # Autocommit mode
    cur = conn.cursor()

    cur.execute("""
        SELECT invoice_id, amount_written_off FROM bad_debt_writeoffs WHERE id = ?
    """, (writeoff_id,))
    write_off = cur.fetchone()

    if not write_off:
        flash("Write-off record not found", "error")
        conn.close()
        return redirect(url_for("baddebt.dashboard"))

    try:
        now = datetime.now().isoformat(timespec="seconds")
        user_id = session.get("user_id")

        # Start explicit transaction
        cur.execute("BEGIN IMMEDIATE")

        # Delete from bad_debt_writeoffs
        cur.execute("DELETE FROM bad_debt_writeoffs WHERE id = ?", (writeoff_id,))

        # Delete related expense
        cur.execute("DELETE FROM expenses WHERE reference_no = ?", (f"WO-{writeoff_id}",))

        # Update invoice status back to original
        invoice_id = write_off["invoice_id"]
        cur.execute("""
            SELECT total_amount, (SELECT IFNULL(SUM(amount_received), 0) FROM receipts WHERE invoice_id = ?) AS paid_amount
            FROM invoices WHERE id = ?
        """, (invoice_id, invoice_id))
        invoice = cur.fetchone()

        if invoice:
            paid_amount = float(invoice["paid_amount"] or 0)
            total_amount = float(invoice["total_amount"] or 0)

            if paid_amount >= total_amount:
                new_status = "paid"
            elif paid_amount > 0:
                new_status = "partially_paid"
            else:
                new_status = "unpaid"

            cur.execute("""
                UPDATE invoices SET status = ?, updated_at = ? WHERE id = ?
            """, (new_status, now, invoice_id))

        # Commit transaction
        cur.execute("COMMIT")
        conn.close()

        # Log activity after transaction is committed
        log_activity(
            user_id,
            None,
            "delete",
            "Bad Debt Write-off",
            writeoff_id,
            f"Deleted write-off of ₹{write_off['amount_written_off']}"
        )

        flash("Bad debt write-off deleted successfully", "success")
        return redirect(url_for("baddebt.dashboard"))

    except Exception as e:
        try:
            cur.execute("ROLLBACK")
        except:
            pass
        conn.close()
        flash(f"Error deleting write-off: {str(e)}", "error")
        return redirect(url_for("baddebt.dashboard"))
