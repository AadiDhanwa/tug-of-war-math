from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit, join_room
import random
import string
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'tugofwar_math_secret_2024'
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="eventlet",
    logger=False,
    engineio_logger=False,
    ping_timeout=60,
    ping_interval=25,
)

game_rooms = {}

ROOM_EXPIRE_SECONDS = 1800  # 30 min inactivity → delete room
ROUND_TIMER_SECONDS = 20    # per-round time limit
MAX_PLAYERS = 2
WIN_SCORE = 5               # rope positions needed to win

DIFFICULTY = {
    "easy":   {"a": (1, 10),  "b": (1, 5),  "ops": ["+", "-"]},
    "medium": {"a": (5, 20),  "b": (1, 10), "ops": ["+", "-", "*"]},
    "hard":   {"a": (10, 30), "b": (2, 12), "ops": ["+", "-", "*", "/"]},
}

# ── Helpers ───────────────────────────────────────────────────

def generate_room_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def generate_question(difficulty="medium"):
    cfg = DIFFICULTY.get(difficulty, DIFFICULTY["medium"])
    op = random.choice(cfg["ops"])

    if op == "/":
        b = random.randint(1, 10)
        answer = random.randint(1, 10)
        a = answer * b
    else:
        a = random.randint(*cfg["a"])
        b = random.randint(*cfg["b"])
        if op == "+":
            answer = a + b
        elif op == "-":
            if a < b: a, b = b, a
            answer = a - b
        elif op == "*":
            answer = a * b

    # Smart distractors
    options = {answer}
    attempts = 0
    while len(options) < 4 and attempts < 100:
        attempts += 1
        strategy = random.randint(0, 2)
        if strategy == 0:
            d = random.choice([-3, -2, -1, 1, 2, 3])
            candidate = answer + d
        elif strategy == 1:
            candidate = answer + random.choice([-10, -5, 5, 10])
        else:
            candidate = answer + random.randint(1, 5)
        if candidate > 0 and candidate != answer:
            options.add(candidate)

    opts = list(options)[:4]
    random.shuffle(opts)
    return {
        "question": f"{a} {op} {b} = ?",
        "answer": answer,
        "options": opts,
    }

def new_room(difficulty="medium"):
    return {
        "players": {},
        "team1_name": "Team 1",
        "team2_name": "Team 2",
        "team1_score": 0,
        "team2_score": 0,
        "rope_position": 0,
        "current_question": {},
        "active": False,
        "winner": None,
        "round_locked": False,
        "wrong_answers": set(),
        "difficulty": difficulty,
        "round_start_time": None,
        "last_active": time.time(),
        "game_history": [],
    }

def room_state(room):
    return {
        "team1_name": room["team1_name"],
        "team2_name": room["team2_name"],
        "team1_score": room["team1_score"],
        "team2_score": room["team2_score"],
        "rope_position": room["rope_position"],
        "current_question": room["current_question"],
        "active": room["active"],
        "winner": room["winner"],
        "player_count": len(room["players"]),
        "difficulty": room["difficulty"],
        "round_timer": ROUND_TIMER_SECONDS,
        "win_score": WIN_SCORE,
    }

def cleanup_expired_rooms():
    now = time.time()
    expired = [
        code for code, r in game_rooms.items()
        if now - r.get("last_active", now) > ROOM_EXPIRE_SECONDS
    ]
    for code in expired:
        del game_rooms[code]

def start_round_timer(room_code):
    def _timer(code=room_code):
        socketio.sleep(ROUND_TIMER_SECONDS)
        if code not in game_rooms:
            return
        r = game_rooms[code]
        if not r["active"] or r["round_locked"]:
            return
        r["round_locked"] = True
        correct_ans = r["current_question"].get("answer")
        r["wrong_answers"] = set()
        socketio.emit("question_skipped", {
            "correct_answer": correct_ans,
            "message": "⏱ Time's up!",
            "timeout": True,
        }, room=code)
        def _next(c=code):
            socketio.sleep(2)
            if c not in game_rooms:
                return
            room = game_rooms[c]
            if not room["active"] or room["winner"]:
                return
            room["current_question"] = generate_question(room["difficulty"])
            room["round_locked"] = False
            room["wrong_answers"] = set()
            room["round_start_time"] = time.time()
            socketio.emit("new_question", {
                "question": room["current_question"],
                "timer": ROUND_TIMER_SECONDS,
            }, room=c)
            start_round_timer(c)
        socketio.start_background_task(_next)
    socketio.start_background_task(_timer)

# ── REST ──────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/create_room", methods=["POST"])
def create_room():
    try:
        cleanup_expired_rooms()
        data = request.get_json(silent=True) or {}
        difficulty = data.get("difficulty", "medium")
        if difficulty not in DIFFICULTY:
            difficulty = "medium"
        code = generate_room_code()
        while code in game_rooms:
            code = generate_room_code()
        game_rooms[code] = new_room(difficulty)
        return jsonify({"room_code": code, "difficulty": difficulty})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/room/<code>")
def get_room(code):
    code = code.upper()
    if code not in game_rooms:
        return jsonify({"error": "Room not found"}), 404
    r = game_rooms[code]
    return jsonify({
        "exists": True,
        "active": r["active"],
        "team1_name": r["team1_name"],
        "team2_name": r["team2_name"],
        "player_count": len(r["players"]),
        "difficulty": r["difficulty"],
        "full": len(r["players"]) >= MAX_PLAYERS,
    })

# ── SocketIO ──────────────────────────────────────────────────

@socketio.on("join_room")
def on_join(data):
    code = data.get("room_code", "").upper()
    name = (data.get("name") or "Player").strip()[:16]
    team = int(data.get("team", 1))

    if code not in game_rooms:
        emit("error", {"message": "Room not found!"})
        return

    r = game_rooms[code]
    r["last_active"] = time.time()
    sid = request.sid

    # Room full check
    if len(r["players"]) >= MAX_PLAYERS and sid not in r["players"]:
        emit("error", {"message": "Room is full! Max 2 players."})
        return

    # Team conflict — auto-assign opposite
    existing_teams = [p["team"] for p in r["players"].values() if p != r["players"].get(sid)]
    if team in existing_teams:
        team = 2 if team == 1 else 1
        emit("team_switched", {"team": team, "message": f"Auto-switched to Team {team} (other was taken)"})

    join_room(code)
    r["players"][sid] = {"name": name, "team": team, "score": 0}

    if team == 1:
        r["team1_name"] = name
    else:
        r["team2_name"] = name

    emit("joined", {
        "room_code": code,
        "name": name,
        "team": team,
        "state": room_state(r),
    })

    socketio.emit("player_joined", {
        "name": name,
        "team": team,
        "player_count": len(r["players"]),
        "team1_name": r["team1_name"],
        "team2_name": r["team2_name"],
    }, room=code)

    # Auto-start when 2 players join
    if len(r["players"]) >= 2 and not r["active"]:
        r["active"] = True
        r["current_question"] = generate_question(r["difficulty"])
        r["round_locked"] = False
        r["wrong_answers"] = set()
        r["round_start_time"] = time.time()
        socketio.emit("game_update", room_state(r), room=code)
        start_round_timer(code)


@socketio.on("submit_answer")
def on_answer(data):
    code = data.get("room_code", "").upper()
    sid = request.sid

    if code not in game_rooms:
        return
    r = game_rooms[code]
    r["last_active"] = time.time()

    if not r["active"] or r["round_locked"]:
        emit("answer_result", {"correct": False, "too_slow": True})
        return

    player = r["players"].get(sid)
    if not player:
        return

    try:
        answer = int(data.get("answer"))
    except (TypeError, ValueError):
        emit("answer_result", {"correct": False, "too_slow": False})
        return

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
            "question": r["current_question"]["question"],
            "answer": r["current_question"]["answer"],
            "solved_by": player["name"],
            "team": team,
        })

        if r["rope_position"] <= -WIN_SCORE:
            r["winner"] = r["team1_name"]
            r["active"] = False
        elif r["rope_position"] >= WIN_SCORE:
            r["winner"] = r["team2_name"]
            r["active"] = False

        socketio.emit("round_result", {
            "winner_name": player["name"],
            "winner_team": team,
            "rope_position": r["rope_position"],
            "team1_score": r["team1_score"],
            "team2_score": r["team2_score"],
            "game_winner": r["winner"],
            "correct_answer": r["current_question"]["answer"],
            "history": r["game_history"][-5:],
        }, room=code)

        if not r["winner"]:
            def next_q(room_code=code):
                socketio.sleep(2)
                if room_code not in game_rooms:
                    return
                room = game_rooms[room_code]
                if not room["active"] or room["winner"]:
                    return
                room["current_question"] = generate_question(room["difficulty"])
                room["round_locked"] = False
                room["wrong_answers"] = set()
                room["round_start_time"] = time.time()
                socketio.emit("new_question", {
                    "question": room["current_question"],
                    "timer": ROUND_TIMER_SECONDS,
                }, room=room_code)
                start_round_timer(room_code)
            socketio.start_background_task(next_q)
    else:
        r["wrong_answers"].add(sid)
        emit("answer_result", {"correct": False, "too_slow": False})

        active_sids = set(r["players"].keys())
        if r["wrong_answers"] >= active_sids:
            r["round_locked"] = True
            r["wrong_answers"] = set()
            socketio.emit("question_skipped", {
                "correct_answer": r["current_question"]["answer"],
                "message": "Both players got it wrong! Skipping...",
                "timeout": False,
            }, room=code)

            def skip_q(room_code=code):
                socketio.sleep(2)
                if room_code not in game_rooms:
                    return
                room = game_rooms[room_code]
                if not room["active"] or room["winner"]:
                    return
                room["current_question"] = generate_question(room["difficulty"])
                room["round_locked"] = False
                room["wrong_answers"] = set()
                room["round_start_time"] = time.time()
                socketio.emit("new_question", {
                    "question": room["current_question"],
                    "timer": ROUND_TIMER_SECONDS,
                }, room=room_code)
                start_round_timer(room_code)
            socketio.start_background_task(skip_q)


@socketio.on("rematch")
def on_rematch(data):
    code = data.get("room_code", "").upper()
    if code not in game_rooms:
        return
    r = game_rooms[code]
    r.update({
        "active": True,
        "winner": None,
        "team1_score": 0,
        "team2_score": 0,
        "rope_position": 0,
        "round_locked": False,
        "wrong_answers": set(),
        "game_history": [],
        "current_question": generate_question(r["difficulty"]),
        "round_start_time": time.time(),
        "last_active": time.time(),
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
                del game_rooms[code]
                return

            if r["active"] and len(r["players"]) < 2:
                r["active"] = False
                r["round_locked"] = False
                socketio.emit("game_paused", {
                    "message": f"{name} left. Waiting for opponent...",
                }, room=code)
            else:
                socketio.emit("player_left", {
                    "name": name,
                    "player_count": len(r["players"]),
                }, room=code)
            break


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
