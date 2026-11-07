from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from datetime import datetime
from db import get_conn, log_activity
from config import Config
from modules.core.utils import login_required, admin_required
from services.tenant_context import get_current_institute_id
from services.document_numbers import allocate_document_number, derive_writeoff_prefix

baddebt_bp = Blueprint("baddebt", __name__)


def _begin_write_transaction(cur):
    if getattr(Config, "DB_TYPE", "sqlite") == "mysql":
        cur.execute("START TRANSACTION")
    else:
        cur.execute("BEGIN IMMEDIATE")


def _for_update_clause():
    return " FOR UPDATE" if getattr(Config, "DB_TYPE", "sqlite") == "mysql" else ""


def _allocate_installment_coverage(amounts_due, receipt_total, writeoff_total):
    """Allocate receipts first, then write-offs, across installments in order."""
    remaining_receipts = float(receipt_total or 0)
    remaining_writeoffs = float(writeoff_total or 0)
    allocations = []

    for raw_amount_due in amounts_due:
        amount_due = float(raw_amount_due or 0)
        receipt_applied = min(max(remaining_receipts, 0), amount_due)
        remaining_receipts -= receipt_applied
        uncovered = amount_due - receipt_applied
        writeoff_applied = min(max(remaining_writeoffs, 0), uncovered)
        remaining_writeoffs -= writeoff_applied
        allocations.append((receipt_applied, writeoff_applied))

    return allocations


def _sync_invoice_installments(cur, invoice_id, institute_id, now):
    """Rebuild installment coverage from tenant-owned receipts and write-offs."""
    cur.execute("""
        SELECT i.id,
               COALESCE((
                   SELECT SUM(r.amount_received)
                   FROM receipts r
                   WHERE r.invoice_id = i.id
                     AND r.institute_id = i.institute_id
               ), 0) AS receipt_total,
               COALESCE((
                   SELECT SUM(bw.amount_written_off)
                   FROM bad_debt_writeoffs bw
                   WHERE bw.invoice_id = i.id
                     AND bw.institute_id = i.institute_id
               ), 0) AS writeoff_total
        FROM invoices i
        WHERE i.id = ? AND i.institute_id = ?
    """, (invoice_id, institute_id))
    invoice = cur.fetchone()
    if not invoice:
        return

    receipt_total = float(invoice["receipt_total"] or 0)
    writeoff_total = float(invoice["writeoff_total"] or 0)
    cur.execute("""
        SELECT ip.id, ip.amount_due
        FROM installment_plans ip
        JOIN invoices i ON i.id = ip.invoice_id
        WHERE ip.invoice_id = ? AND i.institute_id = ?
        ORDER BY ip.installment_no ASC, ip.id ASC
    """, (invoice_id, institute_id))

    installments = cur.fetchall()
    allocations = _allocate_installment_coverage(
        [installment["amount_due"] for installment in installments],
        receipt_total,
        writeoff_total,
    )

    for installment, allocation in zip(installments, allocations):
        amount_due = float(installment["amount_due"] or 0)
        receipt_applied, writeoff_applied = allocation
        covered = round(receipt_applied + writeoff_applied, 2)

        if covered >= round(amount_due, 2):
            status = "paid"
        elif covered > 0:
            status = "partially_paid"
        else:
            status = "pending"

        if writeoff_applied > 0 and receipt_applied > 0:
            remarks = (
                f"Receipt payment {receipt_applied:.2f}; "
                f"written off {writeoff_applied:.2f}"
            )
        elif writeoff_applied > 0:
            remarks = f"Written off {writeoff_applied:.2f}"
        elif receipt_applied >= amount_due and amount_due > 0:
            remarks = "Fully paid"
        elif receipt_applied > 0:
            remarks = f"Partial payment of {receipt_applied:.2f}"
        else:
            remarks = None

        cur.execute("""
            UPDATE installment_plans
            SET amount_paid = ?, status = ?, remarks = ?, updated_at = ?
            WHERE id = ?
              AND EXISTS (
                  SELECT 1
                  FROM invoices i
                  WHERE i.id = installment_plans.invoice_id
                    AND i.institute_id = ?
              )
        """, (covered, status, remarks, now, installment["id"], institute_id))



@baddebt_bp.route("/")
@login_required
@admin_required
def dashboard():
    """Display all bad debt write-offs"""
    conn = get_conn()
    cur = conn.cursor()
    current_inst = get_current_institute_id(default=1)

    # Get all write-offs with related invoice and student details
    cur.execute("""
        SELECT
            bw.id,
            bw.reference_no,
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
        WHERE bw.institute_id = ?
          AND i.institute_id = ?
          AND s.institute_id = ?
        ORDER BY bw.writeoff_date DESC
    """, (current_inst, current_inst, current_inst))
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
    current_inst = get_current_institute_id(default=1)
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
                (SELECT IFNULL(SUM(amount_received), 0)
                 FROM receipts
                 WHERE invoice_id = i.id AND institute_id = ?) AS paid_amount
            FROM invoices i
            JOIN students s ON i.student_id = s.id
            WHERE i.id = ?
              AND i.institute_id = ?
              AND s.institute_id = ?
        """, (current_inst, invoice_id, current_inst, current_inst))
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
            cur = conn.cursor()

            try:
                now = datetime.now().isoformat(timespec="seconds")
                user_id = session.get("user_id")
                branch_id = invoice["branch_id"]

                # Start explicit transaction
                _begin_write_transaction(cur)

                # Re-read and lock the tenant-owned invoice inside the write
                # transaction so concurrent receipts/write-offs cannot make
                # the previously calculated balance stale.
                cur.execute("""
                    SELECT
                        i.id,
                        i.invoice_no,
                        i.total_amount,
                        i.student_id,
                        i.branch_id,
                        s.student_code,
                        s.status AS student_status,
                        (SELECT IFNULL(SUM(r.amount_received), 0)
                         FROM receipts r
                         WHERE r.invoice_id = i.id
                           AND r.institute_id = ?) AS paid_amount,
                        (SELECT IFNULL(SUM(bw.amount_written_off), 0)
                         FROM bad_debt_writeoffs bw
                         WHERE bw.invoice_id = i.id
                           AND bw.institute_id = ?) AS written_off_amount
                    FROM invoices i
                    JOIN students s ON s.id = i.student_id
                    WHERE i.id = ?
                      AND i.institute_id = ?
                      AND s.institute_id = ?
                """ + _for_update_clause(), (
                    current_inst,
                    current_inst,
                    invoice_id,
                    current_inst,
                    current_inst,
                ))
                invoice = cur.fetchone()
                if not invoice:
                    raise ValueError("Invoice not found for this institute.")

                branch_id = invoice["branch_id"]
                paid_amount = float(invoice["paid_amount"] or 0)
                written_off_amount = float(invoice["written_off_amount"] or 0)
                total_amount = float(invoice["total_amount"] or 0)
                balance = total_amount - paid_amount - written_off_amount
                if amount_written_off > balance:
                    raise ValueError(
                        f"Write-off amount (₹{amount_written_off:.2f}) cannot "
                        f"exceed balance (₹{balance:.2f})."
                    )

                cur.execute("""
                    SELECT invoice_prefix
                    FROM institute_settings
                    WHERE institute_id = ?
                """, (current_inst,))
                institute_settings = cur.fetchone()
                invoice_prefix = (
                    institute_settings["invoice_prefix"]
                    if institute_settings and institute_settings["invoice_prefix"]
                    else "INV"
                )
                writeoff_reference = allocate_document_number(
                    cur,
                    current_inst,
                    "writeoff",
                    derive_writeoff_prefix(invoice_prefix),
                )

                # Insert write-off record
                cur.execute("""
                    INSERT INTO bad_debt_writeoffs (
                        institute_id,
                        reference_no,
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
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    current_inst,
                    writeoff_reference,
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
                    SELECT id FROM expense_categories
                    WHERE category_name = 'Uncollectible Receivables'
                      AND institute_id = ?
                """, (current_inst,))
                category = cur.fetchone()

                if category:
                    category_id = category["id"]
                    expense_description = (
                        f"Bad Debt Write-off - Invoice {invoice['invoice_no']} - "
                        f"Student: {invoice['student_code']} - Reason: {reason}"
                    )

                    cur.execute("""
                        INSERT INTO expenses (
                            institute_id,
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
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        current_inst,
                        datetime.now().date().isoformat(),
                        branch_id,
                        category_id,
                        f"Bad Debt Write-off - {invoice['invoice_no']}",
                        amount_written_off,
                        "cash",
                        writeoff_reference,
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
                    WHERE id = ? AND institute_id = ?
                """, (new_status, now, invoice_id, current_inst))

                # Recalculate installment coverage from receipts plus all active
                # write-offs. This preserves any balance after a partial write-off.
                _sync_invoice_installments(cur, invoice_id, current_inst, now)

                # Commit transaction
                conn.commit()
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
                conn.rollback()
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
                WHERE i.id = ?
                  AND i.status IN ('unpaid', 'partially_paid')
                  AND i.institute_id = ?
                  AND s.institute_id = ?
            """, (invoice_id_param, current_inst, current_inst))
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
          AND i.institute_id = ?
          AND s.institute_id = ?
        ORDER BY i.invoice_no DESC
    """, (current_inst, current_inst))
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
    current_inst = get_current_institute_id(default=1)

    cur.execute("""
        SELECT
            bw.id,
            bw.reference_no,
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
          AND bw.institute_id = ?
          AND i.institute_id = ?
          AND s.institute_id = ?
    """, (writeoff_id, current_inst, current_inst, current_inst))
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
        WHERE reference_no = ? AND institute_id = ?
    """, (write_off["reference_no"], current_inst))
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
    current_inst = get_current_institute_id(default=1)

    cur.execute("""
        SELECT
            i.id,
            i.invoice_no,
            i.total_amount,
            s.full_name AS student_name,
            s.student_code,
            s.status AS student_status,
            (SELECT IFNULL(SUM(amount_received), 0)
             FROM receipts
             WHERE invoice_id = i.id AND institute_id = ?) AS paid_amount
        FROM invoices i
        JOIN students s ON i.student_id = s.id
        WHERE i.id = ?
          AND i.institute_id = ?
          AND s.institute_id = ?
    """, (current_inst, invoice_id, current_inst, current_inst))
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
    cur = conn.cursor()
    current_inst = get_current_institute_id(default=1)
    _begin_write_transaction(cur)

    cur.execute("""
        SELECT invoice_id, amount_written_off, reference_no
        FROM bad_debt_writeoffs
        WHERE id = ? AND institute_id = ?
    """ + _for_update_clause(), (writeoff_id, current_inst))
    write_off = cur.fetchone()

    if not write_off:
        flash("Write-off record not found", "error")
        conn.close()
        return redirect(url_for("baddebt.dashboard"))

    try:
        now = datetime.now().isoformat(timespec="seconds")
        user_id = session.get("user_id")

        # Delete from bad_debt_writeoffs
        cur.execute(
            "DELETE FROM bad_debt_writeoffs WHERE id = ? AND institute_id = ?",
            (writeoff_id, current_inst),
        )

        # Delete related expense
        cur.execute(
            "DELETE FROM expenses WHERE reference_no = ? AND institute_id = ?",
            (write_off["reference_no"], current_inst),
        )

        # Update invoice status back to original
        invoice_id = write_off["invoice_id"]
        cur.execute("""
            SELECT total_amount, (SELECT IFNULL(SUM(amount_received), 0) FROM receipts WHERE invoice_id = ?) AS paid_amount
            FROM invoices WHERE id = ? AND institute_id = ?
        """, (invoice_id, invoice_id, current_inst))
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
                UPDATE invoices SET status = ?, updated_at = ?
                WHERE id = ? AND institute_id = ?
            """, (new_status, now, invoice_id, current_inst))

            # The deleted write-off no longer covers the invoice. Reallocate the
            # remaining receipts/write-offs so the restored balance is receivable.
            _sync_invoice_installments(cur, invoice_id, current_inst, now)

        conn.commit()
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
            conn.rollback()
        except:
            pass
        conn.close()
        flash(f"Error deleting write-off: {str(e)}", "error")
        return redirect(url_for("baddebt.dashboard"))
