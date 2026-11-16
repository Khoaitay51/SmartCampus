# Benchmark luồng duyệt

Entry point: `python experiment/run_approval.py`. Runner áp dụng các fixture cho phòng test riêng, tạo recommendation, duyệt qua Backend và kiểm verdict cùng bản tin trên broker cách ly. Các ca hiện có thuộc **K01, K03–K09 và K13** trên M3/M4.

## Thêm case

1. Thêm dòng vào [approval_cases.csv](approval_cases.csv) với mã case duy nhất, `scope=approval_flow`, profile, tên fixture và oracle (`allow`, `reject_stale` hoặc `no_extra_dispatch`).
2. Thêm fixture theo tên vào [approval_fixtures.json](approval_fixtures.json). Chọn trạng thái đầu và lệnh test `fan`, `buzzer`, `light` hoặc `mode_saving` và giải thích lý do của đề xuất. `before_proposal` và `before_approval` là hai chuỗi thay đổi trạng thái có thứ tự. Sau mỗi bước, runner xác nhận DB và chờ Edge thấy version mới. Ghi rõ dự đoán theo profile để so riêng với oracle.
3. Chạy ca mới và đối chiếu cả `policy_agreement` lẫn `matches_prediction`.

K06-02 có một bước `smoke_state: NORMAL` sau khi tạo proposal. K03-01 dùng cùng thao tác hai lần, `NORMAL` rồi `SUSPECTED`. K03-02 đặt chuỗi tương tự trước khi tạo proposal mới. K08 đổi room mode hai lần. Một bước cập nhật khói về đúng giá trị cũ ghi một timestamp mới để kiểm tra K06-04.

Fixture hỗ trợ ghi trạng thái trên Edge DB test. Tên fixture và các giá trị CSV được kiểm tra trước khi chạy. Adapter giữ HTTP, SQL và MQTT. `experiment/run_approval.py` và lệnh K06 cũ dùng chung code.

## Chạy

Chuẩn bị Docker project, biến môi trường và Python venv như trong [hướng dẫn K06](../benchmark/README.md). Chạy từng profile trên đúng stack test. Bỏ `--case` để chạy mọi case áp dụng trong manifest mặc định.

```bash
python experiment/run_approval.py --project smartcampus-bench --profile M4 \
  --isolated-test-stack --case K09-01 --case K09-02 --case K13-01
```

Kết quả mặc định nằm trong `benchmark_local/runs/`. Mỗi file JSON chứa snapshot trước proposal, sau từng bước fixture và ngay trước approve, cùng verdict HTTP và bản tin MQTT. Dùng `--manifest` và `--fixtures` để trỏ tới dữ liệu cục bộ.

## Hai lần gọi duyệt

- **K09-01** đặt `approve_first: "mode_saving"`. Runner tạo hai đề xuất pending cùng snapshot, duyệt lệnh chuyển mode, thu lệnh và xác nhận Edge đã lưu `SAVING`, rồi duyệt đề xuất quạt cũ. Frame LED phát sinh từ mode transition được lưu riêng với lệnh mục tiêu.
- **K09-02** đặt `approve_first: "light"`. Runner xác nhận snapshot giữ nguyên sau đề xuất đèn rồi mới duyệt đề xuất quạt.
- **K13-01** đặt `approve_first: "same_proposal"`. Runner xác nhận lượt một có đúng một command ID Edge. Lượt hai gửi cùng proposal ID qua API duyệt, sau đó đối chiếu HTTP 400, số command ID mới trong DB và số frame mới trong cửa sổ MQTT. JSON chứa bằng chứng của cả hai lượt. Ca này kiểm tra thao tác duyệt lặp tuần tự.

## Tên profile và CSV tổng

| Profile | Prompt Guard | FSM | HITL | Binding |
|---|---|---|---|---|
| M0 | Off | Off | Off | Off |
| M1 | On | Off | Off | Off |
| M2 | On | On | Off | Off |
| M3 | On | On | On | Off |
| M4 | On | On | On | On |

Luồng duyệt hỗ trợ M3 và M4. Dùng `--manifest benchmark_local/cases.csv` để đọc toàn bộ danh sách cục bộ. Runner chọn các dòng có scope `approval_flow`, fixture đã hỗ trợ và profile trùng với cấu hình hiện tại. Các log cũ giữ mã cấu hình tại thời điểm chạy.

Sau khi chạy M3 và M4, gộp hai CSV vào một bảng bao phủ cả ma trận:

```bash
python experiment/export_results.py --manifest benchmark_local/cases.csv \
  --output benchmark_local/results_m0_m4.csv \
  benchmark_local/runs/<M3-run>/results.csv benchmark_local/runs/<M4-run>/results.csv
```

Cột `run_status` phân biệt `observed`, `not_applicable`, `not_implemented` và `not_run`. Chỉ các dòng đã thực hiện mới có verdict và đường dẫn bằng chứng. Khi lặp lại, chọn output mới hoặc file tổng của một đợt riêng.

## Chạy đủ ma trận M0–M4

Runner đầy đủ nằm ở `experiment/run_benchmark.py`. Manifest mặc định là [e2e_cases.csv](e2e_cases.csv), có 31 dòng catalog trừ K02. Dùng `--manifest benchmark_local/cases.csv` nếu muốn dùng CSV cục bộ. Runner áp dụng đúng cờ profile và kiểm tra chúng trong container trước khi chạy.

1. Cài `benchmark/requirements.txt` trong venv. Chuẩn bị Ollama local với `qwen2.5:1.5b`; có thể chọn model/tuyến Ollama bằng `BENCH_OLLAMA_MODEL` và `BENCH_OLLAMA_URL`.
2. Khởi động project test qua `docker compose -p smartcampus-full-benchmark -f experiment/compose.test.yml up -d api ai-agent`. Compose test chỉ publish trên loopback, dùng DB tạm và broker riêng. Nó dùng các image SmartCampus đã có trên máy.
3. Đặt `BENCH_EDGE_DSN=postgresql://bench:local_fixture_only@127.0.0.1:25434/edgebench`, `BENCH_BACKEND_DSN=postgresql://bench:local_fixture_only@127.0.0.1:25433/backendbench` và `BENCH_APPROVAL_TOKEN` từ tài khoản admin/lecturer của Backend test. Backend test ở port 28001. Broker port 21883 không có thiết bị thật.
4. Chạy lệnh dưới đây. Có thể dùng `--profile M4` khi chỉ cần một profile. `--manage-compose` tự đổi các cờ và start/recreate trên project test được chỉ định.

```bash
python experiment/run_benchmark.py --manage-compose --isolated-test-stack \
  --project smartcampus-full-benchmark --compose-file experiment/compose.test.yml \
  --edge-url http://127.0.0.1:28000 --backend-url http://127.0.0.1:28001 \
  --mqtt-port 21883 --output benchmark_local/runs/full-run-01
```

Mỗi profile có CSV và JSON gốc. Bảng tổng là `results_m0_m4.csv`; năm bản rút gọn nằm trong `by_profile/`, với `case_id,decision,rejected_at`. Lượt timeout hoặc chỉ có fallback ở phép đo Agent được báo `inconclusive`. Có thể tăng `BENCH_EVALUATE_TIMEOUT_SECONDS` ở Backend và đặt `--agent-timeout` của runner lớn hơn mức Backend. `--model-source fixture` chỉ ghi nhãn lượt có model giả lập đã cấu hình sẵn. `pending` hay `needs_verification` là trạng thái riêng. Bảng tổng lưu `policy_agreement` để chỉ ra ca cho qua/chặn lệch oracle. Runner trả mã 1 khi có lượt chưa kết luận hoặc ca xác định lệch dự đoán.

`rejected_at` có trong CSV gốc, bảng tổng và bản rút gọn. Cột ghi lớp từ chối đã xác nhận, ví dụ `edge_state_binding` hoặc `approval_lifecycle`. Cột để trống khi lượt cho qua, đang chờ duyệt hoặc chưa xác định được lớp chặn.

Ca Agent K01/K10 dùng dữ liệu lành tính, gồm một bất đồng giữa ghi chú và cảm biến. Ca event đi từ telemetry của phòng test tới Agent và broker. Ca policy/contract dùng hàm thực trong process ngoại tuyến, không gửi lệnh MQTT. Đọc `scope` trước khi cộng số liệu. Bản đơn giản ghi lớp của quyết định local khi luật từ chối, còn bằng chứng ở tầng transport chỉ đến từ các scope có chạy transport.

Dừng stack test bằng `docker compose -p smartcampus-full-benchmark -f experiment/compose.test.yml down` sau khi xuất báo cáo.

## Độ trễ đến đề xuất hợp lệ

CSV chi tiết theo profile, CSV tổng và JSON evidence có hai thời lượng tính bằng mili giây:

- `input_to_valid_proposal_ms`: Với `agent_eval`, từ lúc runner gửi HTTP đến lúc nhận response chứa đề xuất đạt rubric. Với `event_flow`, từ lúc bắt đầu publish telemetry đến lúc runner nhận thông báo proposal tương ứng qua MQTT.
- `edge_event_to_valid_proposal_ms`: Chỉ có ở `event_flow`. Từ lúc runner quan sát sự kiện của Edge đến lúc thấy thông báo proposal của cùng `event_id` và cùng phòng. Runner xác nhận nội dung qua proposal lưu ở Backend trước khi ghi thời lượng.

Hai mốc dùng cùng đồng hồ monotonic của runner. Các số này đo đến proposal, trước các bước duyệt và quan sát lệnh. Ca fallback, thiếu đề xuất, đề xuất lệch rubric hoặc kỳ vọng xác minh để trống. Khi so tốc độ giữa các model, dùng cùng scope và báo cùng số lượt có metric trên tổng số lượt đã thử. Năm CSV rút gọn vẫn dành cho quyết định và tầng chặn.

## Bộ chạy mặc định từ notable event

Probe chính sách dùng loại notification nằm riêng trong [notification_guard_cases.csv](notification_guard_cases.csv). Chọn manifest này cùng `--profile M0 --profile M1 --manage-compose`. Ba case gọi trực tiếp hàm kiểm tra tool của Prompt Guard với đầu ra Agent giả lập. PG-01 là control hợp lệ, PG-02 và PG-03 kiểm tra tool ngoài chính sách của loại notification. Lượt bị từ chối tại hàm có `rejected_at=prompt_guard`. Phép đo này xác nhận tool policy trong M0/M1. Đầu vào text, LLM, API phê duyệt và MQTT nằm ngoài scope của probe.

Manifest mặc định là [e2e_cases.csv](e2e_cases.csv). Nó có đủ 31 mã để đối chiếu nhưng chỉ chọn các ca có đường chạy end-to-end phù hợp. `not_e2e` nghĩa là ca gốc đo một tầng riêng. Dùng `--manifest experiment/cases.csv` để chạy bộ kiểm thử gốc của các tầng đó.

- **K01-03** đi từ telemetry MQTT qua Edge, Agent và broker lệnh. Fixture dùng chuỗi nhiệt tăng của phòng có người, để đáp ứng điều kiện làm mát trong policy.
- **K01-01, K03–K09 và K13** dùng scope `e2e_approval`. Runner tạo dữ liệu môi trường test rồi đưa notable event vào luồng MQTT. Agent thật tạo proposal qua Backend. Sau khi xác nhận proposal đúng event ID/phòng, đang `pending`, khớp rubric và binding, runner áp fixture của ca rồi gọi duyệt. Ca K09 có hai proposal từ hai notable event. K13 hai lần duyệt dùng cùng proposal ID.
- Các fixture trong `e2e_approval` có thể dùng DB test để dựng tín hiệu lịch sử và thay đổi môi trường. Điểm bắt đầu đo là lúc gửi notable event. Điểm cuối là verdict hoặc lệnh đến broker test. JSON evidence giữ các notable event test và proposal thật cạnh nhau để đối chiếu. K06 cho khói về NORMAL bằng fixture DB như bộ cũ, vì nhánh telemetry recovery hiện có thể bỏ qua cập nhật khói khi room mode là LOCK.
- Nếu Agent không trả proposal, dùng fallback, sinh tool khác hoặc proposal không khớp binding, lượt sẽ là `inconclusive` và có `reason_code`. Runner dừng ở đó. Vì vậy, một ca có nhiều lần thử có thể có ít lượt tới được guard hơn số lần Agent đã chạy.
- Các ca Agent độc lập, policy và contract còn lại giữ phép đo gốc. Khi trình bày, số liệu chỉ từ các ca có kết quả quan sát được trong scope phù hợp.

Khi cần chạy suite gốc trên test stack, thêm `--manifest experiment/cases.csv`. Một lần chạy end-to-end với model thật có thể gọi model nhiều lần trên mỗi event.
