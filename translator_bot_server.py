import os
import logging
import asyncio
import shutil
import sys
from types import ModuleType

"""
Монки-патч для решения проблемы с библиотекой python-telegram-bot версии 22+
Проблема: не хватает функций de_json_optional, de_list_optional, parse_sequence_arg
в модуле telegram._utils.argumentparsing
"""

# Создаем фейковые функции, которых не хватает
def de_json_optional(data, cls=None, bot=None):
    """Monkey patch для de_json_optional
    
    Args:
        data: JSON данные
        cls: Класс для десериализации
        bot: Экземпляр бота
    """
    if data is None:
        return None
    if cls is None:
        return data
    return cls.de_json(data, bot)

def de_list_optional(data, cls, bot=None):
    """Monkey patch для de_list_optional"""
    if data is None:
        return None
    return [cls.de_json(d, bot) for d in data]

def parse_sequence_arg(arg):
    """Monkey patch для parse_sequence_arg"""
    if arg is None:
        return ()
    if isinstance(arg, (list, tuple, set)):
        return tuple(arg)
    return (arg,)

def de_json_decrypted_optional(data, cls=None, bot=None):
    """Monkey patch для de_json_decrypted_optional"""
    if data is None:
        return None
    if cls is None:
        return data
    return cls.de_json_decrypted(data, bot)

def de_list_decrypted_optional(data, cls, bot=None):
    """Monkey patch для de_list_decrypted_optional"""
    if data is None:
        return None
    return [cls.de_json_decrypted(d, bot) for d in data]
    
def none_or(value, default):
    """Monkey patch для none_or"""
    return default if value is None else value

def parse_lpo_and_dwpp(limit=None, parse_order=None, disable_web_page_preview=None, link_preview_options=None):
    """Monkey patch для parse_lpo_and_dwpp"""
    # Совместимость с устаревшим и новым API
    result = {}
    if disable_web_page_preview is not None or link_preview_options is not None:
        result['link_preview_options'] = link_preview_options or {'is_disabled': bool(disable_web_page_preview)}

    if limit is not None:
        result['limit'] = limit

    if parse_order is not None:
        result['parse_order'] = bool(parse_order)
        
    return result

# Создаем фейковый модуль с нужными функциями
module = ModuleType('telegram._utils.argumentparsing')
module.de_json_optional = de_json_optional
module.de_list_optional = de_list_optional
module.parse_sequence_arg = parse_sequence_arg
module.de_json_decrypted_optional = de_json_decrypted_optional
module.de_list_decrypted_optional = de_list_decrypted_optional
module.none_or = none_or
module.parse_lpo_and_dwpp = parse_lpo_and_dwpp

# Добавляем фейковый модуль в sys.modules
# Это сделает его доступным при импорте
sys.modules['telegram._utils.argumentparsing'] = module
print("🔧 Монки-патч для python-telegram-bot установлен")

import telegram
import openai
import os
import sys
import time
import uuid
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
from utils.text_splitter import ensure_telegram_limits

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
    "ru": "🇷🇺",
    "en": "🇬🇧",
    "id": "🇮🇩",
    "russian": "🇷🇺",
    "english": "🇬🇧",
    "indonesian": "🇮🇩",
}

LANG_NORMALIZE = {
    "ru": "ru",
    "en": "en",
    "id": "id",
    "russian": "ru",
    "english": "en",
    "indonesian": "id",
}

def normalize_lang_code(lang_code):
    """Нормализует код языка к стандартному формату (ru, en, id)"""
    if lang_code in LANG_NORMALIZE:
        return LANG_NORMALIZE[lang_code]
    return lang_code

VOICES = {
    'ru': 'onyx',
    'id': 'onyx',
    'en': 'onyx'
}

# Инструкции для gpt-4o-mini-tts по языкам
TTS_INSTRUCTIONS = {
    'ru': 'Speak clearly in Russian with native pronunciation.',
    'id': 'Speak clearly in Indonesian (Bahasa Indonesia) with native pronunciation.',
    'en': 'Speak clearly in English with native pronunciation.',
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

def normalize_text_spacing(text: str) -> str:
    """Нормализует пробелы и переносы строк в тексте для улучшения читаемости в Telegram.
    - Убирает множественные пустые строки (больше двух переносов подряд)
    - Нормализует форматирование сообщений
    """
    if not text:
        return ""
        
    # Заменяем последовательности из трех и более переносов строк на двойной перенос
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
    
    # Удаляем пробелы в начале и конце строк
    lines = text.split('\n')
    cleaned_lines = [line.strip() for line in lines]
    text = '\n'.join(cleaned_lines)
    
    # Убираем пробелы перед знаками пунктуации
    text = re.sub(r'\s+([,.!?:;])', r'\1', text)
    
    return text.strip()

def detect_language(text: str) -> str:
    """Определяет язык текста по символам (быстрая эвристика без API)"""
    if not text:
        return 'en'
    # Считаем символы разных алфавитов
    cyrillic = sum(1 for c in text if 'Ѐ' <= c <= 'ӿ')
    latin = sum(1 for c in text if 'a' <= c.lower() <= 'z')
    total = len(text.replace(' ', ''))
    if total == 0:
        return 'en'
    # Если > 30% кириллица — русский
    if cyrillic / total > 0.3:
        return 'russian'
    # Индонезийский vs английский — проверяем характерные слова
    indo_markers = ['yang', 'dan', 'untuk', 'dengan', 'dari', 'ini', 'itu', 'ada', 'tidak', 'akan', 'bisa', 'kami', 'saya', 'sudah', 'juga', 'atau']
    lower_text = text.lower()
    indo_score = sum(1 for w in indo_markers if f' {w} ' in f' {lower_text} ')
    if indo_score >= 2:
        return 'indonesian'
    return 'english'

async def transcribe_audio(audio_file_path: str) -> tuple[str, str]:
    """Преобразует аудио в текст используя gpt-4o-transcribe + определение языка"""
    try:
        logger.info(f"Начинаем транскрибацию файла: {audio_file_path}")
        with open(audio_file_path, "rb") as f:
            response = openai_client.audio.transcriptions.create(
                model="gpt-4o-transcribe",
                file=f,
            )
        
        detected_text = response.text
        
        # gpt-4o-transcribe не возвращает язык — определяем из текста и нормализуем
        detected_lang = normalize_lang_code(detect_language(detected_text))
        
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
    translations = {}  # Не добавляем исходный текст в словарь переводов
    
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
            model="gpt-5.4-mini",
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
        system_prompt = """Ты — эксперт по созданию кратких и структурированных резюме-инструкций для Telegram.
Создай резюме по предоставленному тексту, строго соблюдая правила ниже.

ФОРМАТИРОВАНИЕ (Telegram HTML):
1. Используй <b>текст</b> для выделения текста жирным шрифтом
2. Используй <i>текст</i> для курсивного начертания
3. Используй <code>текст</code> для моноширинного шрифта (код)
4. Используй <a href="URL">текст</a> для создания ссылок (если есть)
5. Используй <pre>текст</pre> для блоков предформатированного текста

ОФОРМЛЕНИЕ ТЕКСТА:
• Разделяй абзацы ОДНОЙ пустой строкой
• Не вставляй два и более переносов строки подряд
• Не добавляй отступы или пробелы перед пунктами списка
• Не оставляй лишних пустых строк между заголовками и абзацами

СПИСКИ:
• Используй простой маркированный список
• Каждый пункт начинай с «- » (тире и пробел)
• Пример:
- Первый пункт
- Второй пункт
- Третий пункт

ЭМОДЗИ:
• Добавь один уместный эмодзи в конце заголовка
• Не добавляй эмодзи в конце резюме или абзацев без смысла
• Вставляй эмодзи по смыслу внутрь текста, рядом с ключевыми словами, чтобы визуально акцентировать важные моменты
• Не перебарщивай: 1 эмодзи на абзац или ключевую мысль достаточно
• Эмодзи должны усиливать сообщение, а не просто украшать

СТРУКТУРА РЕЗЮМЕ:
1. Краткое введение (1–3 предложения)
2. Логические блоки с подзаголовками
3. Емкие списки и абзацы
4. Выделяй <b>ключевые идеи жирным</b>
5. Указывай конкретику: действия, сроки, цифры
6. Заверши выводом или планом действий

ЦЕЛЬ:
Сделай текст удобным для быстрого чтения, визуально чистым, с логичной структурой и ключевыми акцентами через формат и эмодзи."""
        
        user_prompt = f"Создай детальное резюме следующего текста, сохранив все ключевые мысли и идеи: {text}"
        
        response = openai_client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        
        summary = response.choices[0].message.content
        
        # Нормализуем пробелы и переносы строк для улучшения читаемости
        summary = normalize_text_spacing(summary)
        
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

def get_parse_mode_for_mode(mode: str):
    """Возвращает правильный режим парсинга в зависимости от режима работы бота"""
    # В режимах саммаризации используем HTML-форматирование
    if mode in [MODE_SUMMARIZE, MODE_BOTH]:
        return 'HTML'
    # В остальных режимах используем Markdown
    return 'Markdown'

async def safe_send_message(message_obj, text: str, parse_mode: str = None, mode: str = MODE_TRANSLATE):
    """Безопасно отправляет сообщение, разбивая его на части при необходимости"""
    # Проверка на None для предотвращения AttributeError
    if message_obj is None:
        logger.error(f"Ошибка: message_obj равен None. Невозможно отправить сообщение: {text[:50]}...")
        return None
        
    try:
        # Если parse_mode не указан явно, определяем его на основе режима
        if parse_mode is None:
            # Проверяем наличие HTML-тегов в тексте
            if any(tag in text for tag in ['<b>', '<i>', '<code>', '<pre>', '<a href=']):
                parse_mode = 'HTML'
            else:
                parse_mode = get_parse_mode_for_mode(mode)
        
        logger.debug(f"Отправка сообщения с parse_mode: {parse_mode}")
            
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
    """Генерирует аудио используя gpt-4o-mini-tts с языковыми инструкциями"""
    try:
        voice = VOICES.get(lang, 'onyx')
        instructions = TTS_INSTRUCTIONS.get(lang, 'Speak clearly in the language of the text.')

        logger.info(f"TTS [{lang}] voice={voice}: {text[:80]}")

        response = openai_client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice=voice,
            input=text,
            instructions=instructions
        )
        return response.content

    except Exception as e:
        logger.error(f"Ошибка генерации аудио: {e}", exc_info=True)
        raise

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    message_obj = get_effective_message(update)
    if message_obj is None:
        logger.error("None message_obj в start")
        return
        
    await message_obj.reply_text(
        'Привет! Я бот для перевода голосовых сообщений.\n\n'
        'Я автоматически определяю язык (русский или индонезийский) и перевожу:\n'
        'Русский → Индонезийский\n'
        'Индонезийский → Русский\n'
        ' + добавляю перевод на английский\n\n'
        'Просто отправь мне голосовое сообщение!'
    )

def get_effective_message(update: Update):
    """Определяет актуальный объект сообщения (обычное или бизнес)"""
    if hasattr(update, 'message') and update.message is not None:
        return update.message
    elif hasattr(update, 'business_message') and update.business_message is not None:
        return update.business_message
    elif hasattr(update, 'effective_message') and update.effective_message is not None:
        return update.effective_message
    else:
        logger.error("Не удалось получить объект сообщения из update")
        return None

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
        'Для подробной информации отправьте команду /help или >help \n'
        'Для настройки бота используйте /settings или >settings'
    )
    
    # Получаем актуальный объект сообщения и используем безопасную отправку
    message_obj = get_effective_message(update)
    await safe_send_message(message_obj, start_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    # Получаем актуальный объект сообщения
    message_obj = get_effective_message(update)
    
    # Определяем тип чата для показа соответствующих команд
    chat_type = 'unknown'
    if message_obj and hasattr(message_obj, 'chat'):
        chat_type = message_obj.chat.type
    
    # Базовый текст справки
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
        '/tts on/off - традиционное управление аудио\n'
        '/balance - проверить баланс OpenAI API (только для владельца)\n\n'
        'Обработка голосовых сообщений:\n'
        '- Короткие (менее 30 сек): только перевод в режиме "summarize"\n'
        '- Длинные (более 30 сек): автоматически добавляется саммаризация\n\n'
        'Настройки:\n'
        '/settings - все настройки бота для текущего чата\n'
        '/languages - настройка языков перевода\n'
        '/tts - включение/выключение озвучки'
    )
    
    # Добавляем информацию о командах с префиксом ">" для приватных чатов
    if chat_type == ChatType.PRIVATE:
        alternative_help = (
            '\n\n<b>Специальные команды для приватных чатов:</b>\n'
            'В приватных чатах можно использовать команды с префиксом ">" вместо "/"\n\n'
            '<b>Сокращённые команды языков:</b>\n'
            '>ru_en - Русский и Английский\n'
            '>ru_id - Русский и Индонезийский\n'
            '>en_id - Английский и Индонезийский\n\n'
            '<b>Сокращённые команды режимов:</b>\n'
            '>translate - только перевод\n'
            '>summarize - только саммаризация\n'
            '>both - и перевод, и саммаризация\n\n'
            'Также работают все обычные команды с префиксом ">":\n'
            '>help, >settings, >languages, >tts и т.д.'
        )
        help_text += alternative_help
    
    await safe_send_message(message_obj, help_text)

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /settings для настройки бота в чате"""
    message_obj = get_effective_message(update)
    if message_obj is None:
        logger.error("None message_obj в settings_command")
        return
        
    user = update.effective_user
    chat = update.effective_chat
    
    if not chat:
        await safe_send_message(message_obj, "❌ Эта команда может использоваться только в групповых чатах.")
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
    
    # Получаем актуальный объект сообщения для ответа
    message_obj = get_effective_message(update)
    
    if not message_obj:
        logger.error("Не удалось найти объект сообщения для ответа")
        return
        
    # Используем безопасную отправку сообщения
    await safe_send_message(message_obj, message, parse_mode='HTML')

async def settings_langs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /settings_langs для настройки языков перевода"""
    user = update.effective_user
    chat = update.effective_chat
    
    # Получаем объект сообщения с помощью нашей безопасной функции
    message_obj = get_effective_message(update)
    if message_obj is None:
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
    # Получаем объект сообщения
    message_obj = get_effective_message(update)
    if message_obj is None:
        logger.error("None message_obj в settings_mode_command")
        return
        
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
        await message_obj.reply_text("❌ У вас нет прав для изменения настроек бота в этом чате.")
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
        await message_obj.reply_text(
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
    
    await message_obj.reply_text(
        f"✅ Режим работы бота успешно обновлен!\n"
        f"Новый режим: {mode_name.get(mode, mode)}"
    )

async def settings_tts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /settings_tts для включения/выключения генерации аудио"""
    # Получаем объект сообщения
    message_obj = get_effective_message(update)
    if message_obj is None:
        logger.error("None message_obj в settings_tts_command")
        return
        
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
        await message_obj.reply_text("❌ У вас нет прав для изменения настроек бота в этом чате.")
        return
    
    # Получаем текущие настройки
    settings = load_chat_settings()
    chat_id_str = str(chat.id)
    
    if chat_id_str not in settings:
        settings[chat_id_str] = DEFAULT_CHAT_SETTINGS.copy()
    
    # Получаем аргументы команды
    args = context.args
    
    if not args or args[0].lower() not in ["on", "off"]:
        await message_obj.reply_text(
            "❓ Пожалуйста, укажите 'on' для включения или 'off' для выключения генерации аудио.\n"
            "Пример: `/settings_tts on`"
        )
        return
    
    tts_enabled = args[0].lower() == "on"
    
    # Обновляем настройки
    settings[chat_id_str]["tts_enabled"] = tts_enabled
    save_chat_settings(settings)
    
    await message_obj.reply_text(
        f"✅ Настройки генерации аудио обновлены!\n"
        f"Генерация аудио: {'✅ Включена' if tts_enabled else '❌ Выключена'}"
    )

async def is_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверяет, является ли отправитель владельцем бота."""
    message = update.message if update.message else update.callback_query.message
    user = message.from_user
    owner_id = OWNER_ID and str(user.id) == str(OWNER_ID)
    owner_username = user.username and OWNER_USERNAME and user.username.lower() == OWNER_USERNAME.lower()
    
    return owner_id or owner_username


async def check_openai_balance() -> dict:
    """Получает информацию о балансе OpenAI API."""
    try:
        import requests
        import os

        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            return {"success": False, "error": "API ключ не найден в переменных окружения."}

        # Подготовка дат для запросов
        import datetime as dt
        now = datetime.now()
        start_date = (now - dt.timedelta(days=90)).strftime("%Y-%m-%d")
        end_date = (now + dt.timedelta(days=1)).strftime("%Y-%m-%d")
        sub_date = datetime(now.year, now.month, 1).strftime("%Y-%m-%d")

        # Подготовка заголовков
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            # Получаем информацию о подписке (лимит)
            sub_url = "https://api.openai.com/v1/dashboard/billing/subscription"
            response = requests.get(sub_url, headers=headers)
            response.raise_for_status()  # Вызовет исключение при HTTP-ошибках
            total_amount = response.json().get("hard_limit_usd", 0)
            
            # Получаем информацию об использовании
            if total_amount > 20:  # Если лимит большой, используем текущий месяц
                usage_url = f"https://api.openai.com/v1/dashboard/billing/usage?start_date={sub_date}&end_date={end_date}"
            else:
                usage_url = f"https://api.openai.com/v1/dashboard/billing/usage?start_date={start_date}&end_date={end_date}"
            
            response = requests.get(usage_url, headers=headers)
            response.raise_for_status()
            total_usage = response.json().get("total_usage", 0) / 100  # Центы в доллары
            
            # Проверяем доступ к GPT-4
            models_url = "https://api.openai.com/v1/models"
            response = requests.get(models_url, headers=headers)
            response.raise_for_status()
            models = response.json().get("data", [])
            can_access_gpt4 = any(model.get("id") == "gpt-4" for model in models)
            
            # Формируем результат
            return {
                "success": True,
                "usage": total_usage,
                "hard_limit": total_amount,
                "remaining": total_amount - total_usage,
                "start_date": sub_date if total_amount > 20 else start_date,
                "end_date": end_date,
                "can_access_gpt4": can_access_gpt4
            }
            
        except requests.exceptions.HTTPError as e:
            return {"success": False, "error": f"Ошибка API (HTTP {e.response.status_code}): {e.response.text}"}
            
    except Exception as e:
        logger.error(f"Ошибка при проверке баланса OpenAI: {str(e)}", exc_info=True)
        return {"success": False, "error": f"Произошла ошибка: {str(e)}"}


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет информацию о балансе OpenAI API (только для владельца)."""
    # Получаем объект сообщения
    message_obj = get_effective_message(update)
    if message_obj is None:
        logger.error("None message_obj в balance_command")
        return
        
    # Проверяем, что это запрос от владельца бота
    if not await is_owner(update, context):
        await message_obj.reply_text("❌ Эта команда доступна только владельцу бота.")
        return
    
    # Отправляем сообщение о начале проверки
    processing_msg = await message_obj.reply_text("🔄 Проверяю баланс OpenAI API...")
    
    # Получаем информацию о балансе
    balance_info = await check_openai_balance()
    
    if not balance_info["success"]:
        await processing_msg.edit_text(f"❌ Ошибка при проверке баланса: {balance_info['error']}")
        return
    
    # Формируем текст сообщения
    message_text = f"""✅ <b>Информация о балансе OpenAI API:</b>

• Период: {balance_info['start_date']} - {balance_info['end_date']}
• Использовано: ${balance_info['usage']:.2f}
"""
    
    # Добавляем информацию о лимите и остатке, если они есть
    if "hard_limit" in balance_info:
        message_text += f"• Лимит: ${balance_info['hard_limit']:.2f}\n"
    
    if "remaining" in balance_info:
        message_text += f"• Осталось: ${balance_info['remaining']:.2f}\n"
    
    # Добавляем информацию о доступе к GPT-4
    if "can_access_gpt4" in balance_info:
        gpt4_status = "✅ Доступен" if balance_info['can_access_gpt4'] else "❌ Недоступен"
        message_text += f"\n• Доступ к GPT-4: {gpt4_status}\n"
    
    # Добавляем информацию о примечаниях или ошибках, если они есть
    if "subscription_error" in balance_info:
        message_text += f"\n⚠️ <b>Примечание:</b> {balance_info['subscription_error']}\n"
    
    # Добавляем дату и время проверки
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message_text += f"\n<i>Информация актуальна на: {current_time}</i>"
    
    await processing_msg.edit_text(message_text, parse_mode='HTML')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /stats для получения статистики использования бота"""
    # Получаем объект сообщения
    message_obj = get_effective_message(update)
    if message_obj is None:
        logger.error("None message_obj в stats_command")
        return
        
    user = update.effective_user
    
    # Только владелец бота может получать статистику
    # Проверяем по username и по числовому ID
    is_owner = False
    if user.username and user.username.lower() == OWNER_USERNAME.lower():
        is_owner = True
    elif OWNER_ID and str(user.id) == str(OWNER_ID):
        is_owner = True
    
    if not is_owner:
        await message_obj.reply_text("❌ Эта команда доступна только владельцу бота.")
        return
    
    # Загружаем статистику
    stats = load_usage_stats()
    
    # Формируем сообщение со статистикой
    stats_message = generate_stats_message(stats)
    
    await message_obj.reply_text(stats_message, parse_mode='Markdown')

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
    
    # Используем нашу функцию для получения объекта сообщения
    message = get_effective_message(update)
    if message is None:
        logger.error("Не удалось получить объект сообщения в handle_alternative_commands")
        return False
        
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
        # Стандартные команды
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
        "stats": stats_command,
        
        # Добавляем сокращенные версии команд для удобства
        "ru_en": settings_langs_ru_en_command,
        "ru_id": settings_langs_ru_id_command,
        "en_id": settings_langs_en_id_command,
        "translate": settings_mode_translate_command,
        "summarize": settings_mode_summarize_command,
        "both": settings_mode_both_command,
        "perevod": settings_mode_perevod_command,
        "sammarajz": settings_mode_sammarajz_command,
        "bof": settings_mode_bof_command
    }
    
    # Проверяем, есть ли такая команда в словаре
    if command in command_handlers:
        try:
            # Выполняем соответствующую команду
            await command_handlers[command](update, context)
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке альтернативной команды '{command}': {str(e)}", exc_info=True)
            
            # Безопасная отправка ошибки с проверкой на None
            error_text = f"😔 Произошла ошибка при выполнении команды '{command}'"
            if message is not None:
                try:
                    await message.reply_text(error_text)
                except Exception as reply_error:
                    logger.error(f"Не удалось отправить сообщение об ошибке: {str(reply_error)}", exc_info=True)
            return True
    
    return False

async def handle_business_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Универсальный обработчик для всех типов сообщений (обычных и бизнес)"""
    # Определяем сообщение и тип
    if hasattr(update, 'business_message') and update.business_message:
        message = update.business_message
        is_business = True
    elif hasattr(update, 'message') and update.message:
        message = update.message
        is_business = False
    else:
        return

    chat_type = message.chat.type if hasattr(message, 'chat') else "unknown"

    # Альтернативные команды в приватных чатах (>help, >settings и т.д.)
    if hasattr(message, 'text') and message.text and chat_type == ChatType.PRIVATE:
        if await handle_alternative_commands(update, context, message.text, is_business=is_business):
            return

    # Определяем тип медиа
    media_type = None
    if message.voice:
        media_type = "voice"
    elif message.video_note:
        media_type = "video_note"
    elif message.document and message.document.mime_type and message.document.mime_type.startswith('audio/'):
        media_type = "document"
    elif message.audio:
        media_type = "audio"

    if media_type:
        biz_tag = " (бизнес)" if is_business else ""
        logger.info(f"Получено {media_type} сообщение{biz_tag}. Тип чата: {chat_type}")
        await handle_voice(update, context, is_business=is_business, media_type=media_type)
    elif hasattr(message, 'text') and message.text and not message.text.startswith(('/', '>')):
        # Автоперевод текстовых сообщений (если язык отличается от настроенных)
        await handle_text_translation(message, context)

def _get_voice_duration(message, media_type: str) -> int:
    """Извлекает длительность аудио из сообщения"""
    if media_type == "voice" and message.voice and hasattr(message.voice, 'duration'):
        return message.voice.duration
    if media_type == "audio" and message.audio and hasattr(message.audio, 'duration'):
        return message.audio.duration
    if media_type == "video_note" and message.video_note and hasattr(message.video_note, 'duration'):
        return message.video_note.duration
    if media_type == "document":
        return 30
    return 0


def _adjust_mode_by_duration(mode: str, voice_duration: int) -> str:
    """Корректирует режим работы в зависимости от длительности аудио"""
    if voice_duration > 30 and mode == MODE_TRANSLATE:
        logger.info(f"Длинное сообщение ({voice_duration}с): добавлена саммаризация")
        return MODE_BOTH
    return mode


async def _download_audio_file(message, media_type: str) -> tuple:
    """Скачивает аудиофайл из сообщения. Возвращает (file_path, extension) или (None, None)"""
    file_to_download = None
    file_extension = '.ogg'

    if media_type == "voice":
        file_to_download = await message.voice.get_file()
        file_extension = '.ogg'
    elif media_type == "document":
        file_to_download = await message.document.get_file()
        if message.document.file_name:
            _, ext = os.path.splitext(message.document.file_name)
            if ext:
                file_extension = ext
    elif media_type == "audio":
        file_to_download = await message.audio.get_file()
        file_extension = '.mp3'
        if message.audio.file_name:
            _, ext = os.path.splitext(message.audio.file_name)
            if ext:
                file_extension = ext
    elif media_type == "video_note":
        file_to_download = await message.video_note.get_file()
        file_extension = '.mp4'

    if not file_to_download:
        return None, None

    temp_audio = tempfile.NamedTemporaryFile(suffix=file_extension, delete=False)
    await file_to_download.download_to_drive(temp_audio.name)
    temp_audio.close()
    logger.info(f"Сохранено аудио: {temp_audio.name}")
    return temp_audio.name, file_extension


def _format_result_message(result: dict, mode: str, detected_lang: str) -> str:
    """Форматирует результат обработки в текст для отправки"""
    parts = []

    if mode == MODE_SUMMARIZE:
        if result.get("summary"):
            parts.append(result["summary"])

    elif mode == MODE_TRANSLATE:
        parts.append(f"🎙️ Исходный текст ({LANG_EMOJIS.get(detected_lang, '')}):\n{result['original']}\n")
        if result.get("translations"):
            parts.append("🔄 Переводы:")
            for lang, text in result["translations"].items():
                if lang != detected_lang:
                    parts.append(f"{LANG_EMOJIS.get(lang, '')}: {text}\n")

    elif mode == MODE_BOTH:
        if result.get("translations"):
            parts.append("🔄 Переводы:")
            for lang, text in result["translations"].items():
                if lang != detected_lang:
                    parts.append(f"{LANG_EMOJIS.get(lang, '')}: {text}\n")
        if result.get("summary"):
            parts.append(result["summary"])

    return "\n".join(parts).strip()


async def _send_result(context, message, processing_msg, result_message: str, mode: str):
    """Отправляет результат: пытается отредактировать processing_msg, иначе шлёт новое"""
    if not result_message:
        if processing_msg:
            try:
                await processing_msg.delete()
            except Exception:
                pass
        return

    parse_mode = 'HTML' if mode in [MODE_SUMMARIZE, MODE_BOTH] else 'Markdown'
    chat_id = message.chat.id

    # Для коротких сообщений — пробуем отредактировать "Обрабатываю..."
    if processing_msg and len(result_message) <= 4000:
        try:
            await processing_msg.edit_text(text=result_message, parse_mode=parse_mode)
            return
        except Exception as e:
            logger.debug(f"Не удалось редактировать: {e}")

    # Удаляем "Обрабатываю..." и шлём новое сообщение
    if processing_msg:
        try:
            await processing_msg.delete()
        except Exception:
            pass

    await send_split_message(
        context=context,
        chat_id=chat_id,
        message_text=result_message,
        reply_to_message_id=message.message_id,
        parse_mode=parse_mode
    )


async def _handle_tts(context, message, result: dict, detected_lang: str, enabled_languages: list):
    """Генерирует и отправляет озвученный перевод"""
    target_langs = [lang for lang in enabled_languages if lang != detected_lang]
    if not target_langs:
        return

    target_lang = target_langs[0]
    target_text = result.get("translations", {}).get(target_lang)
    if not target_text:
        return

    try:
        audio_content = await generate_audio(target_text, target_lang)
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_tts:
            temp_tts.write(audio_content)
            temp_tts_path = temp_tts.name

        with open(temp_tts_path, 'rb') as f:
            await message.reply_voice(f)
        os.unlink(temp_tts_path)
    except Exception as e:
        logger.error(f"Ошибка генерации аудио: {e}")
        await message.reply_text("😔 Ошибка при создании аудио.")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE, is_business: bool = False, media_type: str = "voice"):
    """Обработка голосовых и аудио сообщений"""
    message = update.business_message if is_business else update.message
    if not message:
        return

    # Проверяем наличие медиа
    if media_type == "voice" and not message.voice:
        return
    if media_type == "video_note" and not message.video_note:
        return
    if media_type == "document" and not message.document:
        return
    if media_type == "audio" and not message.audio:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    user_name = message.from_user.full_name if message.from_user else "Unknown"
    chat_title = message.chat.title if message.chat.title else "Личный чат"

    # Статистика
    if user_id:
        update_usage_stats(user_id, user_name, chat_id, chat_title)

    # Настройки чата
    chat_settings = get_chat_settings(chat_id)
    mode = chat_settings.get("mode", MODE_TRANSLATE)
    tts_enabled = chat_settings.get("tts_enabled", False)
    enabled_languages = chat_settings.get("enabled_languages", ["ru", "en"])

    # Длительность и корректировка режима
    voice_duration = _get_voice_duration(message, media_type)

    # Короткие сообщения в режиме саммаризации — игнорируем
    if voice_duration < 30 and mode == MODE_SUMMARIZE:
        logger.info(f"Короткое голосовое ({voice_duration}с): режим саммаризации, игнорируем")
        return
        

    mode = _adjust_mode_by_duration(mode, voice_duration)

    # Уведомление о начале обработки
    processing_msg = await message.reply_text("🔄 Обрабатываю голосовое сообщение...")

    # Скачиваем аудио
    audio_path = None
    try:
        audio_path, _ = await _download_audio_file(message, media_type)
        if not audio_path:
            await processing_msg.edit_text("❌ Не удалось получить аудиофайл.")
            return

        # Транскрибируем
        detected_text, detected_lang = await transcribe_audio(audio_path)

        # Обработка ошибок транскрипции
        if detected_text.startswith("QUOTA_EXCEEDED:"):
            await processing_msg.edit_text(
                "⚠️ <b>Превышен лимит API OpenAI</b>\n\nОбратитесь к владельцу бота.",
                parse_mode="HTML"
            )
            return
        if detected_text.startswith("RATE_LIMIT:"):
            await processing_msg.edit_text(
                "⚠️ <b>Слишком много запросов</b>\n\nПопробуйте через несколько минут.",
                parse_mode="HTML"
            )
            return

        logger.info(f"Распознан текст: {detected_text[:80]}..., язык: {detected_lang}")

        # Добавляем язык оригинала если его нет в настройках
        temp_languages = enabled_languages.copy()
        if detected_lang not in temp_languages:
            temp_languages.append(detected_lang)

        # Обрабатываем (перевод / саммаризация)
        result = await process_message_content(
            detected_text, detected_lang,
            {"enabled_languages": temp_languages, "mode": mode},
            voice_duration
        )

        # Если результат помечен как "игнорировать" (короткое сообщение в режиме саммаризации)
        if result.get("ignore"):
            try:
                await processing_msg.delete()
            except Exception:
                pass
            return

        # Форматируем результат
        result_message = _format_result_message(result, mode, detected_lang)

        # Отправляем результат
        await _send_result(context, message, processing_msg, result_message, mode)

        # TTS если включён
        if tts_enabled and mode in [MODE_TRANSLATE, MODE_BOTH]:
            await _handle_tts(context, message, result, detected_lang, enabled_languages)

    except Exception as e:
        logger.error(f"Ошибка обработки голосового: {e}", exc_info=True)
        try:
            msg_obj = get_effective_message(update)
            if msg_obj:
                await msg_obj.reply_text("😔 Ошибка при обработке сообщения.")
        except Exception:
            pass
    finally:
        # Чистим temp-файл
        if audio_path and os.path.exists(audio_path):
            os.unlink(audio_path)


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
    application.add_handler(CommandHandler("balance", balance_command))
    
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