# Benchmark & Observability Report — Day 14

> Copy file này thành `BENCHMARK_REPORT.md` trong repo của bạn và điền đầy đủ.
> Mọi con số phải lấy từ report JSON / CSV / screenshot thật, không ước lượng.

**Họ tên:** Nguyễn Thành Liêm (MSSV: 2A202603358)
**Ngày chạy:** 2026-11-25
**Môi trường:** Windows + WSL2 (Ubuntu 26.04, Python 3.11.18) · Docker Desktop 29.9.3

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Đảm bảo trải nghiệm phản hồi nhanh cho người dùng chat interactive; ngưỡng 500ms chịu được ~3% tail latency (~1.7s) rơi vào p99 mà không vi phạm p95. |
| Error rate `/ask` | < 2 % | Cho phép error budget 2% để dung sai lỗi upstream ngẫu nhiên (~1% của mock LLM) mà vẫn giữ độ tin cậy dịch vụ ≥ 98%. |
| Accuracy trên golden dataset | ≥ 85 % | Đủ cao để chặn các bản thiếu RAG/retrieval (v1 chỉ 4.3%) trong CI quality gate, mục tiêu sau khi hoàn thiện knowledge base là 100% không regression. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.7 | 187.1 | 218.5 | 1679.4 | 0.00% | PASS |
| 10 | 35.0 | 188.9 | 215.7 | 1690.9 | 0.67% | PASS |
| 50 | 104.92 | 197.2 | 252.2 | 1706.1 | 1.67% | PASS |
| 100 | 136.73 | 203.9 | 325.2 | 1776.9 | 1.00% | PASS |

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

Không hoàn toàn tuyến tính. Từ concurrency `1 → 10`, RPS tăng gần 7.4 lần (`4.7 → 35.0 req/s`), từ `10 → 50` tăng 3 lần (`35.0 → 104.92 req/s`), nhưng từ `50 → 100` chỉ tăng thêm ~30% (`104.92 → 136.73 req/s`) trong khi `p95` tăng từ `215.7 ms` lên `325.2 ms`. Nguyên nhân là khi nhiều request đồng thời cùng đổ vào 1 process uvicorn, chi phí context switching của event loop, parse/serialize JSON và quản lý kết nối tăng lên khiến latency mỗi request tăng và throughput bắt đầu bão hòa.

### 2.2 Tail latency

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 190.7 | 218.7 | 228.8 |
| 0.03 (mặc định) | 233.7 | 221.6 | 1697.8 |
| 0.1 | 343.6 | 1688.0 | 1712.6 |

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

`p99` (và `p95` khi tỉ lệ request chậm vượt 5%) nhạy nhất với request chậm. Khi `MOCK_SLOW_RATE = 0.03`, latency trung bình (`avg`) chỉ tăng nhẹ `+43 ms` (`190.7 → 233.7 ms`, nhìn rất ổn), nhưng `p99` nhảy vọt hơn 7 lần (`228.8 → 1697.8 ms`). Khi `MOCK_SLOW_RATE = 0.1` (10% request chậm), `avg` mới là `343.6 ms` (vẫn dưới 500ms), nhưng cả `p95` đã vọt lên `1688.0 ms` (vi phạm SLO). `average` bị làm mượt bởi 90–97% request nhanh nên che giấu trải nghiệm tệ của nhóm người dùng gặp đuôi chậm; vì vậy SLO phải đặt theo `p95`/`p99`.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 57.2 | 108.8 | 113.8 |
| Tổng cost (USD) | $0.000405 | $0.000757 | $0.000792 |
| Cost / câu đúng (USD) | $0.00040515 | $0.00003607 | $0.00003443 |
| Quality gate | FAIL | PASS | PASS |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry `(["jwt"], ...)` giải thích JWT là token có chữ ký số và thời điểm hết hạn vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` (và đồng bộ sang `production/utils/mock_llm.py`). |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry `(["hpa", "kubernetes", "autoscal"], ...)` giải thích Kubernetes HPA scale theo CPU, memory hoặc custom metrics vào `KNOWLEDGE_BASE`. |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2 (và CI quality gate):**

- **Trade-off:** So với `v1`, `v2` có thêm bước retrieval và đưa context vào prompt nên tốn khoảng gấp đôi số token mỗi câu (`108.8–113.8` vs `57.2`) và latency `p95` tăng nhẹ (`+34.5 ms` ở lần đo `eval_v2`), nhưng độ chính xác tăng từ `4.3%` lên `91.3% → 100.0%`. Nhờ trả lời đúng gần như mọi câu, **cost trên mỗi câu trả lời đúng** của `v2` (`$0.00003443`) **rẻ hơn ~11.8 lần** so với `v1` (`$0.00040515`).
- **CI Quality Gate:** `eval/run_eval.py` trả về **exit code `1`** nếu `accuracy < --min-accuracy` hoặc có câu nào bị regression so với `--baseline` (`eval_v2_fixed.json` đạt `100%`, 0 regression → exit code `0`, `PASS`; thử chạy `v1` với `--min-accuracy 0.85 --baseline reports/eval_v2.json` in `❌ FAIL` và exit code `1`). Trong GitHub Actions, dùng bước dưới đây để tự động chặn merge PR khi chất lượng tụt:
  ```yaml
  name: quality-gate
  on: [pull_request]
  jobs:
    eval:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - uses: actions/setup-python@v5
          with: { python-version: "3.11" }
        - name: Run agent + eval
          working-directory: 06-lab-complete/benchmark-observability/develop
          run: |
            pip install -r requirements.txt
            AGENT_VERSION=v2 MOCK_ERROR_RATE=0 python app.py &
            sleep 3
            python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85 --baseline reports/eval_v2.json
  ```

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (`screenshots/grafana-dashboard.png`, thấy rõ Golden Signals)
- [x] Một trace chậm trong Jaeger (`screenshots/jaeger-slow-trace.png`, thấy span nào chiếm thời gian)
- [x] Một trace lỗi trong Jaeger (`screenshots/jaeger-error-trace.png`, có event `exception`)
- [x] Trang Alerts của Prometheus với ≥ 2 alert đang **firing** (`screenshots/prometheus-alert-firing.png`)

### 4.2 Thí nghiệm "phá hệ thống"

Chạy stack với `docker compose -p k5-day14-observability` và tải Locust 30 users, sau khi unit test alert rules (`promtool test rules /p/alert_rules_test.yml`) trả về `SUCCESS`:

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`for: 1m`) | ~70s (pending ở 10s, firing ở 70s) | Error rate (`/ask` 5xx) & LLM Calls ok/error |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`for: 2m`) | ~130s (pending ở 10s, firing ở 130s) | Latency p95 / p99 & LLM p95 |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`for: 2m`) | ~10s (vượt ngưỡng $2/h tích hợp cửa sổ 5m từ đợt tải trước) | Cost USD/giờ & LLM Latency |
| D | `docker pause` 1 instance | *(Chưa chạy cô lập; theo rule `up{job="agent"} == 0` với `for: 30s` sẽ firing sau ~30s; lúc restart container đã quan sát thấy chuyển sang `pending` ở 10s)* | ~30s (theo rule `for: 30s`) | Instances up & Nginx 504 (không hiện trên error rate của agent) |
| E | `AGENT_VERSION=v1` | Không có alert nào firing | Không firing | Retrieval hit ratio mất / Tokens/s giảm / Bảng Version |

**Trả lời thêm Exercise 7.4 (Prometheus / Grafana / Nginx):**
- **Khoảng cách `avg` (`231 ms`) ↔ `p95` (`293 ms`) lúc chạy bình thường (`scale=3`):** ở `MOCK_SLOW_RATE=0.03`, chỉ ~3% request chậm nên phần lớn nằm trong 95% đầu, p95 chỉ nhỉnh hơn avg ~62 ms, còn đuôi chậm ~1.7s dồn vào p99.
- **Nginx có chia đều traffic không?** Có — đo từ Prometheus `sum by (instance) (rate(http_requests_total{route="/ask"}[1m]))` trên 3 instance cho kết quả lần lượt `13.35`, `13.98`, `12.80 req/s` (cân bằng đều qua round-robin).
- **Vì sao input tokens/s (`3096.7 tok/s`) lớn hơn output tokens/s (`1622.7 tok/s`)?** Vì prompt gửi vào LLM ở v2 chứa cả `SYSTEM_PROMPT`, context tài liệu truy xuất từ `KNOWLEDGE_BASE` và câu hỏi người dùng, dài hơn câu trả lời ngắn gọn ở đầu ra.
- **`curl http://localhost:8080/metrics` trả về gì? Vì sao?** Trả về **`404 Not Found`**. Nginx chủ động chặn `/metrics` ở cổng public (`8080`) để tránh lộ thông tin nội bộ hệ thống (Prometheus scrape trực tiếp qua mạng Docker nội bộ `obs_net` tới `agent:8000/metrics`).

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Các alert hạ tầng (`error rate`, `p95 latency`, `up`, `cost`) chỉ đo được dịch vụ có chạy nhanh và không crash hay không, không biết câu trả lời **đúng hay sai**. Để phát hiện suy giảm chất lượng như chuyển nhầm `v1` (mất RAG):
1. Chạy **Eval tự động trên golden dataset** (`eval/run_eval.py --min-accuracy 0.85 --baseline ...`) làm quality gate trong CI/CD trước khi deploy.
2. Giám sát thêm **business/RAG metrics** trên dashboard (ví dụ `retrieval_hit_ratio` tụt về 0, phân bố độ dài câu trả lời / token input giảm đột ngột) và thiết lập alert khi tỉ lệ retrieval hit giảm bất thường.
3. Chạy **online eval / sampling** trên traffic thật bằng LLM-as-judge hoặc thu thập user feedback (thumbs up/down).

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất tìm được trong Jaeger (truy vấn `/api/v3/traces` & đối chiếu log):

- `trace_id`: `170effdd107bc82a8efe9cd55b60104f`
- Tổng thời gian: `1789.74 ms`
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (`1765.32 ms`, `98.6%`; `agent.run`: `1783.30 ms` / `99.6%`; `agent.retrieve_context`: `17.82 ms` / `1.0%`)
- Dòng log tương ứng (grep theo `trace_id`):

```json
{"ts": "2026-11-25T09:15:18.840886+00:00", "level": "INFO", "service": "observable-agent", "instance": "2cb9f51730e0", "event": "http_request", "trace_id": "170effdd107bc82a8efe9cd55b60104f", "span_id": "d18bfe043292229e", "request_id": "3becaa4e2a93", "method": "POST", "route": "/ask", "status": 200, "ms": 1787.3}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Số liệu lấy trực tiếp từ dòng `Aggregated` trong `benchmark-results/scale_1_stats.csv` và `scale_3_stats.csv` (chạy `--no-deps` để giữ đúng 1 và 3 instance):

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 65.56 | 190 | 230 | 1700 | 79 / 7793 (1.01%) |
| 3 | 66.15 | 190 | 220 | 1700 | 56 / 7864 (0.71%) |

*(Riêng endpoint `POST /ask`: 1 instance đạt `60.06 req/s`, p50 `190ms`, p95 `230ms`, `79/7140` lỗi 503; 3 instance đạt `60.25 req/s`, p50 `190ms`, p95 `220ms`, `56/7162` lỗi 503.)*

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

Scale từ 1 lên 3 instance chỉ giảm nhẹ `p95` từ `230 ms` xuống `220 ms` và gần như giữ nguyên `RPS` (`65.56 → 66.15 req/s`). Nguyên nhân:
1. 100 user của Locust có khoảng nghỉ (`wait_time`) giữa các request nên tổng tải sinh ra (~66 req/s) chưa làm bão hòa CPU của 1 container FastAPI async.
2. Quan trọng hơn, nút thắt thời gian thực sự nằm ở **bước gọi upstream LLM** (`chat mock-llm-small`, chiếm ~98.6% thời gian xử lý mỗi request ở trace trên). Vì agent xử lý bất đồng bộ (`async/await`), việc thêm replica giúp tăng sức chịu tải đồng thời khi traffic lớn hơn nhiều, nhưng **không thể rút ngắn độ trễ nội tại của chính LLM call**.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. Không đánh giá tốc độ bằng giá trị trung bình (`avg`) vì tail latency (`p95`/`p99`) mới phản ánh nhóm người dùng chờ lâu; mọi tối ưu hóa hay SLO phải bám vào percentile.
  2. Benchmark chất lượng (`eval` trên golden dataset + quality gate) bắt buộc đi cùng observability hạ tầng, vì lỗi logic/mất RAG không làm error rate hay latency đỏ.
  3. 3 trụ cột **Metrics (Prometheus/Grafana) – Traces (OpenTelemetry/Jaeger) – Logs (JSON có `trace_id`)** kết hợp giúp đi nhanh từ triệu chứng tổng quan → span gây chậm → dòng log chi tiết.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?
  - Thêm metric & alert cho **chất lượng & kinh doanh**: `retrieval_hit_ratio` xuống thấp bất thường, `rate_limit_429_total` tăng đột biến (dấu hiệu bị spam/DDoS), và alert **Cost Budget theo ngày** + **Redis connection failure / `/ready` 503**.
