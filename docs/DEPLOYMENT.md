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
http://YOUR_SERVER_IP:3000
```

## 4. Put it behind HTTPS

Point a domain to the VPS, then reverse proxy to `127.0.0.1:3000`.

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
