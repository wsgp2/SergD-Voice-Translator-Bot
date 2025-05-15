from telegram import Update, Message
from utils.text_splitter import ensure_telegram_limits
import logging

logger = logging.getLogger(__name__)

async def send_bot_response(message: Message, text: str, parse_mode=None) -> list:
    """
    Отправляет ответ пользователю с учетом ограничений Telegram.
    
    Args:
        message: Объект сообщения Telegram
        text: Текст для отправки
        parse_mode: Режим форматирования (HTML, Markdown)
    
    Returns:
        Список отправленных сообщений
    """
    # Проверяем длину сообщения и разделяем при необходимости
    parts = ensure_telegram_limits(text)
    
    sent_messages = []
    for i, part in enumerate(parts):
        try:
            if i == 0:
                sent_message = await message.reply(
                    part,
                    parse_mode=parse_mode
                )
            else:
                sent_message = await message.reply(
                    part,
                    parse_mode=parse_mode
                )
            sent_messages.append(sent_message)
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения: {str(e)}", exc_info=True)
            # Пробуем отправить без форматирования, если была ошибка
            if parse_mode:
                try:
                    sent_message = await message.reply(
                        part,
                        parse_mode=None
                    )
                    sent_messages.append(sent_message)
                    logger.info("Сообщение отправлено без форматирования из-за ошибки")
                except Exception as e2:
                    logger.error(f"Невозможно отправить сообщение даже без форматирования: {str(e2)}", exc_info=True)
    
    return sent_messages
