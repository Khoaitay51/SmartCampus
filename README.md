# 🏢 Smart Campus BMS (Building Management System)

Smart Campus BMS là một giải pháp quản lý tòa nhà thông minh AIoT toàn diện (end-to-end), được thiết kế để tự động hóa, giám sát và tối ưu hóa vận hành các phòng học và hành lang trong khuôn viên trường đại học. Hệ thống kết hợp giữa phần cứng nhúng ESP32, gateway tính toán biên (Edge Computing Gateway) hiệu năng cao, cơ sở dữ liệu chuỗi thời gian TimescaleDB và một pipeline trí tuệ nhân tạo (AI Pipeline) hỗ trợ đưa ra quyết định thông minh.


## 🗺️ Kiến trúc hệ thống (System Architecture)

Hệ thống được tổ chức thành 3 phân hệ chính:
1. **[firmware](file:///home/user_kma_chinh/SmartCampus/firmware)**: Phân hệ nhúng trên vi điều khiển ESP32 chịu trách nhiệm thu thập telemetry từ cảm biến, điều khiển các cơ cấu chấp hành cục bộ (quạt 2 dây, khóa cửa, còi, OLED) và điểm danh/đăng ký thẻ RFID thời gian thực.
2. **[edge](file:///home/user_kma_chinh/SmartCampus/edge)**: Phân hệ Edge Computing Gateway chạy cục bộ (FastAPI, TimescaleDB, MQTT Worker, FSM, xử lý logic phòng học, lưu trữ dữ liệu thời gian thực và quản lý quẹt thẻ/đăng ký thẻ lạ).
3. **[AI + Backend](file:///home/user_kma_chinh/SmartCampus/AI%20+%20Backend)**: Phân hệ AI Agent & Central Backend Service kết hợp (LLM ReActXenAgent, RAG Tools với pgVector, Google Gemini, và dịch vụ Backend quản trị mở rộng với JWT/RBAC, REST API).


---

## 🛠️ Yêu cầu chức năng (Functional Requirements)

### 1. Quản lý thiết bị (Device Management)
*   **FR-DM-01 — Tự động đăng ký (Auto provisioning):** Khi node ESP32 khởi động lần đầu, thiết bị tự động gửi yêu cầu đăng ký bằng địa chỉ MAC của nó lên topic `campus/provision/request`.
*   **FR-DM-02 — Gán phòng học (Room assignment):** Admin có thể gán `room_id` cho thiết bị thông qua hệ thống API của Edge Gateway. Ánh xạ từ địa chỉ MAC sang `room_id` được lưu trữ cố định vào cơ sở dữ liệu và lưu trên phân vùng NVS (Non-Volatile Storage) của ESP32.
*   **FR-DM-03 — Cập nhật firmware từ xa (OTA update):** Hỗ trợ cập nhật chương trình cho ESP32 thông qua giao thức OTA kích hoạt bằng lệnh MQTT mà không cần kết nối vật lý.
*   **FR-DM-04 — Giám sát nhịp tim (Heartbeat monitoring):** Node ESP32 định kỳ gửi bản tin heartbeat mỗi 30 giây. Nếu hệ thống không nhận được heartbeat sau 90 giây, thiết bị sẽ tự động được đánh dấu là ngoại tuyến (offline alert).
*   **FR-DM-05 — Di chúc cuối cùng (Last Will Testament):** Khi ESP32 mất kết nối đột ngột với MQTT Broker, broker sẽ tự động phát bản tin LWT để báo trạng thái offline của thiết bị.

### 2. Thu thập dữ liệu cảm biến (Sensor Data Collection)
*   **FR-SD-01 — Nhiệt độ & Độ ẩm (Temperature & Humidity):** Đọc dữ liệu định kỳ từ cảm biến DHT22 mỗi 2 giây và gửi lên MQTT Broker theo định dạng JSON chuẩn.
*   **FR-SD-02 — Đếm số lượng người (Occupancy counting):** Sử dụng hệ thống cảm biến hồng ngoại kép (Dual IR sensor) tại cửa phòng để đếm số lượng người ra/vào. Hướng di chuyển được xác định dựa trên thứ tự kích hoạt:
    *   Vào phòng: Kích hoạt cảm biến $IR_A$ trước, sau đó tới $IR_B$.
    *   Ra khỏi phòng: Kích hoạt cảm biến $IR_B$ trước, sau đó tới $IR_A$.
*   **FR-SD-03 — Phát hiện khói (Smoke detection):** Cảm biến khí/khói MQ2 được đọc liên tục. Khi chỉ số vượt ngưỡng lần đầu, hệ thống chuyển sang trạng thái nghi ngờ (`SUSPECTED`). Nếu có kích hoạt lần thứ 2 trong vòng 5 giây, hệ thống sẽ kích hoạt trạng thái khẩn cấp (`EMERGENCY`).
*   **FR-SD-04 — Quét thẻ RFID (RFID scanning):** Cảm biến RC522 thực hiện đọc UID thẻ RFID tại hai khu vực:
    *   Hành lang: Đóng vai trò là điểm đăng ký thẻ (registration point).
    *   Cửa phòng: Đóng vai trò kiểm soát ra vào và điểm danh (access control & attendance).
*   **FR-SD-05 — Chất lượng không khí (Air quality):** Giám sát liên tục chất lượng không khí và cập nhật thời gian thực lên Broker.

### 3. Máy trạng thái phòng (Room State Machine - FSM)
*   **FR-FSM-01 — 7 Trạng thái phòng:** Hệ thống duy trì 7 trạng thái hoạt động của phòng học bao gồm:
    1.  `SAVING` (Tiết kiệm điện)
    2.  `SELF_STUDY` (Tự học)
    3.  `LECTURE` (Giờ học chính thức)
    4.  `EXAM` (Giờ thi)
    5.  `LOCK` (Khóa phòng)
    6.  `SUSPECTED` (Nghi ngờ có sự cố khói)
    7.  `EMERGENCY` (Tình huống khẩn cấp)
*   **FR-FSM-02 — Chuyển trạng thái tự động (Auto transition):**
    *   Số người trong phòng = 0 $\rightarrow$ `SAVING`.
    *   Số người trong phòng > 0 và không có Giảng viên $\rightarrow$ `SELF_STUDY`.
    *   Giảng viên quét thẻ RFID hợp lệ $\rightarrow$ `LECTURE`.
    *   Trigger từ API quản trị $\rightarrow$ `EXAM`.
    *   Lịch đặt trước hoặc kích hoạt từ quản trị viên $\rightarrow$ `LOCK`.
    *   Cảm biến khói vượt ngưỡng lần 1 $\rightarrow$ `SUSPECTED`.
    *   Cảm biến khói vượt ngưỡng lần 2 trong vòng 5 giây $\rightarrow$ `EMERGENCY`.
*   **FR-FSM-03 — Ưu tiên trạng thái khẩn cấp (Emergency override):** Trạng thái `EMERGENCY` sẽ ghi đè tất cả các trạng thái khác ngoại trừ trạng thái `LOCK` (do phòng đang khóa và không có người bên trong).
*   **FR-FSM-04 — Khôi phục trạng thái (State persistence):**
    *   Khi thoát khỏi trạng thái `EMERGENCY`, phòng sẽ quay về trạng thái hoạt động trước đó.
    *   Khi chế độ `EXAM` kết thúc, phòng chuyển về trạng thái `LECTURE` hoặc `SELF_STUDY` tùy theo điều kiện thực tế.
*   **FR-FSM-05 — Phát trạng thái (State publish):** Bất cứ khi nào trạng thái phòng thay đổi, hệ thống sẽ gửi tin nhắn cập nhật lên topic `campus/room/{id}/mode` dưới dạng retained message để đảm bảo các thiết bị đăng ký sau nhận được trạng thái mới nhất.

### 4. Điều khiển cơ cấu chấp hành (Actuator Control)
*   **FR-AC-01 — Thanh LED chỉ báo (LED strip):** LED WS2812B thay đổi màu sắc hiển thị cục bộ tùy thuộc vào chế độ hiện tại của phòng:
    *   `SAVING`: Tắt hoàn toàn
    *   `SELF_STUDY`: Xanh nhạt (Light green)
    *   `LECTURE`: Trắng (White)
    *   `EXAM`: Vàng hổ phách (Amber yellow)
    *   `SUSPECTED`: Cam (Orange)
    *   `EMERGENCY`: Đỏ nhấp nháy (Flashing red)
    *   `LOCK`: Xám (Grey)
*   **FR-AC-02 — Servo khóa cửa (Servo door):** Động cơ Servo sở hữu một máy trạng thái (FSM) độc lập với trạng thái phòng (`LOCKED` / `UNLOCKED`):
    *   Cho phép điều khiển thủ công qua lệnh MQTT bất kỳ lúc nào.
    *   Khi phòng ở trạng thái `EXAM` $\rightarrow$ Tự động chuyển sang `LOCKED`.
    *   Khi phòng ở trạng thái `EMERGENCY` $\rightarrow$ Tự động chuyển sang `UNLOCKED` ngay lập tức để thoát hiểm.
*   **FR-AC-03 — Điều khiển quạt thông gió 2 dây (2-Wire Fan control):** Quạt DC 5V chỉ có 2 dây (VCC + GND), được điều khiển bật/tắt qua GPIO thông qua Transistor NPN (2N2222) hoặc MOSFET N-channel (IRLZ44N). Hệ thống hỗ trợ 2 chế độ phần cứng cấu hình tại compile-time:
    *   `FAN_2WIRE_GPIO = 1` *(mặc định)*: Quạt 2 dây — Chỉ bật/tắt bằng GPIO, không có điều khiển tốc độ.
    *   `FAN_2WIRE_GPIO = 0`: Quạt 3-4 dây — Điều khiển tốc độ (0-100%) bằng PWM qua LEDC Channel 4.
    *   Sơ đồ đấu nối quạt 2 dây qua Transistor NPN:
        ```
        GPIO14 ---[1kΩ]--- Base(NPN 2N2222)
                            |
                        Emitter --- GND
                            |
                        Collector --- GND_Fan
                                      |
                                   VCC_Fan --- 5V (nguồn ngoài)
        ```
*   **FR-AC-04 — Còi cảnh báo (Buzzer):** Kích hoạt phát âm thanh trực tiếp tại node phần cứng:
    *   Sự cố khẩn cấp (`EMERGENCY`): Buzzer kêu liên tục ngay lập tức (không đợi phản hồi từ Cloud).
    *   Bắt đầu giờ thi (`EXAM` start): Phát 2 tiếng beep ngắn.
    *   Từ chối thẻ RFID (RFID reject): Phát 1 tiếng beep dài.
    *   Chấp nhận thẻ RFID (RFID success): Phát 1 tiếng beep ngắn.
*   **FR-AC-05 — Màn hình OLED hiển thị:** Hiển thị trực quan các thông tin: vai trò và họ tên của người quét thẻ RFID gần nhất, trạng thái các cảm biến môi trường (nhiệt độ/độ ẩm) và tình trạng kết nối MQTT.

### 5. Kiểm soát ra vào và Điểm danh RFID (RFID & Access Control)
*   **FR-RF-01 — Đăng ký thẻ lạ tại Node Hành lang (Unknown card registration at Corridor Node):**
    *   **Node Hành lang (`ROLE_CORRIDOR_NODE = 3`)**: Bo mạch ESP32 chuyên dụng đặt tại sảnh/hành lang trang bị đầu đọc RFID RC522, màn hình OLED SSD1306, RGB LED và còi Buzzer.
    *   **Luồng gửi yêu cầu đăng ký (Pending Request)**: Khi phát hiện thẻ chưa có trong hệ thống (`card_uid` chưa gắn `user_id`), ESP32 phát 2 tiếng beep ngắn, đèn LED chuyển sang **Vàng cam**, màn hình OLED hiển thị `UID: <card_uid>` kèm `ST: CHO DUYET (PENDING)`. Thiết bị gửi tin nhắn lên topic MQTT:
        *   **Topic Request**: `smartcampus/v1/card/registration/request`
        *   **Payload**: `{ "message_id": "...", "payload": { "mac_address": "XX:XX:XX:XX:XX:XX", "card_uid": "...", "room_id": "...", "status": "pending", "node_role": "corridor" } }`
    *   **Lưu trữ Database**: Hệ thống tiếp nhận và lưu tự động vào bảng `card_registration_requests` (Model `CardRegistrationRequest`) với trạng thái `PENDING` để người quản trị (Admin) có thể kiểm duyệt và gán thẻ cho Sinh viên/Giảng viên.
    *   **Phản hồi duyệt thẻ (Approval Response)**: Khi Admin duyệt hoặc từ chối, Gateway gửi gói tin phản hồi xuống topic:
        *   **Topic Response**: `smartcampus/v1/card/registration/response/{mac_address}`
        *   **Payload**: `{ "payload": { "card_uid": "...", "status": "approved" | "rejected" | "pending", "assigned_user_name": "...", "message": "..." } }`
        *   Nếu `approved`: OLED hiển thị tên User + `ST: DA DUYET / OK`, LED đổi sang **Xanh lá**, còi kêu 1 tiếng beep ngắn.
        *   Nếu `rejected`: OLED hiển thị `ST: TU CHOI`, LED đổi sang **Đỏ**, còi hú dài báo lỗi.
*   **FR-RF-02 — Giảng viên điểm danh đầu giờ (Lecturer check-in):** Khi giảng viên quét thẻ hợp lệ tại cửa phòng học, trạng thái phòng chuyển sang `LECTURE`, đồng thời khởi tạo một phiên học mới (session) và bắt đầu mở cửa sổ điểm danh (attendance window).
*   **FR-RF-03 — Sinh viên điểm danh (Student check-in):** Sinh viên đăng ký trong lớp học quét thẻ trong khung giờ điểm danh để ghi nhận sự hiện diện:
    *   Quét sau thời gian giới hạn (deadline) sẽ bị đánh dấu đi muộn (`late = true`).
    *   Sinh viên không có tên trong danh sách lớp sẽ bị từ chối truy cập.
*   **FR-RF-04 — Truy cập trái phép (Unauthorized access):** Thẻ không có trong cơ sở dữ liệu hoặc không có quyền truy cập vào phòng học tương ứng sẽ bị từ chối (reject + phát còi buzzer dài + lưu nhật ký hệ thống).
*   **FR-RF-05 — Kiểm soát ra vào phòng thi (Exam mode access):** Khi phòng học ở chế độ `EXAM`, chỉ có các sinh viên nằm trong danh sách thi của phòng đó mới được phép quét thẻ để mở cửa vào phòng. Các sinh viên khác sẽ bị từ chối và phát cảnh báo.

### 6. Quản lý phiên học và Điểm danh (Session & Attendance)
*   **FR-SA-01 — Khởi tạo phiên học (Session creation):** Khởi tạo phiên học theo lịch hoặc ngay khi giảng viên check-in với thời gian bắt đầu `started_at = NOW()`. Khung thời gian điểm danh tiêu chuẩn kéo dài trong 15 phút kể từ lúc bắt đầu.
*   **FR-SA-02 — Đóng phiên học (Session closure):** Phiên học được đóng tự động hoặc thủ công theo các mức ưu tiên:
    1.  Giảng viên quét thẻ rời phòng (Đóng ngay lập tức).
    2.  Hết thời gian học theo thời khóa biểu đã lên lịch trước.
    3.  Cơ chế dự phòng (Fallback): Tự động đóng sau `lịch bắt đầu + 45` phút.
*   **FR-SA-03 — Theo dõi vắng mặt (Absence tracking):** Sinh viên có tên trong danh sách lớp học nhưng không có dữ liệu check-in khi phiên học kết thúc sẽ được đánh dấu là vắng mặt (`absent`).
*   **FR-SA-04 — Theo dõi đi muộn (Late tracking):** Mọi lượt quét thẻ ghi nhận điểm danh sau 15 phút kể từ lúc bắt đầu phiên học sẽ được ghi nhận đi muộn (`late = true`).
*   **FR-SA-05 — Tự động dọn dẹp các phiên học mồ côi (Orphan cleanup):** Một tiến trình nền chạy định kỳ mỗi 5 phút để tìm kiếm và đóng các phiên học chưa ghi nhận thời gian kết thúc (`ended_at`) sau 45 phút hoạt động.

### 7. Phân tích dữ liệu & Tác nhân AI (AI Pipeline)
*   **FR-AI-01 — LLM tóm tắt hoạt động (LLM summarizer):** Tiến trình lập lịch (scheduler) chạy định kỳ (mỗi giờ/ngày/tuần) để tổng hợp dữ liệu telemetry, gửi tới LLM để tạo các bản tóm tắt vận hành, chuyển đổi thành vector embedding và lưu trữ vào pgVector
*   **FR-AI-02 — Xác thực Cosine Similarity (Cosine validation):** Mỗi vector embedding của bản tóm tắt mới sẽ được đo độ tương đồng cosine (cosine similarity) với các vector lịch sử. Ngưỡng tương đồng (threshold) được hiệu chuẩn từ 10 truy vấn đặc trưng ban đầu để phân biệt giữa các sự kiện thông thường và các sự kiện bất thường nổi bật (nhằm ngăn chặn hiện tượng ảo giác của mô hình LLM).
*   **FR-AI-03 — Trích xuất bối cảnh vận hành (Operational context):** Khi có sự kiện đặc biệt xảy ra (ví dụ: cảnh báo nhiệt độ cao, khói nhẹ), hệ thống tự động tổng hợp dữ liệu telemetry của 15 phút gần nhất làm ngữ cảnh đầu vào (operational context) cho AI Agent.
*   **FR-AI-04 — Tác nhân gọi công cụ (Tool calling agent):** Mô hình Qwen 1B/Google Gemini tiếp nhận thông tin sự kiện cùng bối cảnh vận hành để lựa chọn công cụ thực thi phù hợp từ danh sách công cụ cố định (fixed tool list), sau đó gửi đề xuất khuyến nghị vận hành lên API quản trị.
*   **FR-AI-05 — Duyệt bởi con người (Human-in-the-loop):** Mọi đề xuất công cụ từ AI Agent (ví dụ: bật quạt thông gió, thay đổi chế độ điều hòa) đều cần có sự xác nhận thủ công từ người quản trị qua API để thực thi, ngoại trừ hệ thống buzzer cảnh báo khẩn cấp cục bộ tại node phần cứng.
*   **FR-AI-06 — Chatbot hỗ trợ truy vấn:** Sử dụng Gemini API để xử lý các câu hỏi ngôn ngữ tự nhiên từ người dùng về lịch sử vận hành phòng học hoặc tình hình điểm danh hoặc thực thi các yêu cầu phù hợp.

### 8. Quản lý kịch bản Demo (Scenario Manager)
*   **FR-SM-01 — Các kịch bản nút bấm vật lý (Button scenarios):** Node thiết bị hỗ trợ 4 nút nhấn vật lý để giả lập các kịch bản thực tế tại chỗ:
    *   `BTN1`: Kịch hoạt kịch bản khẩn cấp (Emergency - giả lập phát hiện khói).
    *   `BTN2`: Chuyển đổi qua lại chế độ thi cử (Exam mode toggle).
    *   `BTN3`: Giả lập tình huống phòng học quá tải số lượng người (Occupancy overflow).
    *   `BTN4`: Lệnh khóa hoặc mở khóa toàn bộ các cửa phòng học (Lock all / Unlock all).
*   **FR-SM-02 — Giả lập dữ liệu telemetry (Fake telemetry):** Cung cấp các kịch bản gửi dữ liệu cảm biến giả lập lên hệ thống MQTT để kiểm thử toàn diện pipeline xử lý của Edge Gateway mà không cần kết nối trực tiếp với phần cứng thật.

### 9. Đánh giá hiệu năng hệ thống (Evaluation)
*   **FR-EV-01 — Chỉ số đánh giá tìm kiếm (Retrieval metrics):** Đo lường chất lượng truy vấn thông tin của Chatbot bằng các chỉ số MRR, MAP, và Precision@K sử dụng khung đánh giá tăng cường quan hệ cha-con (parent-offspring augmented evaluation framework).
*   **FR-EV-02 — Đánh giá loại bỏ biến số (Ablation study):** Đánh giá hiệu quả của AI Agent bằng cách so sánh hiệu năng đưa ra quyết định qua 3 điều kiện thử nghiệm:
    *   **Điều kiện A:** Chỉ gửi dữ liệu JSON thô (Raw JSON) trực tiếp đến Qwen.
    *   **Điều kiện B:** Chỉ gửi bối cảnh vận hành (Operational context) đến Qwen.
    *   **Điều kiện C:** Gửi kết hợp cả hai yếu tố trên đến Qwen.
*   **FR-EV-03 — Đo lường chất lượng xác thực (Validation metrics):** Đánh giá độ chính xác của thuật toán cosine similarity thông qua việc lập ma trận nhầm lẫn (confusion matrix), tỷ lệ dương tính giả (FPR), tỷ lệ âm tính giả (FNR) và tỷ lệ trôi dạt ngữ nghĩa cha-con (parent-offspring drift rate).
*   **FR-EV-04 — Đánh giá an ninh & Phòng thủ AI Agent (AI Agent Defense & Security Evaluation):** Đo lường khả năng tự bảo vệ của tác nhân AI trước các hình thức tấn công vào mô hình ngôn ngữ lớn (LLM):
    *   **Prompt Injection & MQTT Payload Injection:** Đo lường tỷ lệ từ chối thành công các yêu cầu jailbreak/chiếm quyền điều khiển (jailbreak rejection rate). Đánh giá cả hai hình thức:
        *   *Tấn công trực tiếp (Direct Injection):* Qua các truy vấn ngôn ngữ tự nhiên của người dùng qua Chatbot.
        *   *Tấn công gián tiếp qua MQTT (Indirect Payload Injection):* Kẻ tấn công tiêm câu lệnh prompt injection độc hại vào các trường dữ liệu JSON của MQTT event payload (ví dụ: chèn câu lệnh điều khiển vào trường họ tên người quét thẻ RFID lạ, hoặc trường mô tả cảnh báo thiết bị) nhằm thao túng AI Agent khi nó tổng hợp bối cảnh vận hành (`operational context`).
    *   **RAG Poisoning (Đầu độc tri thức):** Đánh giá mức độ ảnh hưởng của dữ liệu telemetry giả mạo hoặc tóm tắt bị tiêm mã độc được lưu trong [edge/database.py](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/database.py) (`pgVector`) đến độ chính xác và tính an toàn của các khuyến nghị công cụ do AI Agent sinh ra.
    *   **Adversarial Telemetry Attack:** Đánh giá độ nhạy bén của thuật toán phát hiện và cô lập các chuỗi dữ liệu cảm biến bất thường giả lập liên tục nhằm đánh lừa AI Agent kích hoạt sai công cụ điều khiển.

### 10. Đề xuất mở rộng cơ cấu chấp hành (Recommended Actuator Expansion)

Dưới đây là danh sách các cơ cấu chấp hành **được khuyến nghị tích hợp** để nâng cấp hệ thống SmartCampus BMS trong tương lai, sắp xếp theo mức độ ưu tiên.

| # | Cơ cấu chấp hành | Module gợi ý | Giao tiếp | Đấu nối ESP32 | Ứng dụng trong BMS |
|:---:|:---|:---|:---:|:---|:---|
| 1 | **Rơ-le đèn chiếu sáng** | Relay Module 5V (1/2/4 kênh) | GPIO | GPIO → IN Relay → Đèn AC 220V | Tự động bật/tắt đèn theo trạng thái FSM: `SAVING` → tắt, `LECTURE` → bật, `EMERGENCY` → nhấp nháy |
| 2 | **Rơ-le điều hòa không khí** | Relay Module 5V + IR Blaster (VS1838B) | GPIO / IR | GPIO → Relay cắt nguồn, hoặc IR LED mô phỏng remote | Bật/tắt điều hòa theo nhiệt độ phòng. AI Agent gợi ý `adjust_ac_temperature(24°C)` khi temp > 30°C |
| 3 | **Đèn báo cảnh báo xoay (Beacon)** | Đèn xoay LED 12V + Relay | GPIO → Relay | GPIO → Relay → Đèn 12V (nguồn ngoài) | Cảnh báo trực quan khi `EMERGENCY` / `SUSPECTED`, dễ nhận biết từ xa hơn buzzer |
| 4 | **Màn hình LCD 20x4 / TFT** | LCD2004 (I2C) hoặc ILI9341 TFT (SPI) | I2C / SPI | SDA/SCL hoặc SPI bus | Hiển thị dashboard phòng: trạng thái FSM, nhiệt độ, CO2, số người, countdown điểm danh |
| 5 | **Khóa điện từ (Electromagnetic Lock)** | Khóa điện từ 12V + Relay Module | GPIO → Relay | GPIO → Relay → Solenoid Lock 12V (nguồn ngoài) | Thay thế/bổ sung Servo SG90 cho cửa thực tế, chịu tải nặng hơn |
| 6 | **Cảm biến cửa (Reed Switch)** | Reed Switch MC-38 | GPIO (INPUT_PULLUP) | Reed → GPIO + GND | Phát hiện cửa mở/đóng thực tế, cross-check với lệnh `set_door` |
| 7 | **Quạt hút thông gió** | Quạt hút 12V + Relay | GPIO → Relay | GPIO → Relay → Quạt hút 12V | Kích hoạt khi CO2 > 1000ppm hoặc `air_quality` xấu, AI recommend `activate_exhaust_fan` |
| 8 | **Bơm phun sương** | Bơm mini 5V + Relay/MOSFET | GPIO | GPIO → MOSFET → Bơm 5V | Duy trì độ ẩm tối ưu 40-60% trong phòng server/lab |
| 9 | **Rèm cửa tự động** | Stepper Motor 28BYJ-48 + ULN2003 | GPIO (4 chân) | IN1-IN4 → GPIO | Đóng rèm khi `EXAM` (chống gian lận), mở rèm khi `SAVING` (tận dụng ánh sáng tự nhiên) |
| 10 | **Loa thông báo (PA Speaker)** | DFPlayer Mini + Loa 8Ω 2W | UART (TX/RX) | TX → RX DFPlayer | Phát thông báo giọng nói: "Giờ thi bắt đầu", "Phát hiện khói — vui lòng di tản", "Điểm danh kết thúc" |

> **Lưu ý kỹ thuật:**
> - Các cơ cấu chấp hành dùng nguồn > 5V (12V, 220V AC) **bắt buộc** phải đi qua Relay Module hoặc MOSFET, không nối trực tiếp vào GPIO ESP32.
> - Khi sử dụng Relay với tải AC 220V, cần tuân thủ quy tắc an toàn điện và cách ly quang (Optocoupler đã tích hợp sẵn trên hầu hết Relay Module).
> - Mỗi cơ cấu chấp hành mới cần được đăng ký thêm vào `ALLOWED_ACTION_TOOLS` trong AI Agent và thêm tool definition tương ứng trong `edge/feature/tool/`.

---

## 💾 Cấu trúc dữ liệu và Models (Data Models)

Các mô hình dữ liệu trong hệ thống được quản lý tại thư mục [edge/models](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models) sử dụng thư viện SQLAlchemy.

| File ánh xạ | Lớp (Class) | Mô tả |
| :--- | :--- | :--- |
| [user.py](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/user.py) | [User](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/user.py#L5) | Lưu trữ thông tin người dùng (Giảng viên, Sinh viên, Quản trị viên). |
| [classroom.py](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/classroom.py) | [CourseClass](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/classroom.py#L4)<br>[ClassEnrollment](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/classroom.py#L14) | Quản lý thông tin lớp học phần và danh sách đăng ký học tập của sinh viên. |
| [device.py](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/device.py) | [Device](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/device.py#L4)<br>[DeviceStatus](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/device.py#L15)<br>[DeviceHeartbeat](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/device.py#L23) | Quản lý định danh thiết bị ESP32, trạng thái hoạt động trực tuyến/ngoại tuyến và lưu vết nhịp tim. |
| [room.py](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/room.py) | [Room](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/room.py#L5)<br>[RoomState](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/room.py#L12)<br>[RoomEvent](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/room.py#L22) | Quản lý danh mục phòng học, trạng thái vận hành hiện tại (FSM) và nhật ký các sự kiện chuyển trạng thái. |
| [session.py](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/session.py) | [RoomSession](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/session.py#L4) | Theo dõi các buổi học thực tế được mở bởi giảng viên. |
| [attendance_record.py](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/attendance_record.py) | [AttendanceRecord](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/attendance_record.py#L4) | Lưu vết kết quả điểm danh của sinh viên (Có mặt, Đi muộn, Vắng mặt). |
| [card_registration.py](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/card_registration.py) | [CardRegistrationRequest](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/card_registration.py#L7) | Quản lý yêu cầu đăng ký thẻ RFID lạ tại hành lang với trạng thái PENDING/APPROVED/REJECTED. |
| [peripheral.py](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/peripheral.py) | [Peripheral](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/peripheral.py#L4)<br>[PeripheralAction](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/peripheral.py#L10) | Quản lý các thiết bị ngoại vi kết nối (quạt, rơ-le, còi, khóa servo) và lịch sử gửi lệnh điều khiển. |
| [telemetry/environment.py](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/telemetry/environment.py) | [Environment](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/telemetry/environment.py#L5) | Lưu trữ chuỗi thời gian (time-series) về nhiệt độ, độ ẩm và nồng độ CO2. |
| [telemetry/occupancy.py](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/telemetry/occupancy.py) | [Occupancy](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/telemetry/occupancy.py#L5) | Lưu trữ chuỗi thời gian về mật độ người ra vào và hiện diện trong phòng. |
| [telemetry/attendance_event.py](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/telemetry/attendance_event.py) | [AttendanceStatus](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/telemetry/attendance_event.py#L5)<br>[AttendanceEvent](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/telemetry/attendance_event.py#L12) | Ghi nhận chi tiết các lượt quét thẻ RFID tại các vị trí cửa phòng và hành lang. |
| [__enum.py](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/__enum.py) | [AttendanceEventType](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/__enum.py#L3)<br>[UserRole](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/__enum.py#L8)<br>[RoomType](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/__enum.py#L14)<br>[RoomStatus](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/__enum.py#L18)<br>[RoomModeEnum](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/__enum.py#L22)<br>[SmokeState](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/__enum.py#L31)<br>[DeviceStatusEnum](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/__enum.py#L36)<br>[IRSignalType](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/__enum.py#L40)<br>[CardRegistrationStatus](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/models/__enum.py#L58) | Định nghĩa toàn bộ các kiểu dữ liệu liệt kê (Enums) dùng chung trong hệ thống. |

---

## 🤖 Tác nhân AI: MQTT Consumer & Trợ lý cá nhân (AI Agent Specification)

Hệ thống tích hợp Tác nhân AI (AI Agent) hoạt động độc lập dưới dạng một tiến trình biên (Edge Daemon) thực hiện đồng thời hai vai trò: **MQTT Message Consumer** để giám sát hệ thống và **Trợ lý cá nhân (Private Assistant)** tương tác trực tiếp với người quản lý.

### 1. Kiến trúc MQTT Message Consumer của AI Agent
AI Agent đăng ký (subscribe) trực tiếp các topic sự kiện từ MQTT Broker để liên tục cập nhật trạng thái hoạt động:
*   **Topic giám sát:**
    *   `campus/room/+/event`: Tiếp nhận các sự kiện chuyển đổi trạng thái từ FSM phòng học.
    *   `campus/room/+/anomaly`: Nhận các gói tin cảnh báo bất thường được sàng lọc từ Edge Gateway (ví dụ: phát hiện khói MQ2 vượt ngưỡng, nhiệt độ tăng đột biến).
    *   `campus/manager/+/query`: Nhận các câu hỏi ngôn ngữ tự nhiên trực tiếp từ người quản lý qua kênh chat MQTT.
*   **Cơ chế lưu trữ ngữ cảnh cục bộ (Sliding Window):** AI Agent duy trì một bộ nhớ đệm dạng sliding window lưu trữ dữ liệu telemetry (nhiệt độ, chất lượng không khí, số người hiện diện) trong 15 phút gần nhất của từng phòng học để sẵn sàng trích xuất bối cảnh vận hành (`operational context`) khi cần gọi LLM.

### 2. Trợ lý cá nhân hỗ trợ người quản lý (Manager's Private Assistant)
*   **Tự động đưa ra Khuyến nghị Vận hành (Interactive Recommendations):**
    *   Khi có sự kiện bất thường (ví dụ: nhiệt độ phòng vượt 35°C trong khi phòng đang ở trạng thái `LECTURE`), AI Agent thu thập 15 phút bối cảnh, gọi mô hình **Qwen 1B/Google Gemini** để chọn công cụ phù hợp từ danh sách công cụ cố định (ví dụ: `turn_on_fan`, `adjust_ac_temperature`).
    *   Đề xuất khuyến nghị bao gồm: Tên công cụ, Lý do lựa chọn (Reasoning), Tham số điều khiển. Tin nhắn này được gửi lên topic `campus/manager/alerts/recommendation` dưới dạng một JSON Payload để chờ phê duyệt.
*   **Cơ chế Duyệt qua Con người (Human-in-the-Loop):** Trợ lý không tự động điều khiển thiết bị (trừ cảnh báo cục bộ của còi buzzer phần cứng). Trợ lý xuất bản đề xuất và chờ phản hồi phê duyệt từ Admin trên API (`Execute` hoặc `Ignore`). Khi Admin duyệt, API sẽ gửi lệnh điều khiển xuống thiết bị qua MQTT.
*   **Xử lý Truy vấn Ngôn ngữ Tự nhiên (Natural Language RAG Chatbot):**
    *   Người quản lý gửi câu hỏi (ví dụ: *"Có phòng nào nhiệt độ bất thường vào hôm qua không?"*).
    *   Hệ thống sử dụng LLM để xử lý câu hỏi ngôn ngữ tự nhiên từ người dùng về lịch sử vận hành phòng học hoặc tình hình điểm danh hoặc thực thi các yêu cầu phù hợp.
    *   Sử dụng embedding và thuật toán tìm kiếm cosine similarity truy vấn cơ sở dữ liệu vector (`pgVector` trong [edge/database.py](file:///Ubuntu/home/user_kma_chinh/SmartCampus/edge/database.py)) để tìm các bản tóm tắt vận hành liên quan được tạo định kỳ bởi LLM Summarizer.
    *   Tạo câu trả lời chi tiết và gửi phản hồi đến topic `campus/manager/chat/response`.

---