# Deployment Information

## Public URL
https://apiaithucchien.943269.xyz/day14

## Platform
VPS (Oracle Cloud Ubuntu 24.04 + Docker Compose + Caddy reverse proxy HTTPS qua Cloudflare; kèm cấu hình sẵn `railway.toml` và `render.yaml` trong `06-lab-complete/`)

## Test Commands

### Health & Readiness Check
```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://apiaithucchien.943269.xyz/day14/health
# Expected: 200

curl -sS -o /dev/null -w '%{http_code}\n' https://apiaithucchien.943269.xyz/day14/ready
# Expected: 200
```

### API Test (authentication)
```bash
# Không có API key -> 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST https://apiaithucchien.943269.xyz/day14/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'

# Có API key -> 200
curl -X POST https://apiaithucchien.943269.xyz/day14/ask \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "What is deployment?"}'
```

## Environment Variables Set (trên server, không commit vào Git)
- `PORT=8000`
- `ENVIRONMENT=production`
- `REDIS_URL=redis://redis:6379/0`
- `AGENT_API_KEY=<đặt trên server>`
- `RATE_LIMIT_PER_MINUTE=30`
- `DAILY_BUDGET_USD=5.0`

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
