# Hướng dẫn dùng API ACE-Step (tiếng Việt)

Tài liệu này chỉ tập trung vào **cách dùng**. Đặc tả đầy đủ của mọi endpoint và mọi tham
số nằm ở [`docs/en/API.md`](../en/API.md); ở đây là những gì cần để chạy được việc.

---

## 1. Khởi động server

```bash
cd /path/to/ACE-Step-1.5
acestep-api --host 127.0.0.1 --port 8001
```

Chờ tới khi log hiện `All models initialized successfully!`. Lần đầu mất khoảng 90 giây
vì phải nạp model.

Kiểm tra server sống:

```bash
curl -s http://127.0.0.1:8001/health
# {"data":{"status":"ok","service":"ACE-Step API",...},"code":200,...}
```

`/health` luôn mở, kể cả khi đã bật khóa API.

---

## 2. Khóa API (tùy chọn)

Chỉ cần khi server không phải của riêng bạn, ví dụ máy dùng chung hoặc bind ra ngoài
`127.0.0.1`.

```bash
# Cách 1: cờ dòng lệnh
acestep-api --host 127.0.0.1 --port 8001 --api-key SECRET123

# Cách 2: biến môi trường (cũng đọc được từ file .env)
export ACESTEP_API_KEY=SECRET123
acestep-api --host 127.0.0.1 --port 8001
```

Đặt cả hai thì cờ thắng. Không đặt gì cả thì server mở, ai gọi cũng được.

Khi đã bật khóa, mọi request phải mang nó theo — hoặc bằng header, hoặc bằng trường
`ai_token` trong body:

```bash
curl ... -H 'Authorization: Bearer SECRET123'     # cách A
curl ... -d '{"ai_token":"SECRET123", "prompt":"..."}'   # cách B
```

Thiếu hoặc sai khóa thì nhận `401`.

> **Lưu ý:** `GET /v1/models` **không** bị khóa che, do router tương thích OpenRouter được
> nạp trước và bản `/v1/models` của nó không gắn xác thực. Endpoint đó chỉ lộ tên model và
> trạng thái nạp, nhưng đừng coi khóa API là bịt được mọi đường.

---

## 3. Dạng trả về chung

Mọi response đều bọc trong một lớp vỏ giống nhau:

```json
{
  "data": { ... },
  "code": 200,
  "error": null,
  "timestamp": 1700000000000,
  "extra": null
}
```

Dữ liệu thật nằm ở `data`. `code: 200` là thành công, `error` khác `null` là có lỗi.

---

## 4. Sinh nhạc bằng curl — luồng bất đồng bộ 3 bước

API **không** trả về nhạc ngay trong một lần gọi. Phải: gửi task → hỏi kết quả → tải file.

### Bước 1 — Gửi task

```bash
curl -s -X POST http://127.0.0.1:8001/release_task \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer SECRET123' \
  -d '{
    "prompt": "upbeat pop song, female vocal, summer mood",
    "lyrics": "[Verse]\nHello world\n[Chorus]\nSing it out loud",
    "audio_duration": 120,
    "inference_steps": 8
  }'
```

Trả về:

```json
{"data": {"task_id": "550e8400-...", "status": "queued", "queue_position": 1}, "code": 200}
```

Giữ lấy `task_id`.

### Bước 2 — Hỏi kết quả

Lặp lại lệnh này cho tới khi `status` bằng `1`. Cách 2 giây hỏi một lần là hợp lý.

```bash
curl -s -X POST http://127.0.0.1:8001/query_result \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer SECRET123' \
  -d '{"task_id_list": ["550e8400-..."]}'
```

| `status` | Nghĩa |
| :--- | :--- |
| `0` | Đang xếp hàng **hoặc** đang chạy — API không phân biệt hai trạng thái này |
| `1` | Xong, đã có kết quả |
| `2` | Thất bại |

Vì `0` gộp cả "đang chờ" lẫn "đang chạy", không có cách nào biết task của bạn đã tới lượt
hay chưa. Cứ hỏi lại theo chu kỳ, đừng cố suy ra tiến độ.

Có thể hỏi nhiều task một lúc: `"task_id_list": ["id1", "id2", "id3"]`.

### Bước 3 — Tải file

Trường `data[0].result` là **một chuỗi JSON**, phải parse thêm một lần nữa mới lấy được
mảng kết quả. Trong đó `file` là đường dẫn tải:

```json
[{"file": "/v1/audio?path=...", "seed_value": "12345", "metas": {...}, ...}]
```

```bash
curl -s -H 'Authorization: Bearer SECRET123' \
  "http://127.0.0.1:8001/v1/audio?path=<đường-dẫn-đã-url-encode>" -o bai1.mp3
```

### Làm gọn cả ba bước bằng `jq`

```bash
K='Authorization: Bearer SECRET123'
B=http://127.0.0.1:8001

TID=$(curl -s -X POST $B/release_task -H "$K" -H 'Content-Type: application/json' \
  -d '{"prompt":"lo-fi hip hop, rain on a window","audio_duration":90}' | jq -r .data.task_id)

until [ "$(curl -s -X POST $B/query_result -H "$K" -H 'Content-Type: application/json' \
  -d "{\"task_id_list\":[\"$TID\"]}" | jq -r '.data[0].status')" = "1" ]; do sleep 2; done

URL=$(curl -s -X POST $B/query_result -H "$K" -H 'Content-Type: application/json' \
  -d "{\"task_id_list\":[\"$TID\"]}" | jq -r '.data[0].result | fromjson | .[0].file')

curl -s -H "$K" "$B$URL" -o bai1.mp3
```

---

## 5. Các tham số hay dùng của `/release_task`

| Tham số | Mặc định | Ý nghĩa |
| :--- | :--- | :--- |
| `prompt` | `""` | Mô tả bài nhạc. Bí danh: `caption` |
| `lyrics` | `""` | Lời. Để rỗng thì ra nhạc không lời |
| `audio_duration` | tự chọn | Độ dài (giây), khoảng 10-600. Bí danh: `duration`, `target_duration` |
| `inference_steps` | `8` | Số bước. Model turbo: 1-20 (nên để 8). Model base: 1-200 (nên 32-64) |
| `audio_format` | `"mp3"` | `mp3`, `flac`, `wav`, `wav32`, `opus`, `aac` |
| `vocal_language` | `"en"` | Ngôn ngữ lời hát: `en`, `zh`, `ja`, `vi`... |
| `seed` | `-1` | Cố định seed để tái tạo lại đúng bài đó; nhớ đặt `use_random_seed: false` |
| `batch_size` | `2` | Số bản sinh ra **từ cùng một prompt**. Tối đa 8 |
| `thinking` | `false` | Bật LM 5Hz sinh audio code trước, nhạc thường khá hơn nhưng chậm hơn |
| `model` | mặc định | Chọn model DiT khác; xem danh sách bằng `GET /v1/models` |
| `guidance_scale` | `7.0` | Chỉ có tác dụng với model base, không tác dụng với turbo |

API chấp nhận cả `snake_case` lẫn `camelCase`, và nhiều tham số có bí danh
(`audio_duration` = `duration` = `audioDuration`). **Nhưng file job của `api_batch.py` thì
không** — xem mục 7.

`batch_size` sinh ra **N biến thể của cùng một prompt**, không phải N bài khác nhau. Muốn
nhiều bài khác nhau thì mỗi bài một job. Giữ `batch_size` ≤ 8: qua REST không có tầng nào
chặn, và `batch_size: 16` sẽ hỏng cả task mà không báo lỗi gì rõ ràng.

---

## 6. Sinh một bài bằng CLI — `api_client.py`

Công cụ này làm hết cả ba bước ở trên.

```bash
python -m acestep.api_client \
  --base-url http://127.0.0.1:8001 \
  --api-key SECRET123 \
  --prompt "lo-fi hip hop beat, rain on a window, study mood" \
  --audio-duration 150 \
  --output-dir ./out
```

Mặc định: `--base-url http://127.0.0.1:8001`, `--output-dir api_outputs`,
`--poll-interval 2`, `--timeout 900` (giây, là thời gian tối đa chờ **một** bài).

Thoát với mã `0` nếu thành công, `1` nếu lỗi (kể cả hết giờ), kèm dòng `error: ...`.

---

## 7. Sinh hàng loạt rồi ghép thành một file — `api_batch.py`

Đây là cách dùng cho việc tạo nhiều bài rồi nối lại thành một bản mp3 dài.

### Bước 1 — Viết file `jobs.jsonl`

Mỗi dòng là một bài, viết bằng JSON. Có mẫu sẵn ở
[`examples/batch_jobs.jsonl`](../../examples/batch_jobs.jsonl).

```jsonl
{"id": "t01", "prompt": "warm acoustic folk, sunrise road trip", "lyrics": "[Verse]\nHeaded west before the light", "audio_duration": 180}
{"id": "t02", "prompt": "moody synthwave instrumental, night drive", "lyrics": "", "audio_duration": 180}
{"id": "t03", "prompt": "epic orchestral trailer theme", "lyrics": "", "audio_duration": 180}
```

`id` không bắt buộc — bỏ trống thì hệ thống tự sinh từ nội dung job. Nhưng đặt tay thì log
dễ đọc và tên file dễ tra hơn.

**Tên khóa hợp lệ trong file job khác với tên tham số của REST API.** Chúng là tên cờ dòng
lệnh bỏ dấu gạch, và **không có bí danh**: phải viết `audio_duration`, viết `duration` sẽ
bị từ chối. Có đúng 18 khóa:

`audio_duration`, `audio_format`, `batch_size`, `guidance_scale`, `inference_steps`,
`lyrics`, `model`, `prompt`, `reference_audio`, `repaint_mode`, `repaint_strength`,
`repainting_end`, `repainting_start`, `seed`, `src_audio`, `task_type`, `thinking`,
`vocal_language`.

Khóa lạ bị báo lỗi kèm số dòng **trước khi** gửi bất cứ gì lên server, nên sai chính tả
không làm bạn mất thời gian chạy.

### Bước 2 — Chạy

```bash
python -m acestep.api_batch \
  --jobs jobs.jsonl \
  --base-url http://127.0.0.1:8001 \
  --api-key SECRET123 \
  --output-dir ./album \
  --concat ./album/album.mp3
```

Kết quả: mỗi bài một file trong `./album/`, cộng thêm `album.mp3` là toàn bộ nối liền.

### Những điều cần biết

**Chạy tiếp sau khi đứt.** Mỗi job xong được ghi ngay một dòng vào
`./album/manifest.jsonl`. Đứt giữa chừng thì chạy **đúng lệnh cũ** — nó đọc manifest, bỏ
qua bài đã xong, làm tiếp phần còn lại. Muốn làm lại từ đầu thì thêm `--no-resume`.

**Ghép lại mà không sinh lại.** Chạy lại lệnh trên khi mọi bài đã xong thì in
`nothing to do` rồi vẫn xuất `album.mp3`. Dùng để dựng lại album sau khi lỡ xóa, hoặc để
thêm `--concat` vào một mẻ đã chạy xong từ trước.

**Thứ tự album lấy từ file jobs, không phải thứ tự chạy xong.** Muốn đổi thứ tự thì sắp
lại các dòng trong `jobs.jsonl` rồi chạy lại — không phải sinh lại bài nào.

**`--concat` cần `ffmpeg` trong `PATH`.** Nếu định dạng vào và ra giống nhau thì nó chép
thẳng luồng, không giải mã lại, nên không mất thêm chất lượng.

**`Ctrl-C` an toàn nhưng tốn.** Client thoát trong khoảng một giây, manifest không hỏng,
mọi bài đã xong đều còn. Nhưng server **không hủy** những task đang chạy dở; lần chạy sau
sẽ gửi lại chúng như task mới, nên server làm hai lần. Với `--max-inflight` mặc định là 8,
ngắt giữa chừng tốn tối đa 8 lần sinh trùng.

**`--max-inflight` không làm nhanh hơn.** Server chỉ có một worker, mọi job chạy tuần tự
trên một GPU. Tăng số này chỉ để xếp sẵn nhiều job hơn trong hàng đợi, tránh bị trả
`429`; nó mua độ sâu hàng đợi, không mua tốc độ.

**`--timeout` ở chế độ batch nghĩa khác.** Đây là ngưỡng *đình trệ*: nếu suốt chừng ấy giây
(mặc định 1800) mà **không job nào** xong thì mẻ bỏ các job đang bay. Nó không phải giới
hạn thời gian chờ của từng job trong hàng đợi. Ba lần đình trệ liên tiếp thì mẻ dừng hẳn.

**Mã thoát:** `0` nếu mọi job thành công, `1` nếu có job hỏng hoặc `--concat` không tạo
được file.

---

## 8. Tốc độ thực đo

Đo trên một H100, `inference_steps: 8`, `audio_duration: 180`:

- **Khoảng 16 giây cho mỗi bài 3 phút** khi model đã nóng (29 lần sinh, thấp nhất 14s, trung
  vị 16s, cao nhất 41s).
- Request **đầu tiên** sau khi khởi động chậm hơn hẳn — đo được 101 giây — vì tính cả thời
  gian nạp model. Đừng lấy con số này để ước lượng cả mẻ.
- Theo đó, 20 bài dài 3 phút tốn khoảng 5-6 phút GPU để có 1 tiếng nhạc. Thời gian tăng
  tuyến tính theo số bài vì mọi thứ chạy tuần tự.

---

## 9. Lỗi hay gặp

| Hiện tượng | Nguyên nhân |
| :--- | :--- |
| `401` ở mọi request | Server đang bật khóa mà request không mang `Authorization` hoặc `ai_token` |
| `429 Server busy: queue is full` | Hàng đợi đầy. `api_batch.py` tự xử lý, không tính là lỗi |
| Job lỗi, `files=0`, không thông báo gì rõ | Thường do `batch_size` > 8 |
| Khóa lạ trong `jobs.jsonl` bị từ chối | Dùng tên REST thay vì tên khóa của job, ví dụ `duration` thay cho `audio_duration` |
| `status` mãi bằng `0` | Bình thường — `0` gộp cả xếp hàng lẫn đang chạy. Kiểm tra log server nếu quá lâu |
| `--concat` báo thiếu `ffmpeg` | Cài `ffmpeg` và để nó trong `PATH` |

---

## 10. Đọc thêm

- [`docs/en/API.md`](../en/API.md) — đặc tả đầy đủ: mọi endpoint, mọi tham số, chế độ
  `cover`/`repaint`, tải file lên, biến môi trường, API huấn luyện.
- [`docs/en/CLI.md`](../en/CLI.md) — trình hướng dẫn CLI tương tác.
- [`examples/batch_jobs.jsonl`](../../examples/batch_jobs.jsonl) — file job mẫu.
