# common.py
# Ortak sabitler, mesaj tipleri ve yardımcı fonksiyonlar
import json

# Mesaj tipleri
MSG_MOVE = "move"
MSG_STATE = "state"
MSG_RESTART = "restart"  # yeni eklendi

# Yönler
UP = "UP"
DOWN = "DOWN"
LEFT = "LEFT"
RIGHT = "RIGHT"

# Mesaj oluşturucu örnekleri
def create_move_message(client_id, direction):
    return json.dumps({
        "type": MSG_MOVE,
        "client_id": client_id,
        "direction": direction
    })

def create_state_message(game_state):
    return json.dumps({
        "t": MSG_STATE,
        "s": game_state["snakes"],
        "d": game_state["directions"],
        "f": game_state["food"],  # food artık bir liste
        "a": game_state["active"],
        "c": game_state["colors"],
        "o": game_state["obstacles"],
        "scores": game_state["scores"],
        "p": game_state.get("portals", [])  # <-- PORTALLARI EKLE
    })

def create_restart_message(client_id):
    return json.dumps({
        "type": MSG_RESTART,
        "client_id": client_id
    })

SNAKE_COLORS = [(0, 255, 0), (0, 0, 255), (255, 140, 0)]  # yeşil, mavi, turuncu
MAX_PLAYERS = 3

def get_snake_color(client_id):
    # client_id stringinden bir sayı elde et, ör: 'client-1' -> 0
    try:
        idx = int(str(client_id).split('-')[-1]) - 1
    except Exception:
        idx = 0
    return SNAKE_COLORS[idx % len(SNAKE_COLORS)]

OBSTACLE_TYPES = ["slow", "poison"]
OBSTACLE_COLORS = {
    "slow": (0, 255, 255),    # Açık mavi
    "poison": (128, 0, 128)  # Mor
} 