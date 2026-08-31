[EN](../README.md) | RU

## Lost Gifts 🎁

![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)

Бот и веб-сервис для отслеживания истории передач Telegram NFT-подарков.

Вставь ссылку на подарок - получи смены владельца, метаданные с Fragment и простую веб-страницу с превью.

**Сайт:** [lostgifts.ru](https://lostgifts.ru)

## ✨ Возможности

- Отслеживает collectible gifts по `t.me/nft/{Slug}-{id}`
- Логирует смены владельца в Redis с момента начала трекинга
- Telegram-бот: `/hist` для истории, `/web` для ссылки на страницу
- Фоновые воркеры опрашивают известные подарки и дописывают новые передачи
- Веб-поиск + страницы подарков с Fragment JSON / WebP / Lottie

## 🚀 Быстрый старт

```bash
git clone https://github.com/xvDoshik/tgift-story.git
cd tgift-story

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# BOT_TOKEN, REDIS_URL


```

### Redis

```bash
docker run -d --name lostgifts-redis -p 127.0.0.1:6379:6379 redis:7-alpine
```

### Запуск

```bash
python -m src.logger.worker &
uvicorn src.web.server:app --host 127.0.0.1 --port 8877 &
python -m src.bot.main
```

## 🎮 Использование

### Бот

```
/hist https://t.me/nft/PlushPepe-1
/web https://t.me/nft/PlushPepe-1
```

### Web

| Route | Description |
|-------|-------------|
| `/` | Поиск по ссылке |
| `/gift/PlushPepe-1` | История + Fragment preview |

### CLI

```bash
python -m src.cli.main hist https://t.me/nft/PlushPepe-1
python -m src.cli.main track PlushPepe-1 SignetRing-903
```

## Как это работает

```
Bot / Web / CLI ──► Redis ◄── Logger workers
                      │
                      └──► t.me/nft pages
```

| Redis key | Purpose |
|-----------|---------|
| `gift:{slug}:state` | Latest snapshot |
| `gift:{slug}:history` | Transfer events |
| `gift:{slug}:tracked_since` | When tracking started |
| `gifts:all` | Slugs in rotation |

История строится из наблюдаемых смен владельца после начала трекинга - не полная pre-existing цепочка.

## Deploy

```bash
rsync -avz --exclude '.venv' --exclude '.git' --exclude '.env' ./ root@SERVER:/opt/alex_gift/
ssh root@SERVER "bash /opt/alex_gift/deploy/setup.sh"
ssh root@SERVER "bash /opt/alex_gift/deploy/nginx/setup-lostgifts.sh"
```

Cloudflare NS:

```
albert.ns.cloudflare.com
fiona.ns.cloudflare.com
```

## Links

```
https://t.me/nft/PlushPepe-1
PlushPepe-1
```

Fragment: `https://nft.fragment.com/gift/{slug}.json`

## License

MIT - [LICENSE](LICENSE)
