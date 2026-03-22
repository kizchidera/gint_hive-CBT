# app.py - Complete Working Version with All Features
import os
import csv
import io
import json
import re
import sqlite3
import datetime
import time
import base64
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import pdfkit

# Configure pdfkit with wkhtmltopdf path
WKHTMLTOPDF_PATH = r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe'

# Verify the file exists
if not os.path.exists(WKHTMLTOPDF_PATH):
    alt_path = r'C:\Program Files\wkhtmltopdf\wkhtmltopdf.exe'
    if os.path.exists(alt_path):
        WKHTMLTOPDF_PATH = alt_path
    else:
        print("Warning: wkhtmltopdf not found. PDF generation may fail.")

# Configure pdfkit with the path
config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH) if os.path.exists(WKHTMLTOPDF_PATH) else None

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production'
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=7)

# Configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'csv', 'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Custom Jinja2 filter
@app.template_filter('nl2br')
def nl2br_filter(text):
    """Convert newlines to <br> tags"""
    if not text:
        return ''
    return text.replace('\n', '<br>')

# Helper functions
def hash_password(password):
    return generate_password_hash(password)

def verify_password(password, hashed):
    return check_password_hash(hashed, password)

def get_db_connection(db_path, timeout=30):
    """Get database connection with timeout and WAL mode"""
    conn = sqlite3.connect(db_path, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA cache_size = 10000")
    return conn

def init_main_db():
    conn = get_db_connection('main.db')
    conn.execute('''CREATE TABLE IF NOT EXISTS schools (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_name TEXT UNIQUE,
        school_id TEXT UNIQUE,
        admin_username TEXT,
        admin_password TEXT,
        subscription_level TEXT DEFAULT 'Basic',
        subscription_start TEXT,
        subscription_end TEXT,
        db_path TEXT
    )''')
    conn.commit()
    conn.close()

def init_school_db(db_path):
    conn = get_db_connection(db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    
    # Subjects table
    conn.execute('''CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_code TEXT UNIQUE,
        subject_name TEXT,
        description TEXT,
        created_at TEXT
    )''')
    
    # Students table
    conn.execute('''CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT UNIQUE,
        name TEXT,
        class_id TEXT,
        session TEXT,
        password TEXT
    )''')
    
    # Exams table with subject reference
    conn.execute('''CREATE TABLE IF NOT EXISTS exams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_title TEXT,
        exam_code TEXT UNIQUE,
        subject_code TEXT,
        exam_date TEXT,
        exam_time TEXT,
        timer_minutes INTEGER,
        class_id TEXT,
        is_active INTEGER DEFAULT 0,
        exam_type TEXT DEFAULT 'objective',
        instructions TEXT
    )''')
    
    # Questions table
    conn.execute('''CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_code TEXT,
        serial_no INTEGER,
        question TEXT,
        option1 TEXT,
        option2 TEXT,
        option3 TEXT,
        option4 TEXT,
        correct_answer TEXT,
        score INTEGER
    )''')
    
    # Results table
    conn.execute('''CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        exam_code TEXT,
        score INTEGER,
        total_possible INTEGER,
        submitted_at TEXT
    )''')
    
    # Exam assignments table
    conn.execute('''CREATE TABLE IF NOT EXISTS exam_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_code TEXT,
        student_id TEXT,
        assigned_at TEXT,
        started_at TEXT,
        completed_at TEXT,
        status TEXT DEFAULT 'pending'
    )''')
    
    # Proctor logs table with image storage
    conn.execute('''CREATE TABLE IF NOT EXISTS proctor_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        exam_code TEXT,
        violation_type TEXT,
        image_data TEXT,
        created_at TEXT
    )''')
    
    # School settings table
    conn.execute('''CREATE TABLE IF NOT EXISTS school_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    
    # Exam attempts table for tracking retakes
    conn.execute('''CREATE TABLE IF NOT EXISTS exam_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        exam_code TEXT,
        attempt_number INTEGER DEFAULT 1,
        started_at TEXT,
        completed_at TEXT,
        status TEXT DEFAULT 'in_progress'
    )''')
    
    # Theory answers table
    conn.execute('''CREATE TABLE IF NOT EXISTS theory_answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        exam_code TEXT,
        attempt_id INTEGER,
        question_id INTEGER,
        answer TEXT,
        score INTEGER,
        feedback TEXT,
        submitted_at TEXT
    )''')
    
    # Student responses table
    conn.execute('''CREATE TABLE IF NOT EXISTS student_responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        exam_code TEXT,
        attempt_id INTEGER,
        responses_json TEXT,
        submitted_at TEXT
    )''')
    
    # Create indexes for better performance
    conn.execute('CREATE INDEX IF NOT EXISTS idx_exams_code ON exams(exam_code)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_exams_subject ON exams(subject_code)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_questions_exam ON questions(exam_code)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_assignments_exam ON exam_assignments(exam_code)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_assignments_student ON exam_assignments(student_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_results_student ON results(student_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_results_exam ON results(exam_code)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_attempts_student ON exam_attempts(student_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_proctor_logs ON proctor_logs(exam_code, student_id)')
    
    conn.commit()
    conn.close()

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            flash('Please login as admin', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_super_admin'):
            flash('Super admin access required', 'error')
            return redirect(url_for('super_admin_login_page'))
        return f(*args, **kwargs)
    return decorated_function

@app.context_processor
def utility_processor():
    return {'datetime': datetime}

# ==================== AUTHENTICATION ROUTES ====================
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        role = request.form.get('role')
        username = request.form.get('username')
        password = request.form.get('password')
        
        if role == 'admin':
            try:
                conn = get_db_connection('main.db')
                school = conn.execute('SELECT * FROM schools WHERE admin_username = ?', (username,)).fetchone()
                conn.close()
                if school and verify_password(password, school['admin_password']):
                    session.clear()
                    session['is_admin'] = True
                    session['school_id'] = school['id']
                    session['school_name'] = school['school_name']
                    session['db_path'] = school['db_path']
                    session['subscription_level'] = school['subscription_level']
                    flash('Welcome back, Admin!', 'success')
                    return redirect(url_for('admin_dashboard'))
                flash('Invalid admin credentials', 'error')
            except Exception as e:
                flash(f'Login error: {str(e)}', 'error')
            
        elif role == 'student':
            found = False
            for school_file in os.listdir('.'):
                if school_file.startswith('school_') and school_file.endswith('.db'):
                    try:
                        conn = get_db_connection(school_file)
                        student = conn.execute('SELECT * FROM students WHERE student_id = ?', (username,)).fetchone()
                        
                        if student:
                            password_valid = False
                            try:
                                if verify_password(password, student['password']):
                                    password_valid = True
                            except:
                                if password == student['password']:
                                    password_valid = True
                            
                            if password_valid:
                                session.clear()
                                session['is_student'] = True
                                session['student_id'] = student['student_id']
                                session['student_name'] = student['name']
                                session['student_class'] = student['class_id']
                                session['school_db'] = school_file
                                conn.close()
                                found = True
                                flash(f'Welcome {student["name"]}!', 'success')
                                return redirect(url_for('student_dashboard'))
                        conn.close()
                    except Exception as e:
                        print(f"Error checking {school_file}: {e}")
                        continue
                        
            if not found:
                flash('Invalid student ID or password', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully', 'success')
    return redirect(url_for('login'))

@app.route('/super-admin-login', methods=['GET', 'POST'])
def super_admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == 'hive' and password == 'hivepass01':
            session.clear()
            session['is_super_admin'] = True
            return redirect(url_for('super_admin_dashboard'))
        flash('Invalid super admin credentials', 'error')
    return render_template('super_admin_login.html')

@app.route('/super-admin-login-page')
def super_admin_login_page():
    return redirect(url_for('super_admin_login'))

# ==================== SUPER ADMIN ROUTES ====================
@app.route('/super-admin-dashboard')
@super_admin_required
def super_admin_dashboard():
    conn = get_db_connection('main.db')
    schools = conn.execute('SELECT * FROM schools ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('super_admin_dashboard.html', schools=schools)

@app.route('/create-school', methods=['POST'])
@super_admin_required
def create_school():
    school_name = request.form.get('school_name')
    school_id = request.form.get('school_id')
    admin_username = request.form.get('admin_username')
    admin_password = request.form.get('admin_password')
    subscription_level = request.form.get('subscription_level', 'Basic')
    
    db_path = f'school_{school_id}.db'
    
    try:
        init_school_db(db_path)
        conn = get_db_connection('main.db')
        conn.execute('INSERT INTO schools (school_name, school_id, admin_username, admin_password, subscription_level, db_path) VALUES (?, ?, ?, ?, ?, ?)',
                    (school_name, school_id, admin_username, hash_password(admin_password), subscription_level, db_path))
        conn.commit()
        conn.close()
        flash('School created successfully', 'success')
    except sqlite3.IntegrityError:
        flash('School name or ID already exists', 'error')
    except Exception as e:
        flash(f'Error creating school: {str(e)}', 'error')
    
    return redirect(url_for('super_admin_dashboard'))

@app.route('/delete-school/<int:school_id>')
@super_admin_required
def delete_school(school_id):
    try:
        conn = get_db_connection('main.db')
        school = conn.execute('SELECT * FROM schools WHERE id = ?', (school_id,)).fetchone()
        if school:
            if os.path.exists(school['db_path']):
                os.remove(school['db_path'])
            conn.execute('DELETE FROM schools WHERE id = ?', (school_id,))
            conn.commit()
            flash('School deleted', 'success')
        conn.close()
    except Exception as e:
        flash(f'Error deleting school: {str(e)}', 'error')
    
    return redirect(url_for('super_admin_dashboard'))

@app.route('/update-subscription/<int:school_id>', methods=['POST'])
@super_admin_required
def update_subscription(school_id):
    level = request.form.get('subscription_level')
    days = int(request.form.get('duration_days', 30))
    start_date = datetime.datetime.now().strftime('%Y-%m-%d')
    end_date = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime('%Y-%m-%d')
    
    try:
        conn = get_db_connection('main.db')
        conn.execute('UPDATE schools SET subscription_level = ?, subscription_start = ?, subscription_end = ? WHERE id = ?',
                    (level, start_date, end_date, school_id))
        conn.commit()
        conn.close()
        flash('Subscription updated', 'success')
    except Exception as e:
        flash(f'Error updating subscription: {str(e)}', 'error')
    
    return redirect(url_for('super_admin_dashboard'))

@app.route('/get-school-details/<int:school_id>')
@super_admin_required
def get_school_details(school_id):
    try:
        conn = get_db_connection('main.db')
        school = conn.execute('SELECT id, school_name, school_id as school_identifier, admin_username, subscription_level, subscription_start, subscription_end FROM schools WHERE id = ?', (school_id,)).fetchone()
        conn.close()
        
        if school:
            school_dict = {
                'id': school['id'],
                'school_name': school['school_name'],
                'school_identifier': school['school_identifier'],
                'admin_username': school['admin_username'],
                'subscription_level': school['subscription_level'],
                'subscription_start': school['subscription_start'],
                'subscription_end': school['subscription_end']
            }
            return jsonify(school_dict)
        else:
            return jsonify({'error': 'School not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/edit-school', methods=['POST'])
@super_admin_required
def edit_school():
    school_id = request.form.get('school_id')
    school_name = request.form.get('school_name')
    school_identifier = request.form.get('school_identifier')
    admin_username = request.form.get('admin_username')
    admin_password = request.form.get('admin_password')
    subscription_level = request.form.get('subscription_level')
    duration_days = request.form.get('duration_days')
    
    try:
        conn = get_db_connection('main.db')
        
        if school_identifier:
            existing = conn.execute('SELECT id FROM schools WHERE school_id = ? AND id != ?', 
                                   (school_identifier, school_id)).fetchone()
            if existing:
                flash('School ID already exists', 'error')
                conn.close()
                return redirect(url_for('super_admin_dashboard'))
        
        update_fields = []
        update_values = []
        
        if school_name:
            update_fields.append('school_name = ?')
            update_values.append(school_name)
        
        if school_identifier:
            update_fields.append('school_id = ?')
            update_values.append(school_identifier)
            
            old_school = conn.execute('SELECT db_path FROM schools WHERE id = ?', (school_id,)).fetchone()
            if old_school:
                old_db_path = old_school['db_path']
                new_db_path = f'school_{school_identifier}.db'
                if old_db_path != new_db_path and os.path.exists(old_db_path):
                    os.rename(old_db_path, new_db_path)
                    update_fields.append('db_path = ?')
                    update_values.append(new_db_path)
        
        if admin_username:
            update_fields.append('admin_username = ?')
            update_values.append(admin_username)
        
        if admin_password and admin_password.strip():
            update_fields.append('admin_password = ?')
            update_values.append(hash_password(admin_password))
        
        if subscription_level:
            update_fields.append('subscription_level = ?')
            update_values.append(subscription_level)
        
        if duration_days and duration_days != '0':
            days = int(duration_days)
            if days > 0:
                start_date = datetime.datetime.now().strftime('%Y-%m-%d')
                end_date = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime('%Y-%m-%d')
                update_fields.append('subscription_start = ?')
                update_values.append(start_date)
                update_fields.append('subscription_end = ?')
                update_values.append(end_date)
        
        if update_fields:
            update_values.append(school_id)
            query = f"UPDATE schools SET {', '.join(update_fields)} WHERE id = ?"
            conn.execute(query, update_values)
            conn.commit()
            flash('School details updated successfully', 'success')
        else:
            flash('No changes to update', 'info')
        
        conn.close()
    except Exception as e:
        flash(f'Error updating school: {str(e)}', 'error')
    
    return redirect(url_for('super_admin_dashboard'))

# ==================== ADMIN ROUTES ====================
@app.route('/admin-dashboard')
@admin_required
def admin_dashboard():
    subscription = session.get('subscription_level', 'Basic')
    try:
        conn = get_db_connection(session['db_path'])
        students = conn.execute('SELECT * FROM students ORDER BY id DESC').fetchall()
        exams = conn.execute('SELECT * FROM exams ORDER BY id DESC').fetchall()
        subjects = conn.execute('SELECT * FROM subjects ORDER BY subject_code').fetchall()
        conn.close()
    except Exception as e:
        flash(f'Error loading dashboard: {str(e)}', 'error')
        students = []
        exams = []
        subjects = []
    
    return render_template('admin_dashboard.html', students=students, exams=exams, subjects=subjects, subscription=subscription)

@app.route('/create-student', methods=['POST'])
@admin_required
def create_student():
    name = request.form.get('name')
    class_id = request.form.get('class_id')
    session_year = request.form.get('session')
    student_id = request.form.get('student_id')
    password = request.form.get('password')
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['db_path'], timeout=30)
            try:
                conn.execute('INSERT INTO students (student_id, name, class_id, session, password) VALUES (?, ?, ?, ?, ?)',
                            (student_id, name, class_id, session_year, hash_password(password)))
                conn.commit()
                flash('Student created successfully', 'success')
                break
            except sqlite3.IntegrityError:
                flash('Student ID already exists', 'error')
                break
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            if attempt == max_retries - 1:
                flash(f'Error creating student: {str(e)}', 'error')
            else:
                time.sleep(0.5)
    
    return redirect(url_for('admin_dashboard'))

@app.route('/delete-student/<int:student_id>')
@admin_required
def delete_student(student_id):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['db_path'], timeout=30)
            try:
                conn.execute('DELETE FROM students WHERE id = ?', (student_id,))
                conn.commit()
                flash('Student deleted', 'success')
                break
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            if attempt == max_retries - 1:
                flash(f'Error deleting student: {str(e)}', 'error')
            else:
                time.sleep(0.5)
    
    return redirect(url_for('admin_dashboard'))

# ==================== SUBJECT MANAGEMENT ROUTES ====================
@app.route('/create-subject', methods=['POST'])
@admin_required
def create_subject():
    subject_code = request.form.get('subject_code')
    subject_name = request.form.get('subject_name')
    description = request.form.get('description', '')
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['db_path'], timeout=30)
            try:
                conn.execute('INSERT INTO subjects (subject_code, subject_name, description, created_at) VALUES (?, ?, ?, ?)',
                            (subject_code, subject_name, description, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                conn.commit()
                flash('Subject created successfully', 'success')
                break
            except sqlite3.IntegrityError:
                flash('Subject code already exists', 'error')
                break
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            if attempt == max_retries - 1:
                flash(f'Error creating subject: {str(e)}', 'error')
            else:
                time.sleep(0.5)
    
    return redirect(url_for('admin_dashboard'))

@app.route('/edit-subject', methods=['POST'])
@admin_required
def edit_subject():
    subject_id = request.form.get('subject_id')
    subject_code = request.form.get('subject_code')
    subject_name = request.form.get('subject_name')
    description = request.form.get('description', '')
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['db_path'], timeout=30)
            try:
                existing = conn.execute('SELECT id FROM subjects WHERE subject_code = ? AND id != ?', 
                                       (subject_code, subject_id)).fetchone()
                if existing:
                    flash('Subject code already exists', 'error')
                    return redirect(url_for('admin_dashboard'))
                
                conn.execute('UPDATE subjects SET subject_code = ?, subject_name = ?, description = ? WHERE id = ?',
                            (subject_code, subject_name, description, subject_id))
                conn.commit()
                flash('Subject updated successfully', 'success')
                break
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            if attempt == max_retries - 1:
                flash(f'Error updating subject: {str(e)}', 'error')
            else:
                time.sleep(0.5)
    
    return redirect(url_for('admin_dashboard'))

@app.route('/delete-subject/<int:subject_id>', methods=['POST'])
@admin_required
def delete_subject(subject_id):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['db_path'], timeout=30)
            try:
                subject = conn.execute('SELECT subject_code FROM subjects WHERE id = ?', (subject_id,)).fetchone()
                if subject:
                    exams = conn.execute('SELECT id FROM exams WHERE subject_code = ?', (subject['subject_code'],)).fetchall()
                    if exams:
                        flash('Cannot delete subject that is used in exams. Remove exams first.', 'error')
                        conn.close()
                        return redirect(url_for('admin_dashboard'))
                
                conn.execute('DELETE FROM subjects WHERE id = ?', (subject_id,))
                conn.commit()
                flash('Subject deleted successfully', 'success')
                break
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            if attempt == max_retries - 1:
                flash(f'Error deleting subject: {str(e)}', 'error')
            else:
                time.sleep(0.5)
    
    return redirect(url_for('admin_dashboard'))

@app.route('/get-subject/<int:subject_id>')
@admin_required
def get_subject(subject_id):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['db_path'], timeout=30)
            try:
                subject = conn.execute('SELECT * FROM subjects WHERE id = ?', (subject_id,)).fetchone()
                conn.close()
                return jsonify(dict(subject)) if subject else jsonify({'error': 'Not found'}), 404
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/download-subject-template')
@admin_required
def download_subject_template():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Subject Code', 'Subject Name', 'Description'])
    writer.writerow(['MATH101', 'Mathematics', 'Algebra, Geometry, and Calculus'])
    writer.writerow(['ENG101', 'English', 'Grammar, Literature, and Composition'])
    writer.writerow(['SCI101', 'Science', 'Physics, Chemistry, and Biology'])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()), 
                    mimetype='text/csv', 
                    as_attachment=True, 
                    download_name='subject_template.csv')

@app.route('/upload-subjects-csv', methods=['POST'])
@admin_required
def upload_subjects_csv():
    if session.get('subscription_level') != 'Pro':
        flash('Pro subscription required for bulk upload', 'error')
        return redirect(url_for('admin_dashboard'))
    
    file = request.files['subjects_csv']
    if file and file.filename.endswith('.csv'):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
                csv_input = csv.reader(stream)
                next(csv_input)
                
                conn = get_db_connection(session['db_path'], timeout=30)
                try:
                    count = 0
                    for row in csv_input:
                        if len(row) >= 2:
                            subject_code = row[0].strip()
                            subject_name = row[1].strip()
                            description = row[2].strip() if len(row) > 2 else ''
                            
                            try:
                                conn.execute('INSERT INTO subjects (subject_code, subject_name, description, created_at) VALUES (?, ?, ?, ?)',
                                            (subject_code, subject_name, description, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                                count += 1
                            except sqlite3.IntegrityError:
                                pass
                    conn.commit()
                    conn.close()
                    flash(f'{count} subjects uploaded successfully', 'success')
                    break
                except sqlite3.OperationalError as e:
                    if "database is locked" in str(e) and attempt < max_retries - 1:
                        time.sleep(0.5)
                        continue
                    else:
                        raise e
                finally:
                    conn.close()
            except Exception as e:
                if attempt == max_retries - 1:
                    flash(f'Error uploading subjects: {str(e)}', 'error')
                else:
                    time.sleep(0.5)
    
    return redirect(url_for('admin_dashboard'))

# ==================== EXAM ROUTES ====================
@app.route('/create-exam', methods=['POST'])
@admin_required
def create_exam():
    exam_title = request.form.get('exam_title')
    exam_code = request.form.get('exam_code')
    subject_code = request.form.get('subject_code')
    exam_date = request.form.get('exam_date')
    exam_time = request.form.get('exam_time')
    timer_minutes = request.form.get('timer_minutes')
    class_id = request.form.get('class_id')
    exam_type = request.form.get('exam_type', 'objective')
    instructions = request.form.get('instructions', '')
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['db_path'], timeout=30)
            try:
                conn.execute('''INSERT INTO exams (exam_title, exam_code, subject_code, exam_date, exam_time, timer_minutes, class_id, is_active, exam_type, instructions) 
                                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)''',
                            (exam_title, exam_code, subject_code, exam_date, exam_time, timer_minutes, class_id, exam_type, instructions))
                conn.commit()
                flash('Exam created successfully', 'success')
                break
            except sqlite3.IntegrityError:
                flash('Exam code already exists', 'error')
                break
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            if attempt == max_retries - 1:
                flash(f'Error creating exam: {str(e)}', 'error')
            else:
                time.sleep(0.5)
    
    return redirect(url_for('admin_dashboard'))

@app.route('/upload-questions/<exam_code>', methods=['POST'])
@admin_required
def upload_questions(exam_code):
    file = request.files['questions_csv']
    upload_mode = request.form.get('upload_mode', 'new')
    
    if file and file.filename.endswith('.csv'):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
                csv_input = csv.reader(stream)
                next(csv_input)
                
                conn = get_db_connection(session['db_path'], timeout=30)
                try:
                    # Handle replace mode
                    if upload_mode == 'replace':
                        conn.execute('DELETE FROM questions WHERE exam_code = ?', (exam_code,))
                        flash('Existing questions deleted. Uploading new questions...', 'info')
                    
                    count = 0
                    objective_count = 0
                    theory_count = 0
                    
                    for row in csv_input:
                        if len(row) < 4:
                            continue
                            
                        # Check if it's an objective question (has 4 options)
                        if len(row) >= 8 and row[2] and row[3] and row[4] and row[5]:
                            conn.execute('''INSERT INTO questions 
                                (exam_code, serial_no, question, option1, option2, option3, option4, correct_answer, score) 
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                (exam_code, row[0], row[1], row[2], row[3], row[4], row[5], row[6], int(row[7])))
                            objective_count += 1
                            count += 1
                        else:
                            correct_answer = row[2] if len(row) > 2 else ''
                            score = int(row[3]) if len(row) > 3 else 10
                            conn.execute('''INSERT INTO questions 
                                (exam_code, serial_no, question, option1, option2, option3, option4, correct_answer, score) 
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                (exam_code, row[0], row[1], '', '', '', '', correct_answer, score))
                            theory_count += 1
                            count += 1
                            
                    conn.commit()
                    flash(f'{count} questions uploaded ({objective_count} objective, {theory_count} theory) for exam {exam_code}', 'success')
                    break
                except sqlite3.OperationalError as e:
                    if "database is locked" in str(e) and attempt < max_retries - 1:
                        time.sleep(0.5)
                        continue
                    else:
                        raise e
                finally:
                    conn.close()
            except Exception as e:
                if attempt == max_retries - 1:
                    flash(f'Error uploading questions: {str(e)}', 'error')
                else:
                    time.sleep(0.5)
    
    return redirect(url_for('admin_dashboard'))

@app.route('/download-csv-template/<type>')
@admin_required
def download_csv_template(type):
    if type == 'students':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Serial Number', 'Name', 'Class ID', 'Session', 'Student ID', 'Password'])
        writer.writerow(['1', 'John Doe', 'SS1', '2024/2025', 'STU001', 'pass123'])
        output.seek(0)
        return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/csv', as_attachment=True, download_name='student_template.csv')
    elif type == 'questions':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Serial No', 'Question', 'Option1', 'Option2', 'Option3', 'Option4', 'Correct Answer', 'Score'])
        writer.writerow(['1', 'What is 2+2?', '3', '4', '5', '6', '4', '1'])
        output.seek(0)
        return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/csv', as_attachment=True, download_name='objective_template.csv')
    return redirect(url_for('admin_dashboard'))

@app.route('/download-theory-template')
@admin_required
def download_theory_template():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Serial No', 'Question', 'Correct Answer', 'Score', 'Instructions'])
    writer.writerow(['1', 'Explain the concept of photosynthesis.', 'Photosynthesis is the process by which plants convert light energy into chemical energy.', '10', 'Provide a detailed explanation with key terms.'])
    writer.writerow(['2', 'What is the capital of France?', 'Paris', '5', 'Answer should be the city name only.'])
    writer.writerow(['3', 'Describe the water cycle.', 'The water cycle is the continuous movement of water through evaporation, condensation, and precipitation.', '10', 'Include all three stages in your answer.'])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()), 
                    mimetype='text/csv', 
                    as_attachment=True, 
                    download_name='theory_template.csv')

@app.route('/upload-students-csv', methods=['POST'])
@admin_required
def upload_students_csv():
    if session.get('subscription_level') != 'Pro':
        flash('Pro subscription required for bulk upload', 'error')
        return redirect(url_for('admin_dashboard'))
    
    file = request.files['students_csv']
    if file and file.filename.endswith('.csv'):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
                csv_input = csv.reader(stream)
                next(csv_input)
                
                conn = get_db_connection(session['db_path'], timeout=30)
                try:
                    count = 0
                    for row in csv_input:
                        if len(row) >= 6:
                            try:
                                conn.execute('INSERT INTO students (student_id, name, class_id, session, password) VALUES (?, ?, ?, ?, ?)',
                                            (row[4], row[1], row[2], row[3], hash_password(row[5])))
                                count += 1
                            except sqlite3.IntegrityError:
                                pass
                    conn.commit()
                    conn.close()
                    flash(f'{count} students uploaded successfully', 'success')
                    break
                except sqlite3.OperationalError as e:
                    if "database is locked" in str(e) and attempt < max_retries - 1:
                        time.sleep(0.5)
                        continue
                    else:
                        raise e
                finally:
                    conn.close()
            except Exception as e:
                if attempt == max_retries - 1:
                    flash(f'Error uploading students: {str(e)}', 'error')
                else:
                    time.sleep(0.5)
    
    return redirect(url_for('admin_dashboard'))

@app.route('/upload-exam-csv', methods=['POST'])
@admin_required
def upload_exam_csv():
    if session.get('subscription_level') != 'Pro':
        flash('Pro subscription required for bulk exam upload', 'error')
        return redirect(url_for('admin_dashboard'))
    
    file = request.files['exam_csv']
    exam_code = request.form.get('exam_code')
    
    if file and file.filename.endswith('.csv'):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
                csv_input = csv.reader(stream)
                next(csv_input)
                
                conn = get_db_connection(session['db_path'], timeout=30)
                try:
                    # Check if questions already exist
                    existing = conn.execute('SELECT COUNT(*) as count FROM questions WHERE exam_code = ?', (exam_code,)).fetchone()
                    if existing['count'] > 0:
                        flash('Questions already exist for this exam. Delete existing questions first or use the exam page to replace.', 'warning')
                        conn.close()
                        return redirect(url_for('admin_dashboard'))
                    
                    count = 0
                    objective_count = 0
                    theory_count = 0
                    
                    for row in csv_input:
                        if len(row) < 4:
                            continue
                            
                        if len(row) >= 8 and row[2] and row[3] and row[4] and row[5]:
                            conn.execute('''INSERT INTO questions 
                                (exam_code, serial_no, question, option1, option2, option3, option4, correct_answer, score) 
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                (exam_code, row[0], row[1], row[2], row[3], row[4], row[5], row[6], int(row[7])))
                            objective_count += 1
                            count += 1
                        elif len(row) >= 4:
                            correct_answer = row[2] if len(row) > 2 else ''
                            score = int(row[3]) if len(row) > 3 else 10
                            conn.execute('''INSERT INTO questions 
                                (exam_code, serial_no, question, option1, option2, option3, option4, correct_answer, score) 
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                (exam_code, row[0], row[1], '', '', '', '', correct_answer, score))
                            theory_count += 1
                            count += 1
                            
                    conn.commit()
                    conn.close()
                    flash(f'{count} questions uploaded for exam {exam_code} ({objective_count} objective, {theory_count} theory)', 'success')
                    break
                except sqlite3.OperationalError as e:
                    if "database is locked" in str(e) and attempt < max_retries - 1:
                        time.sleep(0.5)
                        continue
                    else:
                        raise e
                finally:
                    conn.close()
            except Exception as e:
                if attempt == max_retries - 1:
                    flash(f'Error uploading questions: {str(e)}', 'error')
                else:
                    time.sleep(0.5)
    
    return redirect(url_for('admin_dashboard'))

@app.route('/update-settings', methods=['POST'])
@admin_required
def update_settings():
    if session.get('subscription_level') != 'Pro':
        flash('Pro subscription required', 'error')
        return redirect(url_for('admin_dashboard'))
    
    logo = request.files.get('logo')
    address = request.form.get('address')
    school_name = request.form.get('school_name')
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['db_path'], timeout=30)
            try:
                if logo and logo.filename:
                    filename = secure_filename(logo.filename)
                    logo_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    logo.save(logo_path)
                    conn.execute('REPLACE INTO school_settings (key, value) VALUES (?, ?)', ('logo', logo_path))
                if address:
                    conn.execute('REPLACE INTO school_settings (key, value) VALUES (?, ?)', ('address', address))
                if school_name:
                    conn.execute('REPLACE INTO school_settings (key, value) VALUES (?, ?)', ('school_name', school_name))
                conn.commit()
                conn.close()
                flash('Settings updated', 'success')
                break
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            if attempt == max_retries - 1:
                flash(f'Error updating settings: {str(e)}', 'error')
            else:
                time.sleep(0.5)
    
    return redirect(url_for('admin_dashboard'))

@app.route('/get-questions/<exam_code>')
@admin_required
def get_questions(exam_code):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['db_path'], timeout=30)
            try:
                questions = conn.execute('SELECT * FROM questions WHERE exam_code = ? ORDER BY serial_no', (exam_code,)).fetchall()
                conn.close()
                
                questions_list = []
                for q in questions:
                    questions_list.append({
                        'id': q['id'],
                        'exam_code': q['exam_code'],
                        'serial_no': q['serial_no'],
                        'question': q['question'],
                        'option1': q['option1'],
                        'option2': q['option2'],
                        'option3': q['option3'],
                        'option4': q['option4'],
                        'correct_answer': q['correct_answer'],
                        'score': q['score']
                    })
                
                return jsonify({'questions': questions_list})
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/get-question/<int:question_id>')
@admin_required
def get_question(question_id):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['db_path'], timeout=30)
            try:
                question = conn.execute('SELECT * FROM questions WHERE id = ?', (question_id,)).fetchone()
                conn.close()
                
                if question:
                    question_dict = {
                        'id': question['id'],
                        'exam_code': question['exam_code'],
                        'serial_no': question['serial_no'],
                        'question': question['question'],
                        'option1': question['option1'],
                        'option2': question['option2'],
                        'option3': question['option3'],
                        'option4': question['option4'],
                        'correct_answer': question['correct_answer'],
                        'score': question['score']
                    }
                    return jsonify(question_dict)
                else:
                    return jsonify({'error': 'Question not found'}), 404
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/get-exam/<int:exam_id>')
@admin_required
def get_exam(exam_id):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['db_path'], timeout=30)
            try:
                exam = conn.execute('SELECT * FROM exams WHERE id = ?', (exam_id,)).fetchone()
                conn.close()
                
                if exam:
                    exam_dict = {
                        'id': exam['id'],
                        'exam_title': exam['exam_title'],
                        'exam_code': exam['exam_code'],
                        'subject_code': exam['subject_code'],
                        'exam_date': exam['exam_date'],
                        'exam_time': exam['exam_time'],
                        'timer_minutes': exam['timer_minutes'],
                        'class_id': exam['class_id'],
                        'is_active': exam['is_active'],
                        'exam_type': exam['exam_type'],
                        'instructions': exam['instructions']
                    }
                    return jsonify(exam_dict)
                else:
                    return jsonify({'error': 'Exam not found'}), 404
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/get-students-by-class/<class_id>')
@admin_required
def get_students_by_class(class_id):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['db_path'], timeout=30)
            try:
                students = conn.execute('SELECT student_id, name FROM students WHERE class_id = ?', (class_id,)).fetchall()
                conn.close()
                
                students_list = []
                for student in students:
                    students_list.append({
                        'student_id': student['student_id'],
                        'name': student['name']
                    })
                
                return jsonify(students_list)
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/get-students-for-exam/<exam_code>')
@admin_required
def get_students_for_exam(exam_code):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['db_path'], timeout=30)
            try:
                students = conn.execute('''
                    SELECT DISTINCT s.student_id, s.name 
                    FROM exam_assignments ea
                    JOIN students s ON ea.student_id = s.student_id
                    WHERE ea.exam_code = ?
                ''', (exam_code,)).fetchall()
                conn.close()
                
                students_list = [dict(student) for student in students]
                return jsonify(students_list)
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/assign-exam', methods=['POST'])
@admin_required
def assign_exam():
    exam_code = request.form.get('exam_code')
    assignment_type = request.form.get('assignment_type')
    class_id = request.form.get('class_id')
    student_id = request.form.get('student_id')
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['db_path'], timeout=30)
            try:
                if assignment_type == 'class':
                    students = conn.execute('SELECT student_id FROM students WHERE class_id = ?', (class_id,)).fetchall()
                    count = 0
                    for student in students:
                        existing = conn.execute('SELECT id FROM exam_assignments WHERE exam_code = ? AND student_id = ?', 
                                               (exam_code, student['student_id'])).fetchone()
                        if not existing:
                            conn.execute('INSERT INTO exam_assignments (exam_code, student_id, assigned_at, status) VALUES (?, ?, ?, "pending")',
                                        (exam_code, student['student_id'], datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                            count += 1
                    conn.commit()
                    flash(f'Exam assigned to {count} students in class {class_id}', 'success')
                else:
                    existing = conn.execute('SELECT id FROM exam_assignments WHERE exam_code = ? AND student_id = ?', 
                                           (exam_code, student_id)).fetchone()
                    if existing:
                        flash('Exam already assigned to this student', 'warning')
                    else:
                        conn.execute('INSERT INTO exam_assignments (exam_code, student_id, assigned_at, status) VALUES (?, ?, ?, "pending")',
                                    (exam_code, student_id, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                        conn.commit()
                        flash(f'Exam assigned to student {student_id}', 'success')
                break
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            if attempt == max_retries - 1:
                flash(f'Error assigning exam: {str(e)}', 'error')
            else:
                time.sleep(0.5)
    
    return redirect(url_for('admin_dashboard'))

@app.route('/toggle-exam-status/<exam_code>', methods=['POST'])
@admin_required
def toggle_exam_status(exam_code):
    action = request.form.get('action')
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['db_path'], timeout=30)
            try:
                if action == 'start':
                    conn.execute('UPDATE exams SET is_active = 1 WHERE exam_code = ?', (exam_code,))
                    flash(f'Exam {exam_code} has been started. Students can now take it.', 'success')
                else:
                    conn.execute('UPDATE exams SET is_active = 0 WHERE exam_code = ?', (exam_code,))
                    flash(f'Exam {exam_code} has been stopped.', 'warning')
                conn.commit()
                break
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            if attempt == max_retries - 1:
                flash(f'Error toggling exam status: {str(e)}', 'error')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/delete-exam/<int:exam_id>', methods=['POST'])
@admin_required
def delete_exam(exam_id):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['db_path'], timeout=30)
            try:
                exam = conn.execute('SELECT exam_code FROM exams WHERE id = ?', (exam_id,)).fetchone()
                if exam:
                    conn.execute('DELETE FROM questions WHERE exam_code = ?', (exam['exam_code'],))
                    conn.execute('DELETE FROM exam_assignments WHERE exam_code = ?', (exam['exam_code'],))
                    conn.execute('DELETE FROM exam_attempts WHERE exam_code = ?', (exam['exam_code'],))
                    conn.execute('DELETE FROM theory_answers WHERE exam_code = ?', (exam['exam_code'],))
                    conn.execute('DELETE FROM student_responses WHERE exam_code = ?', (exam['exam_code'],))
                    conn.execute('DELETE FROM exams WHERE id = ?', (exam_id,))
                    conn.commit()
                    flash('Exam deleted successfully', 'success')
                else:
                    flash('Exam not found', 'error')
                break
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            if attempt == max_retries - 1:
                flash(f'Error deleting exam: {str(e)}', 'error')
            else:
                time.sleep(0.5)
    
    return redirect(url_for('admin_dashboard'))

@app.route('/edit-exam/<int:exam_id>', methods=['POST'])
@admin_required
def edit_exam(exam_id):
    exam_title = request.form.get('exam_title')
    exam_code = request.form.get('exam_code')
    subject_code = request.form.get('subject_code')
    exam_date = request.form.get('exam_date')
    exam_time = request.form.get('exam_time')
    timer_minutes = request.form.get('timer_minutes')
    class_id = request.form.get('class_id')
    exam_type = request.form.get('exam_type', 'objective')
    instructions = request.form.get('instructions', '')
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['db_path'], timeout=30)
            try:
                existing = conn.execute('SELECT id FROM exams WHERE exam_code = ? AND id != ?', 
                                       (exam_code, exam_id)).fetchone()
                if existing:
                    flash('Exam code already exists', 'error')
                    return redirect(url_for('admin_dashboard'))
                
                old_code = conn.execute('SELECT exam_code FROM exams WHERE id = ?', (exam_id,)).fetchone()
                
                conn.execute('''UPDATE exams 
                                SET exam_title = ?, exam_code = ?, subject_code = ?, exam_date = ?, exam_time = ?, 
                                    timer_minutes = ?, class_id = ?, exam_type = ?, instructions = ?
                                WHERE id = ?''',
                            (exam_title, exam_code, subject_code, exam_date, exam_time, timer_minutes, class_id, exam_type, instructions, exam_id))
                
                if old_code and old_code['exam_code'] != exam_code:
                    conn.execute('UPDATE questions SET exam_code = ? WHERE exam_code = ?', (exam_code, old_code['exam_code']))
                    conn.execute('UPDATE exam_assignments SET exam_code = ? WHERE exam_code = ?', (exam_code, old_code['exam_code']))
                    conn.execute('UPDATE exam_attempts SET exam_code = ? WHERE exam_code = ?', (exam_code, old_code['exam_code']))
                    conn.execute('UPDATE theory_answers SET exam_code = ? WHERE exam_code = ?', (exam_code, old_code['exam_code']))
                    conn.execute('UPDATE student_responses SET exam_code = ? WHERE exam_code = ?', (exam_code, old_code['exam_code']))
                
                conn.commit()
                flash('Exam updated successfully', 'success')
                break
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            if attempt == max_retries - 1:
                flash(f'Error updating exam: {str(e)}', 'error')
            else:
                time.sleep(0.5)
    
    return redirect(url_for('admin_dashboard'))

@app.route('/edit-question/<int:question_id>', methods=['POST'])
@admin_required
def edit_question(question_id):
    serial_no = request.form.get('serial_no')
    question = request.form.get('question')
    option1 = request.form.get('option1')
    option2 = request.form.get('option2')
    option3 = request.form.get('option3')
    option4 = request.form.get('option4')
    correct_answer = request.form.get('correct_answer')
    score = request.form.get('score')
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['db_path'], timeout=30)
            try:
                conn.execute('UPDATE questions SET serial_no = ?, question = ?, option1 = ?, option2 = ?, option3 = ?, option4 = ?, correct_answer = ?, score = ? WHERE id = ?',
                            (serial_no, question, option1, option2, option3, option4, correct_answer, score, question_id))
                conn.commit()
                flash('Question updated successfully', 'success')
                break
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            if attempt == max_retries - 1:
                flash(f'Error updating question: {str(e)}', 'error')
            else:
                time.sleep(0.5)
    
    return redirect(url_for('admin_dashboard'))

@app.route('/delete-question/<int:question_id>', methods=['POST'])
@admin_required
def delete_question(question_id):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['db_path'], timeout=30)
            try:
                conn.execute('DELETE FROM questions WHERE id = ?', (question_id,))
                conn.commit()
                flash('Question deleted successfully', 'success')
                break
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            if attempt == max_retries - 1:
                flash(f'Error deleting question: {str(e)}', 'error')
            else:
                time.sleep(0.5)
    
    return redirect(url_for('admin_dashboard'))

# ==================== PROCTOR LOGS ROUTES ====================
@app.route('/proctor-logs/<exam_code>')
@admin_required
def proctor_logs(exam_code):
    """View proctor violations for an exam"""
    try:
        conn = get_db_connection(session['db_path'])
        
        # Get exam details
        exam = conn.execute('SELECT * FROM exams WHERE exam_code = ?', (exam_code,)).fetchone()
        
        # Get all violations for this exam
        violations = conn.execute('''
            SELECT pl.*, s.name as student_name, s.student_id
            FROM proctor_logs pl
            JOIN students s ON pl.student_id = s.student_id
            WHERE pl.exam_code = ?
            ORDER BY pl.created_at DESC
        ''', (exam_code,)).fetchall()
        
        conn.close()
        
        return render_template('proctor_logs.html', exam=exam, violations=violations)
    except Exception as e:
        flash(f'Error loading proctor logs: {str(e)}', 'error')
        return redirect(url_for('admin_dashboard'))

# ==================== DOWNLOAD STUDENT RESPONSES (ADMIN) ====================
@app.route('/download-student-responses/<exam_code>/<student_id>')
@admin_required
def admin_download_student_responses(exam_code, student_id):
    """Admin download student's exam responses"""
    try:
        conn = get_db_connection(session['db_path'])
        
        # Get exam details
        exam = conn.execute('SELECT * FROM exams WHERE exam_code = ?', (exam_code,)).fetchone()
        
        if not exam:
            flash('Exam not found', 'error')
            return redirect(url_for('admin_dashboard'))
        
        # Get student's results
        result = conn.execute('''
            SELECT * FROM results 
            WHERE student_id = ? AND exam_code = ?
        ''', (student_id, exam_code)).fetchone()
        
        if not result:
            flash('No results found for this student', 'warning')
            return redirect(url_for('admin_dashboard'))
        
        # Get student details
        student = conn.execute('SELECT * FROM students WHERE student_id = ?', (student_id,)).fetchone()
        
        # Get objective questions and student answers
        objective_questions = conn.execute('''
            SELECT q.*, 
                   CASE WHEN r.score IS NOT NULL THEN r.score ELSE NULL END as student_score
            FROM questions q
            LEFT JOIN results r ON q.exam_code = r.exam_code AND r.student_id = ?
            WHERE q.exam_code = ? AND (q.option1 IS NOT NULL OR q.option1 != '')
            ORDER BY q.serial_no
        ''', (student_id, exam_code)).fetchall()
        
        # Get theory answers
        theory_answers = conn.execute('''
            SELECT ta.*, q.question, q.correct_answer, q.score as max_score
            FROM theory_answers ta
            JOIN questions q ON ta.question_id = q.id
            WHERE ta.student_id = ? AND ta.exam_code = ?
            ORDER BY q.serial_no
        ''', (student_id, exam_code)).fetchall()
        
        # Get student's submitted answers from student_responses
        student_response = conn.execute('''
            SELECT responses_json FROM student_responses 
            WHERE student_id = ? AND exam_code = ?
            ORDER BY id DESC LIMIT 1
        ''', (student_id, exam_code)).fetchone()
        
        # Parse answers if available
        student_answers = {}
        if student_response and student_response['responses_json']:
            try:
                responses_data = json.loads(student_response['responses_json'])
                student_answers = responses_data.get('answers', {})
            except:
                pass
        
        # Add student answers to objective questions
        objective_list = []
        for q in objective_questions:
            q_dict = dict(q)
            q_dict['student_answer'] = student_answers.get(str(q['id']), 'Not answered')
            objective_list.append(q_dict)
        
        current_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        html = render_template('student_responses_admin.html',
                              student=student,
                              exam=exam,
                              result=result,
                              objective_questions=objective_list,
                              theory_answers=theory_answers,
                              current_date=current_date,
                              total_score=result['score'],
                              total_possible=result['total_possible'],
                              percentage=round((result['score'] / result['total_possible'] * 100), 1) if result['total_possible'] > 0 else 0)
        
        if config:
            pdf = pdfkit.from_string(html, False, configuration=config)
        else:
            return html
        
        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=student_{student_id}_{exam_code}_responses.pdf'
        return response
        
    except Exception as e:
        flash(f'Error generating responses: {str(e)}', 'error')
        return redirect(url_for('admin_dashboard'))

# ==================== STUDENT DOWNLOAD RESPONSES ====================
@app.route('/download-student-responses/<exam_code>')
def download_student_responses(exam_code):
    """Student download their own exam responses"""
    if not session.get('is_student'):
        flash('Please login as a student', 'error')
        return redirect(url_for('login'))
    
    try:
        conn = get_db_connection(session['school_db'])
        
        # Get exam details
        exam = conn.execute('SELECT * FROM exams WHERE exam_code = ?', (exam_code,)).fetchone()
        
        if not exam:
            flash('Exam not found', 'error')
            return redirect(url_for('student_dashboard'))
        
        # Get student's results
        result = conn.execute('''
            SELECT * FROM results 
            WHERE student_id = ? AND exam_code = ?
        ''', (session['student_id'], exam_code)).fetchone()
        
        if not result:
            flash('No results found for this exam', 'warning')
            return redirect(url_for('student_dashboard'))
        
        # Get student details
        student = conn.execute('SELECT * FROM students WHERE student_id = ?', (session['student_id'],)).fetchone()
        
        # Get objective questions and student answers
        objective_questions = conn.execute('''
            SELECT q.*, 
                   CASE WHEN r.score IS NOT NULL THEN r.score ELSE NULL END as student_score
            FROM questions q
            LEFT JOIN results r ON q.exam_code = r.exam_code AND r.student_id = ?
            WHERE q.exam_code = ? AND (q.option1 IS NOT NULL OR q.option1 != '')
            ORDER BY q.serial_no
        ''', (session['student_id'], exam_code)).fetchall()
        
        # Get theory answers
        theory_answers = conn.execute('''
            SELECT ta.*, q.question, q.correct_answer, q.score as max_score
            FROM theory_answers ta
            JOIN questions q ON ta.question_id = q.id
            WHERE ta.student_id = ? AND ta.exam_code = ?
            ORDER BY q.serial_no
        ''', (session['student_id'], exam_code)).fetchall()
        
        # Get student's submitted answers from student_responses
        student_response = conn.execute('''
            SELECT responses_json FROM student_responses 
            WHERE student_id = ? AND exam_code = ?
            ORDER BY id DESC LIMIT 1
        ''', (session['student_id'], exam_code)).fetchone()
        
        # Parse answers if available
        student_answers = {}
        if student_response and student_response['responses_json']:
            try:
                responses_data = json.loads(student_response['responses_json'])
                student_answers = responses_data.get('answers', {})
            except:
                pass
        
        # Add student answers to objective questions
        objective_list = []
        for q in objective_questions:
            q_dict = dict(q)
            q_dict['student_answer'] = student_answers.get(str(q['id']), 'Not answered')
            objective_list.append(q_dict)
        
        current_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        html = render_template('student_responses_download.html',
                              student=student,
                              exam=exam,
                              result=result,
                              objective_questions=objective_list,
                              theory_answers=theory_answers,
                              current_date=current_date,
                              total_score=result['score'],
                              total_possible=result['total_possible'],
                              percentage=round((result['score'] / result['total_possible'] * 100), 1) if result['total_possible'] > 0 else 0)
        
        if config:
            pdf = pdfkit.from_string(html, False, configuration=config)
        else:
            return html
        
        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=student_{session["student_id"]}_{exam_code}_responses.pdf'
        return response
        
    except Exception as e:
        flash(f'Error generating responses: {str(e)}', 'error')
        return redirect(url_for('student_dashboard'))

# ==================== PDF DOWNLOAD ROUTES ====================
@app.route('/download-result/<exam_code>/<class_id>')
@admin_required
def download_result(exam_code, class_id):
    try:
        conn = get_db_connection(session['db_path'])
        results = conn.execute('''
            SELECT s.name, s.student_id, r.score, r.total_possible 
            FROM results r 
            JOIN students s ON r.student_id = s.student_id 
            WHERE r.exam_code = ? AND s.class_id = ?
        ''', (exam_code, class_id)).fetchall()
        conn.close()
        
        now = datetime.datetime.now()
        current_date = now.strftime('%Y-%m-%d %H:%M:%S')
        
        html = render_template('result_pdf.html', 
                              results=results, 
                              exam_code=exam_code, 
                              class_id=class_id,
                              current_date=current_date)
        
        if config:
            pdf = pdfkit.from_string(html, False, configuration=config)
        else:
            return html
        
        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=results_{exam_code}.pdf'
        return response
    except Exception as e:
        flash(f'Error generating PDF: {str(e)}', 'error')
        return redirect(url_for('admin_dashboard'))

@app.route('/download-pro-result/<student_id>')
@admin_required
def download_pro_result(student_id):
    if session.get('subscription_level') != 'Pro':
        flash('Pro subscription required', 'error')
        return redirect(url_for('admin_dashboard'))
    
    try:
        conn = get_db_connection(session['db_path'])
        settings = {row['key']: row['value'] for row in conn.execute('SELECT * FROM school_settings').fetchall()}
        results = conn.execute('''
            SELECT e.exam_title, e.exam_code, r.score, r.total_possible, r.submitted_at
            FROM results r 
            JOIN exams e ON r.exam_code = e.exam_code 
            WHERE r.student_id = ?
            ORDER BY r.submitted_at DESC
        ''', (student_id,)).fetchall()
        student = conn.execute('SELECT * FROM students WHERE student_id = ?', (student_id,)).fetchone()
        conn.close()
        
        now = datetime.datetime.now()
        current_date = now.strftime('%Y-%m-%d %H:%M:%S')
        current_year = now.strftime('%Y')
        
        html = render_template('pro_result_pdf.html', 
                              results=results, 
                              student=student, 
                              settings=settings,
                              current_date=current_date,
                              current_year=current_year)
        
        if config:
            pdf = pdfkit.from_string(html, False, configuration=config)
        else:
            return html
        
        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=student_{student_id}_transcript.pdf'
        return response
    except Exception as e:
        flash(f'Error generating PDF: {str(e)}', 'error')
        return redirect(url_for('admin_dashboard'))

# ==================== STUDENT ROUTES ====================
@app.route('/student-dashboard')
def student_dashboard():
    if not session.get('is_student'):
        return redirect(url_for('login'))
    return render_template('student_dashboard.html', student_name=session['student_name'])

@app.route('/get-student-exams')
def get_student_exams():
    if not session.get('is_student'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['school_db'], timeout=30)
            try:
                exams = conn.execute('''
                    SELECT e.id, e.exam_title, e.exam_code, e.subject_code, s.subject_name,
                           e.exam_date, e.exam_time, e.timer_minutes, e.is_active,
                           e.exam_type, e.instructions, ea.status, ea.assigned_at, ea.started_at, ea.completed_at
                    FROM exams e
                    LEFT JOIN subjects s ON e.subject_code = s.subject_code
                    INNER JOIN exam_assignments ea ON e.exam_code = ea.exam_code
                    WHERE ea.student_id = ? AND e.is_active = 1
                    ORDER BY e.exam_date || " " || e.exam_time ASC
                ''', (session['student_id'],)).fetchall()
                conn.close()
                
                exams_list = []
                for exam in exams:
                    exams_list.append({
                        'id': exam['id'],
                        'exam_title': exam['exam_title'],
                        'exam_code': exam['exam_code'],
                        'subject_code': exam['subject_code'],
                        'subject_name': exam['subject_name'],
                        'exam_date': exam['exam_date'],
                        'exam_time': exam['exam_time'],
                        'timer_minutes': exam['timer_minutes'],
                        'is_active': exam['is_active'],
                        'exam_type': exam['exam_type'],
                        'instructions': exam['instructions'],
                        'status': exam['status'],
                        'assigned_at': exam['assigned_at'],
                        'started_at': exam['started_at'],
                        'completed_at': exam['completed_at']
                    })
                
                return jsonify({'exams': exams_list})
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            if attempt == max_retries - 1:
                return jsonify({'error': str(e)}), 500
            else:
                time.sleep(0.5)
    
    return jsonify({'error': 'Max retries exceeded'}), 500

@app.route('/get-student-results/<student_id>')
def get_student_results(student_id):
    if not session.get('is_student') and not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        db_path = session.get('school_db') if session.get('is_student') else session.get('db_path')
        if not db_path:
            return jsonify({'error': 'No database found'}), 404
            
        conn = get_db_connection(db_path)
        total_exams = conn.execute('SELECT COUNT(*) as count FROM results WHERE student_id = ?', (student_id,)).fetchone()
        avg_score = conn.execute('SELECT AVG(CAST(score AS FLOAT) / total_possible * 100) as avg FROM results WHERE student_id = ?', (student_id,)).fetchone()
        conn.close()
        
        return jsonify({
            'total_exams': total_exams['count'] if total_exams else 0,
            'average_score': round(avg_score['avg'], 1) if avg_score and avg_score['avg'] else 0
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/take-exam/<exam_code>')
def take_exam(exam_code):
    if not session.get('is_student'):
        flash('Please login as a student', 'error')
        return redirect(url_for('login'))
        
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['school_db'], timeout=30)
            try:
                exam = conn.execute('''
                    SELECT e.*, s.subject_name 
                    FROM exams e
                    LEFT JOIN subjects s ON e.subject_code = s.subject_code
                    WHERE e.exam_code = ?
                ''', (exam_code,)).fetchone()
                
                if not exam:
                    flash('Exam not found', 'error')
                    return redirect(url_for('student_dashboard'))
                
                assignment = conn.execute('''
                    SELECT * FROM exam_assignments 
                    WHERE exam_code = ? AND student_id = ?
                ''', (exam_code, session['student_id'])).fetchone()
                
                if not assignment:
                    flash('This exam has not been assigned to you', 'error')
                    return redirect(url_for('student_dashboard'))
                
                if exam['is_active'] != 1:
                    flash('Exam has not been started by the administrator yet. Please wait.', 'warning')
                    return redirect(url_for('student_dashboard'))
                
                if assignment['status'] == 'completed':
                    flash('You have already completed this exam', 'warning')
                    return redirect(url_for('student_dashboard'))
                
                questions_raw = conn.execute('SELECT * FROM questions WHERE exam_code = ? ORDER BY serial_no', (exam_code,)).fetchall()
                questions = [dict(q) for q in questions_raw]
                
                if len(questions) == 0:
                    flash('This exam has no questions. Please contact your teacher.', 'error')
                    return redirect(url_for('student_dashboard'))
                
                main_conn = get_db_connection('main.db')
                school = main_conn.execute('SELECT subscription_level FROM schools WHERE db_path = ?', (session['school_db'],)).fetchone()
                main_conn.close()
                subscription_level = school['subscription_level'] if school else 'Basic'
                
                # Track attempt
                attempt_number = 1
                existing_attempt = conn.execute('''
                    SELECT attempt_number FROM exam_attempts 
                    WHERE student_id = ? AND exam_code = ? AND status = "completed"
                    ORDER BY attempt_number DESC LIMIT 1
                ''', (session['student_id'], exam_code)).fetchone()
                
                if existing_attempt:
                    attempt_number = existing_attempt['attempt_number'] + 1
                
                # Use cursor to get lastrowid
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO exam_attempts (student_id, exam_code, attempt_number, started_at, status)
                    VALUES (?, ?, ?, ?, 'in_progress')
                ''', (session['student_id'], exam_code, attempt_number, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                attempt_id = cursor.lastrowid
                conn.commit()
                
                if assignment['status'] == 'pending':
                    conn.execute('''
                        UPDATE exam_assignments 
                        SET started_at = ?, status = 'in_progress' 
                        WHERE exam_code = ? AND student_id = ?
                    ''', (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), exam_code, session['student_id']))
                    conn.commit()
                
                exam_dict = {
                    'id': exam['id'],
                    'exam_title': exam['exam_title'],
                    'exam_code': exam['exam_code'],
                    'subject_code': exam['subject_code'],
                    'subject_name': exam['subject_name'],
                    'exam_date': exam['exam_date'],
                    'exam_time': exam['exam_time'],
                    'timer_minutes': exam['timer_minutes'],
                    'class_id': exam['class_id'],
                    'is_active': exam['is_active'],
                    'exam_type': exam['exam_type'],
                    'instructions': exam['instructions'],
                    'status': assignment['status'],
                    'assigned_at': assignment['assigned_at']
                }
                
                return render_template('exam.html', 
                                       exam=exam_dict, 
                                       questions=questions, 
                                       student_name=session['student_name'], 
                                       subscription_level=subscription_level,
                                       attempt_id=attempt_id)
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"Error in take_exam: {str(e)}")
                flash(f'Error loading exam: {str(e)}', 'error')
                return redirect(url_for('student_dashboard'))
            else:
                time.sleep(0.5)
    
    return redirect(url_for('student_dashboard'))

@app.route('/submit-exam', methods=['POST'])
def submit_exam():
    data = request.json
    exam_code = data.get('exam_code')
    answers = data.get('answers')
    theory_answers = data.get('theory_answers', {})
    attempt_id = data.get('attempt_id')
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['school_db'], timeout=30)
            try:
                exam = conn.execute('SELECT exam_type FROM exams WHERE exam_code = ?', (exam_code,)).fetchone()
                exam_type = exam['exam_type'] if exam else 'objective'
                
                total_score = 0
                total_possible = 0
                
                questions = conn.execute('SELECT * FROM questions WHERE exam_code = ?', (exam_code,)).fetchall()
                
                for q in questions:
                    total_possible += q['score']
                    
                    is_theory = exam_type == 'theory' or (not q['option1'] and not q['option2'] and not q['option3'] and not q['option4'])
                    
                    if is_theory:
                        student_answer = theory_answers.get(str(q['id']), '')
                        score = calculate_theory_score(student_answer, q['correct_answer'])
                        feedback = generate_feedback(student_answer, q['correct_answer'], score)
                        total_score += score
                        
                        conn.execute('''
                            INSERT INTO theory_answers (student_id, exam_code, attempt_id, question_id, answer, score, feedback, submitted_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (session['student_id'], exam_code, attempt_id, q['id'], student_answer, score, feedback, 
                              datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                    else:
                        if str(q['id']) in answers and answers[str(q['id'])] == q['correct_answer']:
                            total_score += q['score']
                
                conn.execute('INSERT INTO results (student_id, exam_code, score, total_possible, submitted_at) VALUES (?, ?, ?, ?, ?)',
                            (session['student_id'], exam_code, total_score, total_possible, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                
                conn.execute('UPDATE exam_assignments SET status = "completed", completed_at = ? WHERE exam_code = ? AND student_id = ?',
                            (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), exam_code, session['student_id']))
                
                if attempt_id:
                    conn.execute('UPDATE exam_attempts SET status = "completed", completed_at = ? WHERE id = ?',
                                (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), attempt_id))
                
                responses_json = json.dumps({
                    'answers': answers,
                    'theory_answers': theory_answers
                })
                conn.execute('''
                    INSERT INTO student_responses (student_id, exam_code, attempt_id, responses_json, submitted_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (session['student_id'], exam_code, attempt_id, responses_json, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                
                conn.commit()
                conn.close()
                
                return jsonify({'score': total_score, 'total': total_possible})
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            if attempt == max_retries - 1:
                return jsonify({'error': str(e)}), 500
            else:
                time.sleep(0.5)
    
    return jsonify({'error': 'Max retries exceeded'}), 500

@app.route('/proctor-violation', methods=['POST'])
def proctor_violation():
    """Improved violation detection with face detection"""
    data = request.json
    violation_type = data.get('violation')
    image_data = data.get('image')
    exam_code = data.get('exam_code')
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['school_db'], timeout=30)
            try:
                conn.execute('''
                    INSERT INTO proctor_logs (student_id, exam_code, violation_type, image_data, created_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (session['student_id'], exam_code, violation_type, image_data, 
                      datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                conn.commit()
                conn.close()
                return jsonify({'status': 'logged'})
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            if attempt == max_retries - 1:
                return jsonify({'error': str(e)}), 500
            else:
                time.sleep(0.5)
    
    return jsonify({'error': 'Max retries exceeded'}), 500

# ==================== RESET STUDENT EXAM ====================
@app.route('/reset-student-exam/<student_id>/<exam_code>', methods=['POST'])
@admin_required
def reset_student_exam(student_id, exam_code):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = get_db_connection(session['db_path'], timeout=30)
            try:
                conn.execute('DELETE FROM results WHERE student_id = ? AND exam_code = ?', (student_id, exam_code))
                conn.execute('DELETE FROM theory_answers WHERE student_id = ? AND exam_code = ?', (student_id, exam_code))
                conn.execute('DELETE FROM student_responses WHERE student_id = ? AND exam_code = ?', (student_id, exam_code))
                conn.execute('DELETE FROM exam_attempts WHERE student_id = ? AND exam_code = ?', (student_id, exam_code))
                conn.execute('''
                    UPDATE exam_assignments 
                    SET status = 'pending', started_at = NULL, completed_at = NULL 
                    WHERE student_id = ? AND exam_code = ?
                ''', (student_id, exam_code))
                
                conn.commit()
                conn.close()
                
                flash(f'Student {student_id} can now retake exam {exam_code}', 'success')
                return jsonify({'success': True, 'message': 'Exam reset successfully'})
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                else:
                    raise e
            finally:
                conn.close()
        except Exception as e:
            if attempt == max_retries - 1:
                flash(f'Error resetting exam: {str(e)}', 'error')
                return jsonify({'error': str(e)}), 500
            else:
                time.sleep(0.5)
    
    return jsonify({'error': 'Max retries exceeded'}), 500

# ==================== THEORY GRADING HELPERS ====================
def calculate_theory_score(student_answer, correct_answer):
    if not student_answer or not correct_answer:
        return 0
    
    student_lower = student_answer.lower().strip()
    correct_lower = correct_answer.lower().strip()
    
    if student_lower == correct_lower:
        return 10
    
    keywords = re.findall(r'\b\w+\b', correct_lower)
    matched_keywords = sum(1 for kw in keywords if kw in student_lower)
    keyword_score = (matched_keywords / len(keywords)) * 7 if keywords else 0
    
    length_ratio = min(len(student_lower), len(correct_lower)) / max(len(student_lower), len(correct_lower), 1)
    length_score = length_ratio * 3
    
    total_score = min(10, keyword_score + length_score)
    return round(total_score, 1)

def generate_feedback(student_answer, correct_answer, score):
    if score >= 9:
        return "Excellent! Perfect answer."
    elif score >= 7:
        return "Good answer! You covered most key points."
    elif score >= 5:
        return "Fair answer. You missed some important points."
    elif score >= 3:
        return "Needs improvement. Review the material and try again."
    else:
        return "Incorrect. Please review the correct answer."

# ==================== DEBUG ROUTES ====================
@app.route('/debug-exam/<exam_code>')
@admin_required
def debug_exam(exam_code):
    try:
        conn = get_db_connection(session['db_path'])
        
        exam = conn.execute('SELECT * FROM exams WHERE exam_code = ?', (exam_code,)).fetchone()
        assignments = conn.execute('''
            SELECT ea.*, s.name as student_name 
            FROM exam_assignments ea
            JOIN students s ON ea.student_id = s.student_id
            WHERE ea.exam_code = ?
        ''', (exam_code,)).fetchall()
        
        conn.close()
        
        return jsonify({
            'exam': dict(exam) if exam else None,
            'assignments': [dict(a) for a in assignments],
            'exam_active': exam['is_active'] if exam else False
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/debug-students')
def debug_students():
    if not session.get('is_super_admin'):
        return "Unauthorized", 403
    
    result = {}
    for school_file in os.listdir('.'):
        if school_file.startswith('school_') and school_file.endswith('.db'):
            try:
                conn = get_db_connection(school_file)
                students = conn.execute('SELECT student_id, name, class_id, session FROM students').fetchall()
                conn.close()
                result[school_file] = [dict(student) for student in students]
            except Exception as e:
                result[school_file] = f"Error: {e}"
    
    return jsonify(result)

# ==================== WEBHOOKS ====================
@app.route('/paystack-webhook', methods=['POST'])
def paystack_webhook():
    event = request.json
    if event['event'] == 'charge.success':
        school_id = event['data']['metadata']['school_id']
        try:
            conn = get_db_connection('main.db')
            conn.execute('UPDATE schools SET subscription_level = ?, subscription_start = ?, subscription_end = ? WHERE id = ?',
                        ('Pro', datetime.datetime.now().strftime('%Y-%m-%d'), 
                         (datetime.datetime.now() + datetime.timedelta(days=30)).strftime('%Y-%m-%d'), school_id))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Webhook error: {e}")
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    init_main_db()
    app.run(debug=True, threaded=True)