


I. Cài đặt và chạy bot
chuẩn bị:
cài python 3.13, pip3, chrome, ffmpeg, aria2, python3-is-python, pm2
Cài chrome:
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb & sudo apt install ./google-chrome*.deb
Bước 1: Cấu hình file settings.json:
{
    "websub_url": "https://app158158.doancongdung2k6.click/websub",
    "ngrok_auth_token": "2s1nhBnjhjvlBqvcSHIgk90D663_7xFhBqniyMGDYwsUYRT5M",
    "domain_type": "domain",
    "telegram": "7387987323|8017073901:AAG4EoJoBodCWYjsyTyww0lXcbz6xg3Mup0"
}
- websub_url: url dùng cho websub, cấu hình ở phần II bên dưới
- ngrok_auth_token: Nếu không dùng domain cố định thì sử dụng domain của ngrok, đăng ký account ngrok rồi lấy auth ngrok_auth_token
- domain_type: domain -> nếu không dùng ngrok, ngrok -> nếu chưa có domain thì dùng ngrok
- telegram: Gồm các cặp telegram_chat_id|telegram_bot_token ngăn cách nhau bằng ký tự ";". Được dùng để nhận thông báo khi file cấu hình của 1 kênh YT bị lỗi
- is_human: giá trị chung của is_human khi không được cấu hình trong từng kênh. 1 -> Thêm vài tao tác rê chuột, click vài element khác, 0: không làm thao tác thừa

Bước 2: Tạo folder configs chứa các sub folder là ID của kênh youtube, thêm các file config.json và cookies.json cho từng folder, cấu hình file config cho từng kênh
 Các thông số trong config.json:
- youtube_channel_id: ID của kênh Yt
- youtube_api_key: 1 hoặc nhiều API key ngăn cách nhau bằng ký tự ;
- api_scan_method: Chọn phương pháp quét kênh bằng api. Nếu = "sequence" -> quét tuần tự dùng 1 api key đầu tiên còn khả dụng. Nếu = "parallel" -> quét đồng thời dùng tất cả api key và dừng quét khi có 1 api key trả về kết quả
- youtube_api_type: Chọn loại youtube api để quét, mặc định là "activities", có thể có 2 giá trị là "activities" hoặc "playlistItems"
- telegram: Danh sách bot telegram nhận thông báo. Định dạng là "telegram_chat_id1|telegram_bot_token1;telegram_chat_id2|telegram_bot_token2"
- proxy: Proxy dùng khi upload tiktok. Cú pháp là "ip:port:username:password"
- username: Tên kênh tiktok
- video_format: "299+140-1" -> video 1080p, "298+140-1" -> video 720p, "788+140-1" -> video width=608, "135+140-1" -> video width, bỏ trống là "18"
- user_agent: Chuỗi User Agent để qua mặt bot detection
- detect_video: "both" -> quét bằng cả api key và websub, "websub" -> chỉ đăng ký websub không quét, "api" -> chỉ quét bằng api key 
- render_video_method: Phương pháp render video khi 30s < độ dài video < 60s. "slowdown" -> làm chậm video, "repeat" -> lặp video. Mặc định là "repeat"
- is_new_second: Thời gian tối đa bằng giây tính từ lúc youtube video được xuất bản đến khi phát hiện video và video được coi là mới xuất bản lên Youtube
- scan_interval: Tần suất quét kênh Youtube để lấy video mới tính bằng giây
- is_human: 1 -> Thêm vài tao tác rê chuột, click vài element khác, 0: không làm thao tác thừa
- upload_method: api -> upload tiktok bằng api, browser -> upload bằng playwright với chrome browser
- region: aws region để đẩy video lên. ap-northeast-3 -> cho account Nhật, ap-southeast-1 -> cho account việt nam, us-east-1 -> cho account Mỹ
Bước 3: Đăng nhập vào tiktok, dùng Chrome extension tên J2TEAM Cookies cho trang tiktok, chọn Export -> Export as file
rồi đổi tên file vừa download thành cookies.json -> chuyển file cookies.json vào folder của kênh youtube thay thế file cookies.json cũ
Bước 4: Nếu kênh youtube yêu cầu đăng nhập thì tạo file yt_cookies.txt bằng browser extension get cookies.txt locally
Bước 5: Chạy autobot:
Thiết lập executable cho file install.sh: chmod +x install.sh
Windows: mở Powershell terminal -> chuyển đến thư mục chứa bot -> nhập lệnh .\install.ps1
Mac or Linux: mở bash terminal -> chuyển đến thư mục chứa bot -> nhập lệnh ./install.sh

📌 **Ghi chú riêng cho macOS (Apple Silicon)**
- Cài Homebrew (https://brew.sh/) nếu chưa có, sau đó chạy: `brew install python@3.13 ffmpeg aria2`
- Cài đặt Google Chrome cho macOS (https://www.google.com/chrome/). Nếu đã có Chrome trong thư mục Applications thì script sẽ tái sử dụng.
- Nếu đã có Python 3.13 qua Homebrew, thêm `eval "$(/opt/homebrew/bin/brew shellenv)"` vào shell (zsh/bash) profile để lệnh `python3.13` khả dụng.
- Có thể chạy script mà không khởi động bot ngay bằng lệnh: `RUN_AUTOBOT=0 ./install.sh`. Khi đó, bạn có thể start bot sau bằng cách kích hoạt môi trường ảo (`source venv/bin/activate`) rồi chạy `python autobot.py`.
- Nếu muốn bỏ qua bước tải browser của patchright (khi đã cài sẵn), đặt thêm biến `SKIP_PLAYWRIGHT_INSTALL=1` trước khi chạy script.

Nếu dùng pm2 thì gõ lệnh:
pm2 install.sh --name bot1

II. Cài đặt domain và https cho server:
B1: Vào tenten cấu hình subdomain trỏ tới IP của server. Ex: subdomain app158158.doancongdung2k6.click trỏ tới 158.51.108.158
B2: SSH tới server chạy lệnh: 
sudo apt install ufw -y && ufw allow OpenSSH && sudo apt update && sudo apt install nginx -y && sudo ufw allow 'Nginx Full' && sudo apt install certbot python3-certbot-nginx -y
B3: Tạo server block cho http:
sudo nano /etc/nginx/sites-available/app158158.doancongdung2k6.click
server {
   listen 80;
   listen [::]:80;
   server_name app158158.doancongdung2k6.click;
   location /websub{
       proxy_pass http://127.0.0.1:8000;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
   }
}

sudo ln -s /etc/nginx/sites-available/app158158.doancongdung2k6.click /etc/nginx/sites-enabled/
sudo systemctl restart nginx

B4: Cài đặt https cho subdomain:
sudo certbot --nginx -d app158158.doancongdung2k6.click
B5: cập nhật https://app158158.doancongdung2k6.click/websub vào websub_url trong file settings.json và start bot

III. Chép sang máy khác chạy:
Chỉ cần copy các file:
install.sh
install.ps1
README.txt
requirements.txt
settings.json
yt_cookies.txt (nếu kênh yêu cầu đăng nhập vào youtube để download video)
autobot.py
folder configs