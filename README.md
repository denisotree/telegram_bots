# Telegram bots backends

## LifeStat bot

A backend for a telegram bot that allows you to create counters for all occasions. If you need to calculate how many times a day you drank water, for example, or how many times you were distracted by conversations with colleagues - this bot is for you

### Technologies

The bot is written in Python using the [aiogram](https://docs.aiogram.dev/en/latest/) library

### Environment

To work, it is necessary that the following parameters be passed in the `.env` file or in the global environment:

- `TELEGRAM_API_TOKEN` - token, generated by [Bot Father](https://t.me/BotFather)
- `REDIS_HOST`- host of Redis, where bot wil store it`s state
- `REDIS_PASSWORD` - Redis password

### Life

A working version is available [here](https://t.me/lifestat_bot)
