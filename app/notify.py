"""
Server酱推送模块
通过 Server酱 (sct.ftqq.com) 发送微信通知
"""

import logging
import requests

logger = logging.getLogger(__name__)

# Server酱 SendKey（从环境变量或配置读取）
SERVERCHAN_KEY = ""


def set_key(key: str):
    global SERVERCHAN_KEY
    SERVERCHAN_KEY = key


def send_notification(title: str, content: str = "") -> bool:
    """发送通知到微信"""
    if not SERVERCHAN_KEY:
        logger.warning("Server酱 Key 未配置，跳过通知")
        return False

    url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
    data = {
        "title": title[:32],
        "desp": content,
    }

    try:
        resp = requests.post(url, data=data, timeout=10)
        result = resp.json()
        if result.get("code") == 0:
            logger.info("通知发送成功: %s", title)
            return True
        else:
            logger.warning("通知发送失败: %s", result)
            return False
    except Exception as e:
        logger.error("通知发送异常: %s", e)
        return False


def send_price_drop(product_name: str, product_code: str,
                     old_price: float, new_price: float) -> bool:
    """发送降价通知"""
    discount = old_price - new_price
    discount_pct = round(discount / old_price * 100)

    title = f"降价提醒: {product_name}"
    content = f"""
## {product_name}

| 项目 | 价格 |
|------|------|
| 原价 | ¥{old_price} |
| 现价 | ¥{new_price} |
| 降幅 | ¥{discount}（{discount_pct}%） |

货号: {product_code}
"""
    return send_notification(title, content)
