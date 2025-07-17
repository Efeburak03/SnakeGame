import pika
import pygame
import threading
import json
from common import MSG_MOVE, MSG_STATE, MSG_RESTART, create_move_message, create_restart_message
import sys
import re
import os

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
                "portals": msg.get("p", []) # Portallar bilgisini ekliyoruz
            }
    consume_channel.basic_consume(queue='snake_state', on_message_callback=callback, auto_ack=True)
    consume_channel.start_consuming()

threading.Thread(target=listen_state, daemon=True).start()

pygame.init()
BOARD_WIDTH = 60
BOARD_HEIGHT = 40
CELL_SIZE = 20
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
                # Elendiyse, herhangi bir tuşa basınca restart isteği gönder
                msg = create_restart_message(CLIENT_ID)
                try:
                    channel.basic_publish(exchange='', routing_key='snake_moves', body=msg)
                except Exception as e:
                    print("RabbitMQ bağlantı hatası:", e)
                # Restart sonrası yönü güncelle (varsayılan)
                current_direction = "UP"
            else:
                new_direction = None
                if event.key == pygame.K_UP:
                    new_direction = "UP"
                elif event.key == pygame.K_DOWN:
                    new_direction = "DOWN"
                elif event.key == pygame.K_LEFT:
                    new_direction = "LEFT"
                elif event.key == pygame.K_RIGHT:
                    new_direction = "RIGHT"
                # Ters yöne dönmeyi engelle
                if new_direction and new_direction != current_direction and not (current_direction and OPPOSITE_DIRECTIONS[current_direction] == new_direction):
                    msg = create_move_message(CLIENT_ID, new_direction)
                    try:
                        channel.basic_publish(exchange='', routing_key='snake_moves', body=msg)
                    except Exception as e:
                        print("RabbitMQ bağlantı hatası:", e)
                    current_direction = new_direction
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
                for x, y in snake:
                    pygame.draw.rect(screen, color, (x*CELL_SIZE, y*CELL_SIZE, CELL_SIZE, CELL_SIZE))
            # Skorları yaz
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
                    grass_img = pygame.transform.scale(grass_img, (CELL_SIZE, CELL_SIZE))
                box_img = None
                box_path = os.path.join("assets", "kutu.png")
                if os.path.exists(box_path):
                    box_img = pygame.image.load(box_path)
                    box_img = pygame.transform.scale(box_img, (CELL_SIZE, CELL_SIZE))
                for obs in game_state["obstacles"]:
                    ox, oy = obs["pos"]
                    ocolor = OBSTACLE_COLORS.get(obs["type"], (128, 128, 128))
                    if obs["type"] == "slow" and grass_img:
                        scale = 1.2
                        size = int(CELL_SIZE * scale)
                        offset = int((size - CELL_SIZE) / 2)
                        big_grass = pygame.transform.scale(grass_img, (size, size))
                        screen.blit(big_grass, (ox*CELL_SIZE - offset, oy*CELL_SIZE - offset))
                    elif obs["type"] == "poison" and box_img:
                        screen.blit(box_img, (ox*CELL_SIZE, oy*CELL_SIZE))
                    else:
                        pygame.draw.rect(screen, ocolor, (ox*CELL_SIZE, oy*CELL_SIZE, CELL_SIZE, CELL_SIZE))
            # --- PORTALLARI ÇİZ ---
            if "portals" in game_state:
                for i, (portal_a, portal_b) in enumerate(game_state["portals"]):
                    # Her iki portalı da aynı renkte (ör: mor) çiz
                    portal_color = (128, 0, 255)
                    pygame.draw.rect(screen, portal_color, (portal_a[0]*CELL_SIZE, portal_a[1]*CELL_SIZE, CELL_SIZE, CELL_SIZE))
                    pygame.draw.rect(screen, portal_color, (portal_b[0]*CELL_SIZE, portal_b[1]*CELL_SIZE, CELL_SIZE, CELL_SIZE))
            # Yemleri çiz
            if "food" in game_state:
                apple_img = None
                apple_path = os.path.join("assets", "elma.png")
                if os.path.exists(apple_path):
                    apple_img = pygame.image.load(apple_path)
                    apple_img = pygame.transform.scale(apple_img, (CELL_SIZE, CELL_SIZE))
                foods = game_state["food"]
                if isinstance(foods, tuple):
                    foods = [foods]
                for fx, fy in foods:
                    if apple_img:
                        screen.blit(apple_img, (fx*CELL_SIZE, fy*CELL_SIZE))
                    else:
                        pygame.draw.rect(screen, (255, 0, 0), (fx*CELL_SIZE, fy*CELL_SIZE, CELL_SIZE, CELL_SIZE))
            # Eğer elendiyse mesaj göster
            if not is_active():
                text = font.render("Elenedin! Devam için tuşa bas", True, (255, 255, 255))
                rect = text.get_rect(center=(BOARD_WIDTH*CELL_SIZE//2, BOARD_HEIGHT*CELL_SIZE//2))
                screen.blit(text, rect)
    pygame.display.flip()
    clock.tick(30)  # FPS = 30 