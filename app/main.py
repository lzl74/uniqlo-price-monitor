"""
优衣库价格监控 FastAPI 后端

启动方式:
    cd uniqlo-price-monitor
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""

import logging
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler

from app.database import engine, get_db, Base
from app.models import User, Product, PriceHistory, WatchList, Notification, Log
from app.schemas import (
    UserCreate, UserOut,
    ProductAdd, ProductOut,
    PriceHistoryOut,
    WatchAdd, WatchOut,
)
from app.crawler import fetch_product, extract_product_code, close_browser, is_taobao_or_jd, fetch_code_from_mall
from app.notify import send_price_drop, set_key
from app.config import SERVERCHAN_KEY

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


# ---- 生命周期 ----

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动: 建表 + 定时任务 + 推送配置
    Base.metadata.create_all(bind=engine)
    set_key(SERVERCHAN_KEY)
    scheduler.add_job(crawl_all_products, "interval", hours=3, id="crawl")
    scheduler.start()
    logger.info("Scheduler started, crawling every 3 hours")
    yield
    # 关闭
    scheduler.shutdown()


app = FastAPI(title="优衣库价格监控", version="1.0", lifespan=lifespan)


# ============================================================
# 日志辅助
# ============================================================

def _utcnow():
    from datetime import timezone, timedelta
    return datetime.now(timezone(timedelta(hours=8)))


def add_log(db: Session, action: str, detail: str = ""):
    db.add(Log(action=action, detail=detail, created_at=_utcnow()))
    db.commit()


# ============================================================
# 用户
# ============================================================

@app.post("/api/user/login", response_model=UserOut)
def user_login(payload: UserCreate, db: Session = Depends(get_db)):
    """微信登录：用 code 换取 openId"""
    import requests as req
    from app.config import WECHAT_APP_ID, WECHAT_APP_SECRET

    # 调用微信 code2Session 接口
    url = "https://api.weixin.qq.com/sns/jscode2session"
    params = {
        "appid": WECHAT_APP_ID,
        "secret": WECHAT_APP_SECRET,
        "js_code": payload.code,
        "grant_type": "authorization_code",
    }
    try:
        resp = req.get(url, params=params, timeout=10)
        data = resp.json()
        open_id = data.get("openid", "")
    except Exception as e:
        logger.error("WeChat login failed: %s", e)
        open_id = f"mock_{payload.code}"

    if not open_id:
        raise HTTPException(status_code=400, detail="微信登录失败")

    user = db.query(User).filter(User.open_id == open_id).first()
    if not user:
        user = User(open_id=open_id, nickname="")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


# ============================================================
# 商品
# ============================================================

@app.post("/api/product/add", response_model=ProductOut)
def add_product(payload: ProductAdd, db: Session = Depends(get_db)):
    """添加商品到监控。支持：货号、优衣库链接、淘宝/京东链接。"""
    input_str = payload.product_code.strip()

    # 判断是否为淘宝/京东链接
    if is_taobao_or_jd(input_str):
        logger.info("Detected Taobao/JD link, extracting product code...")
        code = fetch_code_from_mall(input_str, title_hint=payload.title_hint or "")
        if not code:
            raise HTTPException(status_code=404, detail="无法从该链接中识别优衣库货号，请确认商品标题中包含6位货号")
        # 淘宝链接无法自动提取时返回 TAOBAO_xxx
        if code.startswith("TAOBAO_"):
            taobao_id = code.replace("TAOBAO_", "")
            raise HTTPException(
                status_code=404,
                detail=f"淘宝商品(ID:{taobao_id})需要登录才能查看。请在淘宝APP中打开商品页，复制商品标题后重新搜索，或直接输入6位优衣库货号",
            )
    else:
        code = extract_product_code(input_str)

    # 先查库
    existing = db.query(Product).filter(Product.product_code == code).first()
    if existing:
        return existing

    # 爬取
    info = fetch_product(code)
    if not info:
        raise HTTPException(status_code=404, detail=f"找不到货号 {code} 对应的商品")

    product = Product(
        internal_code=info["internal_code"],
        product_code=code,
        name=info["name"],
        original_price=info["original_price"],
        current_price=info["current_price"],
        min_size=info["min_size"],
        max_size=info["max_size"],
        sku_count=info["sku_count"],
        evaluation_count=info["evaluation_count"],
        is_active=info["is_active"],
        url=info["url"],
        last_checked_at=_utcnow(),
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    add_log(db, "add_product", f"添加商品 {product.name} ({product.product_code})")
    return product


@app.get("/api/product/list", response_model=list[ProductOut])
def list_products(db: Session = Depends(get_db)):
    return db.query(Product).all()


@app.get("/api/product/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    return product


@app.get("/api/product/refresh/{product_id}")
def refresh_product_price(product_id: int, db: Session = Depends(get_db)):
    """手动刷新单个商品的最新价格"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")

    info = fetch_product(product.product_code)
    if not info:
        return {"ok": False, "error": "获取价格失败"}

    old_price = product.current_price
    new_price = info["current_price"]

    product.name = info["name"]
    product.original_price = info["original_price"]
    product.current_price = new_price
    product.evaluation_count = info["evaluation_count"]
    product.sku_count = info["sku_count"]
    product.is_active = info["is_active"]
    product.last_checked_at = _utcnow()

    if old_price is not None and old_price != new_price:
        db.add(PriceHistory(product_id=product.id, price=new_price,
            price_type="limited" if info.get("time_limited") else "normal"))
        if new_price < old_price:
            _check_and_notify(db, product, old_price, new_price)

    db.commit()
    if old_price != new_price:
        add_log(db, "refresh_price", f"刷新价格: {product.name} ¥{old_price} → ¥{new_price}")
    else:
        add_log(db, "refresh_price", f"刷新价格: {product.name} ¥{new_price} (无变化)")
    return {"ok": True, "old_price": old_price, "new_price": new_price}


@app.get("/api/product/{product_id}/price_history", response_model=list[PriceHistoryOut])
def get_price_history(product_id: int, db: Session = Depends(get_db)):
    records = (
        db.query(PriceHistory)
        .filter(PriceHistory.product_id == product_id)
        .order_by(PriceHistory.recorded_at.desc())
        .limit(100)
        .all()
    )
    return records


# ============================================================
# 监控列表
# ============================================================

@app.post("/api/watch/add", response_model=WatchOut)
def add_watch(payload: WatchAdd, user_id: int = 1, db: Session = Depends(get_db)):
    """添加商品到监控列表"""
    # 确保用户存在
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        user = User(id=user_id, open_id=f"default_{user_id}", nickname="默认用户")
        db.add(user)
        db.commit()

    code = extract_product_code(payload.product_code)

    # 确保商品存在
    product = db.query(Product).filter(Product.product_code == code).first()
    if not product:
        info = fetch_product(code)
        if not info:
            raise HTTPException(status_code=404, detail=f"找不到货号 {code}")
        product = Product(
            internal_code=info["internal_code"],
            product_code=code,
            name=info["name"],
            original_price=info["original_price"],
            current_price=info["current_price"],
            min_size=info["min_size"],
            max_size=info["max_size"],
            sku_count=info["sku_count"],
            evaluation_count=info["evaluation_count"],
            is_active=info["is_active"],
            url=info["url"],
            last_checked_at=_utcnow(),
        )
        db.add(product)
        db.commit()
        db.refresh(product)

    # 检查重复（不管是否激活）
    existing = (
        db.query(WatchList)
        .filter(WatchList.user_id == user_id, WatchList.product_id == product.id)
        .first()
    )
    if existing:
        if existing.is_active:
            raise HTTPException(status_code=400, detail="该商品已在监控列表中")
        # 已有但已停用，重新激活
        existing.is_active = True
        existing.target_price = payload.target_price
        db.commit()
        db.refresh(existing)
        add_log(db, "add_watch", f"重新激活监控: {product.name}")
        return existing

    watch = WatchList(
        user_id=user_id,
        product_id=product.id,
        target_price=payload.target_price,
    )
    db.add(watch)
    db.commit()
    db.refresh(watch)
    add_log(db, "add_watch", f"添加监控: {product.name} ({product.product_code})")
    return watch


@app.get("/api/watch/list", response_model=list[WatchOut])
def get_watch_list(user_id: int = 1, db: Session = Depends(get_db)):
    items = (
        db.query(WatchList)
        .filter(WatchList.user_id == user_id, WatchList.is_active == True)
        .all()
    )
    return items


@app.delete("/api/watch/{watch_id}")
def remove_watch(watch_id: int, db: Session = Depends(get_db)):
    item = db.query(WatchList).filter(WatchList.id == watch_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="监控项不存在")
    product = db.query(Product).filter(Product.id == item.product_id).first()
    item.is_active = False
    db.commit()
    add_log(db, "remove_watch", f"移除监控: {product.name if product else item.product_id}")
    return {"ok": True}


# ============================================================
# 定时爬取
# ============================================================

def crawl_all_products():
    """定时任务：批量更新所有在售商品的价格，每个商品间隔30秒"""
    import time
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        products = db.query(Product).filter(Product.is_active == True).all()
        logger.info("Crawling %d products...", len(products))
        add_log(db, "crawl_start", f"开始自动检查 {len(products)} 个商品")

        price_changed = 0
        for i, product in enumerate(products):
            try:
                # 每个商品间隔30秒，避免请求过快
                if i > 0:
                    time.sleep(30)

                info = fetch_product(product.product_code)
                if not info:
                    continue

                old_price = product.current_price
                new_price = info["current_price"]

                # 更新商品信息
                product.name = info["name"]
                product.original_price = info["original_price"]
                product.current_price = new_price
                product.evaluation_count = info["evaluation_count"]
                product.sku_count = info["sku_count"]
                product.is_active = info["is_active"]
                product.last_checked_at = _utcnow()

                # 价格变动时才记录历史
                if old_price is not None and old_price != new_price:
                    price_record = PriceHistory(
                        product_id=product.id,
                        price=new_price,
                        price_type="limited" if info.get("time_limited") else "normal",
                    )
                    db.add(price_record)
                    price_changed += 1
                    logger.info("  %s %s: ¥%.0f → ¥%.0f", product.product_code, product.name, old_price, new_price)

                    # 降价 → 检查是否需要通知
                    if new_price < old_price:
                        _check_and_notify(db, product, old_price, new_price)
                elif old_price is None:
                    # 首次记录
                    price_record = PriceHistory(
                        product_id=product.id,
                        price=new_price,
                        price_type="limited" if info.get("time_limited") else "normal",
                    )
                    db.add(price_record)
                    logger.info("  %s %s: ¥%.0f (首次记录)", product.product_code, product.name, new_price)

                db.commit()

            except Exception as e:
                logger.error("  Failed to crawl %s: %s", product.product_code, e)
                try:
                    db.rollback()
                except:
                    db = SessionLocal()

        add_log(db, "crawl_done", f"自动检查完成，{len(products)} 个商品，{price_changed} 个价格变动")

    finally:
        db.close()


def _check_and_notify(db: Session, product: Product, old_price: float, new_price: float):
    """检查监控列表，发送降价通知"""
    watch_items = (
        db.query(WatchList)
        .filter(
            WatchList.product_id == product.id,
            WatchList.is_active == True,
            WatchList.notify_on_drop == True,
        )
        .all()
    )

    # 如果有监控用户，发送通知
    if watch_items:
        for w in watch_items:
            if w.target_price is not None and new_price > w.target_price:
                continue

            notif = Notification(
                user_id=w.user_id,
                product_id=product.id,
                type="price_drop",
                old_price=old_price,
                new_price=new_price,
            )
            db.add(notif)

        # 发送 Server酱 通知
        sent = send_price_drop(product.name, product.product_code, old_price, new_price)
        logger.info("Notification sent: %s, result: %s", product.name, sent)


# ============================================================
# 测试通知
# ============================================================

@app.get("/api/test/notify")
def test_notify():
    """测试发送通知（仅用于调试）"""
    from app.notify import send_notification
    sent = send_notification("测试通知", "这是一条测试消息，如果你看到说明推送正常工作。")
    return {"ok": sent}


# ============================================================
# 数据库管理（单用户，无鉴权）
# ============================================================

@app.get("/api/db/summary")
def db_summary(db: Session = Depends(get_db)):
    """获取数据库概览"""
    return {
        "users": db.query(User).count(),
        "products": db.query(Product).count(),
        "watch_list": db.query(WatchList).filter(WatchList.is_active == True).count(),
        "price_history": db.query(PriceHistory).count(),
        "notifications": db.query(Notification).count(),
    }


@app.get("/api/db/products")
def db_products(db: Session = Depends(get_db)):
    return db.query(Product).all()


@app.get("/api/db/watch")
def db_watch(db: Session = Depends(get_db)):
    return db.query(WatchList).all()


@app.get("/api/db/price_history")
def db_price_history(db: Session = Depends(get_db)):
    return db.query(PriceHistory).order_by(PriceHistory.recorded_at.desc()).limit(200).all()


@app.get("/api/db/notifications")
def db_notifications(db: Session = Depends(get_db)):
    return db.query(Notification).order_by(Notification.created_at.desc()).limit(100).all()


@app.delete("/api/db/product/{product_id}")
def db_delete_product(product_id: int, db: Session = Depends(get_db)):
    db.query(PriceHistory).filter(PriceHistory.product_id == product_id).delete()
    db.query(WatchList).filter(WatchList.product_id == product_id).delete()
    db.query(Notification).filter(Notification.product_id == product_id).delete()
    db.query(Product).filter(Product.id == product_id).delete()
    db.commit()
    return {"ok": True}


@app.delete("/api/db/watch/{watch_id}")
def db_delete_watch(watch_id: int, db: Session = Depends(get_db)):
    db.query(WatchList).filter(WatchList.id == watch_id).delete()
    db.commit()
    return {"ok": True}


@app.delete("/api/db/price_history/{record_id}")
def db_delete_price_history(record_id: int, db: Session = Depends(get_db)):
    db.query(PriceHistory).filter(PriceHistory.id == record_id).delete()
    db.commit()
    return {"ok": True}


@app.delete("/api/db/notification/{notif_id}")
def db_delete_notification(notif_id: int, db: Session = Depends(get_db)):
    db.query(Notification).filter(Notification.id == notif_id).delete()
    db.commit()
    return {"ok": True}


@app.delete("/api/db/clear/{table}")
def db_clear_table(table: str, db: Session = Depends(get_db)):
    """清空指定表"""
    table_map = {
        "price_history": PriceHistory,
        "notifications": Notification,
    }
    model = table_map.get(table)
    if not model:
        raise HTTPException(status_code=400, detail="不支持清空该表")
    db.query(model).delete()
    db.commit()
    return {"ok": True}


@app.get("/api/logs")
def get_logs(limit: int = 50, db: Session = Depends(get_db)):
    return db.query(Log).order_by(Log.created_at.desc()).limit(limit).all()


@app.delete("/api/logs/clear")
def clear_logs(db: Session = Depends(get_db)):
    db.query(Log).delete()
    db.commit()
    return {"ok": True}


# ============================================================
# 健康检查
# ============================================================

@app.get("/api/health")
def health():
    return {"status": "ok", "time": _utcnow().isoformat()}


# ============================================================
# 静态文件（说明页）
# ============================================================

import os
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
