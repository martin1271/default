"""
NAS100 Trading Flashcard Server
Run: python3 app.py
Open: http://localhost:5000
"""
from flask import Flask, jsonify, request, send_from_directory
import json, os, random

app = Flask(__name__, static_folder="static")
DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "nas100_5min.json")

# Load card index (metadata only) at startup; full context loaded on demand
_data = None

def get_data():
    global _data
    if _data is None:
        print("Loading flashcard data …")
        with open(DATA_FILE) as f:
            _data = json.load(f)
        print(f"Loaded {_data['total_cards']} cards")
    return _data

# Session score (in-memory; resets on server restart)
_session = {"correct": 0, "wrong": 0, "skipped": 0, "seen": set()}

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/meta")
def meta():
    d = get_data()
    return jsonify({
        "ticker": d["ticker"],
        "period": d.get("period", ""),
        "total_cards": d["total_cards"],
        "note": d.get("note", ""),
    })

@app.route("/api/card")
def card():
    d = get_data()
    cards = d["cards"]
    mode = request.args.get("mode", "random")

    if mode == "random":
        idx = random.randint(0, len(cards) - 1)
    else:
        idx = int(request.args.get("idx", 0)) % len(cards)

    c = cards[idx]
    return jsonify({
        "id": c["id"],
        "idx": idx,
        "date": c["date"],
        "time": c["time"],
        "entry": c["entry"],
        "context": c["context"],
        "total": len(cards),
    })

@app.route("/api/answer")
def answer():
    d = get_data()
    cards = d["cards"]
    idx = int(request.args.get("idx", 0))
    user_answer = request.args.get("answer", "").upper()

    c = cards[idx]
    correct = c["signal"]

    is_correct = user_answer == correct

    if user_answer:
        if is_correct:
            _session["correct"] += 1
        else:
            _session["wrong"] += 1
        _session["seen"].add(idx)

    return jsonify({
        "correct": correct,
        "is_correct": is_correct,
        "net_pct": c["net_pct"],
        "up_pct": c["up_pct"],
        "down_pct": c["down_pct"],
        "future": c["future"],
        "score": {
            "correct": _session["correct"],
            "wrong": _session["wrong"],
            "total": _session["correct"] + _session["wrong"],
        },
    })

@app.route("/api/score")
def score():
    total = _session["correct"] + _session["wrong"]
    pct = round(_session["correct"] / total * 100, 1) if total else 0
    return jsonify({
        "correct": _session["correct"],
        "wrong": _session["wrong"],
        "total": total,
        "accuracy": pct,
        "seen_count": len(_session["seen"]),
    })

@app.route("/api/reset")
def reset():
    _session["correct"] = 0
    _session["wrong"] = 0
    _session["skipped"] = 0
    _session["seen"] = set()
    return jsonify({"status": "reset"})

if __name__ == "__main__":
    get_data()  # pre-load
    print("\n  NAS100 Flashcards ready → http://localhost:5000\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
