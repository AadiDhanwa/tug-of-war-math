from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit, join_room
import random
import string
import time
import threading

app = Flask(__name__)
app.config['SECRET_KEY'] = 'tugofwar_math_secret_2024'
# socketio = SocketIO(app, cors_allowed_origins="*")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# Each room is a completely independent game session
game_rooms = {}

def generate_room_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def generate_question():
    a = random.randint(5, 15)
    b = random.randint(1, 10)
    op = random.choice(['+', '-', '*'])
    if op == '+':
        answer = a + b
    elif op == '-':
        if a < b: a, b = b, a
        answer = a - b
    else:
        answer = a * b
    options = set([answer])
    while len(options) < 4:
        d = random.randint(-5, 5)
        if d != 0:
            options.add(answer + d)
    opts = list(options)
    random.shuffle(opts)
    return {"question": f"{a} {op} {b} = ?", "answer": answer, "options": opts}

def new_room():
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
    }

# ── REST ──────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/create_room', methods=['POST'])
def create_room():
    code = generate_room_code()
    while code in game_rooms:
        code = generate_room_code()
    game_rooms[code] = new_room()
    return jsonify({"room_code": code})

@app.route('/api/room/<code>')
def get_room(code):
    code = code.upper()
    if code not in game_rooms:
        return jsonify({"error": "Room not found"}), 404
    r = game_rooms[code]
    return jsonify({"exists": True, "active": r["active"],
                    "team1_name": r["team1_name"], "team2_name": r["team2_name"],
                    "player_count": len(r["players"])})

# @app.route('/api/start/<code>', methods=['POST'])
# def start_game(code):
#     code = code.upper()
#     if code not in game_rooms:
#         return jsonify({"error": "Room not found"}), 404
#     r = game_rooms[code]
#     r.update({"active": True, "winner": None, "team1_score": 0,
#                "team2_score": 0, "rope_position": 0, "round_locked": False,
#                "current_question": generate_question()})
#     socketio.emit('game_update', room_state(r), room=code)
#     return jsonify({"status": "started"})
@app.route('/api/start/<code>', methods=['POST'])
def start_game(code):
    code = code.upper()

    if code not in game_rooms:
        return jsonify({"error": "Room not found"}), 404

    r = game_rooms[code]

    # Require minimum 2 players
    if len(r["players"]) < 2:
        return jsonify({"error": "Need at least 2 players"}), 400

    r.update({
        "active": True,
        "winner": None,
        "team1_score": 0,
        "team2_score": 0,
        "rope_position": 0,
        "round_locked": False,
        "current_question": generate_question()
    })

    socketio.emit('game_update', room_state(r), room=code)

    return jsonify({"status": "started"})

# ── SocketIO ──────────────────────────────────────────────────

@socketio.on('join_room')
def on_join(data):
    code = data.get('room_code', '').upper()
    name = (data.get('name') or 'Player').strip()
    team = int(data.get('team', 1))
    if code not in game_rooms:
        emit('error', {'message': 'Room not found!'})
        return
    r = game_rooms[code]
    sid = request.sid
    join_room(code)
    r["players"][sid] = {"name": name, "team": team, "score": 0}
    if team == 1:
        r["team1_name"] = name
    else:
        r["team2_name"] = name
    emit('joined', {"room_code": code, "name": name, "team": team, "state": room_state(r)})

    socketio.emit('player_joined', {
        "name": name,
        "team": team,
        "player_count": len(r["players"]),
        "team1_name": r["team1_name"],
        "team2_name": r["team2_name"],
    }, room=code)

    # Auto start when 2 players join
    if len(r["players"]) >= 2 and not r["active"]:
        r["active"] = True
        r["current_question"] = generate_question()
        r["round_locked"] = False

        socketio.emit('game_update', room_state(r), room=code)

@socketio.on('submit_answer')
def on_answer(data):
    code = data.get('room_code', '').upper()
    answer = data.get('answer')
    sid = request.sid
    if code not in game_rooms:
        return
    r = game_rooms[code]
    if not r["active"] or r["round_locked"]:
        emit('answer_result', {'correct': False, 'too_slow': True})
        return
    player = r["players"].get(sid)
    if not player:
        return
    correct = int(answer) == r["current_question"]["answer"]
    if correct:
        r["round_locked"] = True
        team = player["team"]
        player["score"] += 1
        if team == 1:
            r["team1_score"] += 1
            r["rope_position"] = max(-5, r["rope_position"] - 1)
        else:
            r["team2_score"] += 1
            r["rope_position"] = min(5, r["rope_position"] + 1)
        if r["rope_position"] <= -5:
            r["winner"] = r["team1_name"]
            r["active"] = False
        elif r["rope_position"] >= 5:
            r["winner"] = r["team2_name"]
            r["active"] = False
        socketio.emit('round_result', {
            "winner_name": player["name"],
            "winner_team": team,
            "rope_position": r["rope_position"],
            "team1_score": r["team1_score"],
            "team2_score": r["team2_score"],
            "game_winner": r["winner"],
            "correct_answer": r["current_question"]["answer"],
        }, room=code)
        if not r["winner"]:
            def next_q():
                socketio.sleep(2)
                if code in game_rooms and game_rooms[code]["active"]:
                # if code in game_rooms and game_rooms[code]["active"]:
                    game_rooms[code]["current_question"] = generate_question()
                    game_rooms[code]["round_locked"] = False
                    socketio.emit(
                        'new_question',
                        {"question": game_rooms[code]["current_question"]},
                        room=code
                        )
            # threading.Thread(target=next_q, daemon=True).start()
            socketio.start_background_task(next_q)
    else:
        emit('answer_result', {'correct': False, 'too_slow': False})

@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    for code, r in game_rooms.items():
        if sid in r["players"]:
            name = r["players"][sid]["name"]
            del r["players"][sid]
            socketio.emit('player_left', {"name": name, "player_count": len(r["players"])}, room=code)
            break

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
