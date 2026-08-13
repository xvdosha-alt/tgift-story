# Lost Gifts

Bot and web service for tracking Telegram NFT gift transfer history.

Paste a gift link — get owner changes, metadata from Fragment, and a simple web page with preview.

**Site:** [lostgifts.ru](https://lostgifts.ru)

## What it does

- Tracks collectible gifts from `t.me/nft/{Slug}-{id}`
- Logs owner transfers in Redis from the moment tracking starts
- Telegram bot: `/hist` for history, `/web` for the page link
- Background workers poll known gifts and append new transfers
- Web search + gift pages with Fragment JSON / WebP / Lottie

## Quick start

```bash
git clone https://github.com/xvdosha-alt/tgift-story.git
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

### Run

```bash
python -m src.logger.worker &
uvicorn src.web.server:app --host 127.0.0.1 --port 8877 &
python -m src.bot.main
```

## Usage

### Bot

```
/hist https://t.me/nft/PlushPepe-1
/web https://t.me/nft/PlushPepe-1
```

### Web

| Route | Description |
|-------|-------------|
| `/` | Search by link |
| `/gift/PlushPepe-1` | History + Fragment preview |

### CLI

```bash
python -m src.cli.main hist https://t.me/nft/PlushPepe-1
python -m src.cli.main track PlushPepe-1 SignetRing-903
```

## How it works

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

History is built from observed owner changes after tracking starts — not a full pre-existing chain.

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

MIT — [LICENSE](LICENSE)
