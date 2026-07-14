"""
优衣库商品爬取模块 — 基于 Playwright 浏览器自动化
每次查询使用独立浏览器实例，避免线程冲突
"""

import json
import time
import logging
from typing import Optional
from datetime import datetime

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)


def _create_browser():
    """创建独立的浏览器实例"""
    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1920, "height": 1080},
        locale="zh-CN",
    )
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = { runtime: {} };
    """)
    # 访问首页建立 session
    page = context.new_page()
    page.goto("https://www.uniqlo.cn/", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(2000)
    page.close()
    return pw, browser, context


def close_browser():
    pass


def fetch_product(product_code: str) -> Optional[dict]:
    """查询单个商品信息"""
    pw, browser, context = _create_browser()
    page = context.new_page()
    api_data = {}

    try:
        def on_response(response):
            url = response.url
            try:
                if "json" in response.headers.get("content-type", ""):
                    data = response.json()
                    if "product/spu" in url or "spu/pc/query" in url:
                        api_data["detail"] = data
                    elif "promotion" in url and "optionByProductCode" in url:
                        api_data["promotion"] = data
            except:
                pass

        page.on("response", on_response)

        search_url = f"https://www.uniqlo.cn/search.html?description={product_code}&searchType=1"
        page.goto(search_url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        product_links = page.evaluate("""
            () => {
                const links = document.querySelectorAll('a[href*="product-detail"]');
                return Array.from(links).map(a => {
                    const url = new URL(a.href);
                    return {
                        productCode: url.searchParams.get('productCode'),
                        href: a.href,
                    };
                }).filter(l => l.productCode);
            }
        """)

        if not product_links:
            return None

        seen = set()
        unique = [l for l in product_links if l["productCode"] not in seen and not seen.add(l["productCode"])]

        page.goto(unique[0]["href"], wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(5000)

        return _parse(api_data, unique[0])

    except Exception as e:
        logger.error("fetch_product error: %s", e)
        return None
    finally:
        page.close()
        context.close()
        browser.close()
        pw.stop()


def _parse(api_data: dict, link_info: dict) -> Optional[dict]:
    detail = api_data.get("detail", {})
    if not detail:
        return None

    resp = detail.get("resp", [])
    if not resp or not isinstance(resp, list):
        return None

    first = resp[0]
    summary = first.get("summary", {})
    if not summary:
        return None

    time_limited = None
    if summary.get("timeLimitedBegin"):
        time_limited = {
            "begin": summary["timeLimitedBegin"],
            "end": summary.get("timeLimitedEnd"),
        }

    promotions = []
    promo = api_data.get("promotion", {})
    if promo:
        for item in promo.get("resp", []):
            if isinstance(item, str):
                promotions.append(item)
            elif isinstance(item, dict):
                for act in item.get("activitys", []):
                    if isinstance(act, dict) and act.get("pageShow"):
                        promotions.append(act["pageShow"])

    return {
        "internal_code": summary.get("productCode", ""),
        "product_code": link_info["productCode"],
        "name": summary.get("name", ""),
        "original_price": summary.get("originPrice", 0),
        "current_price": summary.get("minPrice", 0),
        "min_size": summary.get("minSize", ""),
        "max_size": summary.get("maxSize", ""),
        "sku_count": len(first.get("rows", [])),
        "evaluation_count": int(summary.get("evaluationCount", 0)),
        "is_active": summary.get("inactive", "Y") == "N",
        "time_limited": time_limited,
        "promotions": promotions,
        "url": link_info.get("href", ""),
    }


def extract_product_code(input_str: str) -> str:
    """从用户输入中提取货号"""
    import re
    if "uniqlo" in input_str or "http" in input_str:
        m = re.search(r'productCode=(u?\d+)', input_str)
        if m:
            return m.group(1)
        m = re.search(r'(\d{6})', input_str)
        if m:
            return m.group(1)
    m = re.search(r'(\d{6})', input_str)
    if m:
        return m.group(1)
    return input_str.strip()


def is_taobao_or_jd(url: str) -> bool:
    """判断是否为淘宝/京东链接"""
    return any(domain in url for domain in [
        "taobao.com", "tmall.com", "tb.cn",
        "jd.com", "jingdong.com", "3.cn",
    ])


def fetch_code_from_mall(url: str, title_hint: str = "") -> Optional[str]:
    """从淘宝/京东商品页提取优衣库货号"""
    import re
    from urllib.parse import unquote

    is_taobao = any(d in url for d in ["taobao.com", "tmall.com", "tb.cn", "e.tb.cn"])

    if is_taobao:
        return None

    pw, browser, context = _create_browser()
    page = context.new_page()

    try:
        logger.info("Resolving short link: %s", url[:80])
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        redirect_url = unquote(page.url)
        logger.info("Resolved to: %s", redirect_url[:120])

        jd_product_id = None
        m = re.search(r'jd\.com/product/(\d+)', redirect_url)
        if m:
            jd_product_id = m.group(1)
        else:
            m = re.search(r'item\.jd\.com/(\d{5,})', redirect_url)
            if m:
                jd_product_id = m.group(1)

        if jd_product_id:
            pc_url = f"https://item.jd.com/{jd_product_id}.html"
            logger.info("Directly visiting JD PC page: %s", pc_url)
            page.goto(pc_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(5000)

        title = page.title() or ""
        logger.info("Mall page title: %s", title[:120])

        title_codes = re.findall(r'(\d{6})', title)
        if title_codes:
            code = title_codes[0]
            logger.info("Extracted product code from title: %s", code)
            return code

        logger.warning("Could not extract product code")
        return None

    except Exception as e:
        logger.error("fetch_code_from_mall error: %s", e)
        return None
    finally:
        page.close()
        context.close()
        browser.close()
        pw.stop()
