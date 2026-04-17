#!/bin/bash
# Скрипт для першого отримання SSL сертифіката від Let's Encrypt
# Запускати ОДИН РАЗ після деплою на сервер

DOMAIN="netishynanimals.space"
EMAIL="y.m.bilyk@gmail.com"   # <-- замінити на реальний email

set -e

echo "==> Запускаємо nginx для ACME challenge..."
docker compose up -d nginx

echo "==> Чекаємо 3 секунди..."
sleep 3

echo "==> Отримуємо сертифікат для $DOMAIN..."
docker compose run --rm certbot certonly \
  --webroot \
  --webroot-path=/var/www/certbot \
  --email "$EMAIL" \
  --agree-tos \
  --no-eff-email \
  -d "$DOMAIN" \
  -d "www.$DOMAIN"

echo "==> Перезапускаємо nginx з SSL..."
docker compose restart nginx

echo "==> Готово! Сертифікат отримано."
echo "==> Тепер встав WEBHOOK_URL=https://$DOMAIN в .env і запусти: docker compose up -d"
