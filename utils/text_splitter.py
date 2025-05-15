import re

def ensure_telegram_limits(text: str, max_length: int = 4096) -> list:
    """
    Проверяет и разделяет текст, если он превышает максимальную длину сообщения в Telegram.
    
    Args:
        text: Исходный текст
        max_length: Максимальная длина сообщения (по умолчанию 4096 для Telegram)
        
    Returns:
        Список строк, каждая из которых не превышает максимальную длину
    """
    if len(text) <= max_length:
        return [text]
    
    # Если текст слишком длинный, разделяем его по предложениям или абзацам
    parts = []
    current_part = ""
    
    # Сначала пытаемся разделить по абзацам
    paragraphs = text.split('\n\n')
    
    for paragraph in paragraphs:
        # Если абзац сам по себе слишком длинный, разделим его по предложениям
        if len(paragraph) > max_length:
            sentences = re.split(r'(?<=[.!?])\s+', paragraph)
            for sentence in sentences:
                if len(current_part) + len(sentence) + 2 <= max_length:
                    if current_part:
                        current_part += "\n\n" if sentence.strip() else "\n"
                    current_part += sentence
                else:
                    if current_part:
                        parts.append(current_part)
                    current_part = sentence
                    
                    # Если даже одно предложение слишком длинное, разделим его на части
                    if len(sentence) > max_length:
                        words = sentence.split()
                        current_part = ""
                        for word in words:
                            if len(current_part) + len(word) + 1 <= max_length:
                                current_part += " " + word if current_part else word
                            else:
                                parts.append(current_part)
                                current_part = word
        else:
            # Если текущий абзац поместится - добавляем его
            if len(current_part) + len(paragraph) + 2 <= max_length:
                if current_part:
                    current_part += "\n\n" if paragraph.strip() else "\n"
                current_part += paragraph
            else:
                parts.append(current_part)
                current_part = paragraph
    
    # Добавляем последнюю часть, если она не пуста
    if current_part:
        parts.append(current_part)
    
    return parts
