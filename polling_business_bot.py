import os
import json
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.constants import ChatType

# Настройка логирования
log_filename = f"telegram_polling_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - 🤖 %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def log_update(update: Update):
    """Подробное логирование update объекта"""
    try:
        logger.info("💬 Новое сообщение получено!")
        
        # Логируем сырые данные
        if hasattr(update, '_raw_data'):
            logger.info(f"🔍 Raw Update Data:\n{json.dumps(update._raw_data, indent=2, ensure_ascii=False)}")
        
        # Логируем информацию о чате
        if update.effective_chat:
            logger.info(f"💬 Chat Info:")
            logger.info(f"- Chat ID: {update.effective_chat.id}")
            logger.info(f"- Chat Type: {update.effective_chat.type}")
            logger.info(f"- Chat Title: {update.effective_chat.title if update.effective_chat.title else 'Нет'}")
            logger.info(f"- Chat Username: {update.effective_chat.username if update.effective_chat.username else 'Нет'}")
        
        # Логируем информацию о пользователе
        if update.effective_user:
            logger.info(f"👤 User Info:")
            logger.info(f"- User ID: {update.effective_user.id}")
            logger.info(f"- Username: {update.effective_user.username if update.effective_user.username else 'Нет'}")
            logger.info(f"- Full Name: {update.effective_user.full_name}")
            logger.info(f"- Is Bot: {update.effective_user.is_bot}")
        
        # Дополнительное логирование для сообщений
        if update.message:
            logger.info("📬 Message Details:")
            logger.info(f"- Message ID: {update.message.message_id}")
            logger.info(f"- Message Type: {'Text' if update.message.text else 'Voice' if update.message.voice else 'Audio' if update.message.audio else 'Неизвестный'}")
            logger.info(f"- Text Content: {update.message.text if update.message.text else 'Нет'}")
            logger.info(f"- Via Bot: {update.message.via_bot.username if update.message.via_bot else 'Нет'}")
            logger.info(f"- Forward From: {update.message.forward_from.full_name if update.message.forward_from else 'Нет'}")
            logger.info(f"- Is Automatic Forward: {update.message.is_automatic_forward}")
            logger.info(f"- Has Protected Content: {update.message.has_protected_content}")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при логировании update: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик обычных сообщений"""
    logger.info("\n🔔 Получено обычное сообщение")
    log_update(update)
    
    try:
        await update.message.reply_text(
            "✅ Обычное сообщение получено!\n"
            f"💬 Chat ID: {update.effective_chat.id}\n"
            f"📝 Message ID: {update.message.message_id}"
        )
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке ответа на обычное сообщение: {e}")

async def handle_business_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик бизнес-сообщений"""
    logger.info("\n🏢 Получено сообщение в приватном чате")
    log_update(update)
    
    try:
        # Проверяем тип сообщения
        message_type = "Неизвестный тип"
        if update.business_message.text:
            message_type = "Текстовое сообщение"
        elif update.business_message.voice:
            message_type = "Голосовое сообщение"
        elif update.business_message.audio:
            message_type = "Аудио файл"
        
        response_text = (
            f"✅ Получено {message_type}!\n"
            f"👤 От пользователя: {update.effective_user.full_name}\n"
            f"💬 Chat ID: {update.effective_chat.id}\n"
            f"📝 Message ID: {update.business_message.message_id}"
        )
        
        # Добавляем информацию о голосовом сообщении
        if update.business_message.voice:
            voice = update.business_message.voice
            response_text += (f"\n🎤 Информация о голосовом сообщении:\n"
                            f"- Длительность: {voice.duration} сек\n"
                            f"- Размер: {voice.file_size} байт\n"
                            f"- File ID: {voice.file_id}")
            
            # Скачиваем голосовой файл
            voice_file = await context.bot.get_file(voice.file_id)
            file_path = f"voice_messages/{update.business_message.message_id}.ogg"
            os.makedirs("voice_messages", exist_ok=True)
            await voice_file.download_to_drive(file_path)
            
            response_text += f"\n✅ Файл сохранен как: {file_path}"
        
        await update.business_message.reply_text(response_text)
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке ответа на сообщение: {e}")

def main():
    """Запуск бота"""
    # Получаем токен
    token = os.getenv('TELEGRAM_TOKEN')
    if not token:
        logger.error("❌ Не найден токен!")
        return

    # Создаем и настраиваем приложение
    application = Application.builder().token(token).build()
    
    # Добавляем обработчики для разных типов сообщений
    application.add_handler(MessageHandler(
        filters.ALL,  # Обрабатываем все сообщения
        handle_business_message,
        block=False
    ))
    
    # Запускаем бота в режиме polling
    logger.info("🚀 Запуск бота в режиме polling...")
    application.run_polling(
        allowed_updates=[
            "message",
            "edited_message",
            "business_connection",
            "business_message",
            "edited_business_message",
            "deleted_business_messages"
        ],
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()
