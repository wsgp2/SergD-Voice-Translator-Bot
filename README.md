# 🎙️SergD Voice Translator Bot

**⭐ АКТУАЛЬНАЯ ВЕРСИЯ: Эта версия бота является самой новой и рекомендуемой к использованию! ⭐**

Умный Telegram-бот для перевода голосовых сообщений с поддержкой бизнес-чатов.

## 💫 Возможности

- 🎙️ Распознавание голосовых сообщений через OpenAI Whisper
- 🌎 Перевод на русский, английский и индонезийский языки
- 🗣️ Озвучивание перевода через OpenAI TTS и Google TTS
- 💼 Поддержка бизнес-чатов Telegram
- ✨ Красивые анимации и переходы

## 💻 Установка

1. Клонируем репозиторий:
```bash
git clone <repository_url>
cd telegram_voice_translator
```

2. Создаем виртуальное окружение:
```bash
python -m venv venv
source venv/bin/activate  # для Linux/Mac
venv\Scripts\activate  # для Windows
```

3. Устанавливаем зависимости:
```bash
pip install -r requirements.txt
```

4. Создаем файл `.env` с необходимыми токенами:
```env
TELEGRAM_TOKEN=your_telegram_bot_token
OPENAI_API_KEY=your_openai_api_key
GOOGLE_APPLICATION_CREDENTIALS=path/to/your/google_credentials.json
```

## 📚 Использование

### 📦 Запуск бота

```bash
python translator_bot.py
```

### 💬 Команды бота

- `/start` - Начать работу с ботом
- `/help` - Получить справку

## 📝 Примеры кода

### 💼 Обработка бизнес-сообщений

```python
async def handle_business_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Проверяем наличие голосового сообщения
    if hasattr(update, 'business_message') and update.business_message and update.business_message.voice:
        chat_type = update.business_message.chat.type
        logger.info(f"🎯 Получено бизнес-сообщение. Тип чата: {chat_type}")
        await handle_voice(update, context, is_business=True)
```

### ✨ Красивые переходы в интерфейсе

```python
# Заменяем сообщение о процессе на звездочку
try:
    logger.info("✨ Завершаем обработку...")
    await asyncio.sleep(2)
    await processing_msg.edit_text("✨")
except Exception as e:
    logger.debug(f"💬 Не удалось изменить сообщение: {str(e)}")
```

### 💬 Форматирование сообщений

```python
response_text = f"""🎯 Определен язык: {LANG_EMOJIS[detected_lang]}

💬 Исходный текст:
{LANG_EMOJIS[detected_lang]} {translations[detected_lang]}

🌟 Переводы:
{LANG_EMOJIS['en']} {translations['en']}

{LANG_EMOJIS['id' if detected_lang == 'ru' else 'ru']} {translations['id' if detected_lang == 'ru' else 'ru']}

🎤 Отправляю озвученный перевод..."""
```

## 📌 Зависимости

- `python-telegram-bot==21.10`
- `openai`
- `python-dotenv`
- `google-cloud-texttospeech`

## 💡 Подсказки

1. 🔑 Для работы с бизнес-чатами необходим бизнес-аккаунт Telegram
2. 💳 Для работы с OpenAI и Google TTS необходимы действующие API ключи
3. 📁 Все временные файлы автоматически удаляются

## 📘 Лицензия

MIT License

- 🐍 **Python 3.9+** для основной логики
- 📦 **Poetry** для управления зависимостями

## 🚀 Установка

1. **Клонируйте репозиторий**:
   ```bash
   git clone https://github.com/yourusername/telegram-voice-translator.git
   cd telegram-voice-translator
   ```

2. **Установите зависимости**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Настройте переменные окружения**:
   - Создайте файл `.env` на основе `.env.example`
   - Добавьте ваши токены:
     ```
     TELEGRAM_TOKEN=your_telegram_bot_token
     OPENAI_API_KEY=your_openai_api_key
     ```

4. **Запустите бота**:
   ```bash
   python translator_bot.py
   ```

## 💡 Использование

1. 🤖 Найдите бота в Telegram
2. 🎤 Отправьте голосовое сообщение на русском или индонезийском
3. ⚡️ Бот автоматически:
   - Определит язык
   - Сделает перевод
   - Отправит текст и аудио

## 🎯 Примеры сообщений

```
🎯 Определен язык: 🇷🇺

💭 Исходный текст:
🇷🇺 Привет, как дела?

🌟 Переводы:
🇺🇸 Hi, how are you?
🇮🇩 Halo, apa kabar?

🎤 Отправляю озвученный перевод...
```

## 🔧 Конфигурация

### Поддерживаемые голоса

- 🇷🇺 Русский: `shimmer` (женский голос)
- 🇮🇩 Индонезийский: `nova` (женский голос)
- 🇺🇸 Английский: `echo` (мужской голос)

### Настройка промптов

Бот использует специально настроенные промпты для GPT-4, которые обеспечивают:
1. 🎯 Сохранение исходного смысла
2. 💫 Естественность перевода
3. 🎭 Сохранение стиля
4. 🔍 Учет культурных особенностей
5. 📚 Использование идиом

## 📝 Логирование

Бот ведет подробное логирование всех этапов:
- 🎤 Получение голосового сообщения
- 🔍 Распознавание речи
- 🔄 Перевод
- 🔊 Генерация аудио

## 🤝 Вклад в проект

Мы рады любой помощи! Вы можете:
1. 🐛 Сообщать об ошибках
2. 💡 Предлагать новые функции
3. 🔧 Отправлять pull requests

## 📄 Лицензия

MIT License - делайте что хотите, просто упомяните автора 😊

## 👏 Благодарности

- [OpenAI](https://openai.com) за отличные API
- [python-telegram-bot](https://python-telegram-bot.org) за удобную библиотеку
- Всем контрибьюторам за помощь

## Описание для Telegram

### Описание чата:
```
 Русско-Индонезийское Сообщество | RU-ID Community

Добро пожаловать в уникальное пространство для общения между русскоговорящими и индонезийцами!

 Здесь нет языковых барьеров
 Мгновенный перевод голосовых сообщений
 Живое общение на родном языке
 Культурный обмен и новые друзья

У нас работает умный бот-переводчик @SergDTranslator_Bot
Просто отправьте голосовое сообщение, и все поймут вас!
```

## 🚀 Деплой на сервер

### 🔧 Требования к серверу
- Python 3.11+
- Git
- SSH доступ

### 📦 Установка на сервере
1. **Клонируйте репозиторий**:
```bash
git clone https://github.com/yourusername/telegram-voice-translator.git
cd telegram-voice-translator
```

2. **Создайте виртуальное окружение**:
```bash
python3.11 -m venv venv
source venv/bin/activate
```

3. **Установите зависимости**:
```bash
pip install -r requirements.txt
pip install openai==1.61.1
```

4. **Настройте переменные окружения**:
```bash
cp .env.example .env
nano .env  # Добавьте ваши токены
```

### 🎯 Важные заметки по API ключам
- 🔑 Для OpenAI API используйте ключ, начинающийся с `sk-` или `sk-svcacct-`
- ⚠️ Ключи с префиксом `sk-proj-` могут не работать с аудио транскрипцией

### 🚀 Запуск бота
```bash
python3.11 translator_bot.py
```

### 🔄 Перезапуск бота
```bash
pkill -f translator_bot.py
cd ~/telegram_voice_translator
source venv/bin/activate
python3.11 translator_bot.py
```

### 📝 Проверка логов
```bash
tail -f nohup.out  # Если запущен через nohup
# или
ps aux | grep translator_bot.py  # Проверка запущенных процессов
```

### ⚡️ Рекомендации
- 🔄 Используйте `systemd` или `supervisor` для автоматического перезапуска
- 📊 Настройте мониторинг использования памяти и CPU
- 🔒 Регулярно обновляйте зависимости
- 💾 Настройте резервное копирование конфигурации

### Описание бота:
```
SergD Voice Translator - умный переводчик голосовых сообщений между русским и индонезийским языками.

Просто отправьте голосовое сообщение, и бот:
• Распознает язык автоматически
• Переведет на два других языка
• Отправит текст и аудио перевода

Идеально для общения в русско-индонезийских чатах!

Команды:
/start - Начать работу с ботом
/help - Инструкция по использованию
