.PHONY: up down status logs restart-ai restart-edge build-frontend dev-frontend help

help:
	@echo "======================================================================"
	@echo " SmartCampus Platform - Docker Management Commands"
	@echo "======================================================================"
	@echo " make up             : Khởi chạy toàn bộ hệ thống bằng Docker"
	@echo " make down           : Dừng toàn bộ các container Docker"
	@echo " make status         : Xem danh sách container đang chạy (docker ps)"
	@echo " make logs           : Xem logs trực tiếp của AI Service & Edge API"
	@echo " make restart-ai     : Khởi động lại container AI Service"
	@echo " make restart-edge   : Khởi động lại container Edge Gateway"
	@echo " make dev-frontend   : Chạy Frontend ở chế độ dev (Vite hot reload :5173)"
	@echo "======================================================================"

up:
	@echo ">>> [1/3] Khởi chạy Edge Gateway & Mosquitto MQTT & TimescaleDB..."
	@cd edge && docker compose up -d
	@echo ">>> [2/3] Khởi chạy AI Service & pgvector & Ollama..."
	@cd "AI + Backend" && docker compose up -d
	@echo ">>> [3/3] Khởi chạy Frontend Digital Twin Web UI..."
	@docker start smartcampus-frontend 2>/dev/null || docker run -d --name smartcampus-frontend --network smartcampus-network -p 3000:80 smartcampus-frontend
	@echo "✅ Toàn bộ hệ thống SmartCampus đã khởi chạy thành công!"
	@echo "   - Frontend UI:  http://localhost:3000"
	@echo "   - AI Service:   http://localhost:8001"
	@echo "   - Edge API:     http://localhost:8000"
	@echo "   - MQTT Broker:  localhost:1883"

down:
	@echo ">>> Đang dừng các containers..."
	@-docker stop smartcampus-frontend 2>/dev/null || true
	@-cd "AI + Backend" && docker compose down
	@-cd edge && docker compose down
	@echo "🛑 Toàn bộ hệ thống đã dừng."

status:
	@docker ps --filter "name=smartcampus"

logs:
	@docker logs -f --tail 50 smartcampus-ai

restart-ai:
	@cd "AI + Backend" && docker compose restart ai-agent

restart-edge:
	@cd edge && docker compose restart api

build-frontend:
	@echo ">>> Đang build bản bundle mới nhất cho Frontend..."
	@cd frontend && npm run build
	@-docker cp frontend/dist/. smartcampus-frontend:/usr/share/nginx/html/ && docker restart smartcampus-frontend
	@echo "✅ Frontend đã được cập nhật thành công trên http://localhost:3000"


dev-frontend:
	@cd frontend && npm run dev
