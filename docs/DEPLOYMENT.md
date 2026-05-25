# VPS Deployment

This deploys the full app with Docker Compose:

- Next.js web UI on port `3000`
- FastAPI API on the private Docker network
- Postgres with a persistent Docker volume
- SearXNG, Valkey, and Tor
- generated search output in a persistent Docker volume

## 1. Install Docker on the VPS

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Log out and back in after adding your user to the `docker` group.

## 2. Clone and configure

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO
cp deploy.env.example .env
```

Edit `.env`:

```bash
nano .env
```

At minimum set:

- `APP_PASSWORD`
- `APP_SECRET`, generated with `openssl rand -hex 32`
- `POSTGRES_PASSWORD`
- the API key for your configured provider, for example `ANTHROPIC_API_KEY`

The deploy env template also uses a conservative SearXNG profile for VPS IPs:

```bash
SECONDS_BETWEEN_QUERIES=300
SECONDS_BETWEEN_PAGES=180
THROTTLE_JITTER=0.5
MAX_REQUESTS_PER_MINUTE=1
RETRY_BACKOFF_BASE=30
RETRY_BACKOFF_MAX=300
COOLOFF_AFTER_EMPTY_QUERIES=1
COOLOFF_SECONDS=3600
```

That gives roughly 2.5-7.5 minutes between logical queries after jitter, 1.5-4.5
minutes between pages, and a 1-hour pause after the first empty query batch.

## 3. Start the app

```bash
docker compose -f docker-compose.prod.yml --env-file .env up -d --build
docker compose -f docker-compose.prod.yml ps
```

The web app binds to `127.0.0.1:3000` by default. For a quick direct test without
a reverse proxy, set this in `.env` and restart:

```bash
WEB_BIND=0.0.0.0
```

Then open:

```text
http://YOUR_SERVER_IP:3000/projects/job-search
```

## 4. Put it behind HTTPS

For your existing `sumit-gupta.cloud` Caddy setup, this repo is configured to run
under:

```text
/projects/job-search
```

Keep these values in `.env`:

```bash
NEXT_PUBLIC_BASE_PATH=/projects/job-search
NEXT_PUBLIC_API_BASE=/projects/job-search
APP_COOKIE_SECURE=true
APP_CORS_ORIGINS=https://sumit-gupta.cloud,https://www.sumit-gupta.cloud
```

Add this block before your default portfolio `handle`:

```caddyfile
# Job Search Control Plane
redir /projects/job-search /projects/job-search/ 308
handle_path /projects/job-search/* {
  reverse_proxy job-search-web:3000 {
    header_up Host {host}
    header_up X-Forwarded-Host {host}
    header_up X-Forwarded-Proto {scheme}
  }
}
```

Use `handle_path` so Caddy strips `/projects/job-search` before forwarding to
the Next.js server. The built app still emits prefixed asset and navigation URLs
because `NEXT_PUBLIC_BASE_PATH` is enabled at build time.

If Caddy is running as a Docker container, attach `job-search-web` to the same
external Docker network as Caddy. This server uses a network named `web`, so run
Compose with the Caddy override:

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.caddy.yml --env-file .env up -d --build
```

Set `CADDY_NETWORK=YOUR_CADDY_NETWORK` in `.env` if your Caddy network has a
different name.

If Caddy is installed directly on the VPS instead of running in Docker, proxy to
`127.0.0.1:3000` and keep `WEB_BIND=127.0.0.1`.

### Subdomain alternative

If you prefer a subdomain, leave `NEXT_PUBLIC_BASE_PATH` and
`NEXT_PUBLIC_API_BASE` blank, point the subdomain to the VPS, then reverse proxy
to `127.0.0.1:3000`.

Example Caddyfile:

```caddyfile
jobs.example.com {
  reverse_proxy 127.0.0.1:3000
}
```

When HTTPS is working, set this in `.env`:

```bash
APP_COOKIE_SECURE=true
APP_CORS_ORIGINS=https://jobs.example.com
```

Then restart:

```bash
docker compose -f docker-compose.prod.yml --env-file .env up -d
```

## Useful commands

View logs:

```bash
docker compose -f docker-compose.prod.yml logs -f web api
```

Run a search pipeline manually:

```bash
docker compose -f docker-compose.prod.yml exec api python main.py
```

Update after pushing new code:

```bash
git pull
docker compose -f docker-compose.prod.yml --env-file .env up -d --build
```

Back up Postgres:

```bash
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U jobsearch jobsearch > jobsearch-backup.sql
```
