# -*- coding: utf-8 -*-
"""AI行业早报 + 半导体科技股早报 自动生成脚本
运行环境：GitHub Actions (Ubuntu) / 本地
调度：每日 UTC 01:00 (北京时间 09:00) 由 GitHub Actions cron 触发
依赖：feedparser, yfinance, requests
LLM：智谱 GLM-4-Flash（免费额度）
"""
import os
import sys
import json
import re
import glob
import feedparser
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ============ 配置 ============
ZHIPU_API_KEY = os.environ.get("ZHIPU_API_KEY", "")
if not ZHIPU_API_KEY:
    print("⚠️ ZHIPU_API_KEY 未设置，将使用纯RSS数据生成报告（无AI分析）")

SCRIPT_DIR = Path(__file__).parent.resolve()
OUTPUT_DIR = SCRIPT_DIR / "docs" / "reports"
INDEX_FILE = SCRIPT_DIR / "docs" / "index.html"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# AI 新闻 RSS 源
RSS_FEEDS = [
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://www.technologyreview.com/feed/",
    "https://venturebeat.com/feed/",
    "https://techcrunch.com/feed/",
]

# 追踪的11只股票
STOCKS = [
    ("NVDA", "英伟达"),
    ("AMD", "AMD"),
    ("TSM", "台积电ADR"),
    ("MRVL", "Marvell科技"),
    ("MU", "美光科技"),
    ("SOXL", "SOXL(3倍半导体ETF)"),
    ("DELL", "戴尔科技"),
    ("IREN", "IREN(比特币矿企)"),
    ("NBIS", "Nebius Group"),
    ("005930.KS", "三星电子"),
    ("000660.KS", "SK海力士"),
]

# 2026年美股休市日
US_HOLIDAYS_2026 = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
    "2026-05-25", "2026-07-03", "2026-09-07", "2026-11-26",
    "2026-12-25",
}

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# ============ 日期工具 ============
def get_beijing_now():
    utc_now = datetime.now(timezone.utc)
    return utc_now + timedelta(hours=8)

def is_weekend(dt):
    return dt.weekday() >= 5

def is_us_holiday(dt):
    return dt.strftime("%Y-%m-%d") in US_HOLIDAYS_2026

def should_generate_stock_report(dt):
    """工作日且非美股假日才生成股票报告"""
    return not is_weekend(dt) and not is_us_holiday(dt)

# ============ RSS 新闻抓取 ============
def fetch_ai_news(max_per_feed=5):
    """从RSS源抓取AI新闻，自动去重"""
    all_news = []
    seen_titles = set()
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            source_name = feed.feed.get("title", feed_url.split("/")[2])
            count = 0
            for entry in feed.entries:
                if count >= max_per_feed:
                    break
                title = entry.get("title", "").strip()
                if not title:
                    continue
                # 去重：标题前30字作为指纹
                title_key = title[:30]
                if title_key in seen_titles:
                    continue
                seen_titles.add(title_key)
                summary = entry.get("summary", entry.get("description", "")).strip()
                summary = re.sub(r'<[^>]+>', '', summary)[:300]
                link = entry.get("link", "")
                published = entry.get("published", entry.get("updated", ""))
                all_news.append({
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "published": published,
                    "source": source_name,
                })
                count += 1
        except Exception as e:
            print(f"  ⚠️ RSS抓取失败 {feed_url}: {e}")
    print(f"📰 共抓取 {len(all_news)} 条AI新闻（去重后）")
    return all_news

# ============ 股价数据获取 ============
def fetch_stock_data():
    """使用yfinance批量获取股价数据（单次API调用）"""
    import yfinance as yf
    symbols = [s[0] for s in STOCKS]
    names = {s[0]: s[1] for s in STOCKS}

    # 批量下载，1次请求拿全部
    try:
        data = yf.download(symbols, period="5d", progress=False, group_by='ticker')
    except Exception as e:
        print(f"  ⚠️ yfinance批量下载失败: {e}")
        data = None

    stocks_data = []
    for symbol in symbols:
        try:
            if data is not None and symbol in data.columns.get_level_values(0):
                hist = data[symbol]
            elif data is not None and len(symbols) == 1:
                hist = data
            else:
                hist = None

            if hist is None or hist.empty:
                # 降级：单独请求
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="5d")

            if hist.empty:
                stocks_data.append({
                    "symbol": symbol, "name": names[symbol],
                    "price": "N/A", "change_pct": 0, "direction": "flat",
                })
                continue

            current_close = float(hist['Close'].iloc[-1])
            if len(hist) >= 2:
                prev_close = float(hist['Close'].iloc[-2])
                change_pct = ((current_close - prev_close) / prev_close) * 100
                direction = "up" if change_pct > 0 else ("down" if change_pct < 0 else "flat")
            else:
                change_pct = 0
                direction = "flat"

            stocks_data.append({
                "symbol": symbol,
                "name": names[symbol],
                "price": round(current_close, 2),
                "change_pct": round(change_pct, 2),
                "direction": direction,
            })
        except Exception as e:
            print(f"  ⚠️ 股价获取失败 {symbol}: {e}")
            stocks_data.append({
                "symbol": symbol, "name": names[symbol],
                "price": "N/A", "change_pct": 0, "direction": "flat",
            })
    print(f"📈 共获取 {len(stocks_data)} 只股票数据")
    return stocks_data

# ============ GLM-4-Flash API ============
def call_glm(prompt, system_prompt="", temperature=0.7, max_tokens=2048):
    """调用智谱GLM-4-Flash API"""
    if not ZHIPU_API_KEY:
        return None

    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    headers = {
        "Authorization": f"Bearer {ZHIPU_API_KEY}",
        "Content-Type": "application/json",
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    data = {
        "model": "glm-4-flash",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=120)
        resp.raise_for_status()
        result = resp.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"  ⚠️ GLM API调用失败: {e}")
        return None

def call_glm_json(prompt, system_prompt=""):
    """调用GLM并尝试解析JSON输出"""
    raw = call_glm(prompt, system_prompt)
    if not raw:
        return None
    # 尝试提取JSON
    # 先找 ```json ... ``` 块
    m = re.search(r'```json\s*(.*?)\s*```', raw, re.DOTALL)
    if m:
        raw = m.group(1)
    # 再找 { ... } 块
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m and not raw.strip().startswith("{"):
        raw = m.group(0)
    try:
        return json.loads(raw)
    except:
        print(f"  ⚠️ JSON解析失败，原始输出前200字: {raw[:200]}")
        return None

# ============ GLM 生成 AI 报告内容 ============
def generate_ai_report_content(news_items, beijing_dt):
    """使用GLM-4-Flash从新闻数据生成结构化AI报告内容"""
    date_str = beijing_dt.strftime("%Y-%m-%d")
    weekday = WEEKDAY_CN[beijing_dt.weekday()]

    # 准备新闻摘要（精简：只取前15条，摘要截断到100字）
    news_text = ""
    for i, n in enumerate(news_items[:15], 1):
        news_text += f"\n[{i}] {n['title']} | {n['summary'][:100]} | {n['source']}\n"

    system_prompt = "你是AI行业分析师，输出JSON格式AI行业早报，不要输出其他内容。"

    prompt = f"""今日({date_str} {weekday})AI新闻：
{news_text}

整理为8章JSON：1.AI行业全景 2.AI编程工具生态 3.主流大模型 4.大厂AI产品 5.AI基础设施 6.半导体行业 7.今日摘要(3-5条) 8.信息来源(3-5个URL)。每章2-4条。

输出JSON：
{{"chapters":[{{"title":"一、AI行业全景","items":[{{"tag":"重磅","tag_class":"tag-red","title":"标题","body":"80-150字分析","source":"来源"}}]}}],"summary":["要点"],"sources":[{{"url":"URL","text":"来源名"}}]}}

tag_class: tag-red/tag-blue/tag-gray"""

    result = call_glm_json(prompt, system_prompt)
    if not result:
        print("  ⚠️ GLM AI报告生成失败，使用降级方案（纯RSS数据）")
        return generate_ai_report_fallback(news_items, beijing_dt)
    return result

def generate_ai_report_fallback(news_items, beijing_dt):
    """GLM失败时的降级方案：直接用RSS数据组装"""
    chapters = []
    # 把所有新闻放到一个章节
    items = []
    for n in news_items[:15]:
        items.append({
            "tag": "今日",
            "tag_class": "tag-blue",
            "title": n["title"],
            "body": n["summary"][:200],
            "source": n["source"],
        })
    chapters.append({"title": "一、AI行业新闻", "items": items})
    return {
        "chapters": chapters,
        "summary": [n["title"] for n in news_items[:5]],
        "sources": [{"url": n["link"], "text": n["source"]} for n in news_items[:5]],
    }

# ============ GLM 生成股票报告内容 ============
def generate_stock_report_content(stocks_data, beijing_dt):
    """使用GLM-4-Flash从股价数据生成结构化股票报告内容"""
    date_str = beijing_dt.strftime("%Y-%m-%d")
    weekday = WEEKDAY_CN[beijing_dt.weekday()]

    # 准备股价数据（精简格式）
    stock_text = ""
    for s in stocks_data:
        price = s.get("price", "N/A")
        pct = s.get("change_pct", 0)
        direction = "↑" if s.get("direction") == "up" else ("↓" if s.get("direction") == "down" else "→")
        stock_text += f"{s['symbol']}({s['name']}):{price}{direction}{pct}% "

    system_prompt = "你是半导体科技股分析师，输出JSON格式股票早报，不要输出其他内容。"

    prompt = f"""今日({date_str} {weekday})收盘：{stock_text}

生成5章JSON：1.板块综述 2.个股分析(覆盖全部11只) 3.行业要闻 4.风险提示 5.关注要点。涨红跌绿。

输出JSON：
{{"chapters":[{{"title":"一、板块综述","items":[{{"tag":"综述","tag_class":"tag-gray","title":"标题","body":"80-150字","source":"综合分析"}}]}}],"stock_cards":[{{"symbol":"NVDA","name":"英伟达","detail":"80-120字分析"}}],"summary":["要点"],"sources":[]}}

tag_class: tag-red/tag-blue/tag-gray"""

    result = call_glm_json(prompt, system_prompt)
    if not result:
        print("  ⚠️ GLM股票报告生成失败，使用降级方案")
        return generate_stock_report_fallback(stocks_data, beijing_dt)
    return result

def generate_stock_report_fallback(stocks_data, beijing_dt):
    """GLM失败时的降级方案"""
    items = []
    for s in stocks_data:
        direction = "涨" if s.get("direction") == "up" else "跌"
        items.append({
            "tag": s["symbol"],
            "tag_class": "tag-gray",
            "title": f"{s['name']} 收盘{s['price']} ({direction}{s['change_pct']}%)",
            "body": f"{s['name']}（{s['symbol']}）收盘价{s['price']}，涨跌幅{s['change_pct']}%。",
            "source": "yfinance",
        })
    return {
        "chapters": [{"title": "一、个股数据", "items": items}],
        "stock_cards": [{"symbol": s["symbol"], "name": s["name"], "detail": f"收盘价{s['price']}"} for s in stocks_data],
        "summary": [f"{s['name']} {s['change_pct']}%" for s in stocks_data[:5]],
        "sources": [],
    }

# ============ HTML 生成 ============
AI_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>AI行业早报 {title_date}（{weekday_cn}）</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#f0f4f8;color:#1e293b;line-height:1.8}}
.header{{background:linear-gradient(135deg,#1a56db,#2563eb);color:#fff;padding:28px 20px;text-align:center}}
.header h1{{font-size:24px;margin-bottom:6px}}
.header .sub{{font-size:16px;margin:6px 0}}
.header .meta{{font-size:12px;opacity:.82;margin-top:8px}}
.container{{max-width:960px;margin:0 auto;padding:16px}}
.section{{background:#fff;border-radius:12px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.07)}}
.section h2{{font-size:17px;color:#1a56db;border-left:4px solid #2563eb;padding-left:10px;margin-bottom:14px}}
.news-item{{padding:10px 0;border-bottom:1px solid #f1f5f9}}
.news-item:last-child{{border-bottom:none}}
.news-tag{{display:inline-block;font-size:11px;padding:1px 7px;border-radius:4px;margin-right:6px;font-weight:700}}
.tag-red{{background:#fef2f2;color:#dc2626}}
.tag-blue{{background:#eff6ff;color:#2563eb}}
.tag-gray{{background:#f3f4f6;color:#6b7280}}
.news-title{{font-size:14.5px;font-weight:600;margin:5px 0;color:#1e293b}}
.news-body{{font-size:13px;color:#475569;line-height:1.85}}
.news-source{{font-size:12px;color:#94a3b8;margin-top:5px}}
.summary-item{{padding:7px 0;font-size:13.5px;border-bottom:1px solid #f1f5f9}}
.sources a{{color:#2563eb;text-decoration:none;font-size:12.5px}}
.sources a:hover{{text-decoration:underline}}
.footer{{text-align:center;padding:20px;color:#94a3b8;font-size:12px}}
</style>
</head>
<body>
<div class="header">
  <h1>AI行业早报</h1>
  <div class="sub">{title_date}（{weekday_cn}）</div>
  <div class="meta">{meta_line}</div>
</div>
<div class="container">
{sections}
</div>
<div class="footer">由 GitHub Actions + GLM-4-Flash 自动生成 | 数据来源：RSS Feeds</div>
</body>
</html>"""

STOCK_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>半导体科技股早报 {title_date}（{weekday_cn}）</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#f0f4f8;color:#1e293b;line-height:1.8}}
.header{{background:linear-gradient(135deg,#1e3a5f,#2563eb);color:#fff;padding:28px 20px;text-align:center}}
.header h1{{font-size:24px;margin-bottom:6px}}
.header .sub{{font-size:16px;margin:6px 0}}
.header .meta{{font-size:12px;opacity:.82;margin-top:8px}}
.container{{max-width:960px;margin:0 auto;padding:16px}}
.section{{background:#fff;border-radius:12px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.07)}}
.section h2{{font-size:17px;color:#1a56db;border-left:4px solid #2563eb;padding-left:10px;margin-bottom:14px}}
.stock-card{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:16px;margin-bottom:12px}}
.stock-card:hover{{box-shadow:0 2px 8px rgba(0,0,0,.1)}}
.stock-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}}
.stock-name{{font-size:16px;font-weight:700;color:#1e293b}}
.stock-price{{font-size:20px;font-weight:800}}
.price-up{{color:#dc2626}}
.price-down{{color:#059669}}
.stock-change{{font-size:14px;font-weight:600}}
.stock-detail{{font-size:13px;color:#475569;line-height:1.8}}
.news-item{{padding:10px 0;border-bottom:1px solid #f1f5f9}}
.news-item:last-child{{border-bottom:none}}
.news-tag{{display:inline-block;font-size:11px;padding:1px 7px;border-radius:4px;margin-right:6px;font-weight:700}}
.tag-red{{background:#fef2f2;color:#dc2626}}
.tag-blue{{background:#eff6ff;color:#2563eb}}
.tag-gray{{background:#f3f4f6;color:#6b7280}}
.news-title{{font-size:14.5px;font-weight:600;margin:5px 0;color:#1e293b}}
.news-body{{font-size:13px;color:#475569;line-height:1.85}}
.news-source{{font-size:12px;color:#94a3b8;margin-top:5px}}
.summary-item{{padding:7px 0;font-size:13.5px;border-bottom:1px solid #f1f5f9}}
.sources a{{color:#2563eb;text-decoration:none;font-size:12.5px}}
.footer{{text-align:center;padding:20px;color:#94a3b8;font-size:12px}}
</style>
</head>
<body>
<div class="header">
  <h1>半导体科技股早报</h1>
  <div class="sub">{title_date}（{weekday_cn}）</div>
  <div class="meta">{meta_line}</div>
</div>
<div class="container">
{sections}
</div>
<div class="footer">由 GitHub Actions + GLM-4-Flash 自动生成 | 数据来源：Yahoo Finance (yfinance)</div>
</body>
</html>"""


def build_news_item(tag_class, tag_text, title, body="", source="综合分析"):
    parts = [
        '  <div class="news-item">',
        f'      <span class="news-tag {tag_class}">{tag_text}</span>',
        f'      <div class="news-title">{title}</div>',
    ]
    if body:
        parts.append(f'      <div class="news-body">{body}</div>')
    if source:
        parts.append(f'      <div class="news-source">来源：{source}</div>')
    parts.append('    </div>')
    return '\n'.join(parts)

def build_section(title, items_html):
    return f"""  <div class="section">
    <h2>{title}</h2>
{chr(10).join(items_html)}
  </div>"""

def build_stock_card(symbol, name, price, change_pct, direction, detail):
    color_class = "price-up" if direction == "up" else ("price-down" if direction == "down" else "")
    arrow = "▲" if direction == "up" else ("▼" if direction == "down" else "—")
    price_str = f"${price}" if isinstance(price, (int, float)) else str(price)
    return f"""    <div class="stock-card">
      <div class="stock-header">
        <span class="stock-name">{symbol} {name}</span>
        <span class="stock-price {color_class}">{price_str}</span>
      </div>
      <div class="stock-change {color_class}">{arrow} {change_pct}%</div>
      <div class="stock-detail">{detail}</div>
    </div>"""

def build_summary_item(num, text):
    return f'    <div class="summary-item">{num}. <strong>{text}</strong></div>'

def build_source_link(url, text):
    return f'    <p>📌 <a href="{url}" target="_blank">{text}</a></p>'


def generate_ai_html(content, beijing_dt):
    """从GLM生成的内容组装AI报告HTML"""
    date_str = beijing_dt.strftime("%Y-%m-%d")
    weekday = WEEKDAY_CN[beijing_dt.weekday()]
    meta_line = f"自动生成 | GLM-4-Flash 智能分析 | {beijing_dt.strftime('%Y-%m-%d %H:%M')} CST"

    sections_html = []
    for ch in content.get("chapters", []):
        if isinstance(ch, str):
            sections_html.append(build_section(ch, []))
            continue
        items_html = []
        for item in ch.get("items", []):
            if isinstance(item, str):
                items_html.append(build_news_item("tag-gray", "今日", item))
            elif isinstance(item, dict):
                items_html.append(build_news_item(
                    item.get("tag_class", "tag-gray"),
                    item.get("tag", "今日"),
                    item.get("title", ""),
                    item.get("body", ""),
                    item.get("source", "综合分析"),
                ))
        ch_title = ch.get("title", "") if isinstance(ch, dict) else str(ch)
        sections_html.append(build_section(ch_title, items_html))

    # 摘要
    if content.get("summary"):
        summary_items = [build_summary_item(i+1, s if isinstance(s, str) else str(s)) for i, s in enumerate(content["summary"])]
        sections_html.append(build_section("今日摘要", summary_items))

    # 来源
    if content.get("sources"):
        source_items = []
        for s in content["sources"]:
            if isinstance(s, dict):
                source_items.append(build_source_link(s.get("url", ""), s.get("text", "")))
            elif isinstance(s, str):
                source_items.append(build_source_link(s, s))
        sections_html.append(build_section("信息来源", source_items))

    return AI_TEMPLATE.format(
        title_date=date_str,
        weekday_cn=weekday,
        meta_line=meta_line,
        sections='\n'.join(sections_html),
    )

def generate_stock_html(content, stocks_data, beijing_dt):
    """从GLM生成的内容组装股票报告HTML"""
    date_str = beijing_dt.strftime("%Y-%m-%d")
    weekday = WEEKDAY_CN[beijing_dt.weekday()]
    meta_line = f"自动生成 | GLM-4-Flash 智能分析 | {beijing_dt.strftime('%Y-%m-%d %H:%M')} CST"

    sections_html = []

    # 个股卡片（放在最前面）
    stock_cards_html = []
    stock_details = {}
    for s in content.get("stock_cards", []):
        if isinstance(s, dict) and "symbol" in s:
            stock_details[s["symbol"]] = s
    for sd in stocks_data:
        detail = stock_details.get(sd["symbol"], {}).get("detail", f"收盘价{sd['price']}")
        stock_cards_html.append(build_stock_card(
            sd["symbol"], sd["name"], sd["price"],
            sd["change_pct"], sd["direction"], detail,
        ))
    sections_html.append(build_section("个股行情", stock_cards_html))

    # 其他章节
    for ch in content.get("chapters", []):
        if isinstance(ch, str):
            sections_html.append(build_section(ch, []))
            continue
        items_html = []
        for item in ch.get("items", []):
            if isinstance(item, str):
                items_html.append(build_news_item("tag-gray", "综述", item))
            elif isinstance(item, dict):
                items_html.append(build_news_item(
                    item.get("tag_class", "tag-gray"),
                    item.get("tag", "综述"),
                    item.get("title", ""),
                    item.get("body", ""),
                    item.get("source", "综合分析"),
                ))
        ch_title = ch.get("title", "") if isinstance(ch, dict) else str(ch)
        sections_html.append(build_section(ch_title, items_html))

    # 摘要
    if content.get("summary"):
        summary_items = [build_summary_item(i+1, s if isinstance(s, str) else str(s)) for i, s in enumerate(content["summary"])]
        sections_html.append(build_section("关注要点", summary_items))

    # 来源
    if content.get("sources"):
        source_items = []
        for s in content["sources"]:
            if isinstance(s, dict):
                source_items.append(build_source_link(s.get("url", ""), s.get("text", "")))
            elif isinstance(s, str):
                source_items.append(build_source_link(s, s))
        sections_html.append(build_section("信息来源", source_items))

    return STOCK_TEMPLATE.format(
        title_date=date_str,
        weekday_cn=weekday,
        meta_line=meta_line,
        sections='\n'.join(sections_html),
    )

# ============ 索引页生成 ============
def generate_index():
    """扫描所有报告文件，生成索引页"""
    reports = sorted(OUTPUT_DIR.glob("*.html"), reverse=True)
    ai_reports = []
    stock_reports = []
    for f in reports:
        name = f.name
        if name.startswith("AI"):
            ai_reports.append(name)
        elif name.startswith("半导体"):
            stock_reports.append(name)

    # 按日期分组
    all_dates = set()
    for name in ai_reports + stock_reports:
        m = re.search(r'(\d{4}-\d{2}-\d{2})', name)
        if m:
            all_dates.add(m.group(1))
    sorted_dates = sorted(all_dates, reverse=True)

    rows_html = ""
    for date in sorted_dates:
        ai_file = next((n for n in ai_reports if date in n), None)
        stock_file = next((n for n in stock_reports if date in n), None)
        dt = datetime.strptime(date, "%Y-%m-%d")
        weekday = WEEKDAY_CN[dt.weekday()]
        ai_link = f'<a href="reports/{ai_file}">查看</a>' if ai_file else '<span style="color:#94a3b8">—</span>'
        stock_link = f'<a href="reports/{stock_file}">查看</a>' if stock_file else '<span style="color:#94a3b8">休市</span>'
        rows_html += f"""        <tr>
          <td>{date}</td>
          <td>{weekday}</td>
          <td>{ai_link}</td>
          <td>{stock_link}</td>
        </tr>\n"""

    index_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>AI行业早报 & 半导体科技股早报 - 日报索引</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#f0f4f8;color:#1e293b;line-height:1.8}}
.header{{background:linear-gradient(135deg,#1a56db,#2563eb);color:#fff;padding:28px 20px;text-align:center}}
.header h1{{font-size:24px;margin-bottom:6px}}
.header .sub{{font-size:14px;opacity:.85;margin-top:8px}}
.container{{max-width:960px;margin:0 auto;padding:16px}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.07)}}
th{{background:#1a56db;color:#fff;padding:12px 10px;font-size:14px;text-align:left}}
td{{padding:10px;border-bottom:1px solid #f1f5f9;font-size:14px}}
tr:hover{{background:#f8fafc}}
a{{color:#2563eb;text-decoration:none;font-weight:600}}
a:hover{{text-decoration:underline}}
.footer{{text-align:center;padding:20px;color:#94a3b8;font-size:12px}}
.stats{{display:flex;gap:16px;margin-bottom:16px}}
.stat-card{{background:#fff;border-radius:10px;padding:16px;flex:1;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.07)}}
.stat-num{{font-size:28px;font-weight:800;color:#1a56db}}
.stat-label{{font-size:12px;color:#64748b;margin-top:4px}}
</style>
</head>
<body>
<div class="header">
  <h1>AI行业早报 & 半导体科技股早报</h1>
  <div class="sub">GitHub Actions 自动生成 | 每日北京时间 09:00 更新</div>
</div>
<div class="container">
  <div class="stats">
    <div class="stat-card"><div class="stat-num">{len(ai_reports)}</div><div class="stat-label">AI行业早报</div></div>
    <div class="stat-card"><div class="stat-num">{len(stock_reports)}</div><div class="stat-label">半导体科技股早报</div></div>
    <div class="stat-card"><div class="stat-num">{len(sorted_dates)}</div><div class="stat-label">覆盖天数</div></div>
  </div>
  <table>
    <thead>
      <tr><th>日期</th><th>星期</th><th>AI行业早报</th><th>半导体科技股早报</th></tr>
    </thead>
    <tbody>
{rows_html}    </tbody>
  </table>
</div>
<div class="footer">Powered by GitHub Actions + GLM-4-Flash | RSS Feeds + Yahoo Finance</div>
</body>
</html>"""

    INDEX_FILE.write_text(index_html, encoding="utf-8")
    print(f"📋 索引页已更新: {INDEX_FILE}")

# ============ 主流程 ============
def main():
    beijing_dt = get_beijing_now()
    date_str = beijing_dt.strftime("%Y-%m-%d")
    weekday = WEEKDAY_CN[beijing_dt.weekday()]
    print(f"🚀 开始生成 {date_str}（{weekday}）日报...")
    print(f"   北京时间: {beijing_dt.strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. 生成 AI 行业早报
    print("\n📰 [1/3] 抓取AI新闻...")
    news = fetch_ai_news()
    print(f"   抓取到 {len(news)} 条新闻")

    print("🤖 [2/3] GLM-4-Flash 生成AI报告内容...")
    ai_content = generate_ai_report_content(news, beijing_dt)
    ai_html = generate_ai_html(ai_content, beijing_dt)
    ai_filename = f"AI行业早报-{date_str}.html"
    ai_path = OUTPUT_DIR / ai_filename
    ai_path.write_text(ai_html, encoding="utf-8")
    print(f"   ✅ AI报告已保存: {ai_filename}")

    # 2. 生成半导体科技股早报（仅工作日）
    if should_generate_stock_report(beijing_dt):
        print("\n📈 [3/3] 获取股价数据...")
        stocks_data = fetch_stock_data()

        print("🤖 GLM-4-Flash 生成股票报告内容...")
        stock_content = generate_stock_report_content(stocks_data, beijing_dt)
        stock_html = generate_stock_html(stock_content, stocks_data, beijing_dt)
        stock_filename = f"半导体科技股早报-{date_str}.html"
        stock_path = OUTPUT_DIR / stock_filename
        stock_path.write_text(stock_html, encoding="utf-8")
        print(f"   ✅ 股票报告已保存: {stock_filename}")
    else:
        reason = "周末" if is_weekend(beijing_dt) else "美股假日"
        print(f"\n⏭️ 跳过股票报告（{reason}）")

    # 3. 更新索引页
    print("\n📋 更新索引页...")
    generate_index()

    print(f"\n✅ 全部完成！{date_str}（{weekday}）日报已生成。")

if __name__ == "__main__":
    main()
