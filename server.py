import pika
import json
import random
import threading
import time
from common import MSG_MOVE, MSG_STATE, MSG_RESTART, create_state_message, MAX_PLAYERS, get_snake_color, OBSTACLE_TYPES

BOARD_WIDTH = 60   # Enine daha geniş
BOARD_HEIGHT = 40
START_LENGTH = 3
TICK_RATE = 0.07  # saniye, 30 FPS

def random_food(snakes, foods):
    occupied = set()
    for snake in snakes.values():
        occupied.update(snake)
    occupied.update(foods)
    while True:
        fx, fy = random.randint(0, BOARD_WIDTH-1), random.randint(0, BOARD_HEIGHT-1)
        if (fx, fy) not in occupied:
            return (fx, fy)

game_state = {
    "snakes": {},
    "directions": {},
    "food": [(5, 5), (10, 10)],  # 2 yem
    "active": {},  # client_id: True/False
    "colors": {},  # client_id: (r, g, b)
    "obstacles": [],  # {"pos": (x, y), "type": "slow"/"poison"}
    "scores": {}    # client_id: skor
}

def place_obstacles():
    obstacles = []
    for _ in range(3):  # 3 yavaşlatıcı engel
        x, y = random.randint(0, BOARD_WIDTH-1), random.randint(0, BOARD_HEIGHT-1)
        obstacles.append({"pos": (x, y), "type": "slow"})
    for _ in range(2):  # 2 zehirli engel
        x, y = random.randint(0, BOARD_WIDTH-1), random.randint(0, BOARD_HEIGHT-1)
        obstacles.append({"pos": (x, y), "type": "poison"})
    return obstacles

def reset_snake(client_id):
    # Maksimum oyuncu kontrolü
    if len(game_state["snakes"]) >= MAX_PLAYERS and client_id not in game_state["snakes"]:
        return  # Yeni oyuncu kabul etme
    x, y = random.randint(0, BOARD_WIDTH-1), random.randint(0, BOARD_HEIGHT-1)
    snake = [(x, y)]
    for i in range(1, START_LENGTH):
        snake.append((x, y+i))
    game_state["snakes"][client_id] = snake
    game_state["directions"][client_id] = "UP"
    game_state["active"][client_id] = True
    game_state["colors"][client_id] = get_snake_color(client_id)
    if client_id not in game_state["scores"]:
        game_state["scores"][client_id] = 0
    if len(game_state["snakes"]) == 1:
        game_state["obstacles"] = place_obstacles()  # Sadece ilk oyuncu girince engelleri yerleştir

def eliminate_snake(client_id):
    game_state["active"][client_id] = False
    # Yılanı haritada tutmaya devam edelim ama hareket etmesin

def move_snake(client_id):
    if not game_state["active"].get(client_id, True):
        return
    snake = game_state["snakes"].get(client_id)
    direction = game_state["directions"].get(client_id, "UP")
    if not snake:
        reset_snake(client_id)
        snake = game_state["snakes"][client_id]
    head_x, head_y = snake[0]
    if direction == "UP":
        head_y -= 1
    elif direction == "DOWN":
        head_y += 1
    elif direction == "LEFT":
        head_x -= 1
    elif direction == "RIGHT":
        head_x += 1
    new_head = (head_x, head_y)
    # Engel kontrolü
    for obs in game_state.get("obstacles", []):
        if new_head == tuple(obs["pos"]):
            if obs["type"] == "slow":
                time.sleep(0.2)  # Yılanı yavaşlat
            elif obs["type"] == "poison":
                if len(snake) > 1:
                    snake.pop()  # Yılanı kısalt
            break
    # Çarpışma kontrolü
    if not (0 <= head_x < BOARD_WIDTH and 0 <= head_y < BOARD_HEIGHT):
        eliminate_snake(client_id)
        return
    for other_id, other_snake in game_state["snakes"].items():
        if other_id != client_id and new_head in other_snake:
            eliminate_snake(client_id)
            return
    if new_head in snake:
        eliminate_snake(client_id)
        return
    # Büyüme kontrolü
    ate_food = False
    for i, food in enumerate(game_state["food"]):
        if new_head == food:
            snake.insert(0, new_head)
            # Yeni yem üret
            game_state["food"][i] = random_food(game_state["snakes"], game_state["food"])
            ate_food = True
            # Skoru artır
            game_state["scores"][client_id] = game_state["scores"].get(client_id, 0) + 1
            break
    if not ate_food:
        snake.insert(0, new_head)
        snake.pop()
    game_state["snakes"][client_id] = snake

def on_move(ch, method, properties, body):
    msg = json.loads(body)
    if msg.get("type") == MSG_MOVE:
        client_id = msg["client_id"]
        # Maksimum oyuncu kontrolü
        if len(game_state["snakes"]) >= MAX_PLAYERS and client_id not in game_state["snakes"]:
            return  # Yeni oyuncu kabul etme
        direction = msg["direction"]
        # Sadece yönü güncelle
        if client_id in game_state["snakes"]:
            game_state["directions"][client_id] = direction
        else:
            reset_snake(client_id)
            game_state["directions"][client_id] = direction
    elif msg.get("type") == MSG_RESTART:
        client_id = msg["client_id"]
        reset_snake(client_id)
    elif msg.get("type") == 'disconnect':
        client_id = msg["client_id"]
        # Tüm verileri sil
        game_state["snakes"].pop(client_id, None)
        game_state["directions"].pop(client_id, None)
        game_state["active"].pop(client_id, None)
        game_state["colors"].pop(client_id, None)
        game_state["scores"].pop(client_id, None)

def rabbitmq_consume():
    credentials = pika.PlainCredentials('staj2', 'staj2')
    consume_connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq.icrontech.com', credentials=credentials))
    consume_channel = consume_connection.channel()
    consume_channel.queue_declare(queue='snake_moves')
    consume_channel.basic_consume(queue='snake_moves', on_message_callback=on_move, auto_ack=True)
    consume_channel.start_consuming()

# Ana thread için connection/channel
credentials = pika.PlainCredentials('staj2', 'staj2')
connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq.icrontech.com', credentials=credentials))
channel = connection.channel()
channel.queue_declare(queue='snake_moves')
channel.queue_declare(queue='snake_state')

print(' [*] Game server started. Ticking...')

# RabbitMQ dinleyici thread'i
threading.Thread(target=rabbitmq_consume, daemon=True).start()

# Oyun döngüsü
def game_loop():
    last_state_msg = None
    while True:
        for client_id in list(game_state["snakes"].keys()):
            move_snake(client_id)
        # Her tick'te yeni durumu yayınla (aktiflik bilgisiyle birlikte)
        state_msg = create_state_message(game_state)
        if state_msg != last_state_msg:
            channel.basic_publish(
                exchange='',
                routing_key='snake_state',
                body=state_msg
            )
            last_state_msg = state_msg
        time.sleep(TICK_RATE)

game_loop() 