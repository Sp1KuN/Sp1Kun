
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, session, flash, abort
from werkzeug.utils import secure_filename
import os, json, time, random, string

BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "data")
USERS_PATH = os.path.join(DATA_DIR, "users.json")
ASSIGN_DIR = os.path.join(DATA_DIR, "assignments")
GROUPS_DIR = os.path.join(DATA_DIR, "groups")
SUBJECTS_DIR = os.path.join(DATA_DIR, "subjects")

app = Flask(__name__)
app.secret_key = "change_me_secret"
for d in [DATA_DIR, ASSIGN_DIR, GROUPS_DIR, SUBJECTS_DIR]:
    os.makedirs(d, exist_ok=True)

def _read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def load_users():
    return _read_json(USERS_PATH, [])

def save_users(users):
    _write_json(USERS_PATH, users)

def ensure_users_file():
    if not os.path.exists(USERS_PATH):
        save_users([])

def new_id(prefix=""):
    ts = time.strftime("%Y%m%d-%H%M%S")
    rnd = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"{prefix}{ts}-{rnd}"

def human_dt(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))

def next_assignment_number():
    max_num = 0
    if os.path.exists(ASSIGN_DIR):
        for aid in os.listdir(ASSIGN_DIR):
            meta_path = os.path.join(ASSIGN_DIR, aid, "meta.json")
            if os.path.exists(meta_path):
                data = _read_json(meta_path, {})
                try:
                    n = int(data.get("number", 0))
                    max_num = max(max_num, n)
                except Exception:
                    pass
    return max_num + 1

# Always show login first
@app.route("/")
def index():
    return redirect(url_for("login"))

# Global auth guard: block any page without login (except login & static)
@app.before_request
def require_login():
    from flask import request
    if request.endpoint in ("login", "static"):
        return
    if "user" not in session:
        return redirect(url_for("login"))

@app.route("/home")
def home():
    if "user" not in session:
        return redirect(url_for("login"))
    role = session["user"]["role"]
    if role == "admin":
        return redirect(url_for("admin_panel"))
    if role == "teacher":
        return redirect(url_for("teacher_home"))
    if role == "student":
        return redirect(url_for("student_home"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET","POST"])
def login():
    ensure_users_file()
    if request.method == "GET":
        return render_template("login.html")
    username = request.form.get("username","").strip()
    password = request.form.get("password","").strip()
    for u in load_users():
        if u["username"] == username and u["password"] == password:
            session["user"] = {"username": u["username"], "role": u["role"]}
            return redirect(url_for("home"))
    flash("Невірний логін або пароль")
    return redirect(url_for("login"))

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

# -------- Admin --------
@app.route("/admin", methods=["GET","POST"])
def admin_panel():
    if "user" not in session or session["user"]["role"] != "admin":
        abort(403)
    users = load_users()
    if request.method == "POST":
        # delete user if requested
        del_user = request.form.get("delete_username", "").strip()
        if del_user:
            users = [u for u in users if u.get("username") != del_user]
            save_users(users)
            flash("Користувача видалено")
            return redirect(url_for("admin_panel"))

        username = request.form.get("username","").strip()
        password = request.form.get("password","").strip()
        role = request.form.get("role","").strip()
        if not username or not password or role not in ("admin","teacher","student"):
            flash("Заповніть поля коректно")
            return redirect(url_for("admin_panel"))
        if any(u["username"] == username for u in users):
            flash("Користувач вже існує")
            return redirect(url_for("admin_panel"))
        users.append({"username":username,"password":password,"role":role})
        save_users(users)
        flash("Користувача додано")
        return redirect(url_for("admin_panel"))
    return render_template("admin.html", users=users)

# -------- Teacher helpers --------
def teacher_groups(me):
    out = []
    if os.path.exists(GROUPS_DIR):
        for gid in os.listdir(GROUPS_DIR):
            meta = _read_json(os.path.join(GROUPS_DIR, gid, "meta.json"), {})
            if meta.get("teacher") == me:
                out.append(meta)
    out.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return out

def teacher_subjects(me):
    out = []
    if os.path.exists(SUBJECTS_DIR):
        for fn in os.listdir(SUBJECTS_DIR):
            if fn.endswith(".json"):
                meta = _read_json(os.path.join(SUBJECTS_DIR, fn), {})
                if meta.get("teacher") == me:
                    out.append(meta)
    out.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return out

def list_tasks(filter_author=None, for_student=None):
    tasks = []
    if not os.path.exists(ASSIGN_DIR):
        return tasks
    for aid in os.listdir(ASSIGN_DIR):
        meta_path = os.path.join(ASSIGN_DIR, aid, "meta.json")
        if os.path.exists(meta_path):
            item = _read_json(meta_path, {})
            if filter_author and item.get("author") != filter_author:
                continue
            if for_student:
                gid = item.get("group_id")
                students = _read_json(os.path.join(GROUPS_DIR, gid, "students.json"), [])
                if for_student not in students:
                    continue
            subs_dir = os.path.join(ASSIGN_DIR, aid, "submissions")
            item["submissions_count"] = len(os.listdir(subs_dir)) if os.path.exists(subs_dir) else 0
            tasks.append(item)
    tasks.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return tasks

# -------- Teacher home --------
@app.route("/teacher")
def teacher_home():
    if "user" not in session or session["user"]["role"] != "teacher":
        abort(403)
    me = session["user"]["username"]
    return render_template("teacher_index.html", user=session["user"], tasks=list_tasks(filter_author=me), submissions=None, task=None)

# -------- Groups --------
@app.route("/teacher/groups", methods=["GET","POST"])
def groups_page():
    if "user" not in session or session["user"]["role"] != "teacher":
        abort(403)
    me = session["user"]["username"]
    if request.method == "POST":
        name = request.form.get("name","").strip()
        if not name:
            flash("Вкажіть назву групи")
            return redirect(url_for("groups_page"))
        gid = new_id("g-")
        gdir = os.path.join(GROUPS_DIR, gid)
        os.makedirs(gdir, exist_ok=True)
        now = int(time.time())
        _write_json(os.path.join(gdir,"meta.json"), {"id":gid,"name":name,"teacher":me,"created_at":now,"created_at_str":human_dt(now)})
        _write_json(os.path.join(gdir,"students.json"), [])
        flash("Групу створено")
        return redirect(url_for("groups_page"))
    return render_template("teacher_groups.html", user=session["user"], groups=teacher_groups(me))

@app.route("/teacher/groups/<gid>", methods=["GET","POST"])
def group_detail(gid):
    if "user" not in session or session["user"]["role"] != "teacher":
        abort(403)
    me = session["user"]["username"]
    meta = _read_json(os.path.join(GROUPS_DIR, gid, "meta.json"), {})
    if not meta or meta.get("teacher") != me:
        abort(404)
    students = _read_json(os.path.join(GROUPS_DIR, gid, "students.json"), [])
    all_students = [u["username"] for u in load_users() if u.get("role") == "student"]
    if request.method == "POST":
        student = request.form.get("student","").strip()
        if student and student in all_students and student not in students:
            students.append(student)
            _write_json(os.path.join(GROUPS_DIR, gid, "students.json"), students)
            flash("Студента додано")
        else:
            flash("Некоректний студент або вже в групі")
        return redirect(url_for("group_detail", gid=gid))
    return render_template("teacher_group_detail.html", user=session["user"], group=meta, students=students, all_students=all_students)

# -------- Subjects --------
@app.route("/teacher/subjects", methods=["GET","POST"])
def subjects_page():
    if "user" not in session or session["user"]["role"] != "teacher":
        abort(403)
    me = session["user"]["username"]
    if request.method == "POST":
        name = request.form.get("name","").strip()
        if not name:
            flash("Вкажіть назву предмету")
            return redirect(url_for("subjects_page"))
        sid = new_id("s-")
        now = int(time.time())
        _write_json(os.path.join(SUBJECTS_DIR, f"{sid}.json"), {"id":sid,"name":name,"teacher":me,"created_at":now,"created_at_str":human_dt(now)})
        flash("Предмет створено")
        return redirect(url_for("subjects_page"))
    return render_template("teacher_subjects.html", user=session["user"], subjects=teacher_subjects(me))

# -------- New task --------
@app.route("/teacher/new", methods=["GET","POST"])
def teacher_new():
    if "user" not in session or session["user"]["role"] != "teacher":
        abort(403)
    me = session["user"]["username"]
    groups_list = teacher_groups(me)
    subjects_list = teacher_subjects(me)
    if request.method == "GET":
        return render_template("teacher_new.html", user=session["user"], groups=groups_list, subjects=subjects_list)
    title = request.form.get("title","").strip()
    desc = request.form.get("description","").strip()
    group_id = request.form.get("group_id","").strip()
    subject_id = request.form.get("subject_id","").strip()
    if not title or not group_id or not subject_id:
        flash("Назва, група та предмет — обов'язкові")
        return redirect(url_for("teacher_new"))
    gmeta = _read_json(os.path.join(GROUPS_DIR, group_id, "meta.json"), {})
    smeta = _read_json(os.path.join(SUBJECTS_DIR, f"{subject_id}.json"), {})
    if gmeta.get("teacher") != me or smeta.get("teacher") != me:
        abort(403)
    file = request.files.get("file")
    aid = new_id()
    number = next_assignment_number()
    root = os.path.join(ASSIGN_DIR, aid)
    os.makedirs(os.path.join(root, "attachment"), exist_ok=True)
    os.makedirs(os.path.join(root, "submissions"), exist_ok=True)
    attach_name = None
    if file and file.filename:
        attach_name = secure_filename(file.filename)
        file.save(os.path.join(root, "attachment", attach_name))
    created_ts = int(time.time())
    meta = {
        "id": aid,
        "number": number,
        "title": title,
        "description": desc,
        "author": me,
        "created_at": created_ts,
        "created_at_str": human_dt(created_ts),
        "attachment": attach_name,
        "group_id": group_id,
        "group_name": gmeta.get("name"),
        "subject_id": subject_id,
        "subject_name": smeta.get("name")
    }
    _write_json(os.path.join(root, "meta.json"), meta)
    flash("Завдання створено")
    return redirect(url_for("teacher_home"))

# -------- View submissions --------
@app.route("/teacher/submissions/<aid>")
def teacher_submissions(aid):
    if "user" not in session or session["user"]["role"] != "teacher":
        abort(403)
    meta_path = os.path.join(ASSIGN_DIR, aid, "meta.json")
    task = _read_json(meta_path, {"id": aid, "title": aid, "number": None, "created_at_str": ""})
    me = session["user"]["username"]
    if task.get("author") != me:
        abort(403)
    subs_dir = os.path.join(ASSIGN_DIR, aid, "submissions")
    subs = []
    if os.path.exists(subs_dir):
        for user in os.listdir(subs_dir):
            meta = os.path.join(subs_dir, user, "meta.json")
            if os.path.exists(meta):
                subs.append(_read_json(meta, {}))
    subs.sort(key=lambda x: x.get("submitted_at", 0), reverse=True)
    return render_template("teacher_index.html", user=session["user"], tasks=None, submissions=subs, aid=aid, task=task)

# -------- Downloads --------
@app.route("/download/attachment/<aid>/<fname>")
def download_attachment(aid, fname):
    if "user" not in session:
        abort(403)
    folder = os.path.join(ASSIGN_DIR, aid, "attachment")
    if not os.path.exists(os.path.join(folder, fname)):
        abort(404)
    return send_from_directory(folder, fname, as_attachment=True)

@app.route("/download/submission/<aid>/<username>/<fname>")
def download_submission(aid, username, fname):
    if "user" not in session or session["user"]["role"] != "teacher":
        abort(403)
    folder = os.path.join(ASSIGN_DIR, aid, "submissions", username, "file")
    if not os.path.exists(os.path.join(folder, fname)):
        abort(404)
    return send_from_directory(folder, fname, as_attachment=True)

# -------- Student --------
@app.route("/student")
def student_home():
    if "user" not in session or session["user"]["role"] != "student":
        abort(403)
    me = session["user"]["username"]
    return render_template("student_index.html", user=session["user"], tasks=list_tasks(for_student=me))

@app.route("/student/submit/<aid>", methods=["GET","POST"])
def student_submit(aid):
    if "user" not in session or session["user"]["role"] != "student":
        abort(403)
    meta_path = os.path.join(ASSIGN_DIR, aid, "meta.json")
    if not os.path.exists(meta_path):
        abort(404)
    task = _read_json(meta_path, {})
    me = session["user"]["username"]
    students = _read_json(os.path.join(GROUPS_DIR, task.get("group_id",""), "students.json"), [])
    if me not in students:
        abort(403)
    if request.method == "GET":
        return render_template("student_submit.html", user=session["user"], task=task)
    note = request.form.get("note","").strip()
    file = request.files.get("file")
    user_dir = os.path.join(ASSIGN_DIR, aid, "submissions", me)
    os.makedirs(os.path.join(user_dir, "file"), exist_ok=True)
    filename = None
    if file and file.filename:
        filename = secure_filename(file.filename)
        file.save(os.path.join(user_dir, "file", filename))
    ts = int(time.time())
    meta = {"id": aid, "username": me, "note": note, "filename": filename, "submitted_at": ts, "submitted_at_str": human_dt(ts)}
    _write_json(os.path.join(user_dir, "meta.json"), meta)
    flash("Відповідь надіслано")
    return redirect(url_for("student_home"))

# -------- CLI --------
@app.cli.command("init-admin")
def init_admin():
    ensure_users_file()
    users = load_users()
    if not any(u.get("role") == "admin" for u in users):
        users.append({"username":"admin","password":"admin","role":"admin"})
        save_users(users)
        print("Створено admin/admin")
    else:
        print("Admin вже існує")

if __name__ == "__main__":
    ensure_users_file()
    app.run(port=5000, debug=True)
