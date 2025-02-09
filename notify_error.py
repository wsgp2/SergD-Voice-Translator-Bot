#!/usr/bin/env python3
import os
import sys
import requests
from dotenv import load_dotenv

def send_telegram_message(bot_token, chat_id, message):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=data)
        response.raise_for_status()
    except Exception as e:
        print(f"Error sending telegram message: {e}")

if __name__ == "__main__":
    # Загружаем .env файл
    load_dotenv()
    
    # Получаем токен бота из .env
    bot_token = os.getenv("TELEGRAM_TOKEN")
    
    # ID чата админа (можно получить от @userinfobot)
    admin_chat_id = "-1002480465740"  # Замените на ваш ID
    
    # Формируем сообщение об ошибке
    service_name = sys.argv[1] if len(sys.argv) > 1 else "Unknown service"
    error_message = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "No error message provided"
    
    message = f"""⚠️ <b>Бот упал!</b>

🤖 Сервис: <code>{service_name}</code>
❌ Ошибка: <code>{error_message}</code>

🔄 Пытаюсь перезапуститься...
"""
    
    # Отправляем уведомление
    send_telegram_message(bot_token, admin_chat_id, message)
