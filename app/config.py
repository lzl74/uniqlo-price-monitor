import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'data.db')}")

# 爬取间隔（小时）
CRAWL_INTERVAL_HOURS = 3

# Server酱推送 Key（从环境变量读取）
SERVERCHAN_KEY = os.getenv("SERVERCHAN_KEY", "")
