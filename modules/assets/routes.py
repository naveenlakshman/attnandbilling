from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from datetime import datetime
from db import get_conn, log_activity
from modules.core.utils import login_required, admin_required

assets_bp = Blueprint("assets", __name__)


@assets_bp.route("/")
@login_required
def list_assets():
    """Display list of assets with filters"""
    conn = get_conn()
    cur = conn.cursor()

    # Get filters from request
    branch_filter = request.args.get("branch", "").strip()
    category_filter = request.args.get("category", "").strip()
    status_filter = request.args.get("status", "").strip()

    # Get all branches for filter dropdown
    cur.execute("""
        SELECT id, branch_name 
        FROM branches 
        WHERE is_active = 1
        ORDER BY branch_name
    """)
    branches = cur.fetchall()

    # Get all categories for filter dropdown
    cur.execute("""
        SELECT DISTINCT category 
        FROM assets 
        WHERE category IS NOT NULL
        ORDER BY category
    """)
    categories = [row["category"] for row in cur.fetchall()]

    # Build the main query for assets
    query = """
    SELECT
        assets.id,
        assets.asset_code,
        assets.asset_name,
        assets.category,
        assets.brand,
        assets.status,
        assets.condition,
        branches.branch_name,
        (SELECT COUNT(*) FROM asset_allocation 
         WHERE asset_id = assets.id AND status = 'Allocated' LIMIT 1) as is_allocated,
        (SELECT assigned_to FROM asset_allocation 
         WHERE asset_id = assets.id AND status = 'Allocated' LIMIT 1) as assigned_to
    FROM assets
    LEFT JOIN branches ON assets.branch_id = branches.id
    WHERE 1=1
    """

    params = []

    # Apply filters
    if branch_filter:
        query += " AND assets.branch_id = ?"
        params.append(int(branch_filter))

    if category_filter:
        query += " AND assets.category = ?"
        params.append(category_filter)

    if status_filter:
        query += " AND assets.status = ?"
        params.append(status_filter)

    query += " ORDER BY assets.asset_code DESC"

    cur.execute(query, params)
    assets = cur.fetchall()

    conn.close()

    return render_template(
        "assets/list.html",
        assets=assets,
        branches=branches,
        categories=categories,
        branch_filter=branch_filter,
        category_filter=category_filter,
        status_filter=status_filter
    )


# Define asset categories
ASSET_CATEGORIES = [
    "Computer",
    "Laptop",
    "Printer",
    "Chair",
    "Table",
    "Monitor",
    "Keyboard",
    "Mouse",
    "Projector",
    "Whiteboard",
    "Furniture",
    "Network Equipment",
    "Server",
    "Software License",
    "Other"
]


@assets_bp.route("/add", methods=["GET", "POST"])
@login_required
@admin_required
def add_asset():
    """Add new asset"""
    conn = get_conn()
    cur = conn.cursor()

    if request.method == "POST":
        asset_name = request.form.get("asset_name", "").strip()
        category = request.form.get("category", "").strip()
        brand = request.form.get("brand", "").strip()
        purchase_cost = request.form.get("purchase_cost", "0").strip()
        purchase_date = request.form.get("purchase_date", "").strip()
        branch_id = request.form.get("branch_id", "").strip()

        # Validation
        errors = []
        if not asset_name:
            errors.append("Asset Name is required")
        if not category:
            errors.append("Category is required")
        if not purchase_date:
            errors.append("Purchase Date is required")
        if not branch_id:
            errors.append("Branch is required")

        if errors:
            branches = cur.execute("SELECT id, branch_name FROM branches WHERE is_active = 1 ORDER BY branch_name").fetchall()
            return render_template(
                "assets/add.html",
                categories=ASSET_CATEGORIES,
                branches=branches,
                errors=errors,
                form=request.form
            )

        try:
            purchase_cost = float(purchase_cost) if purchase_cost else 0
        except ValueError:
            purchase_cost = 0

        # Generate asset code (format: AST-XXXXXX)
        cur.execute("SELECT MAX(CAST(SUBSTR(asset_code, 5) AS INTEGER)) FROM assets WHERE asset_code LIKE 'AST-%'")
        result = cur.fetchone()
        next_code = (result[0] or 0) + 1
        asset_code = f"AST-{next_code:06d}"

        now = datetime.now().isoformat(timespec="seconds")

        try:
            cur.execute("""
                INSERT INTO assets (
                    asset_code,
                    asset_name,
                    category,
                    brand,
                    purchase_date,
                    purchase_cost,
                    branch_id,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                asset_code,
                asset_name,
                category,
                brand,
                purchase_date,
                purchase_cost,
                branch_id,
                now
            ))

            asset_id = cur.lastrowid

            # Create initial asset log entry
            cur.execute("""
                INSERT INTO asset_logs (
                    asset_id,
                    action,
                    description,
                    done_by,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                asset_id,
                "Created",
                f"Asset created: {asset_name}",
                session.get("user_id"),
                now
            ))

            conn.commit()
            conn.close()

            # Log activity (after committing the transaction)
            log_activity(
                user_id=session.get("user_id"),
                branch_id=int(branch_id),
                action_type="create",
                module_name="assets",
                record_id=asset_id,
                description=f"Created new asset: {asset_name} ({asset_code})"
            )

            flash(f"Asset {asset_code} created successfully!", "success")
            return redirect(url_for("assets.list_assets"))

        except Exception as e:
            conn.rollback()
            conn.close()
            flash(f"Error creating asset: {str(e)}", "danger")
            branches = cur.execute("SELECT id, branch_name FROM branches WHERE is_active = 1 ORDER BY branch_name").fetchall()
            return render_template(
                "assets/add.html",
                categories=ASSET_CATEGORIES,
                branches=branches,
                form=request.form
            )

    # GET request - show form
    branches = cur.execute("SELECT id, branch_name FROM branches WHERE is_active = 1 ORDER BY branch_name").fetchall()
    conn.close()

    return render_template(
        "assets/add.html",
        categories=ASSET_CATEGORIES,
        branches=branches
    )


@assets_bp.route("/<int:asset_id>/allocate", methods=["GET", "POST"])
@login_required
@admin_required
def allocate_asset(asset_id):
    """Allocate asset to staff or student"""
    conn = get_conn()
    cur = conn.cursor()

    # Get asset details
    cur.execute("""
        SELECT 
            assets.id,
            assets.asset_code,
            assets.asset_name,
            assets.category,
            assets.status,
            branches.branch_name
        FROM assets
        LEFT JOIN branches ON assets.branch_id = branches.id
        WHERE assets.id = ?
    """, (asset_id,))
    asset = cur.fetchone()

    if not asset:
        conn.close()
        flash("Asset not found!", "danger")
        return redirect(url_for("assets.list_assets"))

    # Check if asset is already allocated
    cur.execute("""
        SELECT * FROM asset_allocation
        WHERE asset_id = ? AND status = 'Allocated'
    """, (asset_id,))
    current_allocation = cur.fetchone()

    if request.method == "POST":
        assigned_role = request.form.get("assigned_role", "").strip()
        assigned_to = request.form.get("assigned_to", "").strip()
        assigned_date = request.form.get("assigned_date", "").strip()

        # Validation
        errors = []
        if not assigned_role:
            errors.append("Role (Staff/Student/Location) is required")
        if not assigned_to:
            errors.append("Assigned To name/location is required")
        if not assigned_date:
            errors.append("Assigned Date is required")

        if errors:
            return render_template(
                "assets/allocate.html",
                asset=asset,
                current_allocation=current_allocation,
                errors=errors,
                form=request.form
            )

        # If asset is already allocated, return it first
        if current_allocation:
            return_date = datetime.now().isoformat(timespec="seconds")
            cur.execute("""
                UPDATE asset_allocation
                SET status = 'Returned', return_date = ?
                WHERE id = ?
            """, (return_date, current_allocation["id"]))

            # Log the return action
            now = datetime.now().isoformat(timespec="seconds")
            cur.execute("""
                INSERT INTO asset_logs (
                    asset_id,
                    action,
                    description,
                    done_by,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                asset_id,
                "Returned",
                f"Asset returned by {current_allocation['assigned_to']}",
                session.get("user_id"),
                now
            ))

        # Create new allocation
        now = datetime.now().isoformat(timespec="seconds")
        try:
            cur.execute("""
                INSERT INTO asset_allocation (
                    asset_id,
                    assigned_to,
                    assigned_role,
                    assigned_date,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                asset_id,
                assigned_to,
                assigned_role,
                assigned_date,
                "Allocated",
                now
            ))

            # Log the allocation action
            role_display = "Trainer" if assigned_role == "staff" else "Student/Location"
            cur.execute("""
                INSERT INTO asset_logs (
                    asset_id,
                    action,
                    description,
                    done_by,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                asset_id,
                "Assigned",
                f"Asset assigned to {assigned_to} ({role_display})",
                session.get("user_id"),
                now
            ))

            conn.commit()
            conn.close()

            # Log activity (after committing the transaction)
            log_activity(
                user_id=session.get("user_id"),
                branch_id=asset["id"],
                action_type="update",
                module_name="assets",
                record_id=asset_id,
                description=f"Allocated {asset['asset_code']} to {assigned_to}"
            )

            flash(f"Asset {asset['asset_code']} allocated to {assigned_to}!", "success")
            return redirect(url_for("assets.list_assets"))

        except Exception as e:
            conn.rollback()
            conn.close()
            flash(f"Error allocating asset: {str(e)}", "danger")
            return render_template(
                "assets/allocate.html",
                asset=asset,
                current_allocation=current_allocation,
                form=request.form
            )

    conn.close()

    return render_template(
        "assets/allocate.html",
        asset=asset,
        current_allocation=current_allocation
    )


@assets_bp.route("/<int:asset_id>/return", methods=["GET", "POST"])
@login_required
@admin_required
def return_asset(asset_id):
    """Return allocated asset"""
    conn = get_conn()
    cur = conn.cursor()

    # Get asset details
    cur.execute("""
        SELECT 
            assets.id,
            assets.asset_code,
            assets.asset_name,
            assets.category,
            assets.status,
            assets.condition,
            branches.branch_name
        FROM assets
        LEFT JOIN branches ON assets.branch_id = branches.id
        WHERE assets.id = ?
    """, (asset_id,))
    asset = cur.fetchone()

    if not asset:
        conn.close()
        flash("Asset not found!", "danger")
        return redirect(url_for("assets.list_assets"))

    # Get current allocation
    cur.execute("""
        SELECT * FROM asset_allocation
        WHERE asset_id = ? AND status = 'Allocated'
        ORDER BY assigned_date DESC
        LIMIT 1
    """, (asset_id,))
    current_allocation = cur.fetchone()

    if not current_allocation:
        conn.close()
        flash("This asset is not currently allocated!", "warning")
        return redirect(url_for("assets.list_assets"))

    if request.method == "POST":
        return_notes = request.form.get("return_notes", "").strip()
        asset_condition = request.form.get("asset_condition", "").strip()

        # Validation
        errors = []
        if not asset_condition:
            errors.append("Asset Condition is required")

        if errors:
            return render_template(
                "assets/return.html",
                asset=asset,
                current_allocation=current_allocation,
                errors=errors,
                form=request.form
            )

        try:
            now = datetime.now().isoformat(timespec="seconds")

            # Update allocation to Returned
            return_date = now
            cur.execute("""
                UPDATE asset_allocation
                SET status = 'Returned', return_date = ?
                WHERE id = ?
            """, (return_date, current_allocation["id"]))

            # Update asset condition and status
            # If condition is Damaged, set status to In Repair
            new_status = "In Repair" if asset_condition == "Damaged" else "Active"
            
            cur.execute("""
                UPDATE assets
                SET condition = ?, status = ?, updated_at = ?
                WHERE id = ?
            """, (asset_condition, new_status, now, asset_id))

            # Log the return action
            return_description = f"Asset returned by {current_allocation['assigned_to']}"
            if return_notes:
                return_description += f" - {return_notes}"
            if asset_condition == "Damaged":
                return_description += " (Marked for Repair)"

            cur.execute("""
                INSERT INTO asset_logs (
                    asset_id,
                    action,
                    description,
                    done_by,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                asset_id,
                "Returned",
                return_description,
                session.get("user_id"),
                now
            ))

            # If condition is damaged, also log repair action
            if asset_condition == "Damaged":
                cur.execute("""
                    INSERT INTO asset_logs (
                        asset_id,
                        action,
                        description,
                        done_by,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    asset_id,
                    "Repaired",
                    f"Asset marked for repair - {return_notes if return_notes else 'Damage noted during return'}",
                    session.get("user_id"),
                    now
                ))

            conn.commit()
            conn.close()

            # Log activity (after committing the transaction)
            log_activity(
                user_id=session.get("user_id"),
                branch_id=asset.get("id"),
                action_type="update",
                module_name="assets",
                record_id=asset_id,
                description=f"Returned asset {asset['asset_code']} from {current_allocation['assigned_to']} - Condition: {asset_condition}"
            )

            flash(f"Asset {asset['asset_code']} returned successfully! Status updated to {new_status}.", "success")
            return redirect(url_for("assets.list_assets"))

        except Exception as e:
            conn.rollback()
            conn.close()
            flash(f"Error returning asset: {str(e)}", "danger")
            return render_template(
                "assets/return.html",
                asset=asset,
                current_allocation=current_allocation,
                form=request.form
            )

    conn.close()

    return render_template(
        "assets/return.html",
        asset=asset,
        current_allocation=current_allocation
    )


@assets_bp.route("/<int:asset_id>/history")
@login_required
def asset_history(asset_id):
    """View asset history and audit trail"""
    conn = get_conn()
    cur = conn.cursor()

    # Get asset details
    cur.execute("""
        SELECT 
            assets.id,
            assets.asset_code,
            assets.asset_name,
            assets.category,
            assets.brand,
            assets.purchase_date,
            assets.purchase_cost,
            assets.status,
            assets.condition,
            assets.created_at,
            branches.branch_name
        FROM assets
        LEFT JOIN branches ON assets.branch_id = branches.id
        WHERE assets.id = ?
    """, (asset_id,))
    asset = cur.fetchone()

    if not asset:
        conn.close()
        flash("Asset not found!", "danger")
        return redirect(url_for("assets.list_assets"))

    # Get all asset logs (audit trail)
    cur.execute("""
        SELECT 
            asset_logs.id,
            asset_logs.action,
            asset_logs.description,
            asset_logs.created_at,
            users.full_name as done_by_name
        FROM asset_logs
        LEFT JOIN users ON asset_logs.done_by = users.id
        WHERE asset_logs.asset_id = ?
        ORDER BY asset_logs.created_at DESC
    """, (asset_id,))
    logs = cur.fetchall()

    # Get all asset allocations (who used it)
    cur.execute("""
        SELECT 
            asset_allocation.id,
            asset_allocation.assigned_to,
            asset_allocation.assigned_role,
            asset_allocation.assigned_date,
            asset_allocation.return_date,
            asset_allocation.status,
            asset_allocation.created_at
        FROM asset_allocation
        WHERE asset_allocation.asset_id = ?
        ORDER BY asset_allocation.assigned_date DESC
    """, (asset_id,))
    allocations = cur.fetchall()

    conn.close()

    return render_template(
        "assets/history.html",
        asset=asset,
        logs=logs,
        allocations=allocations
    )


