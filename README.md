# 🏢 Smart Campus BMS (Building Management System)

> **Hệ thống Quản lý Tòa nhà Thông minh AIoT Toàn diện cho Khuôn viên Đại học**  
> Kết hợp Phần cứng Nhúng **ESP32 (ESP-IDF/FreeRTOS)**, **Edge Computing Gateway (FastAPI, TimescaleDB, Mosquitto)**, **AI Decision & Central Backend (ReActXenAgent, pgvector, Ollama/Gemini)**, và **Giao diện Điều hành 3D Digital Twin (React 19, Three.js, Tailwind CSS)**.

---

## 🗺️ Kiến trúc Hệ thống (System Architecture)

Hệ thống được tổ chức thành 4 phân hệ chính:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   1. EMBEDDED IOT NODES (firmware)                     │
│  - ESP32 WROOM (ESP-IDF v5 / FreeRTOS)                                │
│  - Cảm biến: DHT22 (Nhiệt/Ẩm), MQ-2 (Khói), MQ-135 (CO2/AQI), Dual IR │
│  - Chấp hành: Servo khóa cửa, Quạt DC, Còi Buzzer, RGB/LED Strip       │
│  - Định danh: RC522 RFID (Điểm danh phòng học & Đăng ký tại Hành lang) │
│  - Hiển thị: Màn hình OLED SSD1306 0.96" I2C                          │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ MQTT (TCP 1883 / TLS) - smartcampus/v1/...
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   2. EDGE COMPUTING GATEWAY (edge)                     │
│  - FastAPI Gateway & Async MQTT Worker (aiomqtt)                       │
│  - TimescaleDB (PostgreSQL 17): Lưu trữ chuỗi thời gian Hypertables    │
│  - Eclipse Mosquitto MQTT Broker (QoS 1, LWT, Retained state)          │
│  - Finite State Machine (FSM): 7 chế độ vận hành phòng học             │
│  - RFID Access & Attendance: Quản lý điểm danh và đối soát quân số     │
│  - REST API & Database đồng bộ thẻ người dùng                          │
└──────────────────┬─────────────────────────────────┬───────────────────┘
                   │ REST / HTTP                     │ MQTT Events
                   ▼                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│                3. AI AGENT & CENTRAL BACKEND (AI + Backend)            │
│  - Central REST API với JWT Authentication & Phân quyền RBAC           │
│  - WebSocket Realtime Tunnel (/ws/campus) hai chiều < 100ms            │
│  - AI ReActXenAgent: Reasoning đa bước (Observe → Think → Act)        │
│  - Hỗ trợ Hybrid LLM: Ollama Qwen2:1.5b (Local SLM) & Google Gemini    │
│  - PostgreSQL 16 + pgvector: RAG tìm kiếm ngữ nghĩa SOP & Memory Logs  │
│  - Cơ chế Phê duyệt Quyết định Con người (Human-in-the-Loop & Autopilot│
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Reverse Proxy / Nginx & WebSocket
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                 4. 3D DIGITAL TWIN WEB APPLICATION (frontend)          │
│  - React 19, TypeScript, Three.js, Tailwind CSS 4, Lucide Icons        │
│  - Bản đồ khuôn viên trường học 3D tương tác thời gian thực            │
│  - Drawer điều khiển chế độ phòng FSM và trạng thái chấp hành          │
│  - Trung tâm phê duyệt khuyến nghị AI (HITL Approval Modal & Alerts)   │
│  - Quầy kiểm duyệt đăng ký thẻ RFID Hành lang (Corridor Registration)   │
│  - Trợ lý hỏi đáp thông minh (AI Assistant RAG Chat)                   │
│  - Nhật ký kiểm toán (Audit Logs) & Xuất báo cáo CSV                   │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Đặc tả Yêu cầu Chức năng Hoàn thiện (Functional Requirements)

Tất cả các chức năng dưới đây đã được lập trình, kiểm thử và đang vận hành thực tế trong hệ sinh thái Smart Campus BMS:

### 1. Quản lý thiết bị (Device Management)
* **FR-DM-01 — Tự động gửi yêu cầu cấp phát (Auto Provisioning):** ESP32 khi khởi động lần đầu tự đọc địa chỉ MAC từ chip Wi-Fi và gửi yêu cầu đăng ký lên topic `smartcampus/v1/device/provision/request`. Edge Gateway tiếp nhận và tạo bản ghi thiết bị.
* **FR-DM-02 — Gán phòng học (Room Assignment):** Quản trị viên gán `room_id` cho thiết bị từ giao diện web/API. Edge Gateway lưu vào CSDL và gửi bản tin cấu hình `smartcampus/v1/device/provision/response/{mac_address}` (`retain=True`). ESP32 nhận cấu hình và lưu vĩnh viễn vào bộ nhớ flash NVS (Non-Volatile Storage).
* **FR-DM-03 — Giám sát nhịp tim (Heartbeat Monitoring):** Các node ESP32 định kỳ 30 giây gửi bản tin sống lên `smartcampus/v1/device/{device_id}/heartbeat`. Gateway ghi nhận vào hypertable `device_heartbeat` (uptime, firmware version, status).
* **FR-DM-04 — Báo trạng thái ngoại tuyến tức thì (Last Will and Testament):** MQTT Broker tự động phát bản tin LWT lên `smartcampus/v1/device/{mac_address}/status` với trạng thái `offline` ngay khi phát hiện thiết bị mất kết nối mạng đột ngột.

### 2. Thu thập dữ liệu cảm biến (Sensor Telemetry)
* **FR-SD-01 — Nhiệt độ & Độ ẩm (Temperature & Humidity):** Cảm biến DHT22 đo chu kỳ định kỳ, đóng gói JSON chuẩn và xuất bản lên `smartcampus/v1/telemetry/room/{room_id}/environment`, lưu vào hypertable `environment`.
* **FR-SD-02 — Đếm số người hai chiều (Occupancy Counting):** Cụm cảm biến hồng ngoại kép (Dual IR) nhận biết hướng di chuyển của người qua cửa (IN/OUT). Gateway xử lý đồng thời với cơ chế khóa hàng nguyên tử (`SELECT ... FOR UPDATE`), chặn số âm và tự động kích hoạt FSM phòng về `SAVING` khi không còn người (`occupancy = 0`).
* **FR-SD-03 — Cảm biến khí & khói (Smoke Detection):** Cảm biến MQ-2 theo dõi nồng độ khói/khí ga liên tục. Khi vượt ngưỡng, hệ thống kích hoạt leo thang trạng thái FSM: kích hoạt lần 1 $\rightarrow$ `SUSPECTED`, kích hoạt lần 2 trong vòng 5 giây $\rightarrow$ `EMERGENCY`.
* **FR-SD-04 — Giám sát chất lượng không khí & CO2 (Air Quality):** Cảm biến MQ-135 đo nồng độ CO2 và chỉ số IAQ, gửi kèm trong bản tin môi trường định kỳ để cung cấp dữ liệu cho thuật toán điều hòa vi khí hậu.
* **FR-SD-05 — Quét thẻ RFID RC522 (RFID Scanning):** Đọc mã thẻ UID tại 2 phân vùng kiến trúc:
  * **Cửa phòng học:** Điểm danh sinh viên, xác nhận giảng viên nhận phòng, mở khóa cửa.
  * **Hành lang:** Tiếp nhận các thẻ chưa đăng ký, phát yêu cầu phê duyệt thẻ mới.

### 3. Máy trạng thái phòng (Room Finite State Machine - FSM)
* **FR-FSM-01 — 7 Trạng thái chuẩn:** Mỗi phòng học được quản lý độc lập qua 7 trạng thái FSM:
  1. `SAVING`: Chế độ tiết kiệm năng lượng (tắt đèn, tắt quạt, khóa cửa khi phòng trống).
  2. `SELF_STUDY`: Chế độ tự học (sinh viên tự do vào học, mở cửa, bật quạt/đèn vừa phải).
  3. `LECTURE`: Chế độ giờ học chính thức (giảng viên đã check-in, bật đầy đủ tiện nghi).
  4. `EXAM`: Chế độ phòng thi (tự động khóa chốt cửa, hạn chế ra vào tự do, đổi màu đèn chỉ báo).
  5. `LOCK`: Chế độ khóa an ninh (khóa phòng học ngoài giờ hành chính hoặc sự kiện đặc biệt).
  6. `SUSPECTED`: Chế độ nghi ngờ có sự cố khói/nhiệt bất thường.
  7. `EMERGENCY`: Chế độ khẩn cấp (báo cháy, còi hú, tự bung chốt cửa thoát hiểm).
* **FR-FSM-02 — Chuyển trạng thái tự động (Auto Transition):** Quản lý nghiêm ngặt qua ma trận chuyển đổi `_ROOM_TRANSITIONS` trong `edge/feature/FSM/statemachine.py`. Tự động kích hoạt khi có sự kiện cảm biến IR, quẹt thẻ RFID hoặc tác động từ quản trị viên qua Web/API.
* **FR-FSM-03 — Ưu tiên sự cố khẩn cấp (Emergency Override):** Trạng thái `EMERGENCY` có độ ưu tiên cao nhất (Priority 100), ghi đè ngay lập tức mọi trạng thái khác, ngoại trừ trạng thái `LOCK` (phòng đã khóa bảo an và không có người).
* **FR-FSM-04 — Tự động phục hồi trạng thái (State Recovery):** Khi thoát khỏi trạng thái khẩn cấp, hệ thống tự động phục hồi về trạng thái hoạt động hợp lệ trước đó (ví dụ: `LECTURE` hoặc `SELF_STUDY`) và đặt lại trạng thái cảm biến khói về an toàn.
* **FR-FSM-05 — Đồng bộ trạng thái tức thời (State Publish):** Mỗi khi trạng thái thay đổi, hệ thống xuất bản gói tin retained lên `smartcampus/v1/room/{room_id}/state` và đẩy sự kiện qua WebSocket tới toàn bộ các máy khách Web đang kết nối.

### 4. Điều khiển cơ cấu chấp hành (Actuator Control)
* **FR-AC-01 — Thanh LED / RGB LED chỉ báo trạng thái:** Hiển thị màu sắc và hiệu ứng trực quan tại node phòng học theo chế độ FSM hiện hành:
  * `SAVING`: Tắt hoàn toàn (`#000000`).
  * `SELF_STUDY`: Xanh lục nhạt (`#66CCFF` / `#00FF88`).
  * `LECTURE`: Trắng sáng (`#FFFFFF`).
  * `EXAM`: Vàng hổ phách (`#FFBF00`).
  * `SUSPECTED`: Cam hiệu ứng thở (`#FF8C00` Breathe).
  * `EMERGENCY`: Đỏ nhấp nháy dồn dập (`#FF0000` Strobe).
  * `LOCK`: Xám mờ (`#404040`).
* **FR-AC-02 — Servo khóa cửa thông minh (Servo Door Lock):** Điều khiển góc quay servo chốt cửa:
  * Tự động chuyển sang `LOCKED` khi vào chế độ `EXAM`.
  * Tự động mở bung `UNLOCKED` ngay lập tức khi phát hiện `EMERGENCY` để tạo lối thoát hiểm.
  * Hỗ trợ mở/khóa thủ công theo lệnh MQTT `smartcampus/v1/command/room/{room_id}` và REST API.
* **FR-AC-03 — Điều khiển quạt thông gió (Fan Control):** Quạt DC điều khiển bật/tắt qua GPIO và mạch công suất Transistor NPN / MOSFET / Relay, hỗ trợ điều khiển tự động theo nhiệt độ vi khí hậu hoặc đề xuất của AI Agent.
* **FR-AC-04 — Còi cảnh báo (Buzzer):**
  * Hú còi liên tục ở cấp độ phần cứng khi rơi vào tình trạng `EMERGENCY`.
  * Phát 2 tiếng bíp ngắn khi bắt đầu giờ thi `EXAM`.
  * Phát 1 tiếng bíp ngắn khi quét thẻ RFID thành công.
  * Phát 1 tiếng bíp dài khi quét thẻ RFID bị từ chối hoặc sai quyền.
* **FR-AC-05 — Màn hình OLED SSD1306 (0.96 inch):**
  * Giao diện Boot: Hiển thị từng bước nạp phần cứng, địa chỉ IP Wi-Fi và tiến trình kết nối MQTT.
  * Giao diện Room Node: Hiển thị Header kết nối, Chế độ phòng FSM, Trạng thái cửa/quạt, Nhiệt độ/Độ ẩm, Số người hiện diện (`OCC`), và UID thẻ RFID vừa thao tác.
  * Giao diện Corridor Node: Hiển thị trạng thái đăng ký thẻ (`CHO DUYET` / `DA DUYET` / `TU CHOI`), UID thẻ, tên người dùng được duyệt.

### 5. Kiểm soát ra vào & Điểm danh RFID (RFID & Access Control)
* **FR-RF-01 — Đăng ký thẻ lạ tại Hành lang (Corridor Registration):**
  * Khi quét thẻ chưa có trong hệ thống tại bo mạch Hành lang, ESP32 phát bíp, đổi LED cam, hiển thị `ST: CHO DUYET` trên OLED và gửi MQTT request lên `smartcampus/v1/card/registration/request`.
  * Edge Gateway lưu yêu cầu vào bảng `card_registration_requests` (`status = PENDING`).
  * Web Frontend nhận thông báo popup tức thì qua WebSocket, người quản trị chọn gán thẻ cho Sinh viên/Giảng viên hoặc từ chối.
  * Khi phê duyệt qua API, Gateway đồng bộ ngay vào bảng `users` (`card_uid`), đồng thời gửi gói tin MQTT response `smartcampus/v1/card/registration/response/{mac_address}` để ESP32 chuyển LED xanh lá, phát bíp xác nhận và cập nhật OLED `DA DUYET`.
* **FR-RF-02 — Giảng viên nhận phòng & Mở phiên học (Lecturer Check-in):**
  * Giảng viên quét thẻ tại cửa phòng học: hệ thống xác thực vai trò `LECTURER`, khởi tạo phiên học mới (`RoomSession`), chuyển trạng thái phòng sang `LECTURE`, tự động bật tiện nghi và mở cửa sổ điểm danh 15 phút.
  * Quét thẻ lần thứ hai khi kết thúc ca học: tự động đóng phiên học và đưa phòng về chế độ `SAVING`.
* **FR-RF-03 — Sinh viên điểm danh tự động (Student Check-in):**
  * Sinh viên quét thẻ tại cửa phòng: hệ thống kiểm tra danh sách đăng ký học phần (`class_enrollments`).
  * Quét trong vòng 15 phút đầu giờ: Ghi nhận có mặt đúng giờ (`late = false`) vào `attendance_records`.
  * Quét sau 15 phút: Ghi nhận đi muộn (`late = true`).
* **FR-RF-04 — Chặn truy cập trái phép (Unauthorized Access):** Thẻ không có trong cơ sở dữ liệu hoặc sinh viên không thuộc danh sách lớp bị từ chối truy cập, còi hú dài báo lỗi và ghi nhận vào nhật ký kiểm toán.
* **FR-RF-05 — Kiểm soát ra vào phòng thi (Exam Mode Access):** Khi phòng ở chế độ `EXAM`, cửa tự động khóa chốt. Chỉ những sinh viên có tên trong danh sách thi của phòng mới được phép quẹt thẻ để mở chốt cửa bước vào.

### 6. Quản lý phiên học & Đối soát quân số (Session & Attendance)
* **FR-SA-01 — Quản lý vòng đời phiên học:** Tự động tạo phiên học với mốc thời gian bắt đầu `started_at` và hạn chót điểm danh `attendance_deadline = started_at + 15 phút`.
* **FR-SA-02 — Đóng phiên học thông minh:** Hỗ trợ kết thúc phiên học qua 3 kênh: Giảng viên quẹt thẻ check-out, hết giờ theo thời khóa biểu cấu hình, hoặc tiến trình dọn dẹp phiên học mồ côi (sau 45 phút không có hoạt động).
* **FR-SA-03 — Đối soát vắng mặt (Absence Tracking):** Khi kết thúc phiên học, hệ thống đối chiếu toàn bộ danh sách lớp với bản ghi điểm danh thực tế để tự động lập danh sách sinh viên vắng mặt.
* **FR-SA-04 — Động cơ phát hiện lệch quân số (Discrepancy Engine):** Tự động so sánh số lượng người do cảm biến hồng ngoại Dual IR đếm được (`occupancy_count`) với số lượng sinh viên đã quẹt thẻ thành công (`attendance_count`):
  $$\Delta = \text{Occupancy} - \text{Attendance}$$
  Xuất bản định kỳ lên `smartcampus/v1/room/{room_id}/discrepancy` để cảnh báo các trường hợp có người lạ vào phòng hoặc trốn điểm danh.

### 7. Trí tuệ Nhân tạo & Quyết định Vận hành (AI Pipeline & Decision Engine)
* **FR-AI-01 — Trích xuất bối cảnh vận hành (Operational Context):** Khi có sự kiện đặc biệt xảy ra (ví dụ: nhiệt độ tăng cao, CO2 vượt ngưỡng, khói nhẹ), hệ thống tự động tổng hợp sliding window 15 phút gần nhất của phòng: Min/Max/Avg nhiệt/ẩm, chỉ số khí, biến động người vào/ra, trạng thái cửa/quạt và phiên học hiện tại.
* **FR-AI-02 — Tác nhân ReAct gọi công cụ (ReActXenAgent):** Mô hình AI (Google Gemini hoặc Ollama Qwen2:1.5b chạy nội bộ) tiếp nhận sự kiện và bối cảnh vận hành, thực hiện chu trình suy luận đa bước (Quan sát $\rightarrow$ Suy nghĩ $\rightarrow$ Hành động) để chọn công cụ phù hợp từ danh mục công cụ an toàn:
  * `set_fan`: Bật/tắt quạt thông gió.
  * `set_door`: Đóng/mở chốt cửa servo.
  * `set_mode`: Chuyển đổi trạng thái FSM phòng học.
  * `trigger_buzzer`: Kích hoạt còi báo động.
  * `send_alert`: Phát cảnh báo khẩn cấp lên giao diện điều hành.
  * `set_led`: Đổi màu và hiệu ứng dải LED.
* **FR-AI-03 — Cơ chế Phê duyệt Con người (Human-in-the-Loop - HITL) & Chế độ Autopilot:**
  * **Chế độ HITL (Mặc định):** Đề xuất của AI Agent được lưu thành bản ghi `AIRecommendation` với trạng thái `PENDING` kèm lý do giải thích và độ tin cậy. Giao diện Web hiển thị popup modal để quản trị viên chọn `[Thực thi]` hoặc `[Bỏ qua]`.
  * **Chế độ Autopilot:** Khi quản trị viên kích hoạt Autopilot, hệ thống tự động thi hành các khuyến nghị có độ tin cậy cao ($\ge 0.8$) kèm theo các cơ chế an toàn: giới hạn tần suất lệnh, cooldown 60 giây và các lệnh can thiệp an ninh cửa/FSM vẫn bắt buộc có xác nhận con người.
* **FR-AI-04 — Trợ lý Thông minh RAG Chatbot (Campus Assistant):** Tích hợp tìm kiếm ngữ nghĩa trên cơ sở dữ liệu vector pgvector (`agent_memory.contextual_memory_logs` và `agent_memory.campus_documents`), cho phép quản trị viên trò chuyện tự nhiên để tra cứu lịch sử vận hành, quy chuẩn an toàn SOP và tình trạng phòng học.

### 8. Bản sao số 3D & Giao diện Điều hành (3D Digital Twin Web UI)
* **FR-DT-01 — Bản đồ khuôn viên 3D tương tác (Interactive 3D Campus):** Xây dựng trên React 19 và Three.js, hiển thị trực quan các phòng học với màu sắc đồng bộ thời gian thực theo trạng thái FSM của từng phòng.
* **FR-DT-02 — Drawer điều khiển phòng học chuyên sâu:** Click vào bất kỳ phòng học nào để xem chi tiết telemetry, bật/tắt quạt, mở/khóa cửa, và chuyển đổi nhanh 6 chế độ FSM (SAVING, SELF_STUDY, LECTURE, EXAM, LOCK, EMERGENCY) có phân quyền RBAC.
* **FR-DT-03 — Trung tâm Cảnh báo & Phê duyệt Quyết định (Alerts & Decisions Center):** Danh sách khuyến nghị từ AI Agent thời gian thực, nút chuyển đổi HITL / Autopilot, và popup cảnh báo nổi bật khi AI gọi công cụ `send_alert`.
* **FR-DT-04 — Bàn Đăng ký Thẻ Hành lang (Corridor Registration Desk):** Tiếp nhận danh sách các thẻ lạ quét tại hành lang, cho phép quản trị viên nhập tên, phân quyền (Giảng viên / Sinh viên) và duyệt thẻ chỉ với 1 click.
* **FR-DT-05 — Kênh truyền hai chiều WebSocket Tunnel:** Kết nối qua `/ws/campus`, truyền phát hai chiều các sự kiện cảm biến, chuyển trạng thái FSM, quẹt thẻ và khuyến nghị AI với độ trễ dưới 100ms.

---

## 🗄️ Cấu trúc Cơ sở Dữ liệu (Database Schemas)

Hệ thống sử dụng kiến trúc Cơ sở Dữ liệu Kép (Dual Database):

### 1. Edge Database — TimescaleDB trên PostgreSQL 17 (Cổng 5434)
* **Bảng dữ liệu quan hệ (Relational Tables):**
  * `users`: Quản lý tài khoản, vai trò (`ADMIN`, `LECTURER`, `STUDENT`), mã thẻ `card_uid`.
  * `room`: Danh mục các phòng học, loại phòng, sức chứa.
  * `device`: Danh mục thiết bị ESP32, địa chỉ MAC, firmware version, trạng thái.
  * `classes`, `class_enrollments`: Danh mục lớp học phần và danh sách sinh viên ghi danh.
  * `room_sessions`: Các buổi học thực tế do giảng viên khởi tạo.
  * `attendance_records`: Kết quả điểm danh sinh viên chính thức (`late`, `attended_at`).
  * `card_registration_requests`: Quản lý yêu cầu đăng ký thẻ lạ quét tại hành lang (`PENDING`, `APPROVED`, `REJECTED`).
  * `command`: Lịch sử các lệnh điều khiển chấp hành và trạng thái ACK.
* **TimescaleDB Hypertables (Chuỗi thời gian):**
  * `environment`: Nhiệt độ, độ ẩm, nồng độ khói MQ-2, nồng độ CO2 MQ-135.
  * `occupancy`: Lịch sử đếm người ra/vào từ cảm biến hồng ngoại Dual IR.
  * `attendance_events`: Lịch sử toàn bộ các lượt quẹt thẻ RFID.
  * `device_heartbeat`: Lịch sử gói tin nhịp tim thiết bị.
  * `room_state`, `room_door_state`, `room_smoke_state`: Lịch sử chuyển trạng thái phòng, cửa và khói.

### 2. AI Database — PostgreSQL 16 với pgvector (Cổng 5433)
* **Bảng quản trị hệ thống Central Backend:**
  * `users`: Tài khoản đăng nhập quản trị hệ thống với mật khẩu băm bcrypt và vai trò RBAC.
  * `ai_recommendations`: Nhật ký lưu trữ các khuyến nghị từ AI Agent, trạng thái phê duyệt HITL, người duyệt, thời gian duyệt.
  * `audit_logs`: Nhật ký kiểm toán bảo mật toàn bộ hành động trên hệ thống.
* **Bảng Vector Memory (pgvector extension):**
  * `agent_memory.contextual_memory_logs`: Lưu trữ tóm tắt bối cảnh vận hành và vector nhúng 768 chiều.
  * `agent_memory.campus_documents`: Lưu trữ quy chuẩn SOP, hướng dẫn xử lý sự cố kèm vector nhúng phục vụ RAG.
  * `agent_memory.agent_experience_logs`: Nhật ký kinh nghiệm hành động được con người phê duyệt để cung cấp Dynamic Few-Shot cho LLM.

---

## 📡 Danh mục MQTT Topic Chuẩn (`smartcampus/v1/...`)

| Topic MQTT | Chiều | QoS | Retain | Ý nghĩa |
|:---|:---:|:---:|:---:|:---|
| `smartcampus/v1/device/provision/request` | Node $\rightarrow$ GW | 1 | False | ESP32 gửi yêu cầu cấp phát kèm MAC |
| `smartcampus/v1/device/provision/response/{mac}` | GW $\rightarrow$ Node | 1 | **True** | Gateway cấp `room_id`, `heartbeat_interval` |
| `smartcampus/v1/device/{device_id}/heartbeat` | Node $\rightarrow$ GW | 1 | False | Bản tin nhịp tim báo sống định kỳ |
| `smartcampus/v1/device/{mac}/status` | Broker $\rightarrow$ All | 1 | **True** | Trạng thái online/offline (kèm Mosquitto LWT) |
| `smartcampus/v1/telemetry/room/{room_id}/environment` | Node $\rightarrow$ GW | 1 | False | Dữ liệu nhiệt độ, độ ẩm, khói, CO2 |
| `smartcampus/v1/telemetry/room/{room_id}/occupancy` | Node $\rightarrow$ GW | 1 | False | Dữ liệu đếm người vào/ra Dual IR |
| `smartcampus/v1/event/room/{room_id}/rfid` | Node $\rightarrow$ GW | 1 | False | Sự kiện quẹt thẻ điểm danh tại phòng |
| `smartcampus/v1/card/registration/request` | Node $\rightarrow$ GW | 1 | False | Yêu cầu đăng ký thẻ lạ quét tại Hành lang |
| `smartcampus/v1/card/registration/response/{mac}` | GW $\rightarrow$ Node | 1 | False | Kết quả phê duyệt thẻ gửi về bo mạch Hành lang |
| `smartcampus/v1/room/{room_id}/state` | GW $\rightarrow$ All | 1 | **True** | Trạng thái FSM phòng (7 chế độ) |
| `smartcampus/v1/command/room/{room_id}` | GW $\rightarrow$ Node | 1 | False | Lệnh chấp hành: cửa, quạt, đèn, còi |
| `smartcampus/v1/ack/device/{mac}/command/{cmd_id}` | Node $\rightarrow$ GW | 1 | False | Xác nhận kết quả thực thi lệnh chấp hành |
| `smartcampus/v1/room/{room_id}/discrepancy` | GW $\rightarrow$ All | 1 | False | Báo cáo độ lệch quân số Dual IR vs Điểm danh |

---

## 🚀 Hướng dẫn Cài đặt & Khởi chạy (Quick Start)

### 1. Yêu cầu Hệ thống
* **Hệ điều hành:** Linux (Ubuntu 22.04+), Windows 10/11 với WSL2, hoặc macOS.
* **Phần mềm:** Docker v24+ và Docker Compose v2+.
* **Phần cứng đề xuất:** 8GB RAM trở lên, 20GB dung lượng đĩa trống.

### 2. Cấu hình Biến Môi trường
Hệ thống sử dụng các file `.env` mẫu đã được cấu hình sẵn cho môi trường Docker:
```bash
# Cấu hình cho Edge Gateway
cp edge/.env.example edge/.env

# Cấu hình cho AI Agent & Central Backend
cp "AI + Backend/.env.example" "AI + Backend/.env"
```

### 3. Khởi chạy Toàn bộ Hệ sinh thái
Khởi chạy toàn bộ hệ thống bằng một lệnh duy nhất từ thư mục gốc:

```bash
docker compose up -d --build
```

Quá trình trên sẽ tự động khởi động:
1. `smartcampus-db`: TimescaleDB (PostgreSQL 17) lưu chuỗi thời gian Edge.
2. `smartcampus-mqtt`: Eclipse Mosquitto MQTT Broker (Cổng 1883 & 9001).
3. `smartcampus-api`: Edge Gateway FastAPI (Cổng 8000).
4. `smartcampus-pgvector`: PostgreSQL 16 với pgvector lưu trữ AI RAG (Cổng 5433).
5. `smartcampus-ollama`: Ollama Local LLM Server (Cổng 11436).
6. `smartcampus-ai`: AI Agent & Central Backend Service (Cổng 8001).
7. `smartcampus-frontend`: Nginx phục vụ Giao diện 3D Digital Twin (Cổng 3001).

### 4. Truy cập Dịch vụ
* **Giao diện Web Điều hành (Digital Twin 3D):** [http://localhost:3001](http://localhost:3001)
  * Tài khoản mặc định: `admin` / Mật khẩu: `admin123456`
* **Swagger API Central Backend & AI Service:** [http://localhost:8001/docs](http://localhost:8001/docs)
* **Swagger API Edge Gateway:** [http://localhost:8000/docs](http://localhost:8000/docs)
* **Kiểm tra sức khỏe hệ thống:**
  ```bash
  curl http://localhost:8000/health
  curl http://localhost:8001/api/health
  ```

---

## 👥 Phân quyền Người dùng (Role-Based Access Control - RBAC)

| Vai trò | Quyền hạn trên Hệ thống |
|:---|:---|
| **ADMIN (Quản trị viên)** | Toàn quyền kiểm soát hệ thống: chuyển đổi mọi chế độ FSM phòng, phê duyệt/từ chối đăng ký thẻ RFID, phê duyệt khuyến nghị AI (HITL), bật/tắt Autopilot, quản lý người dùng, xem toàn bộ nhật ký kiểm toán. |
| **LECTURER (Giảng viên)** | Quẹt thẻ mở phòng học (`LECTURE`), kích hoạt cửa sổ điểm danh, xem danh sách sinh viên có mặt / vắng / muộn, điều khiển quạt và cửa trong giờ học của mình. Không thể cưỡng chế chế độ khẩn cấp hoặc duyệt thẻ lạ. |
| **STUDENT (Sinh viên)** | Quẹt thẻ điểm danh, quẹt thẻ mở cửa trong khung giờ học/thi hợp lệ. Trên giao diện Web chỉ xem trạng thái phòng học, không có quyền can thiệp vào máy trạng thái FSM hoặc cơ cấu chấp hành. |

---
*Smart Campus BMS — Đại học Kỹ thuật Mật mã (KMA).*