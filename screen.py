import pika
import pygame
import threading
import json
from common import MSG_STATE

game_state = None

# RabbitMQ bağlantısı
connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = connection.channel()
channel.queue_declare(queue='snake_state')

def listen_state():
    def callback(ch, method, properties, body):
        global game_state
        msg = json.loads(body)
        if msg.get("t") == MSG_STATE:
            game_state = {
                "snakes": msg["s"],
                "directions": msg["d"],
                "food": msg["f"],
                "active": msg["a"]
            }
    channel.basic_consume(queue='snake_state', on_message_callback=callback, auto_ack=True)
    channel.start_consuming()

threading.Thread(target=listen_state, daemon=True).start()

pygame.init()
screen = pygame.display.set_mode((600, 600), pygame.DOUBLEBUF)
clock = pygame.time.Clock()

while True:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            pygame.quit()
            exit()
    screen.fill((0, 0, 0))
    if game_state:
        for snake in game_state["snakes"].values():
            for x, y in snake:
                pygame.draw.rect(screen, (0, 255, 0), (x*20, y*20, 20, 20))
        fx, fy = game_state["food"]
        pygame.draw.rect(screen, (255, 0, 0), (fx*20, fy*20, 20, 20))
    pygame.display.flip()
    clock.tick(30)  # FPS = 30 