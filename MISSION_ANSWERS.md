# Day 14 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found (`01-localhost-vs-production/develop/app.py`)

1. **Hardcoded secrets (L17–18):** `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"` viết thẳng trong code, dễ lộ khi push lên Git.
2. **In secret ra log bằng `print()` (L33–34, L38):** dùng `print()` thay vì structured logger, và dòng 34 in thẳng `[DEBUG] Using key: {OPENAI_API_KEY}` ra stdout.
3. **Không có config management (L21–22, L51–53):** `DEBUG = True`, `MAX_TOKENS = 500`, `port=8000` cố định trong code, không đọc từ biến môi trường (`os.getenv`).
4. **Không có health check / readiness endpoint (L42–43):** gọi `GET /health` trả về `404 Not Found` nên platform không biết container sống hay chết.
5. **Bind `host="localhost"` và bật `reload=True` (L51, L53):** `localhost` không nhận traffic từ bên ngoài container; `reload=True` chạy tiến trình file watcher không phù hợp production.
6. **Không xử lý graceful shutdown:** không có `lifespan` hay xử lý `SIGTERM` để chờ hoàn thành request đang chạy trước khi tắt.

### Exercise 1.2: Chạy basic version

- Chạy `python app.py` trong `01-localhost-vs-production/develop` (WSL2):
  - `GET /` → `200 OK`: `{"message":"Hello! Agent is running on my machine :)"}`
  - `POST /ask?question=Hello` → `200 OK`: `{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}`
  - `GET /health` → `HTTP 404`
  - Server log thực tế in: `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this`

### Exercise 1.3: Comparison table

| Feature | Develop (`develop/app.py`) | Production (`production/app.py` + `config.py`) | Why Important? |
|---|---|---|---|
| Config & Secrets | Hardcode `OPENAI_API_KEY`, `port=8000`, `DEBUG=True` (L17–22, L51–53) | Đọc từ biến môi trường qua `Settings` (`os.getenv`), `validate()` kiểm tra `AGENT_API_KEY` khi `ENVIRONMENT=production` (`config.py` L15–46) | Tách biệt code và cấu hình (12-Factor III), đổi môi trường không cần sửa code, tránh lộ secret lên Git. |
| Health check | Không có (`GET /health` → `404`) | Có `GET /health` (200) và `GET /ready` (200 hoặc 503 khi `is_ready=False`) (L135–162) | Cloud/load balancer dùng `/health` để restart container lỗi và `/ready` để ngưng route traffic khi app chưa sẵn sàng hoặc đang tắt. |
| Logging | `print()` thô, log cả API key (L33–34) | `logging` định dạng JSON + `json.dumps(...)`, không log secret (L28–32, L111–122) | Log JSON dễ parse/tìm kiếm trên hệ thống tập trung (Loki, Datadog) và không làm lộ credential. |
| Shutdown | Không xử lý `SIGTERM`, tắt đột ngột | `lifespan` đặt `is_ready=False` khi shutdown + `signal.signal(signal.SIGTERM, handle_sigterm)` (L39–68, L180–189) | Cho phép request đang chạy hoàn tất trước khi container dừng, tránh lỗi 502/mất dữ liệu khi deploy. |
| Network binding | `host="localhost"`, `reload=True` (L51–53) | `host=settings.host` (`0.0.0.0`), `port=settings.port`, `reload=settings.debug` (L194–199) | Container/cloud yêu cầu bind `0.0.0.0` và đọc `PORT` động do platform cấp. |

**Ví dụ anti-pattern đã sửa (kèm dòng code):**
- `develop/app.py` L17: `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và L34: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`
- `production/config.py` L27: `openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))` và `production/app.py` L111–115 chỉ log `event`, `question_length`, `client_ip` bằng `json.dumps(...)`, không bao giờ log key.

---

## Part 2: Docker

### Exercise 2.1: Dockerfile questions (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11` (bản đầy đủ Debian + Python runtime, dung lượng lớn ~1 GB).
2. **Working directory:** `/app` (`WORKDIR /app`).
3. **Tại sao `COPY requirements.txt` trước `COPY ... app.py`:** Để tận dụng **Docker layer cache**. `requirements.txt` ít thay đổi hơn code; nếu chỉ sửa `app.py`, Docker dùng lại layer `pip install` đã cache thay vì cài lại toàn bộ thư viện.
4. **CMD vs ENTRYPOINT:** `CMD` là lệnh mặc định khi container chạy và có thể bị ghi đè dễ dàng qua tham số của `docker run <image> <cmd>`; `ENTRYPOINT` định nghĩa executable cố định (các tham số truyền thêm sẽ nối vào sau nó, muốn đổi phải dùng `--entrypoint`).

### Exercise 2.2: Build và run basic container

Build từ gốc repo:
```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -d --name k5-p2-dev -p 8000:8000 my-agent:develop
```
Kết quả test:
- `GET http://localhost:8000/health` → `{"status":"ok","uptime_seconds":0.2,"container":true}`
- `POST http://localhost:8000/ask?question=What%20is%20Docker%3F` → `{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}`

### Exercise 2.3: Image size comparison (Multi-stage build)

Trong `02-docker/production/Dockerfile`:
- **Stage 1 (`builder`, `python:3.11-slim`):** cài `gcc`, `libpq-dev` và chạy `pip install --no-cache-dir --user -r requirements.txt` vào `/root/.local`.
- **Stage 2 (`runtime`, `python:3.11-slim`):** bắt đầu từ image slim sạch, tạo non-root user `appuser`, chỉ `COPY --from=builder /root/.local /home/appuser/.local` cùng source code (`main.py`, `utils/mock_llm.py`), thêm `HEALTHCHECK` và chạy uvicorn với 2 workers.
- **Tại sao nhỏ hơn:** Không mang theo `gcc`, `libpq-dev`, file tạm build và package thừa của image `python:3.11` đầy đủ.

Số đo thực tế bằng `docker images` / `docker image inspect`:
- **Develop (`my-agent:develop`):** **1.67 GB** (`1,667,780,207` bytes; content size `426 MB`)
- **Production (`my-agent:advanced`):** **240 MB** (`239,815,064` bytes; content size `57.4 MB`)
- **Chênh lệch:** Giảm **~85.6%** (`1,427,965,143` bytes nhỏ hơn)

### Exercise 2.4: Docker Compose stack

Tạo `.env.local` trong `02-docker/production/` và khởi động bằng `docker compose -p k5-day14-docker -f 02-docker/production/docker-compose.yml up -d --build`.

**4 services khởi động trên network `internal`:**
- `nginx` (`nginx:alpine`, mở port `80` & `443` ra host) → reverse proxy & rate limit (`10r/s`), forward tới `agent:8000`
- `agent` (build target `runtime`, port nội bộ `8000`) → `depends_on` `redis` và `qdrant` (khi cả 2 `healthy`)
- `redis` (`redis:7-alpine`, port nội bộ `6379`, volume `redis_data`)
- `qdrant` (`qdrant/qdrant:v1.9.0`, port nội bộ `6333`, volume `qdrant_data`)

**Sơ đồ kiến trúc:**
```text
Client ──▶ Nginx (:80/:443) ──▶ Agent (:8000) ──┬──▶ Redis (:6379)
                                                └──▶ Qdrant (:6333)
```

**Kết quả test qua Nginx:**
- `GET http://localhost/health` → `200 OK`: `{"status":"ok","uptime_seconds":0.4,"version":"2.0.0","timestamp":"2026-11-25T08:18:40.748546"}` (kèm security headers `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`)
- `POST http://localhost/ask` (`{"question": "Explain microservices"}`) → `200 OK`: `{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}`

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy agent Part 6 lên cloud

- **URL public:** `https://apiaithucchien.943269.xyz/day14`
- **Nền tảng:** Oracle Cloud VPS (Ubuntu 24.04) chạy `06-lab-complete/` bằng Docker Compose (`agent` + `redis:7-alpine` cô lập, `AGENT_API_KEY` đặt trong `.env` trên server, không ghi vào code) đi qua Caddy reverse proxy HTTPS (`/day14/*`) và Cloudflare.
- **Kết quả kiểm tra 4 lệnh CP6 từ máy cá nhân:**
  - `GET https://apiaithucchien.943269.xyz/day14/health` → `200` (`{"status":"ok","environment":"production"}`)
  - `GET https://apiaithucchien.943269.xyz/day14/ready` → `200` (`{"status":"ready"}`)
  - `POST https://apiaithucchien.943269.xyz/day14/ask` (không có key) → `401`
  - `POST https://apiaithucchien.943269.xyz/day14/ask` (có `X-API-Key`) → `200` (`{"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","cost_usd":2.01e-05}`)
- **Ảnh minh chứng:** `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png` (chi tiết trong [DEPLOYMENT.md](DEPLOYMENT.md)).

### So sánh `railway.toml` và `render.yaml`

| Tiêu chí | `railway.toml` | `render.yaml` (Blueprint) |
|---|---|---|
| **Định dạng & phạm vi** | TOML, cấu hình cho **1 service** hiện tại (`[build]`, `[deploy]`). | YAML, mô tả **toàn bộ hạ tầng nhiều service** (web + Redis add-on + region + plan) theo kiểu Infrastructure as Code. |
| **Cách build** | Chỉ định `builder = "DOCKERFILE"` (hoặc `"NIXPACKS"`). | Chỉ định `runtime: docker` (hoặc `runtime: python` kèm `buildCommand` + `startCommand`). |
| **Health check** | `healthcheckPath = "/health"` trong `[deploy]`. | `healthCheckPath: /health` trong từng web service. |
| **Quản lý secret & env** | Biến môi trường và secret đặt riêng qua Dashboard hoặc `railway variables set` (không khai báo trực tiếp trong `railway.toml`). | Khai báo ngay trong `envVars:` — hỗ trợ `generateValue: true` (tự sinh random secret), `sync: false` (nhập tay trên dashboard), và `fromService` để lấy `REDIS_URL` từ service Redis cùng Blueprint. |

### Exercise 3.3: GCP Cloud Run CI/CD (`03-cloud-deployment/production-cloud-run/`)

Đọc `cloudbuild.yaml` và `service.yaml`, pipeline CI/CD tự động khi push code lên nhánh `main` gồm 4 bước tuần tự (`waitFor`):
1. **Test (`python:3.11-slim`):** cài `requirements.txt`, `pytest` và chạy `pytest tests/ -v`.
2. **Build (`gcr.io/cloud-builders/docker`):** build Docker image với cache từ tag `:latest` và gắn 2 tag `:$COMMIT_SHA` và `:latest`.
3. **Push (`gcr.io/cloud-builders/docker`):** đẩy các image tag lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **Deploy (`gcr.io/cloud-builders/gcloud`):** chạy `gcloud run deploy ai-agent` lên Cloud Run region `asia-southeast1`, cấu hình `--min-instances=1` (giảm cold start), `--max-instances=10`, giới hạn CPU/RAM (`1 CPU / 512Mi`), truyền env và gắn secret từ Google Secret Manager (`--set-secrets`). File `service.yaml` (Knative) còn khai báo thêm `containerConcurrency: 80`, `livenessProbe` (`/health`) và `startupProbe` (`/ready`).

---

## Part 4: API Security

### Exercise 4.1: API Key authentication (`04-api-gateway/develop/app.py`)

- **Check ở đâu:** Hàm `verify_api_key` (L39–54) dùng `APIKeyHeader(name="X-API-Key", auto_error=False)` và được inject vào `/ask` qua `Depends(verify_api_key)` (L70).
- **Nếu thiếu / sai key:** Thiếu key trả về **401 Unauthorized**; sai key trong bản develop trả về **403 Forbidden** (trong Part 6 chuẩn hóa về **401** cho cả thiếu và sai).
- **Rotate key:** Đọc `AGENT_API_KEY` từ biến môi trường (L35). Khi rotate, hỗ trợ danh sách nhiều key hợp lệ trong giai đoạn chuyển tiếp (hoặc cập nhật env var rồi rolling restart).

**Kết quả test bản develop (`AGENT_API_KEY=secret-key-123`):**

Không có key (`401`):
```http
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
```

Có key (`200`):
```http
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 4.2 & 4.3: JWT Authentication & Rate Limiting (`04-api-gateway/production/`)

- **JWT flow (`auth.py`):** Client gửi `POST /auth/token` với `{"username":"student","password":"demo123"}` → server ký JWT bằng `HS256` chứa `sub`, `role`, `iat`, `exp` (60 phút). Khi gọi `POST /ask`, `verify_token` giải mã header `Authorization: Bearer <token>` để lấy `username` và `role`.
- **Rate limiter (`rate_limiter.py`):**
  - **Thuật toán:** **Sliding Window Counter** (dùng `deque` lưu timestamp các request trong `window_seconds = 60`, loại các timestamp cũ `< now - 60` rồi kiểm tra `len(window) >= max_requests`).
  - **Giới hạn:** User (`student`) = **10 requests/phút** (`rate_limiter_user`); Admin (`teacher`) = **100 requests/phút** (`rate_limiter_admin`).
  - **Bypass/nâng limit cho admin:** Trong `app.py` L141, chọn limiter theo `role` (`rate_limiter_admin if role == "admin" else rate_limiter_user`), hoặc bỏ qua bước `limiter.check()` nếu `role == "admin"`.

**Kết quả test `curl -i` (đã che token):**

1. Không gửi token (`401`):
```http
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
content-type: application/json

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}
```

2. Gửi kèm `Authorization: Bearer <TOKEN_REDACTED>` (`200`):
```http
HTTP/1.1 200 OK
content-type: application/json

{"question":"Explain JWT","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}
```

3. Vòng lặp gọi liên tiếp với tài khoản `student` (limit 10 req/phút) — Request 1..10 trả `200 OK` (`requests_remaining` giảm từ `9` xuống `0`), từ Request 11 trở đi trả **`429 Too Many Requests`**:
```http
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795594826
retry-after: 59
content-type: application/json

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Cost guard (`cost_guard.py`)

- **Ý nghĩa:** Rate limit chỉ giới hạn **tốc độ** (số request/phút), còn Cost guard bảo vệ **chi phí tiền** (số token/USD theo ngày hoặc tháng), vì một vài request dài vẫn có thể tiêu tốn rất nhiều token.
- **Cách hoạt động (`cost_guard.py`):**
  - Định nghĩa đơn giá `PRICE_PER_1K_INPUT_TOKENS` và `PRICE_PER_1K_OUTPUT_TOKENS`.
  - Trước khi gọi LLM, `check_budget(user_id)` kiểm tra chi phí tích lũy so với `daily_budget_usd` (và `global_daily_budget_usd`); nếu vượt ngưỡng thì trả **`402 Payment Required`** (hoặc `503` nếu vượt global budget).
  - Sau khi LLM trả lời, `record_usage(user_id, input_tokens, output_tokens)` cộng dồn token và chi phí.
  - Trong production nhiều instance (như Part 6), lưu tổng chi phí vào **Redis** bằng khóa theo ngày/tháng (vd `cost:YYYY-MM-DD`) và cập nhật nguyên tử bằng `INCRBYFLOAT` + `EXPIRE`.

---

## Part 5: Scaling & Reliability

### Exercise 5.1 & 5.2: Health checks & Graceful shutdown (`05-scaling-reliability/develop/app.py`)

- **Phân biệt `/health` (Liveness) vs `/ready` (Readiness):**
  - `GET /health` kiểm tra process còn sống không (trả `status`, `uptime_seconds`, `checks.memory`); nếu fail, platform sẽ **restart container**.
  - `GET /ready` kiểm tra instance đã sẵn sàng nhận traffic chưa (`_is_ready` và dependencies như Redis); nếu trả **503**, load balancer sẽ **ngừng route traffic mới** vào instance đó (khi startup chưa xong hoặc khi đang shutdown) mà không kill container.
- **Graceful shutdown:** Đăng ký handler `SIGTERM` + dùng `lifespan` (`_is_ready = False` → đợi `_in_flight_requests == 0` với middleware `track_requests`) và `timeout_graceful_shutdown=30`.

**Kết quả test thực tế:**
- `GET /health` → `{"status":"ok","uptime_seconds":0.7,"version":"1.0.0","environment":"development","checks":{"memory":{"status":"ok","used_percent":15.9}}}`
- `GET /ready` → `{"ready":true,"in_flight_requests":1}`
- Gửi `POST /ask?question=hello` rồi gửi `kill -SIGTERM <PID>` ngay sau `0.2s`:
  - Request đang xử lý **vẫn trả `HTTP 200`** (`{"answer":"Đây là câu trả lời từ AI agent (mock)..."}`).
  - Log server ghi nhận: `INFO: Shutting down` → `"POST /ask?question=hello HTTP/1.1" 200 OK` → `🔄 Graceful shutdown initiated...` → `✅ Shutdown complete`.

### Exercise 5.3–5.5: Stateless design & Load balancing (`05-scaling-reliability/production/`)

- **Vì sao state trong RAM hỏng khi scale:** Khi chạy nhiều instance sau load balancer, các request kế tiếp của cùng 1 user có thể rơi vào instance khác nhau; nếu session nằm trong RAM của instance 1 thì instance 2 không thấy lịch sử hội thoại (và mất sạch khi restart).
- **Giải pháp:** Lưu session/history vào **Redis** (`save_session` dùng `_redis.setex(f"session:{session_id}", ttl_seconds, serialized)` với TTL 3600s, `load_session` đọc từ Redis).
- **Kết quả chạy `docker compose -p k5-day14-scaling up -d --build --scale agent=3` và `python test_stateless.py`:**
  - `Session ID: cca64acb-371e-40d4-b9f9-ac0b036d6a60`
  - 5 request liên tiếp được Nginx phân tán qua cả 3 instance: `{'instance-688c28', 'instance-6d213d', 'instance-30f79c'}`.
  - `GET /chat/{session_id}/history` trả đủ **10 messages** (5 user + 5 assistant) — chứng minh state được giữ nguyên vẹn xuyên suốt các instance qua Redis.

---

## Part 6: Final Project (`06-lab-complete/`)

Kết quả chạy `python check_production_ready.py` (chế độ đầy đủ có Docker trong WSL2):

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

- Kích thước Docker image đo được: **297 MB** (< 500 MB).
- `docker stop` thoát êm với exit code `0` trong `0.6s`.

---

## AI log

- **CP0–CP1:** Dùng AI hỗ trợ kiểm tra môi trường WSL2 + Docker Desktop, cài virtualenv Python 3.11.18 (`~/.venv-day14`), chạy thử nghiệm thực tế `01-localhost-vs-production/develop/app.py` và `production/app.py` trong WSL2, đối chiếu kết quả thực tế để điền câu trả lời Part 1. Đã tự kiểm tra đầu ra HTTP (`curl -i`) và log của cả 2 server.
- **CP2:** Dùng AI chạy build 2 Docker image (`my-agent:develop`, `my-agent:advanced`), đo dung lượng bằng `docker images` / `docker image inspect` và khởi chạy kiểm tra Docker Compose stack trong `02-docker/production/`. Đã tự kiểm tra HTTP response qua Nginx trước khi `down -v`.
- **CP3:** Dùng AI chạy thử `04-api-gateway/develop/app.py` và `production/app.py`, thực hiện test `401`, `200` (JWT `student/demo123`) và vòng lặp gây `429`. Đã tự kiểm tra đầu ra và che token trước khi lưu vào `MISSION_ANSWERS.md`.
- **CP4:** Dùng AI chạy thử `05-scaling-reliability/develop/app.py` (test `/health`, `/ready`, `SIGTERM` khi request đang chạy) và chạy Docker Compose `--scale agent=3` kèm `test_stateless.py` trong `05-scaling-reliability/production/`. Đã tự kiểm tra log shutdown và output 3 instance của `test_stateless.py`.
- **CP5 (Part 6):** Dùng AI gợi ý hoàn thiện các `TODO` trong `06-lab-complete/` (`app/config.py`, `app/redis_client.py`, `app/auth.py`, `app/rate_limiter.py`, `app/cost_guard.py`, `app/main.py`, `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `.env.example`, `railway.toml`, `render.yaml`). Đã tự kiểm tra code và chạy `python check_production_ready.py` đạt `PASS 12/12` (`43/43 checks passed`).
- **CP6 (Part 3):** Dùng AI hỗ trợ triển khai `06-lab-complete/` lên Oracle Cloud VPS (`https://apiaithucchien.943269.xyz/day14`) bằng Docker Compose cô lập (`agent` + `redis`) qua Caddy reverse proxy, đọc và tóm tắt `cloudbuild.yaml`/`service.yaml` và so sánh `railway.toml` vs `render.yaml`. Đã tự kiểm tra 4 endpoint công khai bằng `curl` trả đúng 200 / 200 / 401 / 200.
- **CP7 (Part 7 Bước 1):** Dùng AI hỗ trợ chạy chuỗi benchmark `load_test.py` (4 mức concurrency và 3 mức `MOCK_SLOW_RATE`), `eval/run_eval.py` cho `v1` và `v2`, thêm metric `agent_question_length_chars` và bổ sung 2 entry `KNOWLEDGE_BASE` (`jwt`, `hpa`). Toàn bộ số liệu trong `BENCHMARK_REPORT.md` đều lấy trực tiếp từ 10 file JSON đã sinh trong `develop/reports/`.
- **CP8 (Part 7 Bước 2):** Dùng AI hỗ trợ test `alert_rules_test.yml` bằng `promtool`, sửa lỗi thiếu `ENV PYTHONUSERBASE=/home/agent/.local` trong `06-lab-complete/benchmark-observability/production/Dockerfile`, chạy Locust headless `--no-deps` cho `scale=1` và `scale=3`, trích xuất slow trace từ Jaeger (`170effdd107bc82a8efe9cd55b60104f`) cùng JSON log, và thực hiện thí nghiệm phá hệ thống để kích hoạt 3 alert firing đồng thời trên Prometheus. Toàn bộ số liệu lấy từ `scale_1_stats.csv`, `scale_3_stats.csv`, Prometheus API và Jaeger API.
