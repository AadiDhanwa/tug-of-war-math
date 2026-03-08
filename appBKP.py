from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
import random
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'tugofwar_math_secret'
socketio = SocketIO(app, cors_allowed_origins="*")

# Game State
game_state = {
    "team1_score": 0,
    "team2_score": 0,
    "rope_position": 0,       # -5 (team1 wins) to +5 (team2 wins)
    "current_question": {},
    "timer": 30,
    "active": False,
    "current_team": 1,
    "winner": None
}

def generate_question(difficulty="medium"):
    if difficulty == "easy":
        a = random.randint(1, 9)
        b = random.randint(1, 9)
        ops = ['+', '-']
    elif difficulty == "medium":
        a = random.randint(5, 15)
        b = random.randint(1, 10)
        ops = ['+', '-', '*']
    else:
        a = random.randint(10, 20)
        b = random.randint(2, 12)
        ops = ['+', '-', '*']

    op = random.choice(ops)
    if op == '+':
        answer = a + b
    elif op == '-':
        if a < b:
            a, b = b, a
        answer = a - b
    else:
        answer = a * b

    return {
        "question": f"{a} {op} {b} = ?",
        "answer": answer,
        "options": generate_options(answer)
    }

def generate_options(correct):
    options = {correct}
    while len(options) < 4:
        delta = random.randint(-5, 5)
        if delta != 0:
            options.add(correct + delta)
    opts = list(options)
    random.shuffle(opts)
    return opts

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/start', methods=['POST'])
def start_game():
    global game_state
    game_state = {
        "team1_score": 0,
        "team2_score": 0,
        "rope_position": 0,
        "current_question": generate_question(),
        "timer": 30,
        "active": True,
        "current_team": 1,
        "winner": None
    }
    socketio.emit('game_update', game_state)
    return jsonify({"status": "started", "game": game_state})

@app.route('/api/answer', methods=['POST'])
def submit_answer():
    global game_state
    data = request.json
    team = data.get('team')
    answer = data.get('answer')
    correct = game_state['current_question']['answer']

    if not game_state['active']:
        return jsonify({"error": "Game not active"}), 400

    result = {
        "correct": False,
        "message": "Wrong answer! Rope moves back.",
        "rope_position": game_state['rope_position']
    }

    if answer == correct:
        result["correct"] = True
        result["message"] = f"Team {team} correct! Rope moves forward!"
        if team == 1:
            game_state['rope_position'] = max(-5, game_state['rope_position'] - 1)
            game_state['team1_score'] += 1
        else:
            game_state['rope_position'] = min(5, game_state['rope_position'] + 1)
            game_state['team2_score'] += 1
    else:
        if team == 1:
            game_state['rope_position'] = min(5, game_state['rope_position'] + 1)
        else:
            game_state['rope_position'] = max(-5, game_state['rope_position'] - 1)

    # Check for winner
    if game_state['rope_position'] <= -5:
        game_state['winner'] = "Team 1"
        game_state['active'] = False
    elif game_state['rope_position'] >= 5:
        game_state['winner'] = "Team 2"
        game_state['active'] = False

    game_state['current_question'] = generate_question()
    game_state['current_team'] = 2 if team == 1 else 1

    result['rope_position'] = game_state['rope_position']
    result['winner'] = game_state['winner']
    result['new_question'] = game_state['current_question']
    result['team1_score'] = game_state['team1_score']
    result['team2_score'] = game_state['team2_score']
    result['current_team'] = game_state['current_team']

    socketio.emit('game_update', game_state)
    return jsonify(result)

@app.route('/api/state')
def get_state():
    return jsonify(game_state)

@socketio.on('connect')
def handle_connect():
    emit('game_update', game_state)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
