import pika
import json
import random
import threading
import time
from common import MSG_MOVE, MSG_STATE, MSG_RESTART, create_state_message, MAX_PLAYERS, get_snake_color, OBSTACLE_TYPES, FOOD_MOVING, FOOD_GOLDEN
import copy

BOARD_WIDTH = 60   # Enine daha geniş
BOARD_HEIGHT = 40
START_LENGTH = 3
TICK_RATE = 0.04  # saniye, 30 FPS

# Power-up türleri
def random_powerup(snakes, foods, obstacles, portals, powerups):
    POWERUP_TYPES = [
        {"type": "speed", "color": (0, 0, 255)},        # Hızlandırıcı (mavi)
        {"type": "shield", "color": (0, 0, 0)},        # Zırh (siyah)
        {"type": "invisible", "color": (128, 128, 128)}, # Görünmezlik (gri)
        {"type": "reverse", "color": (255, 255, 255)},   # Ters kontrol (beyaz)
    ]
    occupied = set()
    for snake in snakes.values():
        occupied.update(snake)
    occupied.update(foods)
    for obs in obstacles:
        occupied.add(tuple(obs["pos"]))
    for portal in portals:
        occupied.add(portal[0])
        occupied.add(portal[1])
    for p in powerups:
        occupied.add(tuple(p["pos"]))
    while True:
        x, y = random.randint(0, BOARD_WIDTH-1), random.randint(0, BOARD_HEIGHT-1)
        if (x, y) not in occupied:
            ptype = random.choice(POWERUP_TYPES)
            return {"pos": (x, y), "type": ptype["type"]}

def random_food(snakes, foods):
    occupied = set()
    for snake in snakes.values():
        occupied.update(snake)
    occupied.update(foods)
    while True:
        fx, fy = random.randint(0, BOARD_WIDTH-1), random.randint(0, BOARD_HEIGHT-1)
        if (fx, fy) not in occupied:
            return (fx, fy)

def random_golden_food(snakes, foods, obstacles, powerups):
    occupied = set()
    for snake in snakes.values():
        occupied.update(snake)
    occupied.update(foods)
    for obs in obstacles:
        occupied.add(tuple(obs["pos"]))
    for pu in powerups:
        occupied.add(tuple(pu["pos"]))
    while True:
        x, y = random.randint(0, BOARD_WIDTH-1), random.randint(0, BOARD_HEIGHT-1)
        if (x, y) not in occupied:
            return (x, y)

# --- Mermi sistemi ve ilgili alanlar kaldırıldı ---

game_state = {
    "snakes": {},
    "directions": {},
    "food": [(5, 5), (10, 10)],  # 2 yem
    "golden_food": None,         # Altın elma
    "active": {},  # client_id: True/False
    "colors": {},  # client_id: (r, g, b)
    "obstacles": [],  # {"pos": (x, y), "type": "slow"/"poison"}
    "scores": {},    # client_id: skor
    "portals": [],   # portal çiftleri
    "powerups": [],   # power-up listesi
    "active_powerups": {}, # client_id: [{"type": "powerup_type", "tick": timestamp}]
    "moving_food": {"pos": (15, 15)},  # Oyuncudan kaçan yem (başlangıçta sabit konum)
}

def place_obstacles():
    obstacles = []
    for _ in range(3):
        x, y = random.randint(0, BOARD_WIDTH-1), random.randint(0, BOARD_HEIGHT-1)
        obstacles.append({"pos": (x, y), "type": "slow"})
    for _ in range(2):
        x, y = random.randint(0, BOARD_WIDTH-1), random.randint(0, BOARD_HEIGHT-1)
        obstacles.append({"pos": (x, y), "type": "poison"})
    # Gizli duvarlar
    for _ in range(5):
        x, y = random.randint(0, BOARD_WIDTH-1), random.randint(0, BOARD_HEIGHT-1)
        obstacles.append({"pos": (x, y), "type": "hidden_wall"})
    return obstacles

def place_portals():
    occupied = set()
    for snake in game_state["snakes"].values():
        occupied.update(snake)
    occupied.update(game_state["food"])
    min_distance = 5  # Minimum Manhattan mesafesi
    while True:
        a = (random.randint(0, BOARD_WIDTH-1), random.randint(0, BOARD_HEIGHT-1))
        b = (random.randint(0, BOARD_WIDTH-1), random.randint(0, BOARD_HEIGHT-1))
        if a != b and a not in occupied and b not in occupied:
            distance = abs(a[0] - b[0]) + abs(a[1] - b[1])
            if distance >= min_distance:
                return [(a, b)]

def reset_snake(client_id):
    # Maksimum oyuncu kontrolü
    if len(game_state["snakes"]) >= MAX_PLAYERS and client_id not in game_state["snakes"]:
        return  # Yeni oyuncu kabul etme
    x = random.randint(0, BOARD_WIDTH-1)
    y = random.randint(5, BOARD_HEIGHT-1)  # Y koordinatı 5 ve üzeri
    snake = [(x, y)]
    for i in range(1, START_LENGTH):
        snake.append((x, y+i))
    game_state["snakes"][client_id] = snake
    game_state["directions"][client_id] = "UP"
    game_state["active"][client_id] = True
    game_state["colors"][client_id] = get_snake_color(client_id)
    if client_id not in game_state["scores"]:
        game_state["scores"][client_id] = 0
    if client_id not in game_state["active_powerups"]:
        game_state["active_powerups"][client_id] = []
    if len(game_state["snakes"]) == 1:
        game_state["obstacles"] = place_obstacles()  # Sadece ilk oyuncu girince engelleri yerleştir
        game_state["portals"] = place_portals()      # Sadece ilk oyuncu girince portalları yerleştir

# --- Power-up etkisi yardımcıları ---
POWERUP_DURATIONS = {"speed": 10, "shield": 10, "invisible": 10, "reverse": 5}

def has_powerup(cid, ptype):
    now = time.time()
    for p in game_state.get("active_powerups", {}).get(cid, []):
        if p["type"] == ptype and now - p["tick"] < POWERUP_DURATIONS.get(ptype, 10):
            return True
    return False

def get_powerup_timeleft(cid, ptype):
    now = time.time()
    for p in game_state.get("active_powerups", {}).get(cid, []):
        if p["type"] == ptype and now - p["tick"] < POWERUP_DURATIONS.get(ptype, 10):
            return max(0, POWERUP_DURATIONS.get(ptype, 10) - (now - p["tick"]))
    return 0

def clear_expired_powerups():
    now = time.time()
    for cid in list(game_state.get("active_powerups", {})):
        game_state["active_powerups"][cid] = [p for p in game_state["active_powerups"][cid] if now - p["tick"] < POWERUP_DURATIONS.get(p["type"], 10)]
        if not game_state["active_powerups"][cid]:
            del game_state["active_powerups"][cid]

def eliminate_snake(client_id):
    game_state["active"][client_id] = False
    # Elenince power-up'ları temizle
    if "active_powerups" in game_state and client_id in game_state["active_powerups"]:
        del game_state["active_powerups"][client_id]
    # Skoru sıfırla
    if client_id in game_state["scores"]:
        game_state["scores"][client_id] = 0
    # Yılanı haritada tutmaya devam edelim ama hareket etmesin

# --- Oyun döngüsünde power-up etkilerini uygula ---
def game_loop():
    last_state_msg = None
    powerup_spawn_chance = 0.01
    golden_spawn_chance = 0.01  # %1 ihtimal
    max_powerups = 3
    tick_count = 0
    # --- Riskli bölge zamanlaması ---
    # --- danger_zone ile ilgili kodlar kaldırıldı ---
    while True:
        clear_expired_powerups()
        global move_queue
        new_queue = []
        # --- Riskli bölge zamanlaması ---
        now = time.time()
        # --- danger_zone zamanlaması ve state_copy'den danger_zone'u kaldır ---
        for msg in move_queue:
            cid = msg["client_id"]
            direction = msg["direction"]
            if has_powerup(cid, "reverse"):
                OPP = {"UP":"DOWN","DOWN":"UP","LEFT":"RIGHT","RIGHT":"LEFT"}
                direction = OPP.get(direction, direction)
            msg["direction"] = direction
            new_queue.append(msg)
        move_queue = new_queue
        while move_queue:
            msg = move_queue.pop(0)
            client_id = msg["client_id"]
            direction = msg["direction"]
            current_dir = game_state["directions"].get(client_id)
            OPPOSITE_DIRECTIONS = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
            if current_dir and OPPOSITE_DIRECTIONS.get(current_dir) == direction:
                continue
            if client_id in game_state["snakes"]:
                game_state["directions"][client_id] = direction
            else:
                reset_snake(client_id)
        # --- Power-up spawn kontrolü ---
        if len(game_state["powerups"]) < max_powerups and random.random() < powerup_spawn_chance:
            pu = random_powerup(
                game_state["snakes"],
                game_state["food"],
                game_state["obstacles"],
                game_state["portals"],
                game_state["powerups"]
            )
            game_state["powerups"].append(pu)
        # --- Golden apple spawn ---
        if game_state["golden_food"] is None and random.random() < golden_spawn_chance:
            pos = random_golden_food(
                game_state["snakes"],
                game_state["food"],
                game_state["obstacles"],
                game_state["powerups"]
            )
            game_state["golden_food"] = pos
        # --- Kaçan yem hareketi ---
        move_moving_food()
        # 2. Yılanları hareket ettir
        for client_id in list(game_state["snakes"].keys()):
            if has_powerup(client_id, "speed"):
                move_snake(client_id)  # Hızlı: her tick hareket
            else:
                if tick_count % 2 == 0:
                    move_snake(client_id)  # Normal: yavaş
        # 3. State mesajı gönder (görünmezlik etkisi uygula ve kalan süreleri ekle)
        state_copy = copy.deepcopy(game_state)
        state_copy["powerup_timers"] = {}
        for cid in state_copy["snakes"].keys():
            timers = {}
            for ptype in ["speed","shield","invisible","reverse"]:
                tleft = get_powerup_timeleft(cid, ptype)
                if tleft > 0:
                    timers[ptype] = tleft
            if timers:
                state_copy["powerup_timers"][cid] = timers
        for cid in list(state_copy["snakes"].keys()):
            if has_powerup(cid, "invisible"):
                for other in state_copy["snakes"].keys():
                    if other != cid:
                        state_copy["snakes"][other] = state_copy["snakes"].get(other, [])
                state_copy["snakes"][cid] = game_state["snakes"][cid]
        state_copy["golden_food"] = game_state["golden_food"]
        state_msg = create_state_message(state_copy)
        if state_msg != last_state_msg:
            channel.basic_publish(
                exchange='',
                routing_key='snake_state',
                body=state_msg
            )
            last_state_msg = state_msg
        tick_count += 1
        time.sleep(TICK_RATE)

# --- Zırh etkisi: move_snake içinde çarpışma kontrolünde uygula ---
MAX_SNAKE_LENGTH = 10
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
    # --- POWER-UP KONTROLÜ ---
    for pu in list(game_state.get("powerups", [])):
        if new_head == tuple(pu["pos"]):
            if "active_powerups" not in game_state:
                game_state["active_powerups"] = {}
            if client_id not in game_state["active_powerups"]:
                game_state["active_powerups"][client_id] = []
            game_state["active_powerups"][client_id].append({"type": pu["type"], "tick": time.time()})
            game_state["powerups"].remove(pu)
    # --- PORTAL KONTROLÜ ---
    for portal_a, portal_b in game_state.get("portals", []):
        if new_head == portal_a:
            new_head = portal_b
            break
        elif new_head == portal_b:
            new_head = portal_a
            break
    # Engel kontrolü
    for obs in game_state.get("obstacles", []):
        if new_head == tuple(obs["pos"]):
            if obs["type"] == "slow":
                time.sleep(0.2)
            elif obs["type"] == "poison":
                if len(snake) > 1:
                    snake.pop()
            elif obs["type"] in ("wall", "hidden_wall"):
                eliminate_snake(client_id)
                return
            break
    # Çarpışma kontrolü (zırh etkisi ve duvardan geçiş)
    shielded = has_powerup(client_id, "shield")
    out_of_bounds = not (0 <= new_head[0] < BOARD_WIDTH and 0 <= new_head[1] < BOARD_HEIGHT)
    if out_of_bounds:
        if shielded:
            # Zırhı harca, yılanı kurtar ve duvardan geçir
            game_state["active_powerups"][client_id] = [p for p in game_state["active_powerups"][client_id] if p["type"] != "shield"]
            # Karşıdan çıkış (wrap)
            nx, ny = new_head
            if nx < 0:
                nx = BOARD_WIDTH - 1
            elif nx >= BOARD_WIDTH:
                nx = 0
            if ny < 0:
                ny = BOARD_HEIGHT - 1
            elif ny >= BOARD_HEIGHT:
                ny = 0
            new_head = (nx, ny)
        else:
            eliminate_snake(client_id)
            return
    for other_id, other_snake in game_state["snakes"].items():
        if other_id != client_id and new_head in other_snake:
            if shielded:
                game_state["active_powerups"][client_id] = [p for p in game_state["active_powerups"][client_id] if p["type"] != "shield"]
                break
            else:
                eliminate_snake(client_id)
                return
    if new_head in snake:
        if shielded:
            game_state["active_powerups"][client_id] = [p for p in game_state["active_powerups"][client_id] if p["type"] != "shield"]
        else:
            eliminate_snake(client_id)
            return
    # Büyüme kontrolü
    # --- Kaçan yem kontrolü ---
    mf = game_state.get("moving_food")
    if mf and new_head == tuple(mf["pos"]):
        snake.insert(0, new_head)
        # Kaçan yemi yeni rastgele yere taşı
        mf["pos"] = random_food(game_state["snakes"], game_state["food"])
        game_state["scores"][client_id] = game_state["scores"].get(client_id, 0) + 2  # Normalden fazla puan
        return
    # --- Golden apple kontrolü ---
    if game_state.get("golden_food") and new_head == tuple(game_state["golden_food"]):
        snake.insert(0, new_head)
        game_state["golden_food"] = None
        game_state["scores"][client_id] = game_state["scores"].get(client_id, 0) + 5  # Altın elma: +5 puan
        # Uzunluk sınırı uygula
        if len(snake) > MAX_SNAKE_LENGTH:
            snake = snake[:MAX_SNAKE_LENGTH]
        game_state["snakes"][client_id] = snake
        return
    ate_food = False
    for i, food in enumerate(game_state["food"]):
        if new_head == food:
            snake.insert(0, new_head)
            game_state["food"][i] = random_food(game_state["snakes"], game_state["food"])
            ate_food = True
            game_state["scores"][client_id] = game_state["scores"].get(client_id, 0) + 1
            break
    if not ate_food:
        snake.insert(0, new_head)
        snake.pop()
    else:
        snake.insert(0, new_head)
    # Uzunluk sınırı uygula
    if len(snake) > MAX_SNAKE_LENGTH:
        snake = snake[:MAX_SNAKE_LENGTH]
    game_state["snakes"][client_id] = snake

def move_moving_food():
    mf = game_state.get("moving_food")
    if not mf or not mf.get("pos"): return
    fx, fy = mf["pos"]
    snakes = game_state["snakes"]
    if not snakes: return
    min_dist = None
    nearest = None
    for snake in snakes.values():
        if not snake: continue
        hx, hy = snake[0]
        dist = abs(fx - hx) + abs(fy - hy)
        if min_dist is None or dist < min_dist:
            min_dist = dist
            nearest = (hx, hy)
    if nearest is None: return
    # Kaçış yönünü bul (en uzaklaştıran yön)
    best_dirs = []
    best_dist = min_dist
    for dx, dy in [(-1,0),(1,0),(0,-1),(0,1)]:
        nx, ny = fx+dx, fy+dy
        if 0 <= nx < BOARD_WIDTH and 0 <= ny < BOARD_HEIGHT:
            dist = abs(nx - nearest[0]) + abs(ny - nearest[1])
            if dist > best_dist:
                best_dirs = [(nx, ny)]
                best_dist = dist
            elif dist == best_dist:
                best_dirs.append((nx, ny))
    if best_dirs:
        mf["pos"] = random.choice(best_dirs)
    # Eğer hiç uzaklaşamıyorsa yerinde kalır

move_queue = []

# --- Fire mesajı işleme ---
def on_move(ch, method, properties, body):
    msg = json.loads(body)
    if msg.get("type") == MSG_MOVE:
        move_queue.append(msg)
    elif msg.get("type") == MSG_RESTART:
        client_id = msg["client_id"]
        reset_snake(client_id)
    elif msg.get("type") == 'disconnect':
        client_id = msg["client_id"]
        game_state["snakes"].pop(client_id, None)
        game_state["directions"].pop(client_id, None)
        game_state["active"].pop(client_id, None)
        game_state["colors"].pop(client_id, None)
        game_state["scores"].pop(client_id, None)
        if "active_powerups" in game_state:
            game_state["active_powerups"].pop(client_id, None)

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
game_loop() 