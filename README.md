# 优衣库价格监控

自动监控优衣库商品价格变动，降价时通过 Server酱 推送微信通知。

## 功能

- 输入货号查询优衣库商品价格
- 自动定时检查价格（默认每 3 小时）
- 价格变动时通过 Server酱 推送微信通知
- 网页管理界面：监控列表、价格历史、操作日志
- 支持京东链接自动识别货号
- Docker 一键部署

## 快速开始

### 1. 获取 Server酱 Key

1. 访问 https://sct.ftqq.com/
2. 微信扫码登录
3. 复制 SendKey

### 2. 部署

```bash
# 克隆项目
git clone https://github.com/你的用户名/uniqlo-price-monitor.git
cd uniqlo-price-monitor

# 创建环境变量文件
cp .env.example .env
```

编辑 `.env`，填入你的 Server酱 Key：

```
DATABASE_URL=sqlite:////data/data.db
SERVERCHAN_KEY=SCT你的Key
```

### 3. Docker 部署（推荐）

```bash
docker-compose up -d --build
```

访问 http://你的IP:17523 即可使用。

### 4. 本地开发

```bash
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium

# 启动
uvicorn app.main:app --host 0.0.0.0 --port 17523
```

## 配置说明

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| DATABASE_URL | 数据库连接 | sqlite:///data.db |
| SERVERCHAN_KEY | Server酱推送 Key | 空（不推送） |

## 技术栈

- **后端**: FastAPI + SQLAlchemy + SQLite
- **爬虫**: Playwright (Chromium)
- **通知**: Server酱 (sct.ftqq.com)
- **部署**: Docker

## 项目结构

```
├── app/
│   ├── config.py          # 配置
│   ├── crawler.py         # 优衣库爬取模块
│   ├── database.py        # 数据库连接
│   ├── main.py            # FastAPI 主程序
│   ├── models.py          # 数据模型
│   ├── notify.py          # Server酱推送
│   ├── schemas.py         # API 数据模型
│   └── static/index.html  # 网页前端
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

## License

MIT
