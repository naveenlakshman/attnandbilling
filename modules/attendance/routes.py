from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session
from datetime import datetime, timedelta
from db import get_conn, log_activity
from functools import wraps

attendance_bp = Blueprint('attendance', __name__)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('core.login'))
        return f(*args, **kwargs)
    return decorated_function


@attendance_bp.route('/dashboard')
@login_required
def dashboard():
    """Attendance Dashboard - Main entry point"""
    user_id = session.get('user_id')
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        # Get user info
        cur.execute("SELECT id, branch_id, can_view_all_branches FROM users WHERE id = ?", (user_id,))
        user = cur.fetchone()
        
        # Get today's date in YYYY-MM-DD format
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Get selected branch from query parameter
        selected_branch_id = request.args.get('branch_id', '', type=int)
        
        # Determine which branch to use
        if user['can_view_all_branches']:
            # If user can view all branches and selected one, use it
            working_branch_id = selected_branch_id if selected_branch_id else None
        else:
            # If user can't view all branches, use their assigned branch
            working_branch_id = user['branch_id']
        
        # Get all branches for the dropdown (only if user can view all branches)
        available_branches = []
        if user['can_view_all_branches']:
            cur.execute("""
                SELECT id, branch_name FROM branches 
                WHERE is_active = 1 
                ORDER BY branch_name ASC
            """)
            available_branches = cur.fetchall()
        
        # Get batches for today based on branch
        if working_branch_id:
            # Filter by specific branch
            cur.execute("""
                SELECT DISTINCT b.id, b.batch_name, b.branch_id, c.course_name, b.start_time, b.end_time, 
                       b.status, u.full_name as trainer_name, br.branch_name
                FROM batches b
                LEFT JOIN courses c ON b.course_id = c.id
                LEFT JOIN users u ON b.trainer_id = u.id
                LEFT JOIN branches br ON b.branch_id = br.id
                WHERE b.status = 'active'
                AND b.branch_id = ?
                AND (
                    b.start_date IS NULL 
                    OR date(b.start_date) <= date(?)
                )
                AND (
                    b.end_date IS NULL 
                    OR date(b.end_date) >= date(?)
                )
                ORDER BY b.start_time ASC
            """, (working_branch_id, today, today))
        elif user['can_view_all_branches']:
            # Show all batches if admin didn't select a specific branch
            cur.execute("""
                SELECT DISTINCT b.id, b.batch_name, b.branch_id, c.course_name, b.start_time, b.end_time, 
                       b.status, u.full_name as trainer_name, br.branch_name
                FROM batches b
                LEFT JOIN courses c ON b.course_id = c.id
                LEFT JOIN users u ON b.trainer_id = u.id
                LEFT JOIN branches br ON b.branch_id = br.id
                WHERE b.status = 'active'
                AND (
                    b.start_date IS NULL 
                    OR date(b.start_date) <= date(?)
                )
                AND (
                    b.end_date IS NULL 
                    OR date(b.end_date) >= date(?)
                )
                ORDER BY b.start_time ASC
            """, (today, today))
        else:
            # Non-admin users see only their branch
            cur.execute("""
                SELECT DISTINCT b.id, b.batch_name, b.branch_id, c.course_name, b.start_time, b.end_time, 
                       b.status, u.full_name as trainer_name, br.branch_name
                FROM batches b
                LEFT JOIN courses c ON b.course_id = c.id
                LEFT JOIN users u ON b.trainer_id = u.id
                LEFT JOIN branches br ON b.branch_id = br.id
                WHERE b.status = 'active'
                AND b.branch_id = ?
                AND (
                    b.start_date IS NULL 
                    OR date(b.start_date) <= date(?)
                )
                AND (
                    b.end_date IS NULL 
                    OR date(b.end_date) >= date(?)
                )
                ORDER BY b.start_time ASC
            """, (user['branch_id'], today, today))
        
        batches = cur.fetchall()
        
        # Get attendance statistics for each batch
        batch_stats = []
        total_present = 0
        total_absent = 0
        total_late = 0
        total_leave = 0
        total_marked = 0
        total_not_marked = 0
        
        for batch in batches:
            batch_id = batch['id']
            
            # Get all students in this batch
            cur.execute("""
                SELECT COUNT(*) as total_students
                FROM student_batches
                WHERE batch_id = ? AND status = 'active'
            """, (batch_id,))
            total_students = cur.fetchone()['total_students']
            
            # Get attendance marked today
            cur.execute("""
                SELECT COUNT(*) as marked_count
                FROM attendance_records
                WHERE batch_id = ? AND attendance_date = ?
            """, (batch_id, today))
            marked_count = cur.fetchone()['marked_count']
            
            # Get attendance counts by status
            cur.execute("""
                SELECT status, COUNT(*) as count
                FROM attendance_records
                WHERE batch_id = ? AND attendance_date = ?
                GROUP BY status
            """, (batch_id, today))
            
            status_counts = {}
            for row in cur.fetchall():
                status_counts[row['status']] = row['count']
            
            present = status_counts.get('present', 0)
            absent = status_counts.get('absent', 0)
            late = status_counts.get('late', 0)
            leave = status_counts.get('leave', 0)
            not_marked = total_students - marked_count
            
            batch_stats.append({
                'batch': batch,
                'total_students': total_students,
                'marked_count': marked_count,
                'not_marked': not_marked,
                'present': present,
                'absent': absent,
                'late': late,
                'leave': leave,
                'percentage_marked': (marked_count / total_students * 100) if total_students > 0 else 0
            })
            
            total_present += present
            total_absent += absent
            total_late += late
            total_leave += leave
            total_marked += marked_count
            total_not_marked += not_marked

        # Sort: currently running batches first, then by start_time ASC
        now_time = datetime.now().strftime("%H:%M")
        batch_stats.sort(key=lambda bs: (
            0 if (bs['batch']['start_time'] and bs['batch']['end_time'] and
                  bs['batch']['start_time'] <= now_time < bs['batch']['end_time']) else 1,
            bs['batch']['start_time'] or '99:99'
        ))

        # Get pending attendance followups
        cur.execute("""
            SELECT af.id, af.student_id, af.batch_id, af.followup_date, af.reason,
                   s.full_name, s.student_code, b.batch_name
            FROM attendance_followups af
            LEFT JOIN students s ON af.student_id = s.id
            LEFT JOIN batches b ON af.batch_id = b.id
            WHERE af.followup_status = 'pending'
            AND (af.batch_id IN (SELECT id FROM batches WHERE status = 'active') OR af.batch_id IS NULL)
            ORDER BY af.followup_date ASC
            LIMIT 5
        """)
        pending_followups = cur.fetchall()
        
        # Calculate branch-wise statistics if "All Branches" is selected
        branch_stats = {}
        if user['can_view_all_branches'] and not selected_branch_id:
            for batch in batches:
                branch_id = batch['branch_id']
                branch_name = batch['branch_name']
                
                if branch_id not in branch_stats:
                    branch_stats[branch_id] = {
                        'branch_name': branch_name,
                        'total_present': 0,
                        'total_absent': 0,
                        'total_late': 0,
                        'total_leave': 0
                    }
                
                # Find the batch_stat entry for this batch
                for bs in batch_stats:
                    if bs['batch']['id'] == batch['id']:
                        branch_stats[branch_id]['total_present'] += bs['present']
                        branch_stats[branch_id]['total_absent'] += bs['absent']
                        branch_stats[branch_id]['total_late'] += bs['late']
                        branch_stats[branch_id]['total_leave'] += bs['leave']
                        break
        
        # Prepare overall statistics
        overall_stats = {
            'total_batches': len(batches),
            'total_students': sum(bs['total_students'] for bs in batch_stats),
            'total_marked': total_marked,
            'total_not_marked': total_not_marked,
            'total_present': total_present,
            'total_absent': total_absent,
            'total_late': total_late,
            'total_leave': total_leave,
            'percentage_marked': (total_marked / (total_marked + total_not_marked) * 100) if (total_marked + total_not_marked) > 0 else 0
        }
        
        return render_template(
            'attendance/dashboard.html',
            today=today,
            batch_stats=batch_stats,
            overall_stats=overall_stats,
            branch_stats=branch_stats,
            pending_followups=pending_followups,
            user=user,
            available_branches=available_branches,
            selected_branch_id=selected_branch_id
        )
    
    finally:
        conn.close()


# ============ BATCH MANAGEMENT ============

@attendance_bp.route('/batches')
@login_required
def list_batches():
    """List all batches with filters"""
    user_id = session.get('user_id')
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        # Get user info
        cur.execute("SELECT id, branch_id, can_view_all_branches FROM users WHERE id = ?", (user_id,))
        user = cur.fetchone()
        
        # Get filter parameters
        status_filter = request.args.get('status', 'all')
        branch_filter = request.args.get('branch_id', '')
        
        # Build query
        query = """
            SELECT b.id, b.batch_name, c.course_name, b.start_date, b.end_date, 
                   b.start_time, b.end_time, b.status, u.full_name as trainer_name, 
                   br.id as branch_id, br.branch_name,
                   (SELECT COUNT(*) FROM student_batches WHERE batch_id = b.id AND status = 'active') as student_count
            FROM batches b
            LEFT JOIN courses c ON b.course_id = c.id
            LEFT JOIN users u ON b.trainer_id = u.id
            LEFT JOIN branches br ON b.branch_id = br.id
            WHERE 1=1
        """
        params = []
        
        # Add branch filter
        if not user['can_view_all_branches']:
            query += " AND b.branch_id = ?"
            params.append(user['branch_id'])
        elif branch_filter:
            query += " AND b.branch_id = ?"
            params.append(int(branch_filter))
        
        # Add status filter
        if status_filter != 'all':
            query += " AND b.status = ?"
            params.append(status_filter)
        
        query += " ORDER BY CASE WHEN b.start_time IS NULL OR b.start_time = '' THEN 1 ELSE 0 END, b.start_time ASC, b.batch_name ASC"
        
        cur.execute(query, params)
        batches = cur.fetchall()
        
        # Get all branches for filter dropdown
        if user['can_view_all_branches']:
            cur.execute("SELECT id, branch_name FROM branches WHERE is_active = 1 ORDER BY branch_name ASC")
            branches = cur.fetchall()
        else:
            branches = []
        
        return render_template(
            'attendance/batch_list.html',
            batches=batches,
            branches=branches,
            status_filter=status_filter,
            branch_filter=branch_filter,
            user=user
        )
    
    finally:
        conn.close()


@attendance_bp.route('/batches/new', methods=['GET', 'POST'])
@login_required
def create_batch():
    """Create new batch"""
    user_id = session.get('user_id')
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        # Get user info
        cur.execute("SELECT id, branch_id, can_view_all_branches FROM users WHERE id = ?", (user_id,))
        user = cur.fetchone()
        
        if request.method == 'POST':
            # Get form data
            batch_name = request.form.get('batch_name', '').strip()
            course_id = request.form.get('course_id') or None
            branch_id = request.form.get('branch_id')
            start_date = request.form.get('start_date') or None
            end_date = request.form.get('end_date') or None
            start_time = request.form.get('start_time') or None
            end_time = request.form.get('end_time') or None
            trainer_id = request.form.get('trainer_id') or None
            status = request.form.get('status', 'active')
            
            # Validate
            if not batch_name:
                return render_template('attendance/batch_form.html', error="Batch name is required", 
                                     courses=[], trainers=[], branches=[], user=user), 400
            if not branch_id:
                return render_template('attendance/batch_form.html', error="Branch is required",
                                     courses=[], trainers=[], branches=[], user=user), 400
            
            now = datetime.now().isoformat(timespec="seconds")
            
            try:
                cur.execute("""
                    INSERT INTO batches (
                        batch_name, course_id, branch_id, start_date, end_date,
                        start_time, end_time, trainer_id, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    batch_name, course_id, int(branch_id), start_date, end_date,
                    start_time, end_time, trainer_id, status, now, now
                ))
                
                batch_id = cur.lastrowid
                conn.commit()
                
                log_activity(user_id, int(branch_id), 'CREATE', 'attendance', batch_id, 
                           f'Created batch: {batch_name}')
                
                return redirect(url_for('attendance.view_batch', batch_id=batch_id))
            
            except Exception as e:
                return render_template('attendance/batch_form.html', error=str(e),
                                     courses=[], trainers=[], branches=[], user=user), 400
        
        # GET request - show form
        # Get courses
        cur.execute("SELECT id, course_name FROM courses WHERE is_active = 1 ORDER BY course_name ASC")
        courses = cur.fetchall()
        
        # Get trainers
        cur.execute("""
            SELECT id, full_name FROM users 
            WHERE role = 'staff' AND is_active = 1 
            ORDER BY full_name ASC
        """)
        trainers = cur.fetchall()
        
        # Get branches
        if user['can_view_all_branches']:
            cur.execute("SELECT id, branch_name FROM branches WHERE is_active = 1 ORDER BY branch_name ASC")
            branches = cur.fetchall()
        else:
            cur.execute("SELECT id, branch_name FROM branches WHERE id = ? AND is_active = 1", 
                       (user['branch_id'],))
            branches = cur.fetchall()
        
        return render_template('attendance/batch_form.html',
                             batch=None, courses=courses, trainers=trainers, 
                             branches=branches, user=user)
    
    finally:
        conn.close()


@attendance_bp.route('/batches/<int:batch_id>')
@login_required
def view_batch(batch_id):
    """View batch details"""
    user_id = session.get('user_id')
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        cur.execute("SELECT id, branch_id, can_view_all_branches FROM users WHERE id = ?", (user_id,))
        user = cur.fetchone()
        
        # Get batch
        cur.execute("""
            SELECT b.id, b.batch_name, c.course_name, b.course_id, b.start_date, b.end_date,
                   b.start_time, b.end_time, b.status, u.full_name as trainer_name, b.trainer_id,
                   br.branch_name, b.branch_id, b.created_at, b.updated_at
            FROM batches b
            LEFT JOIN courses c ON b.course_id = c.id
            LEFT JOIN users u ON b.trainer_id = u.id
            LEFT JOIN branches br ON b.branch_id = br.id
            WHERE b.id = ?
        """, (batch_id,))
        
        batch = cur.fetchone()
        if not batch:
            return redirect(url_for('attendance.list_batches'))
        
        # Check branch access
        if not user['can_view_all_branches'] and batch['branch_id'] != user['branch_id']:
            return redirect(url_for('attendance.list_batches'))
        
        # Get students in batch
        cur.execute("""
            SELECT sb.id, s.student_code, s.full_name, s.phone, sb.joined_on, 
                   sb.status, sb.created_at
            FROM student_batches sb
            JOIN students s ON sb.student_id = s.id
            WHERE sb.batch_id = ?
            ORDER BY sb.joined_on DESC
        """, (batch_id,))
        
        students = cur.fetchall()
        
        return render_template('attendance/batch_detail.html',
                             batch=batch, students=students, user=user)
    
    finally:
        conn.close()


@attendance_bp.route('/batches/<int:batch_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_batch(batch_id):
    """Edit batch"""
    user_id = session.get('user_id')
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        # Get user info
        cur.execute("SELECT id, branch_id, can_view_all_branches FROM users WHERE id = ?", (user_id,))
        user = cur.fetchone()
        
        # Get batch
        cur.execute("""
            SELECT id, batch_name, course_id, branch_id, start_date, end_date,
                   start_time, end_time, trainer_id, status
            FROM batches
            WHERE id = ?
        """, (batch_id,))
        
        batch = cur.fetchone()
        if not batch:
            return redirect(url_for('attendance.list_batches'))
        
        # Check branch access
        if not user['can_view_all_branches'] and batch['branch_id'] != user['branch_id']:
            return redirect(url_for('attendance.list_batches'))
        
        if request.method == 'POST':
            # Get form data
            batch_name = request.form.get('batch_name', '').strip()
            course_id = request.form.get('course_id') or None
            start_date = request.form.get('start_date') or None
            end_date = request.form.get('end_date') or None
            start_time = request.form.get('start_time') or None
            end_time = request.form.get('end_time') or None
            trainer_id = request.form.get('trainer_id') or None
            status = request.form.get('status', 'active')
            
            # Validate
            if not batch_name:
                cur.execute("SELECT id, course_name FROM courses WHERE is_active = 1 ORDER BY course_name ASC")
                courses = cur.fetchall()
                cur.execute("SELECT id, full_name FROM users WHERE role = 'staff' AND is_active = 1 ORDER BY full_name ASC")
                trainers = cur.fetchall()
                cur.execute("SELECT id, branch_name FROM branches WHERE is_active = 1 ORDER BY branch_name ASC")
                branches = cur.fetchall()
                return render_template('attendance/batch_form.html', batch=batch, 
                                     error="Batch name is required", courses=courses, 
                                     trainers=trainers, branches=branches, user=user), 400
            
            now = datetime.now().isoformat(timespec="seconds")
            
            try:
                cur.execute("""
                    UPDATE batches
                    SET batch_name = ?, course_id = ?, start_date = ?, end_date = ?,
                        start_time = ?, end_time = ?, trainer_id = ?, status = ?, updated_at = ?
                    WHERE id = ?
                """, (
                    batch_name, course_id, start_date, end_date,
                    start_time, end_time, trainer_id, status, now, batch_id
                ))
                
                conn.commit()
                
                log_activity(user_id, batch['branch_id'], 'UPDATE', 'attendance', batch_id,
                           f'Updated batch: {batch_name}')
                
                return redirect(url_for('attendance.view_batch', batch_id=batch_id))
            
            except Exception as e:
                cur.execute("SELECT id, course_name FROM courses WHERE is_active = 1 ORDER BY course_name ASC")
                courses = cur.fetchall()
                cur.execute("SELECT id, full_name FROM users WHERE role = 'staff' AND is_active = 1 ORDER BY full_name ASC")
                trainers = cur.fetchall()
                cur.execute("SELECT id, branch_name FROM branches WHERE is_active = 1 ORDER BY branch_name ASC")
                branches = cur.fetchall()
                return render_template('attendance/batch_form.html', batch=batch, 
                                     error=str(e), courses=courses, trainers=trainers, 
                                     branches=branches, user=user), 400
        
        # GET request - show form
        cur.execute("SELECT id, course_name FROM courses WHERE is_active = 1 ORDER BY course_name ASC")
        courses = cur.fetchall()
        
        cur.execute("SELECT id, full_name FROM users WHERE role = 'staff' AND is_active = 1 ORDER BY full_name ASC")
        trainers = cur.fetchall()
        
        if user['can_view_all_branches']:
            cur.execute("SELECT id, branch_name FROM branches WHERE is_active = 1 ORDER BY branch_name ASC")
            branches = cur.fetchall()
        else:
            cur.execute("SELECT id, branch_name FROM branches WHERE id = ? AND is_active = 1",
                       (user['branch_id'],))
            branches = cur.fetchall()
        
        return render_template('attendance/batch_form.html',
                             batch=batch, courses=courses, trainers=trainers,
                             branches=branches, edit=True, user=user)
    
    finally:
        conn.close()


@attendance_bp.route('/batches/<int:batch_id>/delete', methods=['POST'])
@login_required
def delete_batch(batch_id):
    """Delete batch (soft delete - mark as cancelled)"""
    user_id = session.get('user_id')
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        # Get user info
        cur.execute("SELECT id, branch_id, can_view_all_branches FROM users WHERE id = ?", (user_id,))
        user = cur.fetchone()
        
        # Get batch
        cur.execute("SELECT id, branch_id, batch_name FROM batches WHERE id = ?", (batch_id,))
        batch = cur.fetchone()
        
        if not batch:
            return redirect(url_for('attendance.list_batches'))
        
        # Check branch access
        if not user['can_view_all_branches'] and batch['branch_id'] != user['branch_id']:
            return redirect(url_for('attendance.list_batches'))
        
        now = datetime.now().isoformat(timespec="seconds")
        
        # Soft delete - mark as cancelled
        cur.execute("""
            UPDATE batches
            SET status = 'cancelled', updated_at = ?
            WHERE id = ?
        """, (now, batch_id))
        
        conn.commit()
        
        log_activity(user_id, batch['branch_id'], 'DELETE', 'attendance', batch_id,
                   f'Cancelled batch: {batch["batch_name"]}')
        
        return redirect(url_for('attendance.list_batches'))
    
    finally:
        conn.close()


# ============ ASSIGN STUDENTS TO BATCH ============

@attendance_bp.route('/batches/<int:batch_id>/assign-students', methods=['GET', 'POST'])
@login_required
def assign_students(batch_id):
    """Assign/manage students in a batch"""
    user_id = session.get('user_id')
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        # Get user info
        cur.execute("SELECT id, branch_id, can_view_all_branches FROM users WHERE id = ?", (user_id,))
        user = cur.fetchone()
        
        # Get batch
        cur.execute("""
            SELECT b.id, b.batch_name, c.course_name, b.branch_id, br.branch_name
            FROM batches b
            LEFT JOIN courses c ON b.course_id = c.id
            LEFT JOIN branches br ON b.branch_id = br.id
            WHERE b.id = ?
        """, (batch_id,))
        
        batch = cur.fetchone()
        if not batch:
            return redirect(url_for('attendance.list_batches'))
        
        # Check branch access
        if not user['can_view_all_branches'] and batch['branch_id'] != user['branch_id']:
            return redirect(url_for('attendance.list_batches'))
        
        # Get already assigned students in this batch
        cur.execute("""
            SELECT sb.id, sb.student_id, sb.batch_id, sb.joined_on, sb.status,
                   s.student_code, s.full_name, s.phone
            FROM student_batches sb
            JOIN students s ON sb.student_id = s.id
            WHERE sb.batch_id = ?
            ORDER BY sb.joined_on DESC
        """, (batch_id,))
        
        assigned_students = cur.fetchall()
        assigned_student_ids = [s['student_id'] for s in assigned_students]
        
        # Get available students (active students not in this batch, from same branch)
        if assigned_student_ids:
            placeholders = ','.join('?' * len(assigned_student_ids))
            cur.execute(f"""
                SELECT s.id, s.student_code, s.full_name, s.phone, s.email
                FROM students s
                WHERE s.status = 'active'
                AND s.branch_id = ?
                AND s.id NOT IN ({placeholders})
                ORDER BY s.full_name ASC
            """, (batch['branch_id'], *assigned_student_ids))
        else:
            cur.execute("""
                SELECT s.id, s.student_code, s.full_name, s.phone, s.email
                FROM students s
                WHERE s.status = 'active'
                AND s.branch_id = ?
                ORDER BY s.full_name ASC
            """, (batch['branch_id'],))
        
        available_students = cur.fetchall()
        
        if request.method == 'POST':
            action = request.form.get('action')
            
            if action == 'add':
                student_id = request.form.get('student_id')
                
                if not student_id:
                    assigned_students = cur.fetchall()
                    return render_template('attendance/assign_students.html',
                                         batch=batch, assigned_students=assigned_students,
                                         available_students=available_students,
                                         error="Please select a student",
                                         user=user)
                
                now = datetime.now().isoformat(timespec="seconds")
                
                try:
                    cur.execute("""
                        INSERT INTO student_batches (
                            student_id, batch_id, joined_on, status, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (int(student_id), batch_id, now.split('T')[0], 'active', now, now))
                    
                    conn.commit()
                    
                    log_activity(user_id, batch['branch_id'], 'CREATE', 'attendance',
                               batch_id, f'Added student {student_id} to batch')
                    
                    return redirect(url_for('attendance.assign_students', batch_id=batch_id))
                
                except Exception as e:
                    return render_template('attendance/assign_students.html',
                                         batch=batch, assigned_students=assigned_students,
                                         available_students=available_students,
                                         error=str(e), user=user)
            
            elif action == 'remove':
                student_batch_id = request.form.get('student_batch_id')
                
                try:
                    cur.execute("DELETE FROM student_batches WHERE id = ? AND batch_id = ?",
                              (int(student_batch_id), batch_id))
                    conn.commit()
                    
                    log_activity(user_id, batch['branch_id'], 'DELETE', 'attendance',
                               batch_id, f'Removed student from batch')
                    
                    return redirect(url_for('attendance.assign_students', batch_id=batch_id))
                
                except Exception as e:
                    cur.execute("""
                        SELECT sb.id, sb.student_id, sb.batch_id, sb.joined_on, sb.status,
                               s.student_code, s.full_name, s.phone
                        FROM student_batches sb
                        JOIN students s ON sb.student_id = s.id
                        WHERE sb.batch_id = ?
                        ORDER BY sb.joined_on DESC
                    """, (batch_id,))
                    assigned_students = cur.fetchall()
                    return render_template('attendance/assign_students.html',
                                         batch=batch, assigned_students=assigned_students,
                                         available_students=available_students,
                                         error=str(e), user=user)
            
            elif action == 'update-status':
                student_batch_id = request.form.get('student_batch_id')
                new_status = request.form.get('status')
                
                if new_status not in ['active', 'completed', 'dropped']:
                    new_status = 'active'
                
                now = datetime.now().isoformat(timespec="seconds")
                
                try:
                    cur.execute("""
                        UPDATE student_batches
                        SET status = ?, updated_at = ?
                        WHERE id = ? AND batch_id = ?
                    """, (new_status, now, int(student_batch_id), batch_id))
                    
                    conn.commit()
                    
                    log_activity(user_id, batch['branch_id'], 'UPDATE', 'attendance',
                               batch_id, f'Updated student status to {new_status}')
                    
                    return redirect(url_for('attendance.assign_students', batch_id=batch_id))
                
                except Exception as e:
                    cur.execute("""
                        SELECT sb.id, sb.student_id, sb.batch_id, sb.joined_on, sb.status,
                               s.student_code, s.full_name, s.phone
                        FROM student_batches sb
                        JOIN students s ON sb.student_id = s.id
                        WHERE sb.batch_id = ?
                        ORDER BY sb.joined_on DESC
                    """, (batch_id,))
                    assigned_students = cur.fetchall()
                    return render_template('attendance/assign_students.html',
                                         batch=batch, assigned_students=assigned_students,
                                         available_students=available_students,
                                         error=str(e), user=user)
        
        # GET request
        return render_template('attendance/assign_students.html',
                             batch=batch, assigned_students=assigned_students,
                             available_students=available_students, user=user)
    
    finally:
        conn.close()


# ============ MARK ATTENDANCE ============

@attendance_bp.route('/mark-attendance', methods=['GET', 'POST'])
@login_required
def mark_attendance():
    """Mark attendance for a batch"""
    user_id = session.get('user_id')
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        # Get user info
        cur.execute("SELECT id, branch_id, can_view_all_branches FROM users WHERE id = ?", (user_id,))
        user = cur.fetchone()
        
        # Get selected batch and date from request
        batch_id = request.args.get('batch_id') or request.form.get('batch_id')
        attendance_date = request.args.get('date') or request.form.get('attendance_date')
        branch_id = request.args.get('branch_id') or request.form.get('branch_id')
        
        # If no date provided, use today
        if not attendance_date:
            attendance_date = datetime.now().strftime("%Y-%m-%d")
        
        # Get branches
        if user['can_view_all_branches']:
            cur.execute("SELECT id, branch_name FROM branches WHERE is_active = 1 ORDER BY branch_name ASC")
        else:
            cur.execute("SELECT id, branch_name FROM branches WHERE id = ? AND is_active = 1",
                       (user['branch_id'],))
        
        branches = cur.fetchall()
        
        # Default to user's branch if not specified
        if not branch_id:
            branch_id = user['branch_id']
        else:
            branch_id = int(branch_id)
        
        # Check branch access
        if not user['can_view_all_branches'] and branch_id != user['branch_id']:
            return redirect(url_for('attendance.mark_attendance'))
        
        # Get batches for selected branch
        cur.execute("""
            SELECT b.id, b.batch_name, c.course_name, b.start_time, b.end_time
            FROM batches b
            LEFT JOIN courses c ON b.course_id = c.id
            WHERE b.branch_id = ? AND b.status = 'active'
            AND (
                b.start_date IS NULL 
                OR date(b.start_date) <= date(?)
            )
            AND (
                b.end_date IS NULL 
                OR date(b.end_date) >= date(?)
            )
            ORDER BY b.start_time ASC
        """, (branch_id, attendance_date, attendance_date))
        
        batches = cur.fetchall()
        
        students = []
        attendance_data = {}
        batch_info = None
        
        if batch_id and batch_id.isdigit():
            batch_id = int(batch_id)
            
            # Get batch info
            cur.execute("""
                SELECT b.id, b.batch_name, b.branch_id, c.course_name
                FROM batches b
                LEFT JOIN courses c ON b.course_id = c.id
                WHERE b.id = ? AND b.branch_id = ?
            """, (batch_id, branch_id))
            
            batch_info = cur.fetchone()
            
            if batch_info:
                # Get students in this batch
                cur.execute("""
                    SELECT sb.id, sb.student_id, s.student_code, s.full_name, s.phone
                    FROM student_batches sb
                    JOIN students s ON sb.student_id = s.id
                    WHERE sb.batch_id = ? AND sb.status = 'active'
                    ORDER BY s.full_name ASC
                """, (batch_id,))
                
                students = cur.fetchall()
                
                # Get existing attendance for this date
                cur.execute("""
                    SELECT student_id, status, remarks
                    FROM attendance_records
                    WHERE batch_id = ? AND attendance_date = ?
                """, (batch_id, attendance_date))
                
                for row in cur.fetchall():
                    attendance_data[row['student_id']] = {
                        'status': row['status'],
                        'remarks': row['remarks']
                    }

        # Get payment due alerts for students in this batch
        payment_dues = {}
        if students:
            student_ids = [s['student_id'] for s in students]
            try:
                att_date_obj = datetime.strptime(attendance_date, "%Y-%m-%d").date()
            except Exception:
                att_date_obj = datetime.now().date()

            alert_end_date = (att_date_obj + timedelta(days=4)).isoformat()
            att_date_str = att_date_obj.isoformat()
            placeholders = ','.join(['?' for _ in student_ids])

            # Past dues: overdue unpaid installments (MIN date = earliest unpaid = most days overdue)
            cur.execute(f"""
                SELECT i.student_id,
                       SUM(ip.amount_due - ip.amount_paid) AS total_past_due,
                       MIN(parse_date(ip.due_date)) AS earliest_due_date
                FROM installment_plans ip
                JOIN invoices i ON ip.invoice_id = i.id
                WHERE ip.status != 'paid'
                  AND (ip.amount_due - ip.amount_paid) > 0
                  AND date(parse_date(ip.due_date)) < date(?)
                  AND i.student_id IN ({placeholders})
                GROUP BY i.student_id
            """, [att_date_str] + student_ids)
            from datetime import date as date_type
            for row in cur.fetchall():
                sid = row['student_id']
                if sid not in payment_dues:
                    payment_dues[sid] = {}
                payment_dues[sid]['past_due'] = float(row['total_past_due'] or 0)
                try:
                    earliest = date_type.fromisoformat(row['earliest_due_date'])
                    payment_dues[sid]['past_days'] = (att_date_obj - earliest).days
                except Exception:
                    payment_dues[sid]['past_days'] = None

            # Upcoming dues: due within next 4 days (inclusive of today)
            cur.execute(f"""
                SELECT i.student_id,
                       MIN(parse_date(ip.due_date)) AS next_due_date,
                       SUM(ip.amount_due - ip.amount_paid) AS total_upcoming
                FROM installment_plans ip
                JOIN invoices i ON ip.invoice_id = i.id
                WHERE ip.status != 'paid'
                  AND (ip.amount_due - ip.amount_paid) > 0
                  AND date(parse_date(ip.due_date)) >= date(?)
                  AND date(parse_date(ip.due_date)) <= date(?)
                  AND i.student_id IN ({placeholders})
                GROUP BY i.student_id
            """, [att_date_str, alert_end_date] + student_ids)
            for row in cur.fetchall():
                sid = row['student_id']
                if sid not in payment_dues:
                    payment_dues[sid] = {}
                payment_dues[sid]['upcoming_amount'] = float(row['total_upcoming'] or 0)
                payment_dues[sid]['upcoming_date'] = row['next_due_date']
                try:
                    due_d = date_type.fromisoformat(row['next_due_date'])
                    payment_dues[sid]['upcoming_days'] = (due_d - att_date_obj).days
                except Exception:
                    payment_dues[sid]['upcoming_days'] = None

        # Get last 7 days attendance history for each student
        history_7days = {}
        history_dates = []
        if students and batch_id:
            try:
                hist_base = datetime.strptime(attendance_date, "%Y-%m-%d").date()
            except Exception:
                hist_base = datetime.now().date()
            history_dates = [(hist_base - timedelta(days=i)).isoformat() for i in range(7, 0, -1)]
            student_ids_h = [s['student_id'] for s in students]
            ph_d = ','.join(['?' for _ in history_dates])
            ph_s = ','.join(['?' for _ in student_ids_h])
            cur.execute(f"""
                SELECT student_id, attendance_date, status
                FROM attendance_records
                WHERE batch_id = ? AND attendance_date IN ({ph_d})
                AND student_id IN ({ph_s})
            """, [batch_id] + history_dates + student_ids_h)
            for row in cur.fetchall():
                sid = row['student_id']
                if sid not in history_7days:
                    history_7days[sid] = {}
                history_7days[sid][row['attendance_date']] = row['status']

        if request.method == 'POST':
            action = request.form.get('action')
            
            if action == 'mark-all-present':
                # Mark all students as present
                for student in students:
                    status = 'present'
                    remarks = request.form.get(f"remarks_{student['student_id']}", "").strip()
                    _save_attendance(cur, batch_id, student['student_id'], branch_id, 
                                   attendance_date, status, remarks, user_id, conn)
                
                return redirect(url_for('attendance.mark_attendance', 
                                      batch_id=batch_id, date=attendance_date, 
                                      branch_id=branch_id, msg="marked_all_present"))
            
            elif action == 'mark-all-absent':
                # Mark all students as absent
                for student in students:
                    status = 'absent'
                    remarks = request.form.get(f"remarks_{student['student_id']}", "").strip()
                    _save_attendance(cur, batch_id, student['student_id'], branch_id,
                                   attendance_date, status, remarks, user_id, conn)
                
                return redirect(url_for('attendance.mark_attendance',
                                      batch_id=batch_id, date=attendance_date,
                                      branch_id=branch_id, msg="marked_all_absent"))
            
            elif action == 'save':
                # Save individual attendance records
                for student in students:
                    status = request.form.get(f"status_{student['student_id']}", 'absent')
                    remarks = request.form.get(f"remarks_{student['student_id']}", "").strip()
                    
                    if status not in ['present', 'absent', 'late', 'leave']:
                        status = 'absent'
                    
                    _save_attendance(cur, batch_id, student['student_id'], branch_id,
                                   attendance_date, status, remarks, user_id, conn)
                
                return redirect(url_for('attendance.mark_attendance',
                                      batch_id=batch_id, date=attendance_date,
                                      branch_id=branch_id, msg="saved"))
        
        # Get message from redirect
        message = request.args.get('msg')
        
        return render_template('attendance/mark_attendance.html',
                             branches=branches, batches=batches,
                             branch_id=branch_id, batch_id=batch_id,
                             attendance_date=attendance_date,
                             batch_info=batch_info, students=students,
                             attendance_data=attendance_data,
                             payment_dues=payment_dues,
                             history_7days=history_7days,
                             history_dates=history_dates,
                             message=message, user=user)
    
    finally:
        conn.close()


def _save_attendance(cur, batch_id, student_id, branch_id, attendance_date, 
                    status, remarks, user_id, conn):
    """Helper function to save or update attendance record"""
    now = datetime.now().isoformat(timespec="seconds")
    
    # Check if record exists
    cur.execute("""
        SELECT id FROM attendance_records
        WHERE batch_id = ? AND student_id = ? AND attendance_date = ?
    """, (batch_id, student_id, attendance_date))
    
    existing = cur.fetchone()
    
    if existing:
        # Update
        cur.execute("""
            UPDATE attendance_records
            SET status = ?, remarks = ?, marked_by = ?, updated_at = ?
            WHERE batch_id = ? AND student_id = ? AND attendance_date = ?
        """, (status, remarks, user_id, now, batch_id, student_id, attendance_date))
    else:
        # Insert
        cur.execute("""
            INSERT INTO attendance_records (
                attendance_date, student_id, batch_id, branch_id,
                status, remarks, marked_by, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (attendance_date, student_id, batch_id, branch_id,
              status, remarks, user_id, now, now))
    
    conn.commit()
    
    log_activity(user_id, branch_id, 'CREATE' if not existing else 'UPDATE',
               'attendance', batch_id, 
               f'Marked attendance for student {student_id}: {status}')


# ============ DAILY ATTENDANCE REPORT ============

@attendance_bp.route('/daily-report')
@login_required
def daily_report():
    """View daily attendance report"""
    user_id = session.get('user_id')
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        # Get user info
        cur.execute("SELECT id, branch_id, can_view_all_branches FROM users WHERE id = ?", (user_id,))
        user = cur.fetchone()
        
        # Get filter parameters
        reported_date = request.args.get('date') or datetime.now().strftime("%Y-%m-%d")
        branch_id = request.args.get('branch_id')
        batch_id = request.args.get('batch_id')
        
        # Get branches
        if user['can_view_all_branches']:
            cur.execute("SELECT id, branch_name FROM branches WHERE is_active = 1 ORDER BY branch_name ASC")
        else:
            cur.execute("SELECT id, branch_name FROM branches WHERE id = ? AND is_active = 1",
                       (user['branch_id'],))
        
        branches = cur.fetchall()
        
        # Default branch
        if not branch_id:
            branch_id = user['branch_id']
        else:
            branch_id = int(branch_id)
        
        # Check branch access
        if not user['can_view_all_branches'] and branch_id != user['branch_id']:
            return redirect(url_for('attendance.daily_report'))
        
        # Get batches for branch
        cur.execute("""
            SELECT b.id, b.batch_name, c.course_name, 
                   COUNT(DISTINCT ar.student_id) as attendance_count
            FROM batches b
            LEFT JOIN courses c ON b.course_id = c.id
            LEFT JOIN attendance_records ar ON ar.batch_id = b.id AND ar.attendance_date = ?
            WHERE b.branch_id = ? AND b.status = 'active'
            AND (
                b.start_date IS NULL 
                OR date(b.start_date) <= date(?)
            )
            AND (
                b.end_date IS NULL 
                OR date(b.end_date) >= date(?)
            )
            GROUP BY b.id, b.batch_name, c.course_name
            ORDER BY b.batch_name ASC
        """, (reported_date, branch_id, reported_date, reported_date))
        
        batches = cur.fetchall()
        
        # Get attendance records
        attendance_records = []
        batch_info = None
        summary_stats = {
            'total_marked': 0,
            'present': 0,
            'absent': 0,
            'late': 0,
            'leave': 0
        }
        
        if batch_id and batch_id.isdigit():
            batch_id = int(batch_id)
            
            # Get batch info
            cur.execute("""
                SELECT b.id, b.batch_name, c.course_name, u.full_name as trainer_name
                FROM batches b
                LEFT JOIN courses c ON b.course_id = c.id
                LEFT JOIN users u ON b.trainer_id = u.id
                WHERE b.id = ? AND b.branch_id = ?
            """, (batch_id, branch_id))
            
            batch_info = cur.fetchone()
            
            if batch_info:
                # Get attendance records with student details
                cur.execute("""
                    SELECT ar.id, ar.attendance_date, ar.student_id, ar.status, ar.remarks,
                           ar.marked_by, ar.created_at, ar.updated_at,
                           s.student_code, s.full_name, s.phone,
                           u.full_name as marked_by_name
                    FROM attendance_records ar
                    JOIN students s ON ar.student_id = s.id
                    LEFT JOIN users u ON ar.marked_by = u.id
                    WHERE ar.batch_id = ? AND ar.attendance_date = ?
                    ORDER BY s.full_name ASC
                """, (batch_id, reported_date))
                
                attendance_records = cur.fetchall()
                
                # Calculate statistics
                for record in attendance_records:
                    summary_stats['total_marked'] += 1
                    status = record['status']
                    if status == 'present':
                        summary_stats['present'] += 1
                    elif status == 'absent':
                        summary_stats['absent'] += 1
                    elif status == 'late':
                        summary_stats['late'] += 1
                    elif status == 'leave':
                        summary_stats['leave'] += 1
        
        return render_template('attendance/daily_report.html',
                             branches=branches, batches=batches,
                             branch_id=branch_id, batch_id=batch_id,
                             reported_date=reported_date,
                             batch_info=batch_info,
                             attendance_records=attendance_records,
                             summary_stats=summary_stats,
                             user=user)
    
    finally:
        conn.close()


# ============ MONTHLY ATTENDANCE SUMMARY ============

@attendance_bp.route('/monthly-summary')
@login_required
def monthly_summary():
    """View monthly attendance summary by student"""
    user_id = session.get('user_id')
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        # Get user info
        cur.execute("SELECT id, branch_id, can_view_all_branches FROM users WHERE id = ?", (user_id,))
        user = cur.fetchone()
        
        # Get filter parameters
        from_date = request.args.get('from_date')
        to_date = request.args.get('to_date')
        branch_id = request.args.get('branch_id')
        batch_id = request.args.get('batch_id')
        
        # Default date range: current month
        today = datetime.now()
        if not from_date:
            from_date = today.strftime("%Y-%m-01")
        if not to_date:
            # Get last day of current month
            if today.month == 12:
                to_date = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                to_date = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
            to_date = to_date.strftime("%Y-%m-%d")
        
        # Get branches
        if user['can_view_all_branches']:
            cur.execute("SELECT id, branch_name FROM branches WHERE is_active = 1 ORDER BY branch_name ASC")
        else:
            cur.execute("SELECT id, branch_name FROM branches WHERE id = ? AND is_active = 1",
                       (user['branch_id'],))
        
        branches = cur.fetchall()
        
        # Default branch
        if not branch_id:
            branch_id = user['branch_id']
        else:
            branch_id = int(branch_id)
        
        # Check branch access
        if not user['can_view_all_branches'] and branch_id != user['branch_id']:
            return redirect(url_for('attendance.monthly_summary'))
        
        # Get batches for branch
        cur.execute("""
            SELECT id, batch_name, course_id
            FROM batches
            WHERE branch_id = ? AND status = 'active'
            ORDER BY batch_name ASC
        """, (branch_id,))
        
        batches = cur.fetchall()
        
        # Build student summary
        summary_data = []
        
        # Convert batch_id to int if provided (check for non-empty string)
        if batch_id and batch_id.strip() and batch_id != 'None':
            batch_id = int(batch_id)
        else:
            batch_id = None
        
        # Get all active students in branch (and optionally filtered by batch)
        if batch_id:
            cur.execute("""
                SELECT DISTINCT s.id, s.student_code, s.full_name, s.phone
                FROM students s
                JOIN student_batches sb ON s.id = sb.student_id
                WHERE s.branch_id = ? AND sb.batch_id = ? AND sb.status = 'active'
                ORDER BY s.full_name ASC
            """, (branch_id, batch_id))
        else:
            cur.execute("""
                SELECT s.id, s.student_code, s.full_name, s.phone
                FROM students s
                WHERE s.branch_id = ? AND s.status = 'active'
                ORDER BY s.full_name ASC
            """, (branch_id,))
        
        students = cur.fetchall()
        
        # Get attendance statistics for each student
        for student in students:
            cur.execute("""
                SELECT 
                    COUNT(*) as total_marked,
                    SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) as present_count,
                    SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) as absent_count,
                    SUM(CASE WHEN status = 'late' THEN 1 ELSE 0 END) as late_count,
                    SUM(CASE WHEN status = 'leave' THEN 1 ELSE 0 END) as leave_count
                FROM attendance_records
                WHERE student_id = ? 
                AND branch_id = ?
                AND attendance_date BETWEEN ? AND ?
            """, (student['id'], branch_id, from_date, to_date))
            
            stats = cur.fetchone()
            
            total_marked = stats['total_marked'] or 0
            present_count = stats['present_count'] or 0
            absent_count = stats['absent_count'] or 0
            late_count = stats['late_count'] or 0
            leave_count = stats['leave_count'] or 0
            
            # Calculate percentage
            attendance_percentage = 0
            if total_marked > 0:
                attendance_percentage = (present_count / total_marked) * 100
            
            summary_data.append({
                'student_id': student['id'],
                'student_code': student['student_code'],
                'full_name': student['full_name'],
                'phone': student['phone'],
                'total_marked': total_marked,
                'present': present_count,
                'absent': absent_count,
                'late': late_count,
                'leave': leave_count,
                'percentage': attendance_percentage
            })
        
        # Calculate overall statistics
        overall_stats = {
            'total_students': len(summary_data),
            'total_marked_records': sum(s['total_marked'] for s in summary_data),
            'total_present': sum(s['present'] for s in summary_data),
            'total_absent': sum(s['absent'] for s in summary_data),
            'total_late': sum(s['late'] for s in summary_data),
            'total_leave': sum(s['leave'] for s in summary_data),
            'avg_percentage': sum(s['percentage'] for s in summary_data) / len(summary_data) if summary_data else 0
        }
        
        # Sort by attendance percentage (descending first, then by name)
        sort_by = request.args.get('sort_by', 'name')
        if sort_by == 'percentage':
            summary_data.sort(key=lambda x: (-x['percentage'], x['full_name']))
        else:
            summary_data.sort(key=lambda x: x['full_name'])
        
        return render_template('attendance/monthly_summary.html',
                             branches=branches, batches=batches,
                             branch_id=branch_id, batch_id=batch_id,
                             from_date=from_date, to_date=to_date,
                             summary_data=summary_data,
                             overall_stats=overall_stats,
                             sort_by=sort_by,
                             user=user)
    
    finally:
        conn.close()


# ============ LOW ATTENDANCE / DEFAULTERS ============

@attendance_bp.route('/defaulters')
@login_required
def defaulters():
    """View students with low attendance below threshold"""
    user_id = session.get('user_id')
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        # Get user info
        cur.execute("SELECT id, branch_id, can_view_all_branches FROM users WHERE id = ?", (user_id,))
        user = cur.fetchone()
        
        # Get filter parameters
        branch_id = request.args.get('branch_id')
        batch_id = request.args.get('batch_id')
        followup_status = request.args.get('followup_status')
        threshold = float(request.args.get('threshold', 75))  # Default 75% attendance
        
        # Get branches
        if user['can_view_all_branches']:
            cur.execute("SELECT id, branch_name FROM branches WHERE is_active = 1 ORDER BY branch_name ASC")
        else:
            cur.execute("SELECT id, branch_name FROM branches WHERE id = ? AND is_active = 1",
                       (user['branch_id'],))
        
        branches = cur.fetchall()
        
        # Default branch
        if not branch_id:
            branch_id = user['branch_id']
        else:
            branch_id = int(branch_id)
        
        # Check branch access
        if not user['can_view_all_branches'] and branch_id != user['branch_id']:
            return redirect(url_for('attendance.defaulters'))
        
        # Get batches for branch
        cur.execute("""
            SELECT id, batch_name
            FROM batches
            WHERE branch_id = ? AND status = 'active'
            ORDER BY batch_name ASC
        """, (branch_id,))
        
        batches = cur.fetchall()
        
        # Build defaulter list
        defaulters_data = []
        
        # Convert batch_id to int if provided (check for non-empty string)
        if batch_id and batch_id.strip() and batch_id != 'None':
            batch_id = int(batch_id)
        else:
            batch_id = None
        
        # Get all active students enrolled in batches
        if batch_id:
            cur.execute("""
                SELECT DISTINCT s.id, s.student_code, s.full_name, s.phone, sb.batch_id, b.batch_name
                FROM students s
                JOIN student_batches sb ON s.id = sb.student_id
                JOIN batches b ON sb.batch_id = b.id
                WHERE s.branch_id = ? AND sb.batch_id = ? AND sb.status = 'active' AND s.status = 'active'
                ORDER BY s.full_name ASC
            """, (branch_id, batch_id))
        else:
            cur.execute("""
                SELECT DISTINCT s.id, s.student_code, s.full_name, s.phone, sb.batch_id, b.batch_name
                FROM students s
                JOIN student_batches sb ON s.id = sb.student_id
                JOIN batches b ON sb.batch_id = b.id
                WHERE s.branch_id = ? AND sb.status = 'active' AND s.status = 'active'
                ORDER BY s.full_name ASC
            """, (branch_id,))
        
        students = cur.fetchall()
        
        # Get attendance statistics and followup info for each student
        for student in students:
            cur.execute("""
                SELECT 
                    COUNT(*) as total_marked,
                    SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) as present_count
                FROM attendance_records
                WHERE student_id = ? AND branch_id = ?
            """, (student['id'], branch_id))
            
            stats = cur.fetchone()
            total_marked = stats['total_marked'] or 0
            present_count = stats['present_count'] or 0
            
            # Calculate percentage
            attendance_percentage = 0
            if total_marked > 0:
                attendance_percentage = (present_count / total_marked) * 100
            
            # Only include students below threshold
            if attendance_percentage < threshold:
                # Get latest followup info
                cur.execute("""
                    SELECT followup_status, last_followup_date, remarks
                    FROM attendance_followups
                    WHERE student_id = ? AND branch_id = ?
                    ORDER BY last_followup_date DESC
                    LIMIT 1
                """, (student['id'], branch_id))
                
                followup_info = cur.fetchone()
                
                defaulters_data.append({
                    'student_id': student['id'],
                    'student_code': student['student_code'],
                    'full_name': student['full_name'],
                    'phone': student['phone'],
                    'batch_id': student['batch_id'],
                    'batch_name': student['batch_name'],
                    'total_marked': total_marked,
                    'attendance_percentage': attendance_percentage,
                    'followup_status': followup_info['followup_status'] if followup_info else 'pending',
                    'last_followup_date': followup_info['last_followup_date'] if followup_info else None,
                    'followup_remarks': followup_info['remarks'] if followup_info else None
                })
        
        # Filter by followup status if provided
        if followup_status and followup_status != 'all':
            defaulters_data = [d for d in defaulters_data if d['followup_status'] == followup_status]
        
        # Sort by attendance percentage (lowest first)
        defaulters_data.sort(key=lambda x: (x['attendance_percentage'], x['full_name']))
        
        # Calculate summary
        summary_stats = {
            'total_defaulters': len(defaulters_data),
            'pending_followups': len([d for d in defaulters_data if d['followup_status'] == 'pending']),
            'contacted': len([d for d in defaulters_data if d['followup_status'] == 'contacted']),
            'resolved': len([d for d in defaulters_data if d['followup_status'] == 'resolved']),
            'no_response': len([d for d in defaulters_data if d['followup_status'] == 'no_response']),
            'avg_attendance': sum(d['attendance_percentage'] for d in defaulters_data) / len(defaulters_data) if defaulters_data else 0
        }
        
        return render_template('attendance/defaulters.html',
                             branches=branches, batches=batches,
                             branch_id=branch_id, batch_id=batch_id,
                             threshold=threshold,
                             followup_status=followup_status,
                             defaulters_data=defaulters_data,
                             summary_stats=summary_stats,
                             user=user)
    
    finally:
        conn.close()


@attendance_bp.route('/defaulters/<int:student_id>/add-followup', methods=['POST'])
@login_required
def add_followup(student_id):
    """Add or update followup for a student"""
    user_id = session.get('user_id')
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        # Verify user can access this student
        cur.execute("SELECT id, branch_id, can_view_all_branches FROM users WHERE id = ?", (user_id,))
        user = cur.fetchone()
        
        cur.execute("SELECT id, branch_id FROM students WHERE id = ?", (student_id,))
        student = cur.fetchone()
        
        if not student:
            return jsonify({'error': 'Student not found'}), 404
        
        if not user['can_view_all_branches'] and student['branch_id'] != user['branch_id']:
            return jsonify({'error': 'Access denied'}), 403
        
        # Get form data
        followup_date = request.form.get('followup_date', '').strip()
        followup_status = request.form.get('followup_status')
        remarks = request.form.get('remarks', '').strip()
        
        if not followup_date:
            return jsonify({'error': 'Follow-up date is required'}), 400
        
        if not followup_status or followup_status not in ['pending', 'contacted', 'resolved', 'no_response']:
            return jsonify({'error': 'Invalid followup status'}), 400
        
        # Check if followup exists
        cur.execute("""
            SELECT id FROM attendance_followups
            WHERE student_id = ? AND branch_id = ?
        """, (student_id, student['branch_id']))
        
        existing = cur.fetchone()
        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if existing:
            # Update existing
            cur.execute("""
                UPDATE attendance_followups
                SET followup_date = ?, followup_status = ?, last_followup_date = ?, remarks = ?, updated_at = ?
                WHERE student_id = ? AND branch_id = ?
            """, (followup_date, followup_status, today, remarks, today, student_id, student['branch_id']))
        else:
            # Create new
            cur.execute("""
                INSERT INTO attendance_followups
                (student_id, branch_id, followup_date, followup_status, last_followup_date, remarks, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (student_id, student['branch_id'], followup_date, followup_status, today, remarks, today, today))
        
        # Log activity
        cur.execute("""
            INSERT INTO activity_logs (user_id, branch_id, action_type, module_name, record_id, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, student['branch_id'], 'update', 'attendance_followup', student_id,
              f'Attended follow-up for student - Status: {followup_status}', today))
        
        conn.commit()
        return jsonify({'success': 'Follow-up updated successfully'}), 200
    
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    
    finally:
        conn.close()


# ============ ATTENDANCE FOLLOWUPS MANAGEMENT ============

@attendance_bp.route('/followups')
@login_required
def followups():
    """View and manage all attendance follow-ups"""
    user_id = session.get('user_id')
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        # Get user info
        cur.execute("SELECT id, branch_id, can_view_all_branches FROM users WHERE id = ?", (user_id,))
        user = cur.fetchone()
        
        # Get filter parameters
        branch_id = request.args.get('branch_id')
        batch_id = request.args.get('batch_id')
        status = request.args.get('status')
        from_date = request.args.get('from_date')
        to_date = request.args.get('to_date')
        
        # Get branches
        if user['can_view_all_branches']:
            cur.execute("SELECT id, branch_name FROM branches WHERE is_active = 1 ORDER BY branch_name ASC")
        else:
            cur.execute("SELECT id, branch_name FROM branches WHERE id = ? AND is_active = 1",
                       (user['branch_id'],))
        
        branches = cur.fetchall()
        
        # Default branch
        if not branch_id:
            branch_id = user['branch_id']
        else:
            branch_id = int(branch_id)
        
        # Check branch access
        if not user['can_view_all_branches'] and branch_id != user['branch_id']:
            return redirect(url_for('attendance.followups'))
        
        # Get batches for branch
        cur.execute("""
            SELECT id, batch_name
            FROM batches
            WHERE branch_id = ? AND status = 'active'
            ORDER BY batch_name ASC
        """, (branch_id,))
        
        batches = cur.fetchall()
        
        # Build followups list
        query = """
            SELECT 
                af.id,
                af.student_id,
                af.branch_id,
                af.followup_status,
                af.last_followup_date,
                af.remarks,
                af.created_at,
                af.updated_at,
                s.student_code,
                s.full_name,
                s.phone
            FROM attendance_followups af
            JOIN students s ON af.student_id = s.id
            WHERE af.branch_id = ?
        """
        
        params = [branch_id]
        
        # Convert batch_id to int if provided (check for non-empty string)
        if batch_id and batch_id.strip() and batch_id != 'None':
            batch_id = int(batch_id)
        else:
            batch_id = None
        
        # Add filters
        if batch_id:
            query += """ AND af.student_id IN (
                SELECT student_id FROM student_batches WHERE batch_id = ? AND status = 'active'
            )"""
            params.append(batch_id)
        
        if status and status != 'all':
            query += " AND af.followup_status = ?"
            params.append(status)
        
        if from_date:
            query += " AND DATE(af.last_followup_date) >= ?"
            params.append(from_date)
        
        if to_date:
            query += " AND DATE(af.last_followup_date) <= ?"
            params.append(to_date)
        
        query += " ORDER BY af.last_followup_date DESC"
        
        cur.execute(query, params)
        followups_data = cur.fetchall()
        
        # Get batch names for each followup
        for followup in followups_data:
            cur.execute("""
                SELECT DISTINCT batch_name FROM batches
                WHERE id IN (SELECT batch_id FROM student_batches WHERE student_id = ? AND status = 'active')
                LIMIT 1
            """, (followup['student_id'],))
            batch_row = cur.fetchone()
            followup['batch_name'] = batch_row['batch_name'] if batch_row else None
        
        # Calculate summary stats
        summary_stats = {
            'total_followups': len(followups_data),
            'pending': len([f for f in followups_data if f['followup_status'] == 'pending']),
            'contacted': len([f for f in followups_data if f['followup_status'] == 'contacted']),
            'resolved': len([f for f in followups_data if f['followup_status'] == 'resolved']),
            'no_response': len([f for f in followups_data if f['followup_status'] == 'no_response'])
        }
        
        return render_template('attendance/followups.html',
                             branches=branches, batches=batches,
                             branch_id=branch_id, batch_id=batch_id,
                             status=status, from_date=from_date, to_date=to_date,
                             followups_data=followups_data,
                             summary_stats=summary_stats,
                             user=user)
    
    finally:
        conn.close()


@attendance_bp.route('/followups/<int:followup_id>')
@login_required
def followup_detail(followup_id):
    """View detailed followup record with student context"""
    user_id = session.get('user_id')
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        # Get user info
        cur.execute("SELECT id, branch_id, can_view_all_branches FROM users WHERE id = ?", (user_id,))
        user = cur.fetchone()
        
        # Get followup
        cur.execute("""
            SELECT af.*, s.student_code, s.full_name, s.phone, b.batch_name
            FROM attendance_followups af
            JOIN students s ON af.student_id = s.id
            LEFT JOIN (
                SELECT student_id, batch_id FROM student_batches WHERE status = 'active'
            ) sb ON s.id = sb.student_id
            LEFT JOIN batches b ON sb.batch_id = b.id
            WHERE af.id = ?
        """, (followup_id,))
        
        followup = cur.fetchone()
        
        if not followup:
            return redirect(url_for('attendance.followups'))
        
        # Check access
        if not user['can_view_all_branches'] and followup['branch_id'] != user['branch_id']:
            return redirect(url_for('attendance.followups'))
        
        # Get attendance before and after followup
        cur.execute("""
            SELECT 
                COUNT(*) as total_marked,
                SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) as present,
                SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) as absent,
                SUM(CASE WHEN status = 'late' THEN 1 ELSE 0 END) as late,
                SUM(CASE WHEN status = 'leave' THEN 1 ELSE 0 END) as leave
            FROM attendance_records
            WHERE student_id = ? AND branch_id = ? AND attendance_date <= ?
        """, (followup['student_id'], followup['branch_id'], followup['last_followup_date']))
        
        attendance_before = cur.fetchone()
        
        # Get attendance after followup (last 30 days after followup)
        thirty_days_after = (datetime.strptime(followup['last_followup_date'][:10], "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        cur.execute("""
            SELECT 
                COUNT(*) as total_marked,
                SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) as present,
                SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) as absent,
                SUM(CASE WHEN status = 'late' THEN 1 ELSE 0 END) as late,
                SUM(CASE WHEN status = 'leave' THEN 1 ELSE 0 END) as leave
            FROM attendance_records
            WHERE student_id = ? AND branch_id = ? AND attendance_date > ? AND attendance_date <= ?
        """, (followup['student_id'], followup['branch_id'], followup['last_followup_date'][:10], thirty_days_after))
        
        attendance_after = cur.fetchone()
        
        # Get activity logs for this followup
        cur.execute("""
            SELECT logged_at, description, u.username
            FROM activity_logs al
            JOIN users u ON al.user_id = u.id
            WHERE al.entity_id = ? AND al.entity_type = 'attendance_followup'
            ORDER BY al.logged_at DESC
        """, (followup['student_id'],))
        
        activity_logs = cur.fetchall()
        
        return render_template('attendance/followup_detail.html',
                             followup=followup,
                             attendance_before=attendance_before,
                             attendance_after=attendance_after,
                             activity_logs=activity_logs,
                             user=user)
    
    finally:
        conn.close()


# ============ STUDENT ATTENDANCE HISTORY ============

@attendance_bp.route('/student/<int:student_id>')
@login_required
def student_attendance_history(student_id):
    """View detailed attendance history for a single student"""
    user_id = session.get('user_id')
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        # Get user info
        cur.execute("SELECT id, branch_id, can_view_all_branches FROM users WHERE id = ?", (user_id,))
        user = cur.fetchone()
        
        # Get student
        cur.execute("""
            SELECT id, branch_id, student_code, full_name, phone, email, 
                   gender, education_level, status, created_at
            FROM students
            WHERE id = ?
        """, (student_id,))
        
        student = cur.fetchone()
        
        if not student:
            return redirect(url_for('attendance.dashboard'))
        
        # Check access
        if not user['can_view_all_branches'] and student['branch_id'] != user['branch_id']:
            return redirect(url_for('attendance.dashboard'))
        
        # Get enrolled batches
        cur.execute("""
            SELECT sb.id, b.id as batch_id, b.batch_name, sb.joined_on, sb.status,
                   c.course_name, b.start_date, b.end_date
            FROM student_batches sb
            JOIN batches b ON sb.batch_id = b.id
            LEFT JOIN courses c ON b.course_id = c.id
            WHERE sb.student_id = ?
            ORDER BY sb.joined_on DESC
        """, (student_id,))
        
        batches = cur.fetchall()
        
        # Get all attendance records by date
        cur.execute("""
            SELECT ar.id, ar.attendance_date, ar.status, ar.remarks, ar.marked_by,
                   b.batch_name, u.username
            FROM attendance_records ar
            LEFT JOIN batches b ON ar.batch_id = b.id
            LEFT JOIN users u ON ar.marked_by = u.id
            WHERE ar.student_id = ? AND ar.branch_id = ?
            ORDER BY ar.attendance_date DESC
        """, (student_id, student['branch_id']))
        
        attendance_records = cur.fetchall()
        
        # Get monthly attendance statistics
        cur.execute("""
            SELECT 
                strftime('%Y-%m', attendance_date) as month,
                COUNT(*) as total_marked,
                SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) as present,
                SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) as absent,
                SUM(CASE WHEN status = 'late' THEN 1 ELSE 0 END) as late,
                SUM(CASE WHEN status = 'leave' THEN 1 ELSE 0 END) as leave
            FROM attendance_records
            WHERE student_id = ? AND branch_id = ?
            GROUP BY strftime('%Y-%m', attendance_date)
            ORDER BY month DESC
        """, (student_id, student['branch_id']))
        
        monthly_stats = cur.fetchall()
        
        # Get follow-up history
        cur.execute("""
            SELECT id, followup_status, last_followup_date, remarks, created_at, updated_at
            FROM attendance_followups
            WHERE student_id = ? AND branch_id = ?
            ORDER BY last_followup_date DESC
        """, (student_id, student['branch_id']))
        
        followups = cur.fetchall()
        
        # Calculate overall statistics
        cur.execute("""
            SELECT 
                COUNT(*) as total_marked,
                SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) as present,
                SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) as absent,
                SUM(CASE WHEN status = 'late' THEN 1 ELSE 0 END) as late,
                SUM(CASE WHEN status = 'leave' THEN 1 ELSE 0 END) as leave
            FROM attendance_records
            WHERE student_id = ? AND branch_id = ?
        """, (student_id, student['branch_id']))
        
        overall_stats = cur.fetchone()
        
        # Calculate overall percentage
        overall_percentage = 0
        if overall_stats['total_marked']:
            overall_percentage = (overall_stats['present'] / overall_stats['total_marked']) * 100
        
        # Get current batch (active)
        current_batch = None
        for batch in batches:
            if batch['status'] == 'active':
                current_batch = batch
                break
        
        return render_template('attendance/student_history.html',
                             student=student,
                             current_batch=current_batch,
                             batches=batches,
                             attendance_records=attendance_records,
                             monthly_stats=monthly_stats,
                             followups=followups,
                             overall_stats=overall_stats,
                             overall_percentage=overall_percentage,
                             user=user)
    
    finally:
        conn.close()



@attendance_bp.route('/batch-planner')
@login_required
def batch_planner():
    conn = get_conn()
    try:
        cur = conn.cursor()

        can_view_all = session.get('can_view_all_branches', 1)
        user_branch_id = session.get('branch_id')

        if can_view_all:
            cur.execute("SELECT * FROM branches WHERE is_active = 1 ORDER BY branch_name")
        else:
            cur.execute("SELECT * FROM branches WHERE id = ? AND is_active = 1", (user_branch_id,))
        branches = cur.fetchall()

        selected_branch_id = request.args.get('branch_id', type=int)
        if not selected_branch_id and branches:
            selected_branch_id = branches[0]['id']

        selected_branch = None
        existing_batches = []
        capacity_info = {}
        suggested_slots = []
        opening_time = None
        closing_time = None
        batch_duration_mins = request.args.get('batch_duration_mins', 120, type=int)
        if batch_duration_mins < 30:
            batch_duration_mins = 30

        if selected_branch_id:
            cur.execute("SELECT * FROM branches WHERE id = ?", (selected_branch_id,))
            selected_branch = cur.fetchone()

            cur.execute("""
                SELECT b.id, b.batch_name, b.start_time, b.end_time, b.status,
                       c.course_name,
                       COUNT(sb.id) as student_count
                FROM batches b
                LEFT JOIN courses c ON b.course_id = c.id
                LEFT JOIN student_batches sb ON sb.batch_id = b.id AND sb.status = 'active'
                WHERE b.branch_id = ? AND b.status = 'active'
                GROUP BY b.id
                ORDER BY b.start_time
            """, (selected_branch_id,))
            raw_batches = cur.fetchall()

            no_of_computers = selected_branch['no_of_computers'] if selected_branch['no_of_computers'] else 0

            batch_list = [dict(row) for row in raw_batches]
            for batch in batch_list:
                s1 = batch['start_time'] or '00:00'
                e1 = batch['end_time'] or '23:59'
                concurrent_students = 0
                for other in batch_list:
                    s2 = other['start_time'] or '00:00'
                    e2 = other['end_time'] or '23:59'
                    if s1 < e2 and s2 < e1:
                        concurrent_students += other['student_count']
                batch['concurrent_students'] = concurrent_students
                batch['computers_free'] = max(0, no_of_computers - concurrent_students)

                # Calculate duration
                if batch['start_time'] and batch['end_time']:
                    try:
                        sh, sm = map(int, batch['start_time'].split(':'))
                        eh, em = map(int, batch['end_time'].split(':'))
                        diff_mins = (eh * 60 + em) - (sh * 60 + sm)
                        if diff_mins > 0:
                            h, m = divmod(diff_mins, 60)
                            batch['duration_str'] = f"{h}h {m}m" if m else f"{h}h"
                        else:
                            batch['duration_str'] = '—'
                    except Exception:
                        batch['duration_str'] = '—'
                else:
                    batch['duration_str'] = '—'

            existing_batches = batch_list

            proposed_start = request.args.get('proposed_start', '')
            proposed_end = request.args.get('proposed_end', '')
            proposed_students = request.args.get('proposed_students', 0, type=int)

            capacity_info = {
                'no_of_computers': no_of_computers,
                'proposed_start': proposed_start,
                'proposed_end': proposed_end,
                'proposed_students': proposed_students,
                'checked': False,
                'conflicting_batches': [],
                'peak_concurrent': 0,
                'computers_free': no_of_computers,
                'can_fit': None,
            }

            if proposed_start and proposed_end:
                capacity_info['checked'] = True
                conflicting = []
                peak = 0
                for batch in existing_batches:
                    s2 = batch['start_time'] or '00:00'
                    e2 = batch['end_time'] or '23:59'
                    if proposed_start < e2 and s2 < proposed_end:
                        conflicting.append(batch)
                        peak += batch['student_count']

                computers_free = no_of_computers - peak
                capacity_info['conflicting_batches'] = conflicting
                capacity_info['peak_concurrent'] = peak
                capacity_info['computers_free'] = computers_free
                capacity_info['can_fit'] = (computers_free >= proposed_students) if no_of_computers > 0 else None

            # Compute suggested specific-duration batch slots
            suggested_slots = []
            opening_time = selected_branch['opening_time'] if selected_branch['opening_time'] else None
            closing_time = selected_branch['closing_time'] if selected_branch['closing_time'] else None

            if opening_time and closing_time and no_of_computers > 0:
                oh, om = map(int, opening_time.split(':'))
                ch, cm = map(int, closing_time.split(':'))
                open_mins = oh * 60 + om
                close_mins = ch * 60 + cm

                candidate = open_mins
                while candidate + batch_duration_mins <= close_mins:
                    slot_start = f"{candidate // 60:02d}:{candidate % 60:02d}"
                    slot_end_mins = candidate + batch_duration_mins
                    slot_end = f"{slot_end_mins // 60:02d}:{slot_end_mins % 60:02d}"

                    # Count students concurrent during this proposed slot
                    peak = 0
                    for batch in existing_batches:
                        bs = batch['start_time'] or '00:00'
                        be = batch['end_time'] or '23:59'
                        if slot_start < be and bs < slot_end:
                            peak += batch['student_count']

                    free = max(0, no_of_computers - peak)
                    if free > 0:
                        h2, m2 = divmod(batch_duration_mins, 60)
                        dur_str = f"{h2}h {m2}m" if m2 else f"{h2}h"
                        suggested_slots.append({
                            'start': slot_start,
                            'end': slot_end,
                            'computers_free': free,
                            'occupied': peak,
                            'duration_str': dur_str,
                        })

                    candidate += 30  # step every 30 minutes

        return render_template('attendance/batch_planner.html',
                               branches=branches,
                               selected_branch=selected_branch,
                               selected_branch_id=selected_branch_id,
                               existing_batches=existing_batches,
                               capacity_info=capacity_info,
                               suggested_slots=suggested_slots,
                               opening_time=opening_time,
                               closing_time=closing_time,
                               batch_duration_mins=batch_duration_mins)
    finally:
        conn.close()


@attendance_bp.route('/attendance-pattern')
@login_required
def attendance_pattern():
    """Visual 31-day attendance pattern page per student"""
    user_id = session.get('user_id')
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, branch_id, can_view_all_branches FROM users WHERE id = ?", (user_id,))
        user = cur.fetchone()

        # Branch list
        if user['can_view_all_branches']:
            cur.execute("SELECT id, branch_name FROM branches WHERE is_active = 1 ORDER BY branch_name ASC")
        else:
            cur.execute("SELECT id, branch_name FROM branches WHERE id = ? AND is_active = 1", (user['branch_id'],))
        branches = cur.fetchall()

        # Resolve selected branch
        selected_branch_id = request.args.get('branch_id', type=int)
        if not selected_branch_id:
            selected_branch_id = user['branch_id'] if not user['can_view_all_branches'] else None
        if not user['can_view_all_branches']:
            selected_branch_id = user['branch_id']

        # Date range  (default: last 30 days ending today)
        today = datetime.now().date()
        default_to = today.isoformat()
        default_from = (today - timedelta(days=30)).isoformat()
        date_from_str = request.args.get('date_from', default_from)
        date_to_str   = request.args.get('date_to',   default_to)
        try:
            date_from = datetime.strptime(date_from_str, "%Y-%m-%d").date()
            date_to   = datetime.strptime(date_to_str,   "%Y-%m-%d").date()
        except ValueError:
            date_from = today - timedelta(days=30)
            date_to   = today
            date_from_str = date_from.isoformat()
            date_to_str   = date_to.isoformat()

        # Cap to 31 days max
        if (date_to - date_from).days > 30:
            date_from = date_to - timedelta(days=30)
            date_from_str = date_from.isoformat()

        # Build ordered date list
        num_days = (date_to - date_from).days + 1
        date_range = [(date_from + timedelta(days=i)).isoformat() for i in range(num_days)]

        # Batches for filter
        batch_id = request.args.get('batch_id', type=int)
        if selected_branch_id:
            cur.execute("""
                SELECT b.id, b.batch_name, c.course_name
                FROM batches b
                LEFT JOIN courses c ON b.course_id = c.id
                WHERE b.branch_id = ? AND b.status = 'active'
                ORDER BY b.start_time ASC
            """, (selected_branch_id,))
        else:
            cur.execute("""
                SELECT b.id, b.batch_name, c.course_name
                FROM batches b
                LEFT JOIN courses c ON b.course_id = c.id
                WHERE b.status = 'active'
                ORDER BY b.start_time ASC
            """)
        batches = cur.fetchall()

        # Students in selected batch (or all students across branch if no batch)
        students = []
        if batch_id:
            cur.execute("""
                SELECT s.id, s.student_code, s.full_name, s.phone, s.photo_filename
                FROM student_batches sb
                JOIN students s ON sb.student_id = s.id
                WHERE sb.batch_id = ? AND sb.status = 'active'
                ORDER BY s.full_name ASC
            """, (batch_id,))
            students = cur.fetchall()
        elif selected_branch_id:
            cur.execute("""
                SELECT DISTINCT s.id, s.student_code, s.full_name, s.phone, s.photo_filename
                FROM student_batches sb
                JOIN students s ON sb.student_id = s.id
                JOIN batches b ON sb.batch_id = b.id
                WHERE b.branch_id = ? AND sb.status = 'active' AND b.status = 'active'
                ORDER BY s.full_name ASC
            """, (selected_branch_id,))
            students = cur.fetchall()

        # Attendance records for the date range
        pattern = {}  # {student_id: {date_str: status}}
        if students and date_range:
            student_ids = [s['id'] for s in students]
            ph_d = ','.join(['?' for _ in date_range])
            ph_s = ','.join(['?' for _ in student_ids])
            batch_filter = ""
            params = date_range + student_ids
            if batch_id:
                batch_filter = "AND batch_id = ?"
                params.append(batch_id)
            cur.execute(f"""
                SELECT student_id, attendance_date, status
                FROM attendance_records
                WHERE attendance_date IN ({ph_d})
                AND student_id IN ({ph_s})
                {batch_filter}
            """, params)
            for row in cur.fetchall():
                sid = row['student_id']
                if sid not in pattern:
                    pattern[sid] = {}
                pattern[sid][row['attendance_date']] = row['status']

        return render_template('attendance/attendance_pattern.html',
                               branches=branches,
                               batches=batches,
                               students=students,
                               selected_branch_id=selected_branch_id,
                               batch_id=batch_id,
                               date_from=date_from_str,
                               date_to=date_to_str,
                               date_range=date_range,
                               pattern=pattern,
                               user=user)
    finally:
        conn.close()
