# K06 integration benchmark

Runner đọc CSV đã chuẩn bị, tạo phòng test mới trong cả Edge và Backend cho từng lượt, và kiểm tra cảnh báo chờ duyệt khi khói đổi mà mode vẫn LOCK. Cấu hình hiện hỗ trợ M3/M4 và bốn biến thể K06. Mặc định chạy K06-01 và K06-02. K06-03 và K06-04 đo chặn nhầm.

## Chuẩn bị

- Chạy từ repo root trong Ubuntu/WSL với Python 3.11 trở lên và Docker Compose.
- Chuẩn bị một stack Compose cách ly có service `api`, `ai-agent`, PostgreSQL Edge/Backend và Mosquitto. Broker chỉ có subscriber thử nghiệm. Chạy trên stack riêng nếu root Compose đang được dùng cho thiết bị thật. Tên project được truyền bằng `--project`.
- Runner kết nối loopback và kiểm tra bốn cờ trên process Backend, hai cờ liên quan trên Edge và trạng thái HITL thực tế. Dùng địa chỉ/port đã publish của đúng stack. `--compose-file` mặc định là Compose của repo.
- Chuẩn bị token admin/lecturer test. Đặt các biến `BENCH_EDGE_DSN`, `BENCH_BACKEND_DSN` (dạng `postgresql://...` cho **hai DB riêng**) và `BENCH_APPROVAL_TOKEN`. Nếu broker cần auth, đặt `BENCH_MQTT_USERNAME` và `BENCH_MQTT_PASSWORD`. Giữ bí mật trong shell hoặc file cục bộ đã ignore.
- Runner append fixture vào DB test và giữ các phòng/proposal cùng command để đối soát. Mỗi lượt dùng UUID riêng. Dọn dữ liệu bằng vòng đời của stack test.

```bash
python3 -m venv benchmark_local/.venv
source benchmark_local/.venv/bin/activate
python -m pip install -r benchmark/requirements.txt
```

Manifest mặc định của CLI K06 với proposal cố định là [k06_cases.csv](k06_cases.csv). Để chạy bộ có proposal do Agent tạo, xem [runner end-to-end](../experiment/README.md).

## Chạy

Chạy các lệnh Compose trên **stack test đã cách ly**. Ví dụ với một Compose project tên `smartcampus-bench`:

```bash
export SAFETY_PROMPT_GUARD_ENABLED=true SAFETY_FSM_ENABLED=true SAFETY_HITL_ENABLED=true

SAFETY_TOCTOU_BINDING_ENABLED=false docker compose -p smartcampus-bench up -d --force-recreate api ai-agent
python benchmark/run_k06.py --project smartcampus-bench --profile M3 --isolated-test-stack

SAFETY_TOCTOU_BINDING_ENABLED=true docker compose -p smartcampus-bench up -d --no-deps --force-recreate api ai-agent
python benchmark/run_k06.py --project smartcampus-bench --profile M4 --isolated-test-stack
```

Nếu stack cần Compose file hoặc port khác, truyền `--compose-file`, `--backend-url`, `--edge-url` và `--mqtt-port` tương ứng. Dùng `--case K06-03 --case K06-04` để chạy hai ca chặn nhầm. Dùng `--repeat 3` để lặp ba lần. Mỗi lần runner kiểm tra trạng thái DB và version Edge sau khi tạo pending, approve đúng một lần, rồi quan sát các frame MQTT của phòng riêng.

## Đọc kết quả

Mặc định mỗi lệnh tạo một thư mục mới bên dưới `benchmark_local/runs/` chứa `results.csv` và JSON bằng chứng. `predicted_outcome` là dự đoán theo profile. `policy_agreement` đối chiếu với oracle của case. K06-02 dispatch trên M3 có thể đúng dự đoán profile và sai oracle cùng lúc. Chặn K06-03/K06-04 trên M4 có thể đúng dự đoán nhưng là chặn nhầm theo policy thử nghiệm.

Lệnh trả 0 khi mọi lượt khớp dự đoán profile, 1 khi có kết quả lệch hoặc lượt chưa kết luận được, và 2 khi preflight thất bại. `edge_frames` đếm frame khớp Edge command ID, còn `backend_frames` đếm frame bổ sung khớp proposal ID. Ca chặn chỉ có verdict xác định khi response và cửa sổ MQTT đồng thuận. Fixture ghi trực tiếp DB Edge, nên phạm vi kết luận là Backend → Edge → broker test.
