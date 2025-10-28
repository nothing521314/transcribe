# Hướng dẫn cài đặt trên Windows

## 1. Cài đặt Git Bash
- Tải Git Bash từ trang chủ: https://git-scm.com/downloads
- Chọn phiên bản Windows và tiến hành cài đặt
- Trong quá trình cài đặt, giữ các tùy chọn mặc định

## 2. Cài đặt Docker Desktop
- Tải Docker Desktop từ: https://www.docker.com/products/docker-desktop
- Cài đặt Docker Desktop
- Sau khi cài đặt xong, khởi động lại máy tính
- Mở Command Prompt với quyền Administrator
- Chạy lệnh sau để cập nhật WSL:
```bash
wsl --update
```
- Đảm bảo Docker Desktop được cấu hình để khởi động cùng Windows:
  - Mở Docker Desktop
  - Vào Settings > General
  - Chọn "Start Docker Desktop when you log in"

## 3. Khởi chạy ứng dụng
- Di chuyển đến thư mục chứa ứng dụng
- Chạy file start-app.sh bằng cách đúp chuột

## Xử lý sự cố
Nếu gặp lỗi khi chạy Docker, hãy kiểm tra:
- WSL 2 đã được cài đặt và cập nhật
- Virtualization đã được bật trong BIOS
- Docker Desktop đang chạy