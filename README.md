# mamulya-bot
Без залежностей. `python3 bot.py`. ENV: BOT_TOKEN (обов'язково), SALESDRIVE_KEY, MEDUSA_URL, MEDUSA_KEY, DILA_CODE, BOT_NAME, PORT.

- Вхід клієнта: кнопка на thank-you `https://t.me/<BOT_NAME>?start=<order_id>`
- Вебхук SalesDrive → `POST /` (тіло замовлення)
- Правила (стадії, подарунки, lifecycle) — `rules.py`
- Деплой: Render web service, `python3 bot.py`
