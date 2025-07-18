import pika
import pygame
import threading
import json
from common import MSG_MOVE, MSG_STATE, MSG_RESTART, create_move_message, create_restart_message
import sys
import re
import os
import time

# Disconnect mesajı için yeni bir sabit ekle
MSG_DISCONNECT = 'disconnect'

def create_disconnect_message(client_id):
    return json.dumps({"type": MSG_DISCONNECT, "client_id": client_id})

CLIENT_ID = input("Client ID girin (ör: client-1): ")
if not re.match(r'^[A-Za-z0-9_-]+$', CLIENT_ID):
    print("Uyarı: Kullanıcı adında Türkçe karakter, boşluk veya özel karakter olmamalı! Sadece harf, rakam, - ve _ kullanın.")

# RabbitMQ bağlantısı
credentials = pika.PlainCredentials('staj2', 'staj2')
connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq.icrontech.com', credentials=credentials))
channel = connection.channel()
channel.queue_declare(queue='snake_moves')
channel.queue_declare(queue='snake_state')

game_state = None
current_direction = None  # Son gönderilen yön

# Elenme zamanı takibi
elimination_time = None

def is_active():
    if game_state and "active" in game_state:
        return game_state["active"].get(CLIENT_ID, True)
    return True

def listen_state():
    import pika
    credentials = pika.PlainCredentials('staj2', 'staj2')
    consume_connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq.icrontech.com', credentials=credentials))
    consume_channel = consume_connection.channel()
    consume_channel.queue_declare(queue='snake_state')
    def callback(ch, method, properties, body):
        global game_state
        msg = json.loads(body)
        if msg.get("t") == MSG_STATE:
            game_state = {
                "snakes": msg["s"],
                "directions": msg["d"],
                "food": msg["f"],
                "active": msg["a"],
                "colors": msg.get("c", {}),
                "obstacles": msg.get("o", []),
                "scores": msg.get("scores", {}),
                "portals": msg.get("p", []),
                "u": msg.get("u", []),
                "powerup_timers": msg.get("powerup_timers", {}),
                "bullet_pickups": msg.get("bullet_pickups", []),
                "active_bullets": msg.get("active_bullets", []),
                "danger_zone": msg.get("danger_zone", None)
            }
    consume_channel.basic_consume(queue='snake_state', on_message_callback=callback, auto_ack=True)
    consume_channel.start_consuming()

threading.Thread(target=listen_state, daemon=True).start()

pygame.init()
BOARD_WIDTH = 60
BOARD_HEIGHT = 40
CELL_SIZE = 20

# --- YILAN SPRITE'LARI YÜKLE ---
snake_sprites = {}
sprite_names = [
    "head_up", "head_down", "head_left", "head_right",
    "tail_up", "tail_down", "tail_left", "tail_right",
    "body_horizontal", "body_vertical",
    "body_topleft", "body_topright", "body_bottomleft", "body_bottomright"
]
for name in sprite_names:
    path = os.path.join("Graphics", f"{name}.png")
    if os.path.exists(path):
        img = pygame.image.load(path)
        img = pygame.transform.scale(img, (CELL_SIZE, CELL_SIZE))
        snake_sprites[name] = img

screen = pygame.display.set_mode((BOARD_WIDTH*CELL_SIZE, BOARD_HEIGHT*CELL_SIZE), pygame.DOUBLEBUF)
clock = pygame.time.Clock()
font = pygame.font.SysFont(None, 36)
# Arka plan görselini yükle ve ölçekle
background_img = None
bg_path = os.path.join("assets", "Background.jpg")
if os.path.exists(bg_path):
    background_img = pygame.image.load(bg_path)
    background_img = pygame.transform.scale(background_img, (BOARD_WIDTH*CELL_SIZE, BOARD_HEIGHT*CELL_SIZE))

# Başlatma ekranı
started = False
while not started:
    screen.fill((0, 0, 0))
    text = font.render("Başlamak için bir tuşa bas", True, (255, 255, 255))
    rect = text.get_rect(center=(BOARD_WIDTH*CELL_SIZE//2, BOARD_HEIGHT*CELL_SIZE//2))
    screen.blit(text, rect)
    pygame.display.flip()
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            # Disconnect mesajı gönder
            msg = create_disconnect_message(CLIENT_ID)
            try:
                channel.basic_publish(exchange='', routing_key='snake_moves', body=msg)
            except Exception as e:
                print("RabbitMQ bağlantı hatası:", e)
            pygame.quit()
            exit()
        elif event.type == pygame.KEYDOWN:
            started = True
            # Oyun başlarken sunucudan yılanın ilk yönünü ve pozisyonunu al
            if game_state and CLIENT_ID in game_state["directions"]:
                current_direction = game_state["directions"][CLIENT_ID]
            else:
                current_direction = "UP"  # Sunucudan gelmezse varsayılan
            # Sunucuya ilk hareket mesajı gönderme gereksiz, çünkü yılan zaten sunucuda başlatılıyor

# Yönlerin terslerini tanımla
OPPOSITE_DIRECTIONS = {
    "UP": "DOWN",
    "DOWN": "UP",
    "LEFT": "RIGHT",
    "RIGHT": "LEFT"
}

# send_message_safe fonksiyonunu ve delivery_mode parametresini kaldır
# Tüm basic_publish çağrılarını doğrudan eski haline getir
while True:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            # Disconnect mesajı gönder
            msg = create_disconnect_message(CLIENT_ID)
            try:
                channel.basic_publish(exchange='', routing_key='snake_moves', body=msg)
            except Exception as e:
                print("RabbitMQ bağlantı hatası:", e)
            pygame.quit()
            sys.exit()
        elif event.type == pygame.KEYDOWN:
            if not is_active():
                now = time.time()
                # Elenme zamanı kaydedilmemişse kaydet
                if elimination_time is None:
                    elimination_time = now
                # 5 saniye geçmediyse hiçbir şey yapma
                elif now - elimination_time < 5:
                    pass  # Bekleme devam ediyor
                else:
                    # 5 saniye geçtiyse restart isteği gönder
                    msg = create_restart_message(CLIENT_ID)
                    try:
                        channel.basic_publish(exchange='', routing_key='snake_moves', body=msg)
                    except Exception as e:
                        print("RabbitMQ bağlantı hatası:", e)
                    # Restart sonrası yönü güncelle (varsayılan)
                    current_direction = "UP"
                    elimination_time = None  # Yeniden başlatınca sıfırla
            else:
                # Yön tuşları
                new_direction = None
                if event.key == pygame.K_UP:
                    new_direction = "UP"
                elif event.key == pygame.K_DOWN:
                    new_direction = "DOWN"
                elif event.key == pygame.K_LEFT:
                    new_direction = "LEFT"
                elif event.key == pygame.K_RIGHT:
                    new_direction = "RIGHT"
                if new_direction and new_direction != current_direction and not (current_direction and OPPOSITE_DIRECTIONS[current_direction] == new_direction):
                    msg = create_move_message(CLIENT_ID, new_direction)
                    try:
                        channel.basic_publish(exchange='', routing_key='snake_moves', body=msg)
                    except Exception as e:
                        print("RabbitMQ bağlantı hatası:", e)
                    current_direction = new_direction
                # Space tuşu
                # if event.key == pygame.K_SPACE:
                #     if game_state and "bullets" in game_state and CLIENT_ID in game_state["bullets"] and game_state["bullets"][CLIENT_ID] > 0:
                #         msg = json.dumps({"type": "fire", "client_id": CLIENT_ID})
                #         try:
                #             channel.basic_publish(exchange='', routing_key='snake_moves', body=msg)
                #         except Exception as e:
                #             print("RabbitMQ bağlantı hatası:", e)
    # Arka planı çiz
    if background_img:
        screen.blit(background_img, (0, 0))
    else:
        screen.fill((0, 0, 0))
    if game_state:
        if game_state and "snakes" in game_state:
            # Yılanları çiz
            for snake_id, snake in game_state["snakes"].items():
                color = (0, 255, 0)  # Varsayılan yeşil
                if "colors" in game_state and snake_id in game_state["colors"]:
                    color = tuple(game_state["colors"][snake_id])
                # --- YILAN KARE İLE ÇİZİM ---
                for x, y in snake:
                    pygame.draw.rect(screen, color, (x*CELL_SIZE, y*CELL_SIZE, CELL_SIZE, CELL_SIZE))
                else:
                    # Yılan yoksa bir şey çizme
                    pass
            # Skorları ve mermi sayılarını yaz
            if "scores" in game_state and game_state["scores"]:
                ids = list(game_state["scores"].keys())
                positions = [
                    (20, 10),  # sol üst
                    (BOARD_WIDTH*CELL_SIZE//2, 10),  # orta üst
                    (BOARD_WIDTH*CELL_SIZE-200, 10)  # sağ üst
                ]
                shown = 0
                for pid in ids:
                    # Sadece aktif oyuncuların skorunu göster
                    if "active" in game_state and not game_state["active"].get(pid, True):
                        continue
                    if shown >= 3:
                        break
                    score = game_state["scores"].get(pid, 0)
                    name = str(pid)
                    text = font.render(f"{name}: {score}", True, (255, 255, 255))
                    rect = text.get_rect()
                    rect.topleft = positions[shown]
                    screen.blit(text, rect)
                    shown += 1
            # Engelleri çiz
            if "obstacles" in game_state:
                from common import OBSTACLE_COLORS
                grass_img = None
                grass_path = os.path.join("assets", "çimen.png")
                if os.path.exists(grass_path):
                    grass_img = pygame.image.load(grass_path)
                    grass_img = pygame.transform.scale(grass_img, (int(CELL_SIZE*1.2), int(CELL_SIZE*1.2)))
                box_img = None
                box_path = os.path.join("assets", "kutu.png")
                if os.path.exists(box_path):
                    box_img = pygame.image.load(box_path)
                    box_img = pygame.transform.scale(box_img, (int(CELL_SIZE*1.5), int(CELL_SIZE*1.5)))
                for obs in game_state["obstacles"]:
                    ox, oy = obs["pos"]
                    otype = obs["type"]
                    # Gizli duvar ise, sadece yılan başına yakınsa çiz
                    if otype == "hidden_wall":
                        show = False
                        for snake in game_state["snakes"].values():
                            if not snake:
                                continue
                            hx, hy = snake[0]
                            if abs(ox - hx) <= 4 and abs(oy - hy) <= 4:
                                show = True
                                break
                        if not show:
                            continue  # Çizme
                    ocolor = OBSTACLE_COLORS.get(otype, (128, 128, 128))
                    if otype == "slow" and grass_img:
                        size = int(CELL_SIZE*1.2)
                        offset = int((size - CELL_SIZE) / 2)
                        screen.blit(grass_img, (ox*CELL_SIZE - offset, oy*CELL_SIZE - offset))
                    elif otype == "poison" and box_img:
                        size = int(CELL_SIZE*1.5)
                        offset = int((size - CELL_SIZE) / 2)
                        screen.blit(box_img, (ox*CELL_SIZE - offset, oy*CELL_SIZE - offset))
                    else:
                        pygame.draw.rect(screen, ocolor, (ox*CELL_SIZE, oy*CELL_SIZE, CELL_SIZE, CELL_SIZE))

            # --- PORTALLARI ÇİZ ---
            if "portals" in game_state:
                portal_img = None
                portal_path = os.path.join("assets", "portal.png")
                if os.path.exists(portal_path):
                    portal_img = pygame.image.load(portal_path)
                    portal_img = pygame.transform.scale(portal_img, (int(CELL_SIZE*1.2), int(CELL_SIZE*1.2)))
                for i, (portal_a, portal_b) in enumerate(game_state["portals"]):
                    if portal_img:
                        size = int(CELL_SIZE*1.2)
                        offset = int((size - CELL_SIZE) / 2)
                        screen.blit(portal_img, (portal_a[0]*CELL_SIZE - offset, portal_a[1]*CELL_SIZE - offset))
                        screen.blit(portal_img, (portal_b[0]*CELL_SIZE - offset, portal_b[1]*CELL_SIZE - offset))
                    else:
                        portal_color = (128, 0, 255)
                        pygame.draw.rect(screen, portal_color, (portal_a[0]*CELL_SIZE, portal_a[1]*CELL_SIZE, CELL_SIZE, CELL_SIZE))
                        pygame.draw.rect(screen, portal_color, (portal_b[0]*CELL_SIZE, portal_b[1]*CELL_SIZE, CELL_SIZE, CELL_SIZE))

            # Yemleri çiz
            if "food" in game_state:
                apple_img = None
                apple_path = os.path.join("assets", "elma.png")
                if os.path.exists(apple_path):
                    apple_img = pygame.image.load(apple_path)
                    apple_img = pygame.transform.scale(apple_img, (int(CELL_SIZE*1.2), int(CELL_SIZE*1.2)))
                foods = game_state["food"]
                if isinstance(foods, tuple):
                    foods = [foods]
                for fx, fy in foods:
                    if apple_img:
                        size = int(CELL_SIZE*1.2)
                        offset = int((size - CELL_SIZE) / 2)
                        screen.blit(apple_img, (fx*CELL_SIZE - offset, fy*CELL_SIZE - offset))
                    else:
                        pygame.draw.rect(screen, (255, 0, 0), (fx*CELL_SIZE, fy*CELL_SIZE, CELL_SIZE, CELL_SIZE))
            # --- Golden apple çiz ---
            if "golden_food" in game_state and game_state["golden_food"]:
                gfx, gfy = game_state["golden_food"]
                center = (gfx*CELL_SIZE + CELL_SIZE//2, gfy*CELL_SIZE + CELL_SIZE//2)
                radius = int(CELL_SIZE*0.5)
                pygame.draw.circle(screen, (255, 215, 0), center, radius)  # Sarı altın elma
            # --- Kaçan yem (moving_food) çiz ---
            if "moving_food" in game_state and game_state["moving_food"] and "pos" in game_state["moving_food"]:
                mfx, mfy = game_state["moving_food"]["pos"]
                center = (mfx*CELL_SIZE + CELL_SIZE//2, mfy*CELL_SIZE + CELL_SIZE//2)
                radius = int(CELL_SIZE*0.45)
                pygame.draw.circle(screen, (255, 0, 0), center, radius)
            # Eğer elendiyse mesaj ve sayaç göster
            if not is_active():
                now = time.time()
                if elimination_time is None:
                    elimination_time = now
                elapsed = now - elimination_time
                if elapsed < 3:
                    kalan = int(3 - elapsed) + 1
                    text = font.render(f"Elenedin! {kalan} sn sonra devam edebilirsin", True, (255, 255, 255))
                else:
                    text = font.render("Devam için tuşa bas", True, (255, 255, 255))
                rect = text.get_rect(center=(BOARD_WIDTH*CELL_SIZE//2, BOARD_HEIGHT*CELL_SIZE//2))
                screen.blit(text, rect)
            # Power-up'ları çiz
            if "u" in game_state:
                for pu in game_state["u"]:
                    x, y = pu["pos"]
                    ptype = pu["type"]
                    if ptype == "speed":
                        color = (0, 0, 255)
                    elif ptype == "shield":
                        color = (0, 0, 0)
                    elif ptype == "invisible":
                        color = (128, 128, 128)
                    elif ptype == "reverse":
                        color = (255, 255, 255)
                    else:
                        color = (200, 200, 200)
                    center = (x*CELL_SIZE + CELL_SIZE//2, y*CELL_SIZE + CELL_SIZE//2)
                    radius = int(CELL_SIZE*0.4)
                    pygame.draw.circle(screen, color, center, radius)
           
            # --- Riskli bölge çiz ---
            # danger_zone ile ilgili kodlar kaldırıldı
    pygame.display.flip()
    clock.tick(30)  # FPS = 30 