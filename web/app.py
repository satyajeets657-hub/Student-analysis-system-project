from pathlib import Path
import os
import sqlite3, hashlib, re
from werkzeug.utils import secure_filename
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, send_from_directory
BASE = Path(__file__).resolve().parents[1]
DATA = BASE / 'data' / 'students.csv'
DB = BASE / 'web' / 'student_intelligence.db'
app = Flask(__name__)
app.secret_key = 'student-performance-intelligence-demo-key'


def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def performance_score(row):
    # Main project score: combines academic and engagement indicators.
    study_score = min(float(row['Study_Hours']) / 6 * 100, 100)
    return round(
        row['Final_Marks']*.35 + row['Attendance']*.15 + study_score*.10 +
        row['Assignment_Score']*.10 + row['Quiz_Average']*.10 +
        row['Practical_Score']*.10 + row['Internal_Marks']*.10, 1
    )


def status(score):
    if score >= 85: return 'Excellent'
    if score >= 70: return 'Good'
    if score >= 55: return 'Stable'
    if score >= 40: return 'Attention'
    return 'High Risk'


def risk_score(row):
    score = 0
    if row['Attendance'] < 60: score += 3
    elif row['Attendance'] < 75: score += 2
    elif row['Attendance'] < 85: score += 1
    if row['Study_Hours'] < 2: score += 3
    elif row['Study_Hours'] < 4: score += 1
    if row['Final_Marks'] < 50: score += 3
    elif row['Final_Marks'] < 65: score += 2
    elif row['Final_Marks'] < 75: score += 1
    if row['Practical_Score'] < 50: score += 2
    elif row['Practical_Score'] < 60: score += 1
    if row['Assignment_Score'] < 50: score += 2
    if row['Quiz_Average'] < 50: score += 2
    return score


def risk_level(score):
    if score >= 6: return 'High'
    if score >= 3: return 'Medium'
    return 'Low'


def support(row):
    return 'High Priority' if risk_score(row) >= 6 else ('Needs Support' if risk_score(row) >= 3 else 'Normal')


def enrich(row):
    d = dict(row)
    d['Risk_Score'] = risk_score(d)
    d['Risk_Level'] = risk_level(d['Risk_Score'])
    metrics = {
        'Attendance': d['Attendance'], 'Study Hours': d['Study_Hours'],
        'Assignment': d['Assignment_Score'], 'Quiz': d['Quiz_Average'],
        'Practical': d['Practical_Score'], 'Internal': d['Internal_Marks'], 'Final Marks': d['Final_Marks']
    }
    d['Strengths'] = [k for k,v in metrics.items() if v >= 80]
    d['Improvement_Areas'] = [k for k,v in metrics.items() if v < 65]
    recs = []
    if d['Attendance'] < 75: recs.append('Maintain more regular class attendance.')
    if d['Study_Hours'] < 4: recs.append('Build a consistent daily study routine.')
    if d['Assignment_Score'] < 65: recs.append('Complete assignments on time and review feedback.')
    if d['Quiz_Average'] < 65: recs.append('Use short practice quizzes for regular revision.')
    if d['Practical_Score'] < 65: recs.append('Spend more time on practical exercises and hands-on practice.')
    if d['Final_Marks'] < 65: recs.append('Prioritise revision of topics linked to lower assessment scores.')
    if not recs: recs.append('Continue the current routine and use periodic self-assessment.')
    d['Recommendations'] = recs
    return d


def seed_database():
    DB.parent.mkdir(exist_ok=True)
    conn = get_db()
    conn.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL, student_id TEXT)')
    conn.execute('''CREATE TABLE IF NOT EXISTS students (
        Student_ID TEXT PRIMARY KEY, Name TEXT, Gender TEXT, Department TEXT, Semester INTEGER,
        Attendance REAL, Study_Hours REAL, Assignment_Submission_Rate REAL, Assignment_Score REAL,
        Quiz_Average REAL, Practical_Score REAL, Internal_Marks REAL, Previous_Semester_Score REAL,
        Participation_Score REAL, Extra_Curricular TEXT, Final_Marks REAL, Grade TEXT,
        Performance_Score REAL, Performance_Status TEXT, Support_Flag TEXT, Department_Average REAL,
        Performance_Gap REAL, Primary_Insight TEXT)''')
    if conn.execute('SELECT COUNT(*) AS n FROM students').fetchone()['n'] == 0:
        df = pd.read_csv(DATA).drop_duplicates()
        df['Performance_Score'] = df.apply(performance_score, axis=1)
        df['Performance_Status'] = df['Performance_Score'].apply(status)
        df['Support_Flag'] = df.apply(support, axis=1)
        dept_avg = df.groupby('Department')['Performance_Score'].mean()
        df['Department_Average'] = df['Department'].map(dept_avg).round(1)
        df['Performance_Gap'] = (df['Performance_Score'] - df['Department_Average']).round(1)
        def insight(r):
            if r.Attendance < 70: return 'Improve attendance'
            if r.Study_Hours < 2: return 'Increase study hours'
            if r.Assignment_Submission_Rate < 70: return 'Submit assignments regularly'
            if r.Quiz_Average < 55: return 'Focus on quizzes'
            if r.Practical_Score < 55: return 'Improve practical performance'
            if r.Performance_Gap >= 5: return 'Above department average'
            return 'Performance is stable'
        df['Primary_Insight'] = df.apply(insight, axis=1)
        cols = ['Student_ID','Name','Gender','Department','Semester','Attendance','Study_Hours','Assignment_Submission_Rate','Assignment_Score','Quiz_Average','Practical_Score','Internal_Marks','Previous_Semester_Score','Participation_Score','Extra_Curricular','Final_Marks','Grade','Performance_Score','Performance_Status','Support_Flag','Department_Average','Performance_Gap','Primary_Insight']
        df[cols].to_sql('students', conn, if_exists='append', index=False)
    for u in [('teacher', hash_password('teacher123'), 'teacher', None), ('ST0001', hash_password('student123'), 'student', 'ST0001'), ('ST0002', hash_password('student123'), 'student', 'ST0002')]:
        conn.execute('INSERT OR IGNORE INTO users(username,password_hash,role,student_id) VALUES(?,?,?,?)', u)
    conn.commit(); conn.close()


def login_required(role=None):
    return 'username' in session and (role is None or session.get('role') == role)


def student_for_session():
    conn = get_db(); row = conn.execute('SELECT * FROM students WHERE Student_ID=?', (session.get('student_id'),)).fetchone(); conn.close()
    return row


def all_students():
    conn = get_db(); rows = conn.execute('SELECT * FROM students ORDER BY Performance_Score DESC').fetchall(); conn.close()
    return [enrich(r) for r in rows]


def teacher_ai_answer(question):
    """Local V1 teacher assistant using only authorised class data."""
    q = re.sub(r'\s+', ' ', (question or '').lower().strip())
    rows = all_students()
    if not rows:
        return 'No student data is available.'

    total = len(rows)
    avg = sum(r['Performance_Score'] for r in rows) / total
    avg_att = sum(r['Attendance'] for r in rows) / total
    avg_study = sum(r['Study_Hours'] for r in rows) / total
    excellent = sum(r['Performance_Status'] == 'Excellent' for r in rows)
    good = sum(r['Performance_Status'] == 'Good' for r in rows)
    stable = sum(r['Performance_Status'] in ('Stable', 'Developing') for r in rows)
    attention = sum(r['Performance_Status'] in ('Needs Attention', 'Needs_Attention') for r in rows)
    high = [r for r in rows if r['Risk_Level'] == 'High']
    medium = [r for r in rows if r['Risk_Level'] == 'Medium']
    low_att = sorted([r for r in rows if r['Attendance'] < 70], key=lambda r: r['Attendance'])
    low_marks = sorted(rows, key=lambda r: r['Performance_Score'])

    # Student ID queries must be checked before broad intents.
    m = re.search(r'\bst\s*\d{4}\b', q)
    if m:
        sid = re.sub(r'\s+', '', m.group(0)).upper()
        match = next((r for r in rows if r['Student_ID'].upper() == sid), None)
        if not match:
            return f'I could not find student {sid} in the current class data.'
        strengths = ', '.join(match['Strengths']) if match['Strengths'] else 'No metric currently crosses the configured strength threshold.'
        areas = ', '.join(match['Improvement_Areas']) if match['Improvement_Areas'] else 'No major improvement area currently flagged.'
        return (f"{match['Name']} ({sid}): performance {match['Performance_Score']:.1f}/100, "
                f"status {match['Performance_Status']}, attendance {match['Attendance']:.1f}%, "
                f"risk {match['Risk_Level']} ({match['Risk_Score']}). Strengths: {strengths}. "
                f"Improvement areas: {areas}. Primary insight: {match['Primary_Insight']}.")

    # Greetings use whole words so 'hi' does not accidentally match 'high'.
    if re.search(r'\b(hello|hi|hey|namaste)\b', q):
        return 'Hello! I can analyse the current class data. Try class summary, high-risk students, low attendance, common weak areas, top students, or a student such as ST0001.'

    if any(k in q for k in ['class summary', 'overall performance', 'overall class', 'class performance', 'overall', 'summary']):
        return (f'Class summary: {total} students are available. Average performance is {avg:.1f}/100, '
                f'average attendance is {avg_att:.1f}%, and average study time is {avg_study:.1f} hours/day. '
                f'Performance status: {excellent} Excellent, {good} Good, {stable} Stable, and {attention} needing attention. '
                f'{len(high) + len(medium)} students are currently flagged by the configured risk rules.')

    if any(k in q for k in ['how many students', 'number of students', 'total students', 'kitne students']):
        return f'The current class dataset contains {total} students.'

    # Intervention/action queries must be checked before broad risk queries.
    # Explicitly prioritise questions that combine high-risk + action/help wording.
    action_words = ['action', 'what should', 'what can', 'how to help', 'help', 'intervention',
                    'action plan', 'support plan', 'teacher action', 'teacher intervention',
                    'improve', 'steps', 'strategy', 'recommendation']
    high_risk_words = ['high risk', 'high-risk', 'highrisk', 'high priority']
    if (any(k in q for k in high_risk_words) and any(k in q for k in action_words)) or \
       any(k in q for k in ['what action', 'what should', 'what can', 'how to help', 'action plan',
                            'support plan', 'teacher action', 'teacher intervention', 'intervention plan']):
        return ('High-Risk Student Intervention Plan: 1) review each student\'s attendance, study hours and academic indicators, '
                '2) identify the main improvement area for each student, 3) provide targeted academic support or remedial practice, '
                '4) follow up on attendance, assignments and assessments, and 5) reassess the student\'s risk indicators after the intervention.')

    # Explicit high-risk queries.
    if any(k in q for k in ['high risk', 'high-risk', 'highest risk', 'high priority']):
        if not high:
            return 'No students are currently classified as High risk by the configured rules.'
        parts = ', '.join(f"{r['Name']} ({r['Student_ID']}, risk {r['Risk_Score']})" for r in high[:20])
        more = f' and {len(high)-20} more' if len(high) > 20 else ''
        return f'{len(high)} students are currently High risk: {parts}{more}.'

    if any(k in q for k in ['need attention', 'needing attention', 'students needing', 'at-risk', 'at risk', 'risk students', 'risk']):
        selected = high + medium
        if not selected:
            return 'No students are currently flagged for academic support by the configured risk rules.'
        parts = ', '.join(f"{r['Name']} ({r['Student_ID']}, {r['Risk_Level']}, risk {r['Risk_Score']})" for r in selected[:20])
        more = f' and {len(selected)-20} more' if len(selected) > 20 else ''
        return f'Students needing attention: {parts}{more}. Open an individual student profile to review the contributing indicators.'

    if any(k in q for k in ['low attendance', 'attendance below', 'attendance less', 'attendance under', 'attendance kam']):
        if not low_att:
            return 'No students currently have attendance below 70%.'
        names = ', '.join(f"{r['Name']} ({r['Student_ID']}, {r['Attendance']:.1f}%)" for r in low_att[:20])
        more = f' and {len(low_att)-20} more' if len(low_att) > 20 else ''
        return f'{len(low_att)} students have attendance below 70%: {names}{more}.'

    if any(k in q for k in ['weak area', 'weak areas', 'common weakness', 'common weak', 'improvement area']):
        counts = {}
        for r in rows:
            for area in r['Improvement_Areas']:
                counts[area] = counts.get(area, 0) + 1
        top = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:6]
        if not top:
            return 'No prominent improvement area is currently identified by the configured thresholds.'
        return 'Common improvement areas: ' + '; '.join(f'{k} ({v} students)' for k, v in top) + '.'
        # Top-performing students
        if any(k in q for k in [
            'top student',
            'top students',
            'top performing',
            'top performers',
            'top performance',
            'best student',
            'best students',
            'highest performance',
            'highest score',
            'highest marks'
        ]):
            top = sorted(
                rows,
                key=lambda r: r['Performance_Score'],
                reverse=True
            )[:10]

            names = ', '.join(
                f"{r['Name']} ({r['Student_ID']}, {r['Performance_Score']:.1f})"
                for r in top
            )

            return "Highest current performance scores: " + names + "."

        groups = {}
        for r in rows:
            groups.setdefault(r['Department'], []).append(r['Performance_Score'])
        summary = ', '.join(f"{d}: {sum(v)/len(v):.1f}" for d, v in sorted(groups.items()))
        return f'Average performance by department: {summary}.'

    if any(k in q for k in ['suggest', 'strategy', 'intervention', 'action', 'improve class', 'improvement plan']):
        return ('Suggested class actions: 1) group students by their main improvement area, '
                '2) monitor attendance and assignment completion, 3) provide targeted revision/practice, '
                '4) review the next assessment for progress, and 5) revisit high-risk students individually.')

    if any(k in q for k in ['study hours', 'study time', 'studying']):
        return f'Average study time in the current dataset is {avg_study:.1f} hours/day. Students below 2 hours/day should be reviewed alongside their other performance indicators.'

    if 'attendance' in q:
        lowest = sorted(rows, key=lambda r: r['Attendance'])[:8]
        names = ', '.join(f"{r['Name']} ({r['Attendance']:.1f}%)" for r in lowest)
        return f'Class average attendance is {avg_att:.1f}%. The lowest current attendance values include: {names}.'

    return ('I can help with class summary, high-risk students, students needing attention, low attendance, '
            'common weak areas, top or low-performing students, department averages, individual student summaries '
            '(e.g. ST0001), study hours, and intervention suggestions.')


@app.route('/')
def index():
    if session.get('role') == 'teacher': return redirect(url_for('teacher_dashboard'))
    if session.get('role') == 'student': return redirect(url_for('student_dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username=request.form.get('username','').strip(); password=request.form.get('password','')
        conn=get_db(); user=conn.execute('SELECT * FROM users WHERE username=? AND password_hash=?',(username,hash_password(password))).fetchone(); conn.close()
        if user:
            session.clear(); session['username']=user['username']; session['role']=user['role']; session['student_id']=user['student_id']
            return redirect(url_for('teacher_dashboard' if user['role']=='teacher' else 'student_dashboard'))
        flash('Invalid username or password.')
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('index'))
@app.route('/teacher/upload-material', methods=['POST'])
def teacher_upload_material():
    if not login_required('teacher'):
        return jsonify({'error': 'Please login as teacher.'}), 401

    if 'material' not in request.files:
        return jsonify({'error': 'No file selected.'}), 400

    file = request.files['material']

    if not file.filename:
        return jsonify({'error': 'Please select a file.'}), 400

    allowed_extensions = {
        '.pdf',
        '.docx',
        '.txt',
        '.md'
    }

    filename = file.filename
    topic = request.form.get('topic', 'General')
    extension = os.path.splitext(filename)[1].lower()

    if extension not in allowed_extensions:
        return jsonify({
            'error': 'Only PDF, DOCX, TXT and MD files are allowed.'
        }), 400

    upload_dir = BASE / 'uploads' / 'learning_materials'
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = secure_filename(filename)

    file_path = upload_dir / safe_name

    counter = 1

    while file_path.exists():
        original_name = Path(safe_name).stem
        extension = Path(safe_name).suffix

        safe_name = f"{original_name}_{counter}{extension}"
        file_path = upload_dir / safe_name

        counter += 1

    file.save(file_path)
    metadata_path = upload_dir / (safe_name + '.json')

    with open(metadata_path, 'w', encoding='utf-8') as f:
        import json
        json.dump({
            'filename': safe_name,
            'topic': topic
        }, f, ensure_ascii=False, indent=2)

    return jsonify({
        'message': 'Learning material uploaded successfully.',
        'filename': safe_name
    })
@app.route('/teacher')
def teacher_dashboard():
    if not login_required('teacher'): return redirect(url_for('login'))
    rows=all_students(); departments=sorted({r['Department'] for r in rows})
    avg=sum(r['Performance_Score'] for r in rows)/len(rows); avg_att=sum(r['Attendance'] for r in rows)/len(rows)
    high=sum(r['Risk_Level']=='High' for r in rows); med=sum(r['Risk_Level']=='Medium' for r in rows)
    return render_template('teacher.html', students=rows, departments=departments, avg=avg, avg_att=avg_att, high=high, med=med)

@app.route('/teacher/student/<student_id>')
def teacher_student(student_id):
    if not login_required('teacher'): return redirect(url_for('login'))
    conn=get_db(); row=conn.execute('SELECT * FROM students WHERE Student_ID=?',(student_id,)).fetchone(); conn.close()
    if not row: return 'Student not found',404
    return render_template('student_detail.html', student=enrich(row), teacher=True)

@app.route('/api/teacher-ai', methods=['POST'])
def teacher_ai():
    if not login_required('teacher'): return jsonify({'answer':'Please login as a teacher.'}),401
    return jsonify({'answer':teacher_ai_answer(request.json.get('question',''))})
@app.route('/teacher/materials')
def teacher_materials():
    if not login_required('teacher'):
        return jsonify({'error': 'Please login as teacher.'}), 401

    upload_dir = BASE / 'uploads' / 'learning_materials'

    if not upload_dir.exists():
        return jsonify({'materials': []})

    import json

    materials = []

    for file_path in sorted(upload_dir.iterdir()):

        if not file_path.is_file():
            continue

        if file_path.suffix.lower() == '.json':
            continue

        metadata_path = upload_dir / (file_path.name + '.json')

        topic = 'General'

        if metadata_path.exists():
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

                topic = metadata.get('topic', 'General')

            except Exception:
                topic = 'General'

        materials.append({
            'filename': file_path.name,
            'topic': topic,
            'url': url_for(
                'student_download_material',
                filename=file_path.name
            )
        })

    return jsonify({
        'materials': materials
    })
    if not login_required('teacher'):
        return jsonify({'error': 'Please login as teacher.'}), 401

    upload_dir = BASE / 'uploads' / 'learning_materials'

    if not upload_dir.exists():
        return jsonify({'materials': []})

    materials = []

    for file_path in sorted(upload_dir.iterdir()):
        if file_path.is_file():
            materials.append({
                'filename': file_path.name,
                'url': url_for(
                    'student_download_material',
                    filename=file_path.name
                )
            })

    return jsonify({'materials': materials})
@app.route('/student/materials')
def student_materials():
    if not login_required('student'):
        return jsonify({'error': 'Please login as student.'}), 401

    upload_dir = BASE / 'uploads' / 'learning_materials'

    if not upload_dir.exists():
        return jsonify({'materials': []})

    row = enrich(student_for_session())
    improvement_areas = row.get('Improvement_Areas', [])

    materials = []

    import json

    for file_path in sorted(upload_dir.iterdir()):

        if not file_path.is_file():
            continue
        if file_path.suffix.lower() == '.json':
            continue    

        metadata_path = upload_dir / (file_path.name + '.json')

        topic = 'General'

        if metadata_path.exists():
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

                topic = metadata.get('topic', 'General')

            except Exception:
                topic = 'General'

        materials.append({
            'filename': file_path.name,
            'topic': topic,
            'url': url_for(
                'student_download_material',
                filename=file_path.name
            )
        })
    return jsonify({
        'materials': materials,
        'improvement_areas': improvement_areas
    })
@app.route('/teacher/delete-material/<path:filename>', methods=['POST'])
def teacher_delete_material(filename):
    if not login_required('teacher'):
        return jsonify({'error': 'Please login as teacher.'}), 401

    upload_dir = BASE / 'uploads' / 'learning_materials'

    safe_filename = Path(filename).name
    file_path = upload_dir / safe_filename
    metadata_path = upload_dir / (safe_filename + '.json')

    if not file_path.exists() or not file_path.is_file():
        return jsonify({'error': 'Material not found.'}), 404

    file_path.unlink()

    if metadata_path.exists() and metadata_path.is_file():
        metadata_path.unlink()

    return jsonify({
        'message': 'Learning material deleted successfully.',
        'filename': safe_filename
    })
    if not login_required('teacher'):
        return jsonify({'error': 'Please login as teacher.'}), 401

    upload_dir = BASE / 'uploads' / 'learning_materials'
    file_path = upload_dir / filename

    if not file_path.exists() or not file_path.is_file():
        return jsonify({'error': 'Material not found.'}), 404

    file_path.unlink()

    return jsonify({
        'message': 'Learning material deleted successfully.',
        'filename': filename
    })
@app.route('/student/materials/<path:filename>')
def student_download_material(filename):
    if not login_required('student'):
        return jsonify({'error': 'Please login as student.'}), 401

    upload_dir = BASE / 'uploads' / 'learning_materials'

    file_path = upload_dir / filename

    if not file_path.exists() or not file_path.is_file():
        return jsonify({'error': 'Material not found.'}), 404

    return send_from_directory(upload_dir, filename)
@app.route('/student')
def student_dashboard():
    if not login_required('student'): return redirect(url_for('login'))
    row=student_for_session()
    if not row: return 'Student profile not found',404
    return render_template('student.html', student=enrich(row))

@app.route('/api/student-ai', methods=['POST'])
def student_ai():
    if not login_required('student'): return jsonify({'answer':'Please login as a student.'}),401
    row=enrich(student_for_session()); q=request.json.get('question','').lower(); hours=max(1,min(8,int(request.json.get('hours',3))))
    if any(k in q for k in ['plan','schedule','timetable','time']):
        focus=row['Improvement_Areas'][0] if row['Improvement_Areas'] else 'revision and practice'
        return jsonify({'answer':f'For {hours} hours today: prioritise {focus} for about {max(1,hours//2)} hour(s), then assignments/practice, followed by revision or a self-test. Take short breaks between sessions.'})
    if 'performance' in q or 'score' in q: return jsonify({'answer':f"Your performance score is {row['Performance_Score']:.1f}/100 ({row['Performance_Status']}). Main insight: {row['Primary_Insight']}."})
    if 'attendance' in q: return jsonify({'answer':f"Your attendance is {row['Attendance']:.1f}%. Regular attendance supports continuity with coursework."})
    if 'risk' in q: return jsonify({'answer':f"Your current risk level is {row['Risk_Level']} with a risk score of {row['Risk_Score']}. Main factors should be reviewed in the Risk Assessment section."})
    return jsonify({'answer':f"Your main focus area is {row['Primary_Insight']}. Ask me for a study plan, time-management schedule, performance explanation, risk explanation, or improvement suggestions."})
@app.route('/api/student-quiz', methods=['GET'])
def student_quiz():
    if not login_required('student'):
        return jsonify({'error': 'Unauthorised'}), 401

    row = enrich(student_for_session())

    questions = [
        {
            'question': 'Which action is most useful when you identify a weak academic area?',
            'options': [
                'Ignore it until the final exam',
                'Practise and review the topic regularly',
                'Stop attending related classes',
                'Only study strong subjects'
            ],
            'answer': 1
        },
        {
            'question': 'What is a useful way to manage limited study time?',
            'options': [
                'Study without any plan',
                'Spend all time on one easy topic',
                'Prioritise important and weak areas',
                'Avoid revision'
            ],
            'answer': 2
        },
        {
            'question': 'Why are practice quizzes useful?',
            'options': [
                'They help identify learning gaps',
                'They replace all classroom learning',
                'They guarantee marks',
                'They remove the need for revision'
            ],
            'answer': 0
        },
        {
            'question': 'What should a student do after making mistakes in a quiz?',
            'options': [
                'Ignore the mistakes',
                'Review the mistakes and practise again',
                'Stop attempting quizzes',
                'Only study easy questions'
            ],
            'answer': 1
        },
        {
            'question': 'Which combination supports consistent academic improvement?',
            'options': [
                'Regular study, practice and revision',
                'Only studying before exams',
                'Skipping assignments',
                'Ignoring attendance'
            ],
            'answer': 0
        }
    ]

    return jsonify({
        'student_id': row['Student_ID'],
        'focus_areas': row.get('Improvement_Areas', []),
        'questions': questions
    })
@app.route('/api/student-whatif', methods=['POST'])
def student_whatif():
    if not login_required('student'): return jsonify({'error':'Unauthorised'}),401
    row=student_for_session(); attendance=float(request.json.get('attendance',row['Attendance'])); study=float(request.json.get('study_hours',row['Study_Hours']))
    simulated=dict(row); simulated['Attendance']=max(0,min(100,attendance)); simulated['Study_Hours']=max(0,study)
    # Study hours are represented through the existing study-hours input only in this scenario; the dashboard score remains consistent with the current formula.
    score=performance_score(simulated)
    return jsonify({'score':score,'status':status(score),'change':round(score-row['Performance_Score'],1)})

if __name__=='__main__':
    seed_database(); app.run(debug=True)
