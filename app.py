from flask import Flask, render_template, jsonify, request, session
from flask_socketio import SocketIO, emit, join_room
import random
import string
import time
import hashlib
import uuid
import json
from functools import wraps

app = Flask(__name__)
app.config['SECRET_KEY'] = 'mathbattle_edtech_secret_2024'
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="eventlet",
    logger=False,
    engineio_logger=False,
    ping_timeout=60,
    ping_interval=25,
)

# ── In-memory stores (replace with DB in production) ──────────
users        = {}   # email -> user dict
classes      = {}   # class_code -> class dict
game_rooms   = {}   # room_code -> room dict
sessions     = {}   # token -> email

# ── Constants ─────────────────────────────────────────────────
ROUND_TIMER   = 20
WIN_SCORE     = 5
MAX_PLAYERS   = 2
ROOM_EXPIRE   = 1800

PLANS = {
    "free":  {"teachers": 1,  "students": 30,  "price": 0,    "label": "Free"},
    "basic": {"teachers": 5,  "students": 999, "price": 999,  "label": "Basic ₹999/mo"},
    "pro":   {"teachers": 99, "students": 999, "price": 2499, "label": "Pro ₹2499/mo"},
}

DIFFICULTY = {
    "easy":   {"a": (1,10),  "b": (1,5),  "ops": ["+","-"]},
    "medium": {"a": (5,20),  "b": (1,10), "ops": ["+","-","*"]},
    "hard":   {"a": (10,30), "b": (2,12), "ops": ["+","-","*","/"]},
}

CBSE_GRADES = {
    "grade3": {"label":"Grade 3", "difficulty":"easy"},
    "grade4": {"label":"Grade 4", "difficulty":"easy"},
    "grade5": {"label":"Grade 5", "difficulty":"medium"},
    "grade6": {"label":"Grade 6", "difficulty":"medium"},
    "grade7": {"label":"Grade 7", "difficulty":"hard"},
    "grade8": {"label":"Grade 8", "difficulty":"hard"},
}

# ── Helpers ───────────────────────────────────────────────────
def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()
def gen_code(n=6): return ''.join(random.choices(string.ascii_uppercase+string.digits, k=n))
def gen_token(): return str(uuid.uuid4())

def auth_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-Auth-Token') or request.cookies.get('auth_token')
        if not token or token not in sessions:
            return jsonify({"error": "Unauthorized"}), 401
        request.user_email = sessions[token]
        request.user = users.get(request.user_email, {})
        return f(*args, **kwargs)
    return decorated

def teacher_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-Auth-Token') or request.cookies.get('auth_token')
        if not token or token not in sessions:
            return jsonify({"error": "Unauthorized"}), 401
        email = sessions[token]
        user  = users.get(email, {})
        if user.get('role') != 'teacher':
            return jsonify({"error": "Teacher access required"}), 403
        request.user_email = email
        request.user = user
        return f(*args, **kwargs)
    return decorated

def generate_question(difficulty="medium"):
    cfg = DIFFICULTY.get(difficulty, DIFFICULTY["medium"])
    op  = random.choice(cfg["ops"])
    if op == "/":
        b      = random.randint(1, 10)
        answer = random.randint(1, 10)
        a      = answer * b
    else:
        a = random.randint(*cfg["a"])
        b = random.randint(*cfg["b"])
        if op == "+": answer = a + b
        elif op == "-":
            if a < b: a, b = b, a
            answer = a - b
        elif op == "*": answer = a * b

    options = {answer}
    attempts = 0
    while len(options) < 4 and attempts < 100:
        attempts += 1
        d = random.choice([-5,-3,-2,-1,1,2,3,5,10,-10])
        c = answer + d
        if c > 0 and c != answer:
            options.add(c)
    opts = list(options)[:4]
    random.shuffle(opts)
    return {"question": f"{a} {op} {b} = ?", "answer": answer, "options": opts}

def new_room(difficulty="medium", class_code=None, teacher_email=None):
    return {
        "players":       {},
        "team1_name":    "Team 1",
        "team2_name":    "Team 2",
        "team1_score":   0,
        "team2_score":   0,
        "rope_position": 0,
        "current_question": {},
        "active":        False,
        "winner":        None,
        "round_locked":  False,
        "wrong_answers": set(),
        "difficulty":    difficulty,
        "round_start":   None,
        "last_active":   time.time(),
        "game_history":  [],
        "class_code":    class_code,
        "teacher_email": teacher_email,
    }

def room_state(room):
    return {
        "team1_name":       room["team1_name"],
        "team2_name":       room["team2_name"],
        "team1_score":      room["team1_score"],
        "team2_score":      room["team2_score"],
        "rope_position":    room["rope_position"],
        "current_question": room["current_question"],
        "active":           room["active"],
        "winner":           room["winner"],
        "player_count":     len(room["players"]),
        "difficulty":       room["difficulty"],
        "round_timer":      ROUND_TIMER,
        "win_score":        WIN_SCORE,
    }

def cleanup_rooms():
    now = time.time()
    expired = [c for c, r in game_rooms.items() if now - r.get("last_active", now) > ROOM_EXPIRE]
    for c in expired:
        del game_rooms[c]

def start_round_timer(room_code):
    def _timer(code=room_code):
        socketio.sleep(ROUND_TIMER)
        if code not in game_rooms: return
        r = game_rooms[code]
        if not r["active"] or r["round_locked"]: return
        r["round_locked"] = True
        r["wrong_answers"] = set()
        socketio.emit("question_skipped", {
            "correct_answer": r["current_question"].get("answer"),
            "message": "⏱ Time's up!",
            "timeout": True,
        }, room=code)
        def _next(c=code):
            socketio.sleep(2)
            if c not in game_rooms: return
            rm = game_rooms[c]
            if not rm["active"] or rm["winner"]: return
            rm["current_question"] = generate_question(rm["difficulty"])
            rm["round_locked"] = False
            rm["wrong_answers"] = set()
            rm["round_start"] = time.time()
            socketio.emit("new_question", {"question": rm["current_question"], "timer": ROUND_TIMER}, room=c)
            start_round_timer(c)
        socketio.start_background_task(_next)
    socketio.start_background_task(_timer)

def record_student_stats(room, winner_player, correct_answer):
    """Save per-student stats into their class record."""
    class_code = room.get("class_code")
    if not class_code or class_code not in classes:
        return
    cls = classes[class_code]
    for sid, p in room["players"].items():
        sname = p["name"]
        if sname not in cls["student_stats"]:
            cls["student_stats"][sname] = {"correct": 0, "wrong": 0, "games": 0, "last_seen": ""}
        if p == winner_player:
            cls["student_stats"][sname]["correct"] += 1
        cls["student_stats"][sname]["last_seen"] = time.strftime("%Y-%m-%d")
    cls["total_rounds"] += 1

# ── AUTH ROUTES ───────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/auth/register", methods=["POST"])
def register():
    d = request.get_json() or {}
    email = (d.get("email") or "").strip().lower()
    pw    = (d.get("password") or "").strip()
    name  = (d.get("name") or "").strip()
    role  = d.get("role", "teacher")  # teacher | student

    if not email or not pw or not name:
        return jsonify({"error": "All fields required"}), 400
    if email in users:
        return jsonify({"error": "Email already registered"}), 400
    if len(pw) < 6:
        return jsonify({"error": "Password min 6 characters"}), 400

    school = d.get("school", "").strip()
    users[email] = {
        "email":      email,
        "password":   hash_pw(pw),
        "name":       name,
        "role":       role,
        "school":     school,
        "plan":       "free",
        "plan_expiry": None,
        "created_at": time.strftime("%Y-%m-%d"),
        "classes":    [],  # class codes owned/enrolled
    }
    token = gen_token()
    sessions[token] = email
    return jsonify({"token": token, "user": safe_user(users[email])})

@app.route("/api/auth/login", methods=["POST"])
def login():
    d     = request.get_json() or {}
    email = (d.get("email") or "").strip().lower()
    pw    = (d.get("password") or "").strip()
    user  = users.get(email)
    if not user or user["password"] != hash_pw(pw):
        return jsonify({"error": "Invalid email or password"}), 401
    token = gen_token()
    sessions[token] = email
    return jsonify({"token": token, "user": safe_user(user)})

@app.route("/api/auth/me")
@auth_required
def me():
    return jsonify({"user": safe_user(request.user)})

def safe_user(u):
    return {k: v for k, v in u.items() if k != "password"}

# ── CLASS ROUTES (Teacher) ─────────────────────────────────────

@app.route("/api/classes", methods=["GET"])
@teacher_required
def get_classes():
    email   = request.user_email
    teacher = request.user
    my_classes = [classes[c] for c in teacher.get("classes", []) if c in classes]
    return jsonify({"classes": my_classes})

@app.route("/api/classes", methods=["POST"])
@teacher_required
def create_class():
    d        = request.get_json() or {}
    name     = (d.get("name") or "").strip()
    grade    = d.get("grade", "grade5")
    subject  = d.get("subject", "Math")
    email    = request.user_email
    teacher  = request.user

    if not name:
        return jsonify({"error": "Class name required"}), 400

    # Plan limit check
    plan    = PLANS.get(teacher.get("plan", "free"), PLANS["free"])
    current = len(teacher.get("classes", []))
    if current >= plan["teachers"]:
        return jsonify({"error": f"Upgrade plan to create more classes. Current plan: {plan['label']}"}), 403

    code = gen_code(6)
    while code in classes:
        code = gen_code(6)

    difficulty = CBSE_GRADES.get(grade, {}).get("difficulty", "medium")
    classes[code] = {
        "code":          code,
        "name":          name,
        "grade":         grade,
        "subject":       subject,
        "difficulty":    difficulty,
        "teacher_email": email,
        "teacher_name":  teacher["name"],
        "school":        teacher.get("school", ""),
        "created_at":    time.strftime("%Y-%m-%d"),
        "student_stats": {},   # name -> {correct, wrong, games, last_seen}
        "total_rounds":  0,
        "active_rooms":  [],
    }
    teacher["classes"].append(code)
    return jsonify({"class": classes[code]})

@app.route("/api/classes/<code>", methods=["GET"])
@teacher_required
def get_class(code):
    cls = classes.get(code.upper())
    if not cls:
        return jsonify({"error": "Class not found"}), 404
    if cls["teacher_email"] != request.user_email:
        return jsonify({"error": "Not your class"}), 403

    # Compute leaderboard
    lb = sorted(
        [{"name": k, **v} for k, v in cls["student_stats"].items()],
        key=lambda x: x["correct"],
        reverse=True
    )
    return jsonify({"class": cls, "leaderboard": lb[:20]})

@app.route("/api/classes/<code>", methods=["DELETE"])
@teacher_required
def delete_class(code):
    cls = classes.get(code.upper())
    if not cls or cls["teacher_email"] != request.user_email:
        return jsonify({"error": "Not found"}), 404
    del classes[code.upper()]
    request.user["classes"] = [c for c in request.user["classes"] if c != code.upper()]
    return jsonify({"status": "deleted"})

@app.route("/api/classes/<code>/leaderboard")
@teacher_required
def class_leaderboard(code):
    cls = classes.get(code.upper())
    if not cls or cls["teacher_email"] != request.user_email:
        return jsonify({"error": "Not found"}), 404
    lb = sorted(
        [{"name": k, **v} for k, v in cls["student_stats"].items()],
        key=lambda x: x["correct"], reverse=True
    )
    return jsonify({"leaderboard": lb, "total_rounds": cls["total_rounds"]})

# ── SUBSCRIPTION ROUTES ────────────────────────────────────────

@app.route("/api/subscription/upgrade", methods=["POST"])
@teacher_required
def upgrade_plan():
    d    = request.get_json() or {}
    plan = d.get("plan")
    if plan not in PLANS:
        return jsonify({"error": "Invalid plan"}), 400
    # In production: verify Razorpay payment here
    # razorpay_payment_id = d.get("razorpay_payment_id")
    request.user["plan"] = plan
    request.user["plan_expiry"] = time.strftime("%Y-%m-%d", time.localtime(time.time() + 30*24*3600))
    return jsonify({"status": "upgraded", "plan": plan, "details": PLANS[plan]})

@app.route("/api/subscription/plans")
def get_plans():
    return jsonify({"plans": PLANS})

# ── GAME ROOM ROUTES ───────────────────────────────────────────

@app.route("/api/create_room", methods=["POST"])
def create_room():
    cleanup_rooms()
    d          = request.get_json(silent=True) or {}
    difficulty = d.get("difficulty", "medium")
    class_code = (d.get("class_code") or "").upper() or None
    token      = request.headers.get('X-Auth-Token') or d.get("token")
    teacher_email = None

    if class_code and class_code in classes:
        difficulty = classes[class_code]["difficulty"]
        if token and token in sessions:
            teacher_email = sessions[token]

    if difficulty not in DIFFICULTY:
        difficulty = "medium"

    code = gen_code(6)
    while code in game_rooms:
        code = gen_code(6)
    game_rooms[code] = new_room(difficulty, class_code, teacher_email)

    if class_code and class_code in classes:
        classes[class_code]["active_rooms"].append(code)

    return jsonify({"room_code": code, "difficulty": difficulty})

@app.route("/api/room/<code>")
def get_room(code):
    code = code.upper()
    if code not in game_rooms:
        return jsonify({"error": "Room not found"}), 404
    r = game_rooms[code]
    return jsonify({
        "exists":      True,
        "active":      r["active"],
        "team1_name":  r["team1_name"],
        "team2_name":  r["team2_name"],
        "player_count":len(r["players"]),
        "difficulty":  r["difficulty"],
        "full":        len(r["players"]) >= MAX_PLAYERS,
        "class_code":  r.get("class_code"),
    })

# ── SOCKET.IO ──────────────────────────────────────────────────

@socketio.on("join_room")
def on_join(data):
    code  = data.get("room_code", "").upper()
    name  = (data.get("name") or "Player").strip()[:16]
    team  = int(data.get("team", 1))

    if code not in game_rooms:
        emit("error", {"message": "Room not found!"}); return

    r   = game_rooms[code]
    r["last_active"] = time.time()
    sid = request.sid

    if len(r["players"]) >= MAX_PLAYERS and sid not in r["players"]:
        emit("error", {"message": "Room is full!"}); return

    existing_teams = [p["team"] for pid, p in r["players"].items() if pid != sid]
    if team in existing_teams:
        team = 2 if team == 1 else 1
        emit("team_switched", {"team": team, "message": f"Auto-switched to Team {team}"})

    join_room(code)
    r["players"][sid] = {"name": name, "team": team, "score": 0}
    if team == 1: r["team1_name"] = name
    else:         r["team2_name"] = name

    emit("joined", {"room_code": code, "name": name, "team": team, "state": room_state(r)})
    socketio.emit("player_joined", {
        "name": name, "team": team,
        "player_count": len(r["players"]),
        "team1_name": r["team1_name"],
        "team2_name": r["team2_name"],
    }, room=code)

    if len(r["players"]) >= 2 and not r["active"]:
        r["active"]           = True
        r["current_question"] = generate_question(r["difficulty"])
        r["round_locked"]     = False
        r["wrong_answers"]    = set()
        r["round_start"]      = time.time()
        socketio.emit("game_update", room_state(r), room=code)
        start_round_timer(code)


@socketio.on("submit_answer")
def on_answer(data):
    code = data.get("room_code", "").upper()
    sid  = request.sid
    if code not in game_rooms: return

    r = game_rooms[code]
    r["last_active"] = time.time()

    if not r["active"] or r["round_locked"]:
        emit("answer_result", {"correct": False, "too_slow": True}); return

    player = r["players"].get(sid)
    if not player: return

    try:
        answer = int(data.get("answer"))
    except (TypeError, ValueError):
        emit("answer_result", {"correct": False, "too_slow": False}); return

    correct = answer == r["current_question"]["answer"]

    if correct:
        r["round_locked"] = True
        r["wrong_answers"] = set()
        team = player["team"]
        player["score"] += 1

        if team == 1:
            r["team1_score"] += 1
            r["rope_position"] = max(-WIN_SCORE, r["rope_position"] - 1)
        else:
            r["team2_score"] += 1
            r["rope_position"] = min(WIN_SCORE, r["rope_position"] + 1)

        r["game_history"].append({
            "question":  r["current_question"]["question"],
            "answer":    r["current_question"]["answer"],
            "solved_by": player["name"],
            "team":      team,
        })

        # Record stats in class
        record_student_stats(r, player, answer)

        if r["rope_position"] <= -WIN_SCORE:
            r["winner"] = r["team1_name"]; r["active"] = False
        elif r["rope_position"] >= WIN_SCORE:
            r["winner"] = r["team2_name"]; r["active"] = False

        # Update class stats on game end
        if not r["active"] and r.get("class_code") and r["class_code"] in classes:
            cls = classes[r["class_code"]]
            for p in r["players"].values():
                sname = p["name"]
                if sname not in cls["student_stats"]:
                    cls["student_stats"][sname] = {"correct":0,"wrong":0,"games":0,"last_seen":""}
                cls["student_stats"][sname]["games"] += 1

        socketio.emit("round_result", {
            "winner_name":   player["name"],
            "winner_team":   team,
            "rope_position": r["rope_position"],
            "team1_score":   r["team1_score"],
            "team2_score":   r["team2_score"],
            "game_winner":   r["winner"],
            "correct_answer":r["current_question"]["answer"],
            "history":       r["game_history"][-5:],
        }, room=code)

        if not r["winner"]:
            def next_q(rc=code):
                socketio.sleep(2)
                if rc not in game_rooms: return
                rm = game_rooms[rc]
                if not rm["active"] or rm["winner"]: return
                rm["current_question"] = generate_question(rm["difficulty"])
                rm["round_locked"] = False
                rm["wrong_answers"] = set()
                rm["round_start"] = time.time()
                socketio.emit("new_question", {"question": rm["current_question"], "timer": ROUND_TIMER}, room=rc)
                start_round_timer(rc)
            socketio.start_background_task(next_q)
    else:
        r["wrong_answers"].add(sid)
        # Track wrong in class
        if r.get("class_code") and r["class_code"] in classes:
            cls = classes[r["class_code"]]
            sname = player["name"]
            if sname not in cls["student_stats"]:
                cls["student_stats"][sname] = {"correct":0,"wrong":0,"games":0,"last_seen":""}
            cls["student_stats"][sname]["wrong"] += 1
            cls["student_stats"][sname]["last_seen"] = time.strftime("%Y-%m-%d")

        emit("answer_result", {"correct": False, "too_slow": False})

        active_sids = set(r["players"].keys())
        if r["wrong_answers"] >= active_sids:
            r["round_locked"] = True
            r["wrong_answers"] = set()
            socketio.emit("question_skipped", {
                "correct_answer": r["current_question"]["answer"],
                "message": "Both wrong! Skipping...",
                "timeout": False,
            }, room=code)
            def skip_q(rc=code):
                socketio.sleep(2)
                if rc not in game_rooms: return
                rm = game_rooms[rc]
                if not rm["active"] or rm["winner"]: return
                rm["current_question"] = generate_question(rm["difficulty"])
                rm["round_locked"] = False
                rm["wrong_answers"] = set()
                rm["round_start"] = time.time()
                socketio.emit("new_question", {"question": rm["current_question"], "timer": ROUND_TIMER}, room=rc)
                start_round_timer(rc)
            socketio.start_background_task(skip_q)


@socketio.on("rematch")
def on_rematch(data):
    code = data.get("room_code", "").upper()
    if code not in game_rooms: return
    r = game_rooms[code]
    r.update({
        "active": True, "winner": None,
        "team1_score": 0, "team2_score": 0,
        "rope_position": 0, "round_locked": False,
        "wrong_answers": set(), "game_history": [],
        "current_question": generate_question(r["difficulty"]),
        "round_start": time.time(), "last_active": time.time(),
    })
    socketio.emit("game_update", room_state(r), room=code)
    start_round_timer(code)


@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    for code, r in list(game_rooms.items()):
        if sid in r["players"]:
            name = r["players"][sid]["name"]
            del r["players"][sid]
            r["last_active"] = time.time()
            if len(r["players"]) == 0:
                del game_rooms[code]; return
            if r["active"] and len(r["players"]) < 2:
                r["active"] = False; r["round_locked"] = False
                socketio.emit("game_paused", {"message": f"{name} left. Waiting..."}, room=code)
            else:
                socketio.emit("player_left", {"name": name, "player_count": len(r["players"])}, room=code)
            break


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
