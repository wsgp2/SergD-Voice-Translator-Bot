# 🚀 Инструкция по деплою на DigitalOcean с GitHub Actions

## 📋 Содержание
1. [Подготовка сервера на DigitalOcean](#1-подготовка-сервера-на-digitalocean)
2. [Подготовка репозитория на GitHub](#2-подготовка-репозитория-на-github)
3. [Создание SSH-ключей для GitHub Actions](#3-создание-ssh-ключей-для-github-actions)
4. [Настройка GitHub Actions](#4-настройка-github-actions)
5. [Тестирование и отладка](#5-тестирование-и-отладка)
6. [Рекомендации и улучшения](#6-рекомендации-и-улучшения)

## 1. Подготовка сервера на DigitalOcean

### 1.1. Регистрация и создание Droplet
1. Зарегистрируйтесь (или войдите) на DigitalOcean
2. Нажмите «Create Droplet» и выберите образ (рекомендуется Ubuntu 20.04 LTS или 22.04 LTS)
3. На этапе настройки безопасности добавьте свой публичный SSH-ключ
4. Выберите тарифный план (для небольшого Python-приложения базовый план будет достаточным)
5. Завершите создание droplet и запомните его IP-адрес

### 1.2. Первичная настройка сервера

Подключитесь к серверу по SSH:
```bash
ssh your_username@your_droplet_ip
```

Создание пользователя для деплоя:
```bash
# Создаем пользователя deploy и задаем пароль
sudo adduser deploy

# Добавляем пользователя в группу sudo
sudo usermod -aG sudo deploy

# Переключаемся на нового пользователя
su - deploy
```

### 1.3. Установка необходимых пакетов

Обновление системы и установка Python:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip python3-venv git -y

# Создаем директорию для приложения
mkdir ~/my_python_app
cd ~/my_python_app

# Создаем виртуальное окружение
python3 -m venv venv
source venv/bin/activate
```

## 2. Подготовка репозитория на GitHub

### 2.1. Создание репозитория
1. Создайте новый репозиторий на GitHub
2. Инициализируйте репозиторий локально
3. Добавьте код и requirements.txt

### 2.2. Пример файловой структуры
```
my-python-app/
├── app.py
├── requirements.txt
└── .github/
    └── workflows/
        └── deploy.yml
```

## 3. Создание SSH-ключей для GitHub Actions

1. Создание ключей:
```bash
ssh-keygen -t rsa -b 4096 -C "github-actions-deploy" -f github_actions_key
```

2. Добавление публичного ключа на сервер:
```bash
cat github_actions_key.pub >> ~/.ssh/authorized_keys
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
```

## 4. Настройка GitHub Actions

### 4.1. Добавление секретов в GitHub
Добавьте в Settings → Secrets and variables → Actions:
- `SSH_HOST`: IP-адрес droplet
- `SSH_USERNAME`: имя пользователя (deploy)
- `SSH_PRIVATE_KEY`: содержимое приватного ключа

### 4.2. Создание файла workflow
Создайте `.github/workflows/deploy.yml`:

```yaml
name: Deploy Python App to DigitalOcean

on:
  push:
    branches:
      - main

jobs:
  deploy:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v2

      - name: Deploy to DigitalOcean Droplet via SSH
        uses: appleboy/ssh-action@master
        with:
          host: ${{ secrets.SSH_HOST }}
          username: ${{ secrets.SSH_USERNAME }}
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          port: 22
          script: |
            cd ~/my_python_app
            git pull origin main
            source venv/bin/activate
            pip install -r requirements.txt
            pkill -f app.py || true
            nohup python3 app.py > app.log 2>&1 &
```

## 5. Тестирование и отладка

1. Коммит и пуш изменений:
```bash
git add .
git commit -m "Настройка CI/CD деплоя на DigitalOcean"
git push origin main
```

2. Проверьте выполнение workflow на вкладке Actions
3. Проверьте работу приложения на сервере

## 6. Рекомендации и улучшения

### Процесс управления приложением
- Используйте systemd или Supervisor для управления процессами
- Настройте автоматический перезапуск при сбоях

### Безопасность
- Не храните приватные ключи в репозитории
- Используйте GitHub Secrets
- Ограничьте права пользователя deploy

### Расширение функциональности
- Добавьте тесты перед деплоем
- Настройте уведомления в Slack/email
- Добавьте мониторинг работы приложения
