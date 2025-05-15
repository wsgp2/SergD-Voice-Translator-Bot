import os
import logging
import asyncio
import shutil
import telegram
import openai
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatType
from telegram.error import BadRequest
from openai import OpenAI
from dotenv import load_dotenv
import tempfile
import json
import re
from google.cloud import texttospeech

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)
logger.info('🚀 Бот запускается...')

# Глобальные флаги
disable_message_deletion = True  # Отключаем удаление сообщений, чтобы избежать повторных отправок

# Инициализация OpenAI
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
google_client = texttospeech.TextToSpeechClient()

# Константы
# Идентификаторы владельца бота
OWNER_USERNAME = "sergei_dyshkant"  # Username владельца бота (case-insensitive)
OWNER_ID = os.getenv('OWNER_ID')  # Числовой ID владельца бота

# Пути к файлам настроек и статистики
SETTINGS_FILE = 'chat_settings.json'
STATS_FILE = 'usage_stats.json'

# Режимы работы бота
MODE_TRANSLATE = "translate"    # Только перевод
MODE_SUMMARIZE = "summarize"    # Только саммаризация
MODE_BOTH = "both"              # И перевод, и саммаризация

LANG_EMOJIS = {
    'ru': '🇷🇺',
    'id': '🇮🇩',
    'en': '🇺🇸'
}

VOICES = {
    'ru': 'shimmer',  # женский голос 👩
    'id': 'nova',     # женский голос 👩
    'en': 'echo'      # мужской голос 👨
}

# Структура настроек по умолчанию для нового чата
DEFAULT_CHAT_SETTINGS = {
    "enabled_languages": ["ru", "en"],  # Языки, для которых активен перевод
    "mode": MODE_TRANSLATE,             # Режим работы бота (по умолчанию - только перевод)
    "tts_enabled": False                # Генерация аудио отключена по умолчанию
}

# Загрузка настроек чатов
def load_chat_settings():
    """Загружает настройки чатов из JSON-файла"""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Ошибка загрузки настроек: {str(e)}", exc_info=True)
        return {}

# Сохранение настроек чатов
def save_chat_settings(settings):
    """Сохраняет настройки чатов в JSON-файл"""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения настроек: {str(e)}", exc_info=True)

# Загрузка статистики использования
def load_usage_stats():
    """Загружает статистику использования из JSON-файла"""
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"users": {}, "chats": {}, "daily_usage": {}}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Ошибка загрузки статистики: {str(e)}", exc_info=True)
        return {"users": {}, "chats": {}, "daily_usage": {}}

# Сохранение статистики использования
def save_usage_stats(stats):
    """Сохраняет статистику использования в JSON-файл"""
    try:
        with open(STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения статистики: {str(e)}", exc_info=True)

# Функция для разделения длинных сообщений
async def send_split_message(context, chat_id, message_text, reply_to_message_id=None, parse_mode=None):
    """Отправляет сообщение, разделяя его на части, если оно слишком длинное с учетом HTML-форматирования"""
    # Максимальная длина сообщения в Telegram
    MAX_MESSAGE_LENGTH = 3000  # Используем значение меньше 4096 для безопасности
    MAX_PART_LENGTH = MAX_MESSAGE_LENGTH - 20  # Учитываем место для маркера части и запас
    
    # Если сообщение меньше максимальной длины, отправляем как есть
    if len(message_text) <= MAX_PART_LENGTH:
        return await context.bot.send_message(
            chat_id=chat_id,
            text=message_text,
            reply_to_message_id=reply_to_message_id,
            parse_mode=parse_mode
        )
    
    # Проверяем, нужно ли обрабатывать HTML-форматирование
    is_html = parse_mode == 'HTML'
    
    # Если сообщение слишком длинное, разделяем его на части
    parts = []
    
    # Для HTML-форматированного текста используем специальную логику разделения
    if is_html:
        logger.info("Обнаружено HTML-форматирование, используем корректное разделение")
        
        # Функция для проверки незакрытых HTML-тегов
        def ensure_html_tags_closed(text):
            # Список распространенных HTML-тегов в Telegram
            common_tags = ['b', 'i', 'code', 'pre', 'a']
            open_tags = []
            
            # Добавляем закрывающие теги, если они отсутствуют
            for tag in common_tags:
                tag_open = f"<{tag}"
                tag_close = f"</{tag}>"
                
                # Подсчитываем количество открывающих и закрывающих тегов
                open_count = text.count(tag_open) - text.count(f"</{tag}>")
                
                # Если есть незакрытые теги, добавляем закрывающие
                if open_count > 0:
                    open_tags.extend([tag] * open_count)
            
            # Закрываем теги в обратном порядке
            closing_tags = ''
            for tag in reversed(open_tags):
                closing_tags += f"</{tag}>"
            
            return text + closing_tags, closing_tags
        
        # Разделяем текст на части с учетом HTML-тегов
        current_position = 0
        while current_position < len(message_text):
            # Берем часть текста максимальной длины
            part = message_text[current_position:current_position + MAX_PART_LENGTH]
            
            # Проверяем, что не разрываем HTML-тег
            last_open_bracket = part.rfind('<')
            last_close_bracket = part.rfind('>')
            
            # Если открывающая скобка находится после закрывающей, то тег разорван
            if last_open_bracket > last_close_bracket:
                # Обрезаем текст до последнего открытого тега
                part = part[:last_open_bracket]
            
            # Проверяем и закрываем незакрытые теги в текущей части
            part_with_closed_tags, closing_tags = ensure_html_tags_closed(part)
            parts.append(part_with_closed_tags)
            
            # Если были добавлены закрывающие теги, нужно добавить открывающие в следующую часть
            opening_tags = ''
            for tag in reversed(open_tags):
                opening_tags += f"<{tag}>"
            
            # Добавляем открывающие теги в начало следующей части
            if current_position + MAX_PART_LENGTH < len(message_text) and opening_tags:
                # Получаем следующую часть и добавляем к ней открывающие теги
                current_position += len(part)
                message_text = message_text[:current_position] + opening_tags + message_text[current_position:]
            else:
                # Переходим к следующей позиции (с учетом длины текущей части без закрывающих тегов)
                current_position += len(part)
    else:
        # Для обычного текста используем простое разделение
        for i in range(0, len(message_text), MAX_PART_LENGTH):
            parts.append(message_text[i:i + MAX_PART_LENGTH])
    
    logger.info(f"Сообщение разделено на {len(parts)} частей с учетом форматирования {parse_mode}")
    
    # Отправляем каждую часть
    sent_messages = []
    first_message = None
    
    for i, part in enumerate(parts):
        part_text = part.strip()
        # Добавляем маркер части только если частей больше одной
        if len(parts) > 1:
            part_text += f"\n\n(Часть {i+1}/{len(parts)})"
        
        try:
            if i == 0:
                # Первую часть отправляем с reply_to_message_id
                msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=part_text,
                    reply_to_message_id=reply_to_message_id,
                    parse_mode=parse_mode
                )
                first_message = msg
            else:
                # Остальные части просто отправляем в тот же чат
                msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=part_text,
                    parse_mode=parse_mode
                )
            sent_messages.append(msg)
        except Exception as e:
            logger.error(f"Ошибка при отправке части {i+1}/{len(parts)}: {e}", exc_info=True)
            # Если часть слишком длинная, пробуем укоротить
            shortened_text = part_text[:MAX_PART_LENGTH//2] + "...\n[\u0421ообщение слишком длинное, часть пропущена]\n..."
            try:
                msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=shortened_text,
                    parse_mode=None  # Отключаем парсинг разметки для безопасности
                )
                sent_messages.append(msg)
                if i == 0 and not first_message:
                    first_message = msg
            except Exception as e2:
                logger.error(f"Не удалось отправить даже укороченное сообщение: {e2}", exc_info=True)
    
    return first_message

# Обновление статистики при использовании бота
def update_usage_stats(user_id, user_name, chat_id, chat_title):
    """Обновляет статистику использования бота"""
    try:
        stats = load_usage_stats()
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Обновляем статистику пользователя
        if str(user_id) not in stats["users"]:
            stats["users"][str(user_id)] = {
                "name": user_name,
                "usage_count": 0,
                "last_used": ""
            }
        
        stats["users"][str(user_id)]["usage_count"] += 1
        stats["users"][str(user_id)]["last_used"] = datetime.now().isoformat()
        
        # Обновляем статистику чата
        if str(chat_id) not in stats["chats"]:
            stats["chats"][str(chat_id)] = {
                "name": chat_title if chat_title else "Личный чат",
                "usage_count": 0
            }
        
        stats["chats"][str(chat_id)]["usage_count"] += 1
        
        # Обновляем дневную статистику
        if today not in stats.get("daily_usage", {}):
            stats["daily_usage"] = stats.get("daily_usage", {})
            stats["daily_usage"][today] = 0
        
        stats["daily_usage"][today] += 1
        
        save_usage_stats(stats)
    except Exception as e:
        logger.error(f"Ошибка обновления статистики: {str(e)}", exc_info=True)

# Получение настроек для конкретного чата
def get_chat_settings(chat_id):
    """Возвращает настройки для конкретного чата, или настройки по умолчанию"""
    settings = load_chat_settings()
    return settings.get(str(chat_id), DEFAULT_CHAT_SETTINGS.copy())

def clean_text(text: str) -> str:
    """Очищает текст от лишних пробелов и знаков препинания"""
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s+([.,!?])', r'\1', text)
    text = re.sub(r'[«»"""]', '"', text)
    return text.strip()

async def transcribe_audio(audio_file_path: str) -> tuple[str, str]:
    """Преобразует аудио в текст используя Whisper API"""
    try:
        logger.info(f"Начинаем транскрибацию файла: {audio_file_path}")
        response = openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=open(audio_file_path, "rb"),
            response_format="verbose_json"
        )
        
        detected_text = response.text
        detected_lang = response.language
        
        logger.info(f"Транскрибация завершена. Язык: {detected_lang}")
        return detected_text, detected_lang
    except openai.RateLimitError as e:
        # Специальная обработка ошибки превышения квоты или лимита запросов
        error_message = str(e)
        if "insufficient_quota" in error_message or "exceeded your current quota" in error_message:
            logger.error(f"❌ Исчерпан лимит API OpenAI: {error_message}", exc_info=True)
            # Добавляем маркер в начало текста ошибки
            error_message = "QUOTA_EXCEEDED: " + error_message
        else:
            # Обычная ошибка превышения скорости запросов
            logger.error(f"❌ Превышен лимит запросов API OpenAI: {error_message}", exc_info=True)
            error_message = "RATE_LIMIT: " + error_message
        # Возвращаем текст ошибки с маркером, чтобы потом обработать ее в handle_voice
        return error_message, ""
    except Exception as e:
        logger.error(f"Ошибка при транскрибации: {str(e)}", exc_info=True)
        raise

async def translate_with_gpt(text: str, source_lang: str, target_languages: list = None) -> dict:
    """Переводит текст используя ChatGPT с учетом целевых языков"""
    translations = {source_lang: clean_text(text)}
    
    # Если целевые языки не указаны, используем все поддерживаемые
    if target_languages is None:
        if source_lang == 'ru':
            target_languages = ['en', 'id']
        elif source_lang == 'id':
            target_languages = ['en', 'ru']
        elif source_lang == 'en':
            target_languages = ['ru', 'id']
    
    try:
        logger.info(f"🔄 Начинаем перевод текста: {text} с языка {source_lang} на языки {target_languages}")
        
        # Формируем промпт для GPT в зависимости от исходного языка и целевых языков
        target_languages_dict = {}
        format_parts = []
        
        for lang in target_languages:
            if lang != source_lang:
                if lang == 'ru':
                    target_languages_dict['russian'] = 'Russian'
                    format_parts.append('"russian": "translation"')
                elif lang == 'en':
                    target_languages_dict['english'] = 'English'
                    format_parts.append('"english": "translation"')
                elif lang == 'id':
                    target_languages_dict['indonesian'] = 'Indonesian'
                    format_parts.append('"indonesian": "translation"')
        
        # Если нет целевых языков, возвращаем только исходный текст
        if not target_languages_dict:
            return translations
            
        # Создаем строку с языками для промпта
        languages_str = ", ".join(target_languages_dict.values())
        format_str = "{" + ", ".join(format_parts) + "}"
        
        source_lang_name = "Russian" if source_lang == 'ru' else "Indonesian" if source_lang == 'id' else "English"
        
        system_prompt = f"""You are a professional translator with expertise in {source_lang_name} and {languages_str}. 
        Your task is to translate the given {source_lang_name} text while:
        1. 🎯 Preserving the original meaning and context
        2. 💫 Using natural, fluent language in the target languages
        3. 🎭 Maintaining the tone and style of the original text
        4. 🔍 Being attentive to cultural nuances
        5. 📚 Using appropriate idioms when applicable
        
        Return translations in this exact JSON format:
        {format_str}"""
        
        user_prompt = f"Translate this text with attention to context and cultural nuances: {text}"

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={ "type": "json_object" }
        )
        
        # Парсим JSON ответ
        result = json.loads(response.choices[0].message.content)
        logger.info(f"Получен перевод: {result}")
        
        # Добавляем переводы в результат
        if 'english' in result and 'en' in target_languages:
            translations['en'] = clean_text(result['english'])
        if 'russian' in result and 'ru' in target_languages:
            translations['ru'] = clean_text(result['russian'])
        if 'indonesian' in result and 'id' in target_languages:
            translations['id'] = clean_text(result['indonesian'])
            
    except Exception as e:
        logger.error(f"Ошибка при переводе: {str(e)}", exc_info=True)
        for lang in target_languages:
            if lang != source_lang and lang not in translations:
                translations[lang] = "Error during translation"
    
    return translations

async def summarize_with_gpt(text: str, lang: str) -> str:
    """Создает структурированное резюме текста с помощью ChatGPT"""
    try:
        logger.info(f"📝 Начинаем создание резюме текста на языке {lang}: {text[:100]}...")
        
        # Улучшенный промпт для структурированной саммаризации с HTML-форматированием для Telegram
        system_prompt = """Ты - эксперт по созданию информативных резюме-инструкций для Telegram. 

Создай структурированное резюме-инструкцию для предоставленного текста, строго соблюдая следующие правила форматирования Telegram HTML:

1. Используй <b>текст</b> для выделения текста жирным шрифтом
2. Используй <i>текст</i> для курсивного начертания
3. Используй <code>текст</code> для моноширинного шрифта (код)
4. Используй <a href="URL">текст</a> для создания ссылок (если есть)
5. Используй <pre>текст</pre> для блоков предформатированного текста
6. Разделяй параграфы и разделы пустой строкой для лучшей читаемости

Структура резюме-инструкции:
1. Начни с краткого введения о сути текста (2-3 предложения)
2. Раздели текст на логические блоки/подзаголовки
3. Используй короткие и емкие фразы
4. Выдели <b>ключевые моменты жирным шрифтом</b>
5. Если упоминаются суммы, условия, даты, действия — приводи конкретику (что за что платится, кто что делает и когда)
6. Обязательно разделяй абзацы пропуском строки для лучшей читаемости
7. Сделай вывод или заключение или план действий в конце, описав дальнейшие действия по плану если они обсуждены

Добавь уместные эмодзи (не более 15 штук) для улучшения восприятия. Используй короткие абзацы, четкие формулировки, избегай перегрузки текста. Оформи текст так, чтобы его было удобно и быстро прочитать, сохраняя все важные детали и последовательность действий. Фокусируйся на практической пользе для читателя."""
        
        user_prompt = f"Создай детальное резюме следующего текста, сохранив все ключевые мысли и идеи: {text}"
        
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        
        summary = response.choices[0].message.content
        logger.info(f"Получено резюме длиной {len(summary)} символов")
        return summary
        
    except Exception as e:
        logger.error(f"Ошибка при создании резюме: {str(e)}", exc_info=True)
        return f"❌ Ошибка при создании резюме: {str(e)}"

async def process_message_content(text: str, source_lang: str, chat_settings: dict, voice_duration: int = 0) -> dict:
    """Обрабатывает текстовое сообщение в соответствии с настройками чата
    
    Args:
        text: текст для обработки
        source_lang: язык исходного текста
        chat_settings: настройки чата
        voice_duration: длительность голосового сообщения в секундах (0 если не голосовое сообщение)
    """
    result = {
        "original": text,
        "translations": {},
        "summary": None,
        "source_lang": source_lang
    }
    
    # Определяем целевые языки на основе настроек чата
    target_languages = chat_settings.get("enabled_languages", ["ru", "en"])
    mode = chat_settings.get("mode", MODE_TRANSLATE)
    
    # Для коротких сообщений (<30 сек) изменяем режим
    original_mode = mode
    if voice_duration > 0 and voice_duration < 30:
        if mode == MODE_BOTH:
            mode = MODE_TRANSLATE
            logger.info(f"Короткое голосовое сообщение ({voice_duration} сек): только перевод без саммаризации")
        elif mode == MODE_SUMMARIZE:
            # Для коротких сообщений в режиме саммаризации ничего не делаем
            logger.info(f"Короткое голосовое сообщение ({voice_duration} сек): в режиме саммаризации игнорируем короткие сообщения")
            # Возвращаем специальный флаг, чтобы бот ничего не делал
            return {
                "original": text,
                "translations": {},
                "summary": None,
                "source_lang": source_lang,
                "ignore": True  # Специальный флаг для игнорирования сообщения
            }
    
    # Выполняем перевод, если это требуется
    if mode in [MODE_TRANSLATE, MODE_BOTH]:
        translations = await translate_with_gpt(text, source_lang, target_languages)
        result["translations"] = translations
    
    # Выполняем саммаризацию, если это требуется
    if mode in [MODE_SUMMARIZE, MODE_BOTH]:
        # Определяем язык для саммаризации
        summary_lang = None
        
        # В режиме только саммаризации используем язык оригинала
        if mode == MODE_SUMMARIZE:
            summary_lang = source_lang
            logger.info(f"Режим только саммаризации: используем язык оригинала {source_lang}")
        # В режиме и перевод, и саммаризация используем целевой язык
        else:
            # Если есть только два языка, выбираем противоположный
            if len(target_languages) == 2:
                summary_lang = target_languages[0] if target_languages[1] == source_lang else target_languages[1]
            # Если язык исходного текста указан в списке, выбираем первый отличный от исходного
            else:
                for lang in target_languages:
                    if lang != source_lang:
                        summary_lang = lang
                        break
            
            # Если не нашли подходящий язык, используем английский или русский
            if not summary_lang or summary_lang == source_lang:
                summary_lang = "en" if source_lang != "en" else "ru"
                
            logger.info(f"Режим перевода и саммаризации: саммаризация будет на языке: {summary_lang}")
        
        # Подготовка текста для саммаризации
        text_to_summarize = text
        
        # Переводим только если нужно саммаризировать на другом языке и это не режим "только саммаризация"
        if summary_lang != source_lang and mode != MODE_SUMMARIZE:
            translations = await translate_with_gpt(text, source_lang, [summary_lang])
            if summary_lang in translations:
                text_to_summarize = translations[summary_lang]
        
        # Теперь выполняем саммаризацию на языке перевода
        summary = await summarize_with_gpt(text_to_summarize, summary_lang)
        result["summary"] = summary
        result["summary_lang"] = summary_lang
    
    return result

async def split_long_message(text: str, max_length: int = 4000) -> list:
    """Разбивает длинные сообщения на части, не превышающие max_length символов"""
    if len(text) <= max_length:
        return [text]
        
    parts = []
    # Находим ближайший к max_length символу перенос строки или пробел
    current_pos = 0
    while current_pos < len(text):
        if current_pos + max_length >= len(text):
            parts.append(text[current_pos:])
            break
            
        # Находим место для разделения
        split_pos = text.rfind('\n', current_pos, current_pos + max_length)
        if split_pos == -1 or split_pos == current_pos:
            split_pos = text.rfind(' ', current_pos, current_pos + max_length)
            
        if split_pos == -1 or split_pos == current_pos:
            # Если не нашли подходящее место для разделения, просто разделяем по max_length
            split_pos = current_pos + max_length
            
        parts.append(text[current_pos:split_pos])
        current_pos = split_pos + 1
        
    return parts

async def safe_delete_message(message, force_delete=False):
    """Безопасно удаляет сообщение, игнорируя ошибки если сообщение не найдено или уже удалено
    
    Параметры:
    message - объект сообщения для удаления
    force_delete - если True, удаляем в любом случае; если False, пропускаем удаление, чтобы избежать дублирования
    """
    # Добавляем глобальный флаг отключения удаления сообщений
    global disable_message_deletion
    
    # Проверяем, надо ли удалять сообщение
    if disable_message_deletion and not force_delete:
        logger.info("Удаление сообщений отключено глобально")
        return False
    
    if message:
        # Проверяем, приватный ли это чат
        is_private_chat = False
        if hasattr(message, 'chat') and message.chat and message.chat.type == ChatType.PRIVATE:
            is_private_chat = True
        
        # Проверяем, является ли это бизнес-сообщением
        is_business = False
        if hasattr(message, 'business_chat_id'):
            is_business = True
        
        # Если это приватный чат или бизнес-чат и не является принудительным удалением
        if (is_private_chat or is_business) and not force_delete:
            logger.info("Не удаляем сообщение в приватном/бизнес чате")
            return False
        
        # Во всех остальных случаях пытаемся удалить
        try:
            await message.delete()
            logger.info("Сообщение успешно удалено")
            return True
        except Exception as e:
            logger.debug(f"Игнорируемая ошибка при удалении сообщения: {e}")
            return False
    return False

async def safe_edit_message(context, processing_msg, text, parse_mode='Markdown'):
    """Безопасно обновляет текст сообщения без удаления и повторной отправки"""
    if not processing_msg or not text:
        logger.warning("Не удалось обновить сообщение: отсутствуют обязательные параметры")
        return False
    
    # Проверяем, приватный ли это чат
    is_private = False
    is_business_message = False
    
    if hasattr(processing_msg, 'chat') and processing_msg.chat and processing_msg.chat.type == ChatType.PRIVATE:
        is_private = True
        logger.debug("Обнаружен приватный чат, используем прямое редактирование")
    
    # Проверяем, является ли это бизнес-сообщением
    if hasattr(processing_msg, 'business_chat_id'):
        is_business_message = True
        logger.debug("Обнаружено бизнес-сообщение")
    
    try:
        # Пытаемся напрямую редактировать сообщение через объект сообщения (как в translator_bot.py)
        if hasattr(processing_msg, 'edit_text'):
            await processing_msg.edit_text(
                text=text.strip(),
                parse_mode=parse_mode
            )
            logger.debug("Сообщение успешно обновлено через edit_text")
            return True
        else:
            # Если нет метода edit_text, используем context.bot
            await context.bot.edit_message_text(
                text=text.strip(),
                chat_id=processing_msg.chat_id,
                message_id=processing_msg.message_id,
                parse_mode=parse_mode
            )
            logger.debug("Сообщение успешно обновлено через context.bot")
            return True
    except telegram.error.BadRequest as br_error:
        # Обрабатываем случай, когда текст не изменился
        if "message is not modified" in str(br_error):
            logger.debug("Текст сообщения не был изменен")
            return True  # Это не ошибка, так как текст уже такой как нужно
        elif "Message to edit not found" in str(br_error) and is_private:
            # В приватных чатах иногда нельзя редактировать сообщения
            logger.info("Невозможно редактировать сообщение в приватном чате: сообщение не найдено")
            # Попробуем отправить новое сообщение
            try:
                if hasattr(processing_msg, 'reply_text'):
                    await processing_msg.reply_text(text.strip(), parse_mode=parse_mode)
                    logger.debug("Отправлено новое сообщение вместо редактирования")
                    return True
            except Exception as reply_error:
                logger.warning(f"Ошибка при отправке нового сообщения: {reply_error}")
        else:
            logger.warning(f"Ошибка при обновлении: {br_error}")
    except Exception as e:
        logger.warning(f"Общая ошибка при обновлении сообщения: {e}")
    
    # Если мы дошли до этой точки, значит все попытки не удались
    return False

async def get_parse_mode_for_mode(mode: str):
    """Возвращает правильный режим парсинга в зависимости от режима работы бота"""
    # В режимах саммаризации используем HTML-форматирование
    if mode in [MODE_SUMMARIZE, MODE_BOTH]:
        return 'HTML'
    # В остальных режимах используем Markdown
    return 'Markdown'

async def safe_send_message(message_obj, text: str, parse_mode: str = None, mode: str = MODE_TRANSLATE):
    """Безопасно отправляет сообщение, разбивая его на части при необходимости"""
    try:
        # Если parse_mode не указан явно, определяем его на основе режима
        if parse_mode is None:
            parse_mode = get_parse_mode_for_mode(mode)
            
        if len(text) <= 4096:
            return await message_obj.reply_text(text, parse_mode=parse_mode)
        else:
            # Разбиваем сообщение на части и отправляем по очереди
            parts = split_long_message(text)
            last_message = None
            for part in parts:
                last_message = await message_obj.reply_text(part, parse_mode=parse_mode)
            return last_message
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения: {str(e)}", exc_info=True)
        # Если не удалось отправить сообщение с форматированием, пробуем без него
        try:
            return await message_obj.reply_text(text)
        except Exception as inner_e:
            logger.error(f"Не удалось отправить даже простое сообщение: {str(inner_e)}", exc_info=True)
            return None

async def generate_audio(text: str, lang: str) -> bytes:
    """Генерирует аудио из текста используя OpenAI TTS или Google TTS для индонезийского языка"""
    try:
        logger.info(f"🔊 Генерируем аудио для текста: {text} на языке {lang}")
        
        # Для индонезийского языка используем Google Cloud TTS
        if lang == 'id':
            input_text = texttospeech.SynthesisInput(text=text)
            
            voice = texttospeech.VoiceSelectionParams(
                language_code='id-ID',
                name='id-ID-Standard-A'
            )
            
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3
            )
            
            response = google_client.synthesize_speech(
                input=input_text,
                voice=voice,
                audio_config=audio_config
            )
            
            return response.audio_content
            
        # Для остальных языков используем OpenAI TTS как раньше
        if lang not in VOICES:
            logger.error(f"❌ Неподдерживаемый язык для TTS: {lang}")
            raise ValueError(f"Unsupported language for TTS: {lang}")
            
        response = openai_client.audio.speech.create(
            model="tts-1",
            voice=VOICES[lang],
            input=text
        )
        return response.content
        
    except Exception as e:
        logger.error(f"❌ Ошибка при генерации аудио: {str(e)}", exc_info=True)
        raise

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        'Привет! Я бот для перевода голосовых сообщений.\n\n'
        'Я автоматически определяю язык (русский или индонезийский) и перевожу:\n'
        'Русский → Индонезийский\n'
        'Индонезийский → Русский\n'
        ' + добавляю перевод на английский\n\n'
        'Просто отправь мне голосовое сообщение!'
    )

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    username = update.effective_user.first_name if update.effective_user else "пользователь"
    start_text = (
        f'👋 Привет, {username}!\n\n'
        'Я голосовой переводчик и саммаризатор. Отправляйте мне голосовые сообщения, а я буду их переводить и/или создавать краткое резюме.\n\n'
        '🔥 Основные возможности:\n'
        '• Перевод голосовых сообщений\n'
        '• Саммаризация длинных сообщений (>30 сек)\n'
        '• Поддержка русского, английского и индонезийского языков\n'
        '• Быстрые команды для переключения режимов\n\n'
        'Для подробной информации отправьте команду /help\n'
        'Для настройки бота используйте /settings'
    )
    
    # Используем безопасную отправку сообщения
    await safe_send_message(update.message, start_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = (
        'Как использовать бота:\n\n'
        '1. Отправьте голосовое сообщение\n'
        '2. Бот определит язык\n'
        '3. Переведет и/или саммаризирует согласно настройкам\n'
        '4. Покажет результат\n\n'
        'Поддерживаемые языки:\n'
        'Русский, Индонезийский, Английский\n\n'
        'Быстрые команды для языков:\n'
        '/settings_langs_ru_en - Русский и Английский\n'
        '/settings_langs_ru_id - Русский и Индонезийский\n'
        '/settings_langs_en_id - Английский и Индонезийский\n\n'
        'Быстрые команды для режимов:\n'
        '/settings_mode_translate - только перевод\n'
        '/settings_mode_summarize - только саммаризация\n'
        '/settings_mode_both - и перевод, и саммаризация\n\n'
        'Дополнительные настройки:\n'
        '/settings - общие настройки бота\n'
        '/tts_on - включить генерацию аудио\n'
        '/tts_off - выключить генерацию аудио\n'
        '/tts on/off - традиционное управление аудио\n\n'
        'Обработка голосовых сообщений:\n'
        '- Короткие (<30 сек): только перевод в режиме "summarize"\n'
        '- Длинные (>30 сек): автоматически добавляется саммаризация\n\n'
        'Настройки:\n'
        '/settings - все настройки бота для текущего чата\n'
        '/languages - настройка языков перевода\n'
        '/tts - включение/выключение озвучки'
    )
    
    # Используем безопасную отправку сообщения
    await safe_send_message(update.message, help_text)

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /settings для настройки бота в чате"""
    user = update.effective_user
    chat = update.effective_chat
    
    if not chat:
        await update.message.reply_text("❌ Эта команда может использоваться только в групповых чатах.")
        return
    
    # Проверяем права администратора для пользователя в чате
    is_admin = False
    if chat.type != ChatType.PRIVATE:
        try:
            chat_member = await context.bot.get_chat_member(chat.id, user.id)
            is_admin = chat_member.status in ['creator', 'administrator']
        except Exception as e:
            logger.error(f"Ошибка при проверке прав администратора: {str(e)}", exc_info=True)
    else:
        # В личных чатах пользователь всегда имеет права администратора
        is_admin = True
    
    # Также проверяем, является ли пользователь владельцем бота
    is_owner = False
    if user.username and user.username.lower() == OWNER_USERNAME.lower():
        is_owner = True
    elif OWNER_ID and str(user.id) == str(OWNER_ID):
        is_owner = True
    
    if not (is_admin or is_owner):
        await update.message.reply_text("❌ У вас нет прав для изменения настроек бота в этом чате.")
        return
    
    # Получаем текущие настройки чата
    settings = load_chat_settings()
    chat_id_str = str(chat.id)
    
    if chat_id_str not in settings:
        settings[chat_id_str] = DEFAULT_CHAT_SETTINGS.copy()
    
    chat_settings = settings[chat_id_str]
    
    # Формируем сообщение с инструкциями по настройке (используем HTML-форматирование)
    message = (
        "⚙️ <b>Настройки бота для этого чата</b>\n\n"
        "Вы можете настроить бота, используя следующие команды:\n\n"
        
        "🔄 <b>Режим работы</b>:\n"
        "/settings_mode_translate - только перевод\n"
        "/settings_mode_summarize - только саммаризация\n"
        "/settings_mode_both - и перевод, и саммаризация\n\n"
        
        "🌐 <b>Языки перевода</b>:\n"
        "/settings_langs_ru_en - Русский и Английский\n"
        "/settings_langs_ru_id - Русский и Индонезийский\n"
        "/settings_langs_en_id - Английский и Индонезийский\n\n"
        
        "🔊 <b>Генерация аудио</b>:\n"
        "/tts_on - включить генерацию аудио\n"
        "/tts_off - выключить генерацию аудио\n\n"
        
        "📊 <b>Статистика</b> (только для владельца):\n"
        "/stats - получить статистику использования бота\n\n"
        
        "🔄 <b>Текущие настройки</b>:\n"
        f"- Языки: {', '.join(chat_settings['enabled_languages'])}\n"
        f"- Режим: {chat_settings['mode']}\n"
        f"- Генерация аудио: {'✅ Включена' if chat_settings['tts_enabled'] else '❌ Выключена'}"
    )
    
    # Определяем объект сообщения для ответа (может быть бизнес-сообщение или обычное)
    message_obj = update.message
    if not message_obj and hasattr(update, 'business_message') and update.business_message:
        message_obj = update.business_message
    
    if not message_obj:
        logger.error("Не удалось найти объект сообщения для ответа")
        return
        
    # Используем безопасную отправку сообщения
    await safe_send_message(message_obj, message, parse_mode='HTML')

async def settings_langs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /settings_langs для настройки языков перевода"""
    user = update.effective_user
    chat = update.effective_chat
    
    # Определяем объект сообщения для ответа (может быть бизнес-сообщение или обычное)
    message_obj = update.message
    if not message_obj and hasattr(update, 'business_message') and update.business_message:
        message_obj = update.business_message
    
    if not message_obj:
        logger.error("Не удалось найти объект сообщения для ответа в settings_langs_command")
        return
        
    if not chat:
        return
    
    # Проверяем права администратора
    is_admin = False
    if chat.type != ChatType.PRIVATE:
        try:
            chat_member = await context.bot.get_chat_member(chat.id, user.id)
            is_admin = chat_member.status in ['creator', 'administrator']
        except Exception as e:
            logger.error(f"Ошибка при проверке прав администратора: {str(e)}", exc_info=True)
    else:
        is_admin = True
    
    # Правильная проверка на владельца бота
    is_owner = False
    if user.username and OWNER_USERNAME and user.username.lower() == OWNER_USERNAME.lower():
        is_owner = True
    elif OWNER_ID and str(user.id) == str(OWNER_ID):
        is_owner = True
    
    if not (is_admin or is_owner):
        await update.message.reply_text("❌ У вас нет прав для изменения настроек бота в этом чате.")
        return
    
    # Получаем текущие настройки
    settings = load_chat_settings()
    chat_id_str = str(chat.id)
    
    if chat_id_str not in settings:
        settings[chat_id_str] = DEFAULT_CHAT_SETTINGS.copy()
    
    # Получаем аргументы команды
    args = context.args
    
    if not args:
        await message_obj.reply_text(
            "❓ Пожалуйста, укажите языки для перевода. Например:\n"
            "`/settings_langs ru en` - для русского и английского\n"
            "Доступные языки: ru (Русский), en (Английский), id (Индонезийский)\n\n"
            "Или используйте быстрые команды:\n"
            "/settings_langs_ru_en - Русский и Английский\n"
            "/settings_langs_ru_id - Русский и Индонезийский\n"
            "/settings_langs_en_id - Английский и Индонезийский"
        )
        return
    
    # Валидация языков
    valid_langs = ["ru", "en", "id"]
    selected_langs = []
    
    for lang in args:
        lang = lang.lower()
        if lang in valid_langs:
            selected_langs.append(lang)
    
    if not selected_langs:
        await message_obj.reply_text(
            "❌ Не указаны корректные языки. Доступные языки:\n"
            "ru (Русский), en (Английский), id (Индонезийский)"
        )
        return
    
    # Обновляем настройки
    settings[chat_id_str]["enabled_languages"] = selected_langs
    save_chat_settings(settings)
    
    await message_obj.reply_text(
        f"✅ Языки перевода успешно обновлены!\n"
        f"Теперь для этого чата будут использоваться следующие языки: {', '.join(selected_langs)}"
    )

async def settings_langs_ru_en_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрая команда для выбора русского и английского языков"""
    # Создаем аргументы вручную и перенаправляем на основную функцию
    context.args = ["ru", "en"]
    await settings_langs_command(update, context)

async def settings_langs_ru_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрая команда для выбора русского и индонезийского языков"""
    # Создаем аргументы вручную и перенаправляем на основную функцию
    context.args = ["ru", "id"]
    await settings_langs_command(update, context)

async def settings_langs_en_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрая команда для выбора английского и индонезийского языков"""
    # Создаем аргументы вручную и перенаправляем на основную функцию
    context.args = ["en", "id"]
    await settings_langs_command(update, context)

async def settings_mode_translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрая команда для включения режима перевода"""
    # Создаем аргументы вручную и перенаправляем на основную функцию
    context.args = ["translate"]
    await settings_mode_command(update, context)

async def settings_mode_summarize_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрая команда для включения режима саммаризации"""
    # Создаем аргументы вручную и перенаправляем на основную функцию
    context.args = ["summarize"]
    await settings_mode_command(update, context)

async def settings_mode_both_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрая команда для включения режима перевода и саммаризации"""
    # Создаем аргументы вручную и перенаправляем на основную функцию
    context.args = ["both"]
    await settings_mode_command(update, context)

# Добавляем обработчики для транслитерированных команд

async def settings_mode_perevod_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Транслитерированная команда для включения режима перевода"""
    context.args = ["translate"]
    await settings_mode_command(update, context)

async def settings_mode_sammarajz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Транслитерированная команда для включения режима саммаризации"""
    context.args = ["summarize"]
    await settings_mode_command(update, context)

async def settings_mode_bof_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Транслитерированная команда для включения режима перевода и саммаризации"""
    context.args = ["both"]
    await settings_mode_command(update, context)

# Быстрые команды для включения/выключения генерации аудио
async def tts_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрая команда для включения генерации аудио"""
    # Создаем аргументы вручную и перенаправляем на основную функцию
    context.args = ["on"]
    await settings_tts_command(update, context)

async def tts_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрая команда для выключения генерации аудио"""
    # Создаем аргументы вручную и перенаправляем на основную функцию
    context.args = ["off"]
    await settings_tts_command(update, context)

async def settings_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /settings_mode для настройки режима работы бота"""
    user = update.effective_user
    chat = update.effective_chat
    
    if not chat:
        return
    
    # Проверяем права администратора
    is_admin = False
    if chat.type != ChatType.PRIVATE:
        try:
            chat_member = await context.bot.get_chat_member(chat.id, user.id)
            is_admin = chat_member.status in ['creator', 'administrator']
        except Exception as e:
            logger.error(f"Ошибка при проверке прав администратора: {str(e)}", exc_info=True)
    else:
        is_admin = True
    
    # Правильная проверка на владельца бота
    is_owner = False
    if user.username and OWNER_USERNAME and user.username.lower() == OWNER_USERNAME.lower():
        is_owner = True
    elif OWNER_ID and str(user.id) == str(OWNER_ID):
        is_owner = True
    
    if not (is_admin or is_owner):
        await update.message.reply_text("❌ У вас нет прав для изменения настроек бота в этом чате.")
        return
    
    # Получаем текущие настройки
    settings = load_chat_settings()
    chat_id_str = str(chat.id)
    
    if chat_id_str not in settings:
        settings[chat_id_str] = DEFAULT_CHAT_SETTINGS.copy()
    
    # Получаем аргументы команды
    args = context.args
    
    if not args:
        await update.message.reply_text(
            "❓ Выберите режим работы бота:\n\n"
            "Доступные режимы:\n"
            "- `translate` - только перевод\n"
            "- `summarize` - только саммаризация\n"
            "- `both` - и перевод, и саммаризация\n\n"
            "Быстрые команды:\n"
            "/settings_mode_translate - только перевод\n"
            "/settings_mode_summarize - только саммаризация\n"
            "/settings_mode_both - и перевод, и саммаризация\n\n"
            "Транслитерация:\n"
            "/settings_mode_perevod - только перевод\n"
            "/settings_mode_sammarajz - только саммаризация\n"
            "/settings_mode_bof - и перевод, и саммаризация"
        )
        return
    
    mode = args[0].lower()
    
    if mode not in [MODE_TRANSLATE, MODE_SUMMARIZE, MODE_BOTH]:
        await update.message.reply_text(
            "❌ Некорректный режим. Доступные режимы:\n"
            "- `translate` - только перевод\n"
            "- `summarize` - только саммаризация\n"
            "- `both` - и перевод, и саммаризация"
        )
        return
    
    # Обновляем настройки
    settings[chat_id_str]["mode"] = mode
    save_chat_settings(settings)
    
    mode_name = {
        MODE_TRANSLATE: "только перевод",
        MODE_SUMMARIZE: "только саммаризация",
        MODE_BOTH: "перевод и саммаризация"
    }
    
    await update.message.reply_text(
        f"✅ Режим работы бота успешно обновлен!\n"
        f"Новый режим: {mode_name.get(mode, mode)}"
    )

async def settings_tts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /settings_tts для включения/выключения генерации аудио"""
    user = update.effective_user
    chat = update.effective_chat
    
    if not chat:
        return
    
    # Проверяем права администратора
    is_admin = False
    if chat.type != ChatType.PRIVATE:
        try:
            chat_member = await context.bot.get_chat_member(chat.id, user.id)
            is_admin = chat_member.status in ['creator', 'administrator']
        except Exception as e:
            logger.error(f"Ошибка при проверке прав администратора: {str(e)}", exc_info=True)
    else:
        is_admin = True
    
    # Правильная проверка на владельца бота
    is_owner = False
    if user.username and OWNER_USERNAME and user.username.lower() == OWNER_USERNAME.lower():
        is_owner = True
    elif OWNER_ID and str(user.id) == str(OWNER_ID):
        is_owner = True
    
    if not (is_admin or is_owner):
        await update.message.reply_text("❌ У вас нет прав для изменения настроек бота в этом чате.")
        return
    
    # Получаем текущие настройки
    settings = load_chat_settings()
    chat_id_str = str(chat.id)
    
    if chat_id_str not in settings:
        settings[chat_id_str] = DEFAULT_CHAT_SETTINGS.copy()
    
    # Получаем аргументы команды
    args = context.args
    
    if not args or args[0].lower() not in ["on", "off"]:
        await update.message.reply_text(
            "❓ Пожалуйста, укажите 'on' для включения или 'off' для выключения генерации аудио.\n"
            "Пример: `/settings_tts on`"
        )
        return
    
    tts_enabled = args[0].lower() == "on"
    
    # Обновляем настройки
    settings[chat_id_str]["tts_enabled"] = tts_enabled
    save_chat_settings(settings)
    
    await update.message.reply_text(
        f"✅ Настройки генерации аудио обновлены!\n"
        f"Генерация аудио: {'✅ Включена' if tts_enabled else '❌ Выключена'}"
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /stats для получения статистики использования бота"""
    user = update.effective_user
    
    # Только владелец бота может получать статистику
    # Проверяем по username и по числовому ID
    is_owner = False
    if user.username and user.username.lower() == OWNER_USERNAME.lower():
        is_owner = True
    elif OWNER_ID and str(user.id) == str(OWNER_ID):
        is_owner = True
    
    if not is_owner:
        await update.message.reply_text("❌ Эта команда доступна только владельцу бота.")
        return
    
    # Загружаем статистику
    stats = load_usage_stats()
    
    # Формируем сообщение со статистикой
    message = generate_stats_message(stats)
    
    await update.message.reply_text(message, parse_mode='Markdown')

def generate_stats_message(stats):
    """Генерирует сообщение со статистикой использования бота"""
    # Общее количество использований
    total_uses = sum(user_data.get("usage_count", 0) for user_data in stats.get("users", {}).values())
    
    # Количество пользователей
    total_users = len(stats.get("users", {}))
    
    # Количество чатов
    total_chats = len(stats.get("chats", {}))
    
    # Топ пользователей
    top_users = sorted(
        [(user_id, data.get("name", "Unknown"), data.get("usage_count", 0)) for user_id, data in stats.get("users", {}).items()],
        key=lambda x: x[2],
        reverse=True
    )[:5]  # Топ 5 пользователей
    
    # Топ чатов
    top_chats = sorted(
        [(chat_id, data.get("name", "Unknown"), data.get("usage_count", 0)) for chat_id, data in stats.get("chats", {}).items()],
        key=lambda x: x[2],
        reverse=True
    )[:5]  # Топ 5 чатов
    
    # Статистика по дням
    daily_stats = stats.get("daily_usage", {})
    recent_days = sorted(list(daily_stats.keys()), reverse=True)[:7]  # Последние 7 дней
    
    # Формируем сообщение
    message = (
        "📊 **Общая статистика**\n"
        f"- Всего использований: {total_uses}\n"
        f"- Всего пользователей: {total_users}\n"
        f"- Всего чатов: {total_chats}\n\n"
        
        "👤 **Топ пользователей**\n"
    )
    
    for i, (user_id, name, count) in enumerate(top_users):
        message += f"{i+1}. {name}: {count} использований\n"
    
    message += "\n💬 **Топ чатов**\n"
    
    for i, (chat_id, name, count) in enumerate(top_chats):
        message += f"{i+1}. {name}: {count} использований\n"
    
    message += "\n📅 **Статистика по дням**\n"
    
    for day in recent_days:
        message += f"- {day}: {daily_stats.get(day, 0)} использований\n"
    
    return message

async def send_daily_stats(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет ежедневную статистику владельцу бота"""
    try:
        stats = load_usage_stats()
        message = generate_stats_message(stats)
        
        # Поиск ID чата владельца
        owner_chat = None
        for chat_id, chat_data in stats.get("chats", {}).items():
            # Предполагаем, что у владельца есть личный чат с ботом
            if not chat_id.startswith("-"):  # Не групповой чат
                try:
                    chat = await context.bot.get_chat(int(chat_id))
                    if chat.type == ChatType.PRIVATE and (chat.username == OWNER_ID or str(chat.id) == OWNER_ID):
                        owner_chat = chat.id
                        break
                except Exception as e:
                    logger.error(f"Ошибка при получении информации о чате: {str(e)}", exc_info=True)
        
        if owner_chat:
            await context.bot.send_message(
                chat_id=owner_chat,
                text=f"📊 **Ежедневная статистика использования бота**\n\n{message}",
                parse_mode='Markdown'
            )
        else:
            logger.error("Не удалось найти чат владельца для отправки статистики")
    except Exception as e:
        logger.error(f"Ошибка при отправке ежедневной статистики: {str(e)}", exc_info=True)

async def handle_alternative_commands(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str, is_business: bool = False) -> bool:
    """Обработчик альтернативных команд с префиксом ">"""
    if not message_text.startswith(">"):
        return False
    
    message = update.business_message if is_business else update.message
    chat_type = message.chat.type if hasattr(message, 'chat') else 'unknown'
    
    # Извлекаем команду без префикса ">" и любые аргументы
    parts = message_text[1:].split()
    command = parts[0].lower()
    args = parts[1:] if len(parts) > 1 else []
    
    # Сохраняем аргументы в контексте, как это делает стандартный обработчик команд
    context.args = args
    
    logger.info(f"🔍 Обнаружена альтернативная команда: >{command} с аргументами: {args} в {chat_type} чате")
    
    # Словарь соответствия альтернативных команд стандартным обработчикам
    command_handlers = {
        "start": start_command,
        "help": help_command,
        "settings": settings_command,
        "languages": settings_langs_command,
        "settings_langs_ru_en": settings_langs_ru_en_command,
        "settings_langs_ru_id": settings_langs_ru_id_command,
        "settings_langs_en_id": settings_langs_en_id_command,
        "mode": settings_mode_command,
        "settings_mode": settings_mode_command,
        "settings_mode_translate": settings_mode_translate_command,
        "settings_mode_summarize": settings_mode_summarize_command,
        "settings_mode_both": settings_mode_both_command,
        "settings_mode_perevod": settings_mode_perevod_command,
        "settings_mode_sammarajz": settings_mode_sammarajz_command, 
        "settings_mode_bof": settings_mode_bof_command,
        "tts": settings_tts_command,
        "tts_on": tts_on_command,
        "tts_off": tts_off_command,
        "stats": stats_command
    }
    
    # Проверяем, есть ли такая команда в словаре
    if command in command_handlers:
        try:
            # Выполняем соответствующую команду
            await command_handlers[command](update, context)
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке альтернативной команды '{command}': {str(e)}", exc_info=True)
            await message.reply_text(f"😔 Произошла ошибка при выполнении команды '{command}'")
            return True
    
    return False

async def handle_business_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Универсальный обработчик для всех типов сообщений"""
    # Проверяем наличие бизнес-сообщения
    if hasattr(update, 'business_message') and update.business_message:
        message = update.business_message
        is_business = True
        chat_type = message.chat.type if hasattr(message, 'chat') else "unknown"
        
        # Проверяем текстовые сообщения для альтернативных команд в приватных чатах
        if hasattr(message, 'text') and message.text and chat_type == ChatType.PRIVATE:
            if await handle_alternative_commands(update, context, message.text, is_business=True):
                return
        
        # Обрабатываем голосовые сообщения
        if message.voice:
            logger.info(f"🎯 Получено бизнес-голосовое сообщение. Тип чата: {chat_type}")
            await handle_voice(update, context, is_business=True, media_type="voice")
        # Обрабатываем аудиофайлы, отправленные как документы
        elif message.document and message.document.mime_type and message.document.mime_type.startswith('audio/'):
            logger.info(f"🎵 Получен аудио-документ (бизнес). Тип чата: {chat_type}, MIME: {message.document.mime_type}")
            await handle_voice(update, context, is_business=True, media_type="document")
        # Обрабатываем аудиофайлы, отправленные с метаданными (music)
        elif message.audio:
            logger.info(f"🎵 Получен аудиофайл с метаданными (бизнес). Тип чата: {chat_type}")
            await handle_voice(update, context, is_business=True, media_type="audio")
    
    # Проверяем наличие обычного сообщения
    elif hasattr(update, 'message') and update.message:
        message = update.message
        chat_type = message.chat.type if hasattr(message, 'chat') else "unknown"
        
        # Проверяем текстовые сообщения для альтернативных команд в приватных чатах
        if hasattr(message, 'text') and message.text and chat_type == ChatType.PRIVATE:
            if await handle_alternative_commands(update, context, message.text, is_business=False):
                return
        
        # Обрабатываем голосовые сообщения
        if message.voice:
            logger.info(f"Получено обычное голосовое сообщение. Тип чата: {chat_type}")
            await handle_voice(update, context, is_business=False, media_type="voice")
        # Обрабатываем аудиофайлы, отправленные как документы
        elif message.document and message.document.mime_type and message.document.mime_type.startswith('audio/'):
            logger.info(f"🎵 Получен аудио-документ. Тип чата: {chat_type}, MIME: {message.document.mime_type}")
            await handle_voice(update, context, is_business=False, media_type="document")
        # Обрабатываем аудиофайлы, отправленные с метаданными (music)
        elif message.audio:
            logger.info(f"🎵 Получен аудиофайл с метаданными. Тип чата: {chat_type}")
            await handle_voice(update, context, is_business=False, media_type="audio")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE, is_business: bool = False, media_type: str = "voice"):
    """Обработка голосовых и аудио сообщений с учетом настроек чата"""
    try:
        # Определяем объект сообщения в зависимости от типа
        message = update.business_message if is_business else update.message
        
        # Проверяем наличие сообщения и правильного медиа контента в зависимости от типа
        if not message:
            return
            
        # Проверяем наличие соответствующего типа медиа
        if media_type == "voice" and not message.voice:
            return
        elif media_type == "document" and not message.document:
            return
        elif media_type == "audio" and not message.audio:
            return
            
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else None
        user_name = message.from_user.full_name if message.from_user else "Unknown"
        is_chat_owner = message.chat.type != ChatType.PRIVATE and message.from_user and message.from_user.id == message.chat.id
        chat_title = message.chat.title if message.chat.title else "Личный чат"
        
        # Обновляем статистику использования
        if user_id:
            update_usage_stats(user_id, user_name, chat_id, chat_title)
        
        # Получаем настройки для текущего чата
        chat_settings = get_chat_settings(chat_id)
        
        # Определяем режим работы и другие параметры
        mode = chat_settings.get("mode", MODE_TRANSLATE)
        tts_enabled = chat_settings.get("tts_enabled", False)
        enabled_languages = chat_settings.get("enabled_languages", ["ru", "en"])
        
        # Проверка длительности аудиосообщения в зависимости от типа
        voice_duration = 0
        if media_type == "voice" and message.voice and hasattr(message.voice, 'duration'):
            voice_duration = message.voice.duration
        elif media_type == "audio" and message.audio and hasattr(message.audio, 'duration'):
            voice_duration = message.audio.duration
        elif media_type == "document":
            # Для документов у нас нет длительности напрямую, устанавливаем значение по умолчанию
            # чтобы обработка шла в любом случае
            voice_duration = 30  # Достаточно для активации функции саммаризации
        
        # Проверка коротких сообщений в режиме саммаризации - просто игнорируем их
        if voice_duration < 30 and mode == MODE_SUMMARIZE:
            logger.info(f"Короткое голосовое сообщение ({voice_duration} сек): в режиме саммаризации игнорируем короткие сообщения")
            # Ранний возврат - не отправляем никаких уведомлений и не выполняем запросы к API
            return
        
        # Автоматическая саммаризация для сообщений длиннее 30 секунд
        if voice_duration > 30:
            if mode == MODE_TRANSLATE:
                # Если был активен только режим перевода, включаем режим с переводом и саммаризацией
                mode = MODE_BOTH
                logger.info(f"Длинное голосовое сообщение ({voice_duration} сек): автоматически добавлена саммаризация")
            # Если режим саммаризации (MODE_SUMMARIZE) или оба режима (MODE_BOTH), оставляем без изменений
        
        # Проверяем, является ли сообщение собственным
        is_owner_message = False
        if user_id:
            if OWNER_ID and str(user_id) == str(OWNER_ID) or user_id and user_id == context.bot.id:
                is_owner_message = True
                
        # Проверяем, не является ли сообщение пересланным
        is_forwarded = hasattr(message, 'forward_date') and message.forward_date is not None
        
        # Всегда отправляем уведомление о начале обработки голосового сообщения
        processing_msg = await message.reply_text("🔄 Обрабатываю голосовое сообщение...")
        
        # Скачиваем аудиофайл в зависимости от его типа
        file_to_download = None
        file_extension = '.ogg'  # По умолчанию
        
        if media_type == "voice":
            file_to_download = await message.voice.get_file()
            file_extension = '.ogg'
        elif media_type == "document":
            file_to_download = await message.document.get_file()
            # Определяем расширение на основе MIME-типа или имени файла
            if message.document.file_name:
                _, ext = os.path.splitext(message.document.file_name)
                if ext:
                    file_extension = ext
        elif media_type == "audio":
            file_to_download = await message.audio.get_file()
            file_extension = '.mp3'  # Обычно аудиофайлы в телеграм это mp3
            if message.audio.file_name:
                _, ext = os.path.splitext(message.audio.file_name)
                if ext:
                    file_extension = ext
        
        if not file_to_download:
            await message.reply_text("❌ Не удалось получить аудиофайл. Попробуйте отправить его как голосовое сообщение.")
            return
        
        # Создаем временный файл для аудио
        with tempfile.NamedTemporaryFile(suffix=file_extension, delete=False) as temp_audio:
            # Скачиваем аудио во временный файл
            await file_to_download.download_to_drive(temp_audio.name)
            logger.info(f"💾 Сохранено голосовое сообщение: {temp_audio.name}")
            
            try:
                # Распознаем речь и определяем язык через Whisper API
                # Распознаем речь и определяем язык через Whisper API
                detected_text, detected_lang = await transcribe_audio(temp_audio.name)
                
                # Проверяем результат на наличие сообщения об ошибке
                if detected_text.startswith("QUOTA_EXCEEDED:"):
                    # Ошибка квоты API
                    await processing_msg.edit_text(
                        "⚠️ <b>Превышен лимит использования API OpenAI</b>\n\n"
                        "Пожалуйста, обратитесь к владельцу бота для пополнения счета API.", 
                        parse_mode="HTML"
                    )
                    return
                elif detected_text.startswith("RATE_LIMIT:"):
                    # Ошибка лимита запросов
                    await processing_msg.edit_text(
                        "⚠️ <b>Слишком много запросов</b>\n\n"
                        "Пожалуйста, попробуйте еще раз через несколько минут.", 
                        parse_mode="HTML"
                    )
                    return
                
                # Если ошибок нет, продолжаем обработку
                logger.info(f"🎯 Распознан текст: {detected_text}, язык: {detected_lang}")
                
                # Проверяем, поддерживается ли исходный язык в настройках чата
                if detected_lang not in enabled_languages:
                    logger.info(f"Язык {detected_lang} не включен в настройках чата {chat_id}")
                    # Добавляем язык в список для этого сообщения
                    temp_languages = enabled_languages.copy()
                    temp_languages.append(detected_lang)
                else:
                    temp_languages = enabled_languages
                
                # Обрабатываем содержимое сообщения в соответствии с настройками
                result = await process_message_content(detected_text, detected_lang, {
                    "enabled_languages": temp_languages, 
                    "mode": mode
                }, voice_duration)
                
                # Создаем сообщение с результатами обработки в зависимости от режима
                result_message = ""
                
                # В режиме саммаризации показываем только результат без исходного текста
                if mode == MODE_SUMMARIZE:
                    if "summary" in result and result["summary"]:
                        result_message = f"{result['summary']}\n\n"
                # В режиме перевода показываем исходный текст и переводы
                elif mode == MODE_TRANSLATE:
                    result_message = f"🎙️ **Исходный текст ({LANG_EMOJIS.get(detected_lang, '')}):**\n{result['original']}\n\n"
                    
                    # Добавляем переводы
                    if "translations" in result and result["translations"]:
                        result_message += "🔄 **Переводы:**\n"
                        for lang, translated_text in result["translations"].items():
                            if lang != detected_lang:
                                result_message += f"{LANG_EMOJIS.get(lang, '')}: {translated_text}\n\n"
                # В комбинированном режиме показываем и переводы, и саммаризацию, но без исходного текста
                elif mode == MODE_BOTH:
                    # Добавляем переводы
                    if "translations" in result and result["translations"]:
                        result_message += "🔄 **Переводы:**\n"
                        for lang, translated_text in result["translations"].items():
                            if lang != detected_lang:
                                result_message += f"{LANG_EMOJIS.get(lang, '')}: {translated_text}\n\n"
                    
                    # Добавляем резюме, если есть
                    if "summary" in result and result["summary"]:
                        result_message += f"{result['summary']}\n\n"
                
                # Проверяем, можно ли модифицировать сообщение
                # Это возможно, если сообщение от владельца бота и не является пересланным
                is_owner_message = False
                if user_id:
                    if OWNER_ID and str(user_id) == str(OWNER_ID) or user_id and user_id == context.bot.id:
                        is_owner_message = True
                        
                # Проверяем, не является ли сообщение пересланным
                is_forwarded = hasattr(message, 'forward_date') and message.forward_date is not None
                
                # Сохраняем голосовое сообщение во временный файл, если требуется для TTS
                voice_copy_path = None
                if tts_enabled:
                    with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as voice_copy:
                        shutil.copy2(temp_audio.name, voice_copy.name)
                        voice_copy_path = voice_copy.name
                
                # Больше не удаляем исходное сообщение
                message_deleted = False
                
                # Флаги для отслеживания состояния сообщений
                message_sent = False
                message_successfully_updated = False  # Флаг для отслеживания успешного обновления сообщения
                
                # Начинаем блок try для обработки отправки результатов
                try:
                    # Проверяем флаг ignore - если он установлен, просто удаляем промежуточное сообщение и завершаем обработку
                    if "ignore" in result and result["ignore"]:
                        logger.info("Игнорируем короткое сообщение в режиме саммаризации")
                        if processing_msg:
                            try:
                                await safe_delete_message(processing_msg)
                            except Exception as e:
                                logger.error(f"Ошибка при удалении сообщения: {e}", exc_info=True)
                        return
                    
                    # Обработка специальных сообщений
                    if "message" in result:
                        # Если есть специальное сообщение (например, о коротком сообщении), просто отвечаем текстом
                        if processing_msg:
                            try:
                                # Используем метод context.bot.edit_message_text вместо processing_msg.edit_text для надежности
                                await context.bot.edit_message_text(
                                    text=result["message"],
                                    chat_id=processing_msg.chat_id,
                                    message_id=processing_msg.message_id,
                                    parse_mode='Markdown'
                                )
                                logger.info(f"Отправлено уведомление: {result['message']}")
                            except Exception as e:
                                logger.error(f"Ошибка при обновлении сообщения: {e}", exc_info=True)
                                # Если не удалось обновить сообщение, пробуем удалить и отправить новое
                                try:
                                    await safe_delete_message(processing_msg)
                                except:
                                    pass
                                await message.reply_text(result["message"], parse_mode='Markdown')
                        else:
                            await message.reply_text(result["message"], parse_mode='Markdown')
                        
                        # Ранний возврат: если это специальное сообщение, прекращаем обработку
                        # и не отправляем текст сообщения
                        return
                    # Проверяем длину итогового сообщения и TTS настройки
                    elif tts_enabled and "message" not in result:
                        # Если сообщение слишком длинное, отправляем голосовое без капшена
                        if len(result_message) > 1024:
                            sent_msg = await context.bot.send_voice(
                                chat_id=chat_id,
                                voice=open(voice_copy_path, 'rb')
                            )
                            
                            # И отдельно отправляем текст разделенным
                            # Только если мы не обновили сообщение ранее (WhatsApp избавляемся от дублей)
                            if not message_successfully_updated:
                                current_parse_mode = 'HTML' if mode in [MODE_SUMMARIZE, MODE_BOTH] else 'Markdown'
                                await send_split_message(
                                    context=context,
                                    chat_id=chat_id,
                                    message_text=result_message.strip(),
                                    reply_to_message_id=sent_msg.message_id,
                                    parse_mode=current_parse_mode
                                )
                        else:
                            # Если текст помещается в капшен, отправляем с ним
                            sent_msg = await context.bot.send_voice(
                                chat_id=chat_id,
                                voice=open(voice_copy_path, 'rb'),
                                caption=result_message.strip(),
                                parse_mode='Markdown'
                            )
                            # Отмечаем, что мы уже отправили сообщение с переводом в капшене
                            message_sent = True
                    # Если не выполнено ни одно из предыдущих условий, просто отправляем текстовый ответ
                    else:
                        # Проверяем длину сообщения - для длинных сразу используем разделение
                        message_length = len(result_message.strip())
                        
                        # Для длинных сообщений (>1000 символов) используем разделение без удаления
                        if message_length > 1000 or 'summary' in result and result['summary']:
                            logger.info(f"Длинное сообщение ({message_length} символов) или режим саммаризации: используем разделение")
                            
                            # Проверяем - если уже есть обновленное сообщение, не удаляем его
                            if processing_msg and not message_deleted and not disable_message_deletion:
                                try:
                                    # Удаляем сообщение о процессе обработки
                                    await safe_delete_message(processing_msg)
                                    message_deleted = True
                                except Exception as e:
                                    logger.warning(f"Не удалось удалить сообщение: {str(e)}")
                            
                            # Определяем режим форматирования в зависимости от режима работы
                            current_parse_mode = 'HTML' if mode in [MODE_SUMMARIZE, MODE_BOTH] else 'Markdown'
                            logger.info(f"Используем режим форматирования: {current_parse_mode} для режима: {mode}")
                            
                            # Отправляем разделенное сообщение
                            await send_split_message(
                                context=context,
                                chat_id=chat_id,
                                message_text=result_message.strip(),
                                reply_to_message_id=message.message_id,
                                parse_mode=current_parse_mode
                            )
                            message_sent = True
                        else:
                            # Для коротких сообщений пробуем редактировать
                            if processing_msg:
                                # Используем безопасную функцию обновления сообщения
                                success = await safe_edit_message(context, processing_msg, result_message.strip())
                                if success:
                                    logger.info("Сообщение успешно обновлено")
                                    message_successfully_updated = True  # Помечаем сообщение как успешно обновленное
                                    
                                    # !!! ВАЖНО !!! Раннее завершение функции при успешном обновлении сообщения
                                    # Это предотвращает дублирование сообщений
                                    
                                    # Удаляем временный файл перед выходом, если он существует
                                    if voice_copy_path and os.path.exists(voice_copy_path):
                                        os.unlink(voice_copy_path)
                                    
                                    # Обрабатываем TTS отдельно
                                    if tts_enabled and mode in [MODE_TRANSLATE, MODE_BOTH]:
                                        # Выбираем язык для озвучки - первый из списка доступных, исключая исходный
                                        target_langs = [lang for lang in enabled_languages if lang != detected_lang]
                                        if target_langs:
                                            target_lang = target_langs[0]
                                            target_text = result["translations"].get(target_lang)
                                            if target_text:
                                                await process_tts_async(target_text, target_lang, chat_id, context, message.message_id)
                                    
                                    # Завершаем функцию, чтобы избежать любых дальнейших действий и дублирования сообщений
                                    return
                                else:
                                    # Если не удалось обновить сообщение, пробуем разные способы восстановления
                                    logger.warning("Не удалось обновить сообщение")
                                    
                                    # Пробуем альтернативный метод обновления сообщения
                                    if not message_successfully_updated and hasattr(processing_msg, 'edit_text'):
                                        try:
                                            await processing_msg.edit_text(
                                                text=result_message.strip(),
                                                parse_mode='Markdown'
                                            )
                                            message_successfully_updated = True
                                            logger.info("Сообщение обновлено резервным способом")
                                        except Exception as edit_error:
                                            logger.warning(f"Ошибка резервного обновления: {edit_error}")
                                    
                                    # Если не удалось обновить сообщение никаким способом, тогда удаляем и отправляем заново
                                    # НО! Для приватных чатов не удаляем сообщения, чтобы избежать дублирования
                                    if not message_successfully_updated:  
                                        # Проверяем, является ли это приватным чатом
                                        is_private_chat = False
                                        if (hasattr(message, 'chat') and message.chat and message.chat.type == ChatType.PRIVATE) or \
                                           (hasattr(processing_msg, 'chat') and processing_msg.chat and processing_msg.chat.type == ChatType.PRIVATE):
                                            is_private_chat = True
                                        
                                        # Проверяем, является ли это бизнес-сообщением
                                        is_business = False
                                        if hasattr(message, 'business_chat_id') or hasattr(processing_msg, 'business_chat_id'):
                                            is_business = True
                                        
                                        # Если это приватный чат или бизнес-сообщение, не пытаемся удалять - просто отправляем новое сообщение
                                        if is_private_chat or is_business:
                                            logger.info("Не удаляем сообщение в приватном/бизнес чате во избежание дублирования")
                                            try:
                                                # Отправляем новое сообщение, но не удаляем предыдущее
                                                await send_split_message(
                                                    context=context,
                                                    chat_id=chat_id,
                                                    message_text=result_message.strip(),
                                                    reply_to_message_id=message.message_id,
                                                    parse_mode='Markdown'
                                                )
                                                message_successfully_updated = True  # Помечаем как обработанное
                                            except Exception as inner_error:
                                                logger.error(f"Не удалось отправить новое сообщение: {inner_error}")
                                        else:
                                            # Для групповых чатов тоже не удаляем сообщения, а просто отправляем новое
                                            logger.info("Для группового чата не удаляем сообщение, отправляем новое")
                                            try:
                                                # Отправляем новое сообщение без удаления предыдущего
                                                await send_split_message(
                                                    context=context,
                                                    chat_id=chat_id,
                                                    message_text=result_message.strip(),
                                                    reply_to_message_id=message.message_id,
                                                    parse_mode='Markdown'
                                                )
                                                message_successfully_updated = True  # Помечаем как обработанное
                                            except Exception as inner_error:
                                                logger.error(f"Не удалось отправить новое сообщение: {inner_error}")
                            else:
                                # Проверяем оба флага. Если сообщение успешно обновлено или отправлено, мы не делаем ничего дополнительного
                                # Исправлено для предотвращения дублирования сообщений
                                if message_successfully_updated:
                                    logger.info(f"Сообщение успешно обновлено ранее, не дублируем")
                                    # Ничего не делаем, сообщение уже обновлено
                                elif message_sent:
                                    logger.info(f"Сообщение уже отправлено ранее, не дублируем")
                                    # Ничего не делаем, сообщение уже отправлено
                                else:
                                    # Только если сообщение не было ни обновлено, ни отправлено - отправляем его
                                    logger.info("Отправляем новое сообщение, так как ранее не было отправлено")
                                    await send_split_message(
                                        context=context,
                                        chat_id=chat_id,
                                        message_text=result_message.strip(),
                                        reply_to_message_id=message.message_id,
                                        parse_mode='Markdown'
                                    )
                                    message_sent = True
                    
                    # Удаляем временный файл если он существует
                    if voice_copy_path and os.path.exists(voice_copy_path):
                        os.unlink(voice_copy_path)
                            
                except Exception as e:
                    logger.error(f"Ошибка при обработке голосового сообщения: {e}", exc_info=True)
                    # В случае ошибки отправляем текстовое сообщение
                    if processing_msg:
                        try:
                            await context.bot.edit_message_text(
                                text=result_message.strip(),
                                chat_id=processing_msg.chat_id,
                                message_id=processing_msg.message_id,
                                parse_mode='Markdown'
                            )
                        except Exception as edit_error:
                            logger.error(f"Ошибка при обновлении сообщения: {edit_error}", exc_info=True)
                            # Если не удалось обновить, пробуем ответить на исходное сообщение
                            await message.reply_text(result_message.strip(), parse_mode='Markdown')
                    else:
                        # Если нет сообщения об обработке, отвечаем на исходное
                        await message.reply_text(result_message.strip(), parse_mode='Markdown')
                else:
                    # Для чужих сообщений - стандартная обработка
                    if is_chat_owner and processing_msg is not None:
                        # Для владельца чата - редактируем сообщение с обработкой, если оно есть
                        try:
                            # Пробуем отредактировать сообщение
                            await context.bot.edit_message_text(
                                text=result_message.strip(),
                                chat_id=processing_msg.chat_id,
                                message_id=processing_msg.message_id,
                                parse_mode='Markdown'
                            )
                        except Exception as e:
                            # Если не получилось (например, сообщение слишком длинное), удаляем сообщение об обработке
                            logger.warning(f"Не удалось отредактировать сообщение: {e}")
                            await safe_delete_message(processing_msg)
                            
                            # И отправляем разделенное сообщение
                            await send_split_message(
                                context=context,
                                chat_id=chat_id,
                                message_text=result_message.strip(),
                                reply_to_message_id=message.message_id,
                                parse_mode='Markdown'
                            )
                    elif processing_msg is None:
                        # Если нет сообщения об обработке (для собственных сообщений), просто отправляем ответ
                        try:
                            await message.reply_text(result_message.strip(), parse_mode='Markdown')
                        except Exception as e:
                            logger.warning(f"Не удалось отправить сообщение: {e}")
                            # Используем функцию разделения для длинных сообщений
                            await send_split_message(
                                context=context,
                                chat_id=chat_id,
                                message_text=result_message.strip(),
                                reply_to_message_id=message.message_id,
                                parse_mode='Markdown'
                            )
                    else:
                        # Если сообщение еще не было отправлено
                        if not message_sent:
                            # Для остальных - отправляем новое сообщение и удаляем сообщение о обработке, если оно есть
                            if processing_msg:
                                await safe_delete_message(processing_msg)
                            
                            # Отправляем сообщение с учетом возможной большой длины
                            try:
                                await message.reply_text(result_message.strip(), parse_mode='Markdown')
                                message_sent = True
                            except Exception as e:
                                logger.warning(f"Не удалось отправить сообщение сразу: {e}")
                                # Если не получилось, используем функцию разделения
                                await send_split_message(
                                    context=context,
                                    chat_id=chat_id,
                                    message_text=result_message.strip(),
                                    reply_to_message_id=message.message_id,
                                    parse_mode='Markdown'
                                )
                                message_sent = True
                        else:
                            # Если сообщение уже было отправлено, просто удаляем сообщение о обработке
                            if processing_msg:
                                await safe_delete_message(processing_msg)
                    
                # Если включена генерация аудио, отправляем озвученный перевод
                if tts_enabled and mode in [MODE_TRANSLATE, MODE_BOTH]:
                    # Выбираем язык для озвучки - первый из списка доступных, исключая исходный
                    target_langs = [lang for lang in enabled_languages if lang != detected_lang]
                    if target_langs:
                        target_lang = target_langs[0]
                        target_text = result["translations"].get(target_lang)
                        
                        if target_text:
                            # Проверяем тип чата, чтобы избежать дублирования в приватных
                            chat_type = message.chat.type if hasattr(message, 'chat') else "unknown"
                            is_private = chat_type == ChatType.PRIVATE
                            
                            # В приватных чатах отправляем дополнительное сообщение только если основной перевод
                            # уже был успешно отправлен или обновлен ранее
                            should_send_notification = not is_private or (is_private and (message_successfully_updated or message_sent))
                            
                            if should_send_notification:
                                await message.reply_text(f"🎤 Отправляю озвученный перевод на {LANG_EMOJIS.get(target_lang, '')}...")
                            else:
                                logger.info(f"Не отправляем дополнительное сообщение об аудио в приватном чате")
                            
                            try:
                                audio_content = await generate_audio(target_text, target_lang)
                                
                                # Сохраняем аудио во временный файл
                                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_tts:
                                    temp_tts.write(audio_content)
                                    logger.info(f"💾 Сохранено аудио перевода: {temp_tts.name}")
                                    # Отправляем аудио перевода
                                    await message.reply_voice(temp_tts.name)
                                    # Удаляем временный файл
                                    os.unlink(temp_tts.name)
                            except Exception as e:
                                logger.error(f"❌ Ошибка при генерации аудио: {str(e)}", exc_info=True)
                                await message.reply_text("😔 Извините, произошла ошибка при создании аудио.")
            finally:
                # Удаляем временный файл с аудио
                os.unlink(temp_audio.name)
                
    except Exception as e:
        logger.error(f"❌ Ошибка при обработке голосового сообщения: {str(e)}", exc_info=True)
        try:
            # Пытаемся отправить ответ через правильный объект сообщения
            error_message = "😔 Извините, произошла ошибка при обработке сообщения."
            if is_business and hasattr(update, 'business_message') and update.business_message:
                await update.business_message.reply_text(error_message)
            elif hasattr(update, 'message') and update.message:
                await update.message.reply_text(error_message)
        except Exception as inner_e:
            logger.error(f"❌ Ошибка при отправке сообщения об ошибке: {str(inner_e)}", exc_info=True)

def main():
    """Запуск бота"""
    # Получаем токены из переменных окружения
    telegram_token = os.getenv('TELEGRAM_TOKEN')
    if not telegram_token:
        logger.error("Не найден токен Telegram бота!")
        return
    
    # Очищаем токен от возможных комментариев (удаляем все после '#')
    if '#' in telegram_token:
        telegram_token = telegram_token.split('#')[0].strip()
        logger.info("Токен был очищен от комментариев")
    
    if not os.getenv('OPENAI_API_KEY'):
        logger.error("Не найден токен OpenAI API!")
        return

    # Создаем приложение
    application = Application.builder().token(telegram_token).build()

    # Добавляем обработчики основных команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    
    # Добавляем обработчики команд настроек
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("languages", settings_langs_command))
    application.add_handler(CommandHandler("settings_langs_ru_en", settings_langs_ru_en_command))
    application.add_handler(CommandHandler("settings_langs_ru_id", settings_langs_ru_id_command))
    application.add_handler(CommandHandler("settings_langs_en_id", settings_langs_en_id_command))
    application.add_handler(CommandHandler("mode", settings_mode_command))
    application.add_handler(CommandHandler("settings_mode", settings_mode_command))
    
    # Добавляем быстрые команды для режимов
    application.add_handler(CommandHandler("settings_mode_translate", settings_mode_translate_command))
    application.add_handler(CommandHandler("settings_mode_summarize", settings_mode_summarize_command))
    application.add_handler(CommandHandler("settings_mode_both", settings_mode_both_command))
    
    # Добавляем транслитерированные команды для режимов
    application.add_handler(CommandHandler("settings_mode_perevod", settings_mode_perevod_command))
    application.add_handler(CommandHandler("settings_mode_sammarajz", settings_mode_sammarajz_command))
    application.add_handler(CommandHandler("settings_mode_bof", settings_mode_bof_command))
    
    # Добавляем команды для управления генерацией аудио
    application.add_handler(CommandHandler("tts", settings_tts_command))
    application.add_handler(CommandHandler("tts_on", tts_on_command))
    application.add_handler(CommandHandler("tts_off", tts_off_command))
    
    # Добавляем обработчик статистики
    application.add_handler(CommandHandler("stats", stats_command))
    
    # Запланированная отправка ежедневной статистики
    # Отправка будет происходить автоматически по расписанию
    
    # Обработка всех сообщений
    # Используем только один универсальный обработчик, как в translator_bot.py
    application.add_handler(MessageHandler(
        filters.ALL,
        handle_business_voice,
        block=False
    ))
    logger.info("Добавлен универсальный обработчик для всех типов сообщений")

    # Запускаем бота
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()