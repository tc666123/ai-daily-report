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
import time
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

# 追踪的11只股票 - 包含交易所和币种信息
STOCKS = [
    {"symbol": "NVDA",      "name": "英伟达",         "exchange": "NASDAQ",   "currency": "USD"},
    {"symbol": "AMD",       "name": "超威半导体",     "exchange": "NASDAQ",   "currency": "USD"},
    {"symbol": "TSM",       "name": "台积电ADR",      "exchange": "NYSE",     "currency": "USD"},
    {"symbol": "MRVL",      "name": "Marvell科技",    "exchange": "NASDAQ",   "currency": "USD"},
    {"symbol": "MU",        "name": "美光科技",       "exchange": "NASDAQ",   "currency": "USD"},
    {"symbol": "SOXL",      "name": "三倍做多半导体ETF", "exchange": "NYSEARCA", "currency": "USD"},
    {"symbol": "DELL",      "name": "戴尔科技",       "exchange": "NYSE",     "currency": "USD"},
    {"symbol": "IREN",      "name": "IREN(Iris Energy)", "exchange": "NASDAQ", "currency": "USD"},
    {"symbol": "NBIS",      "name": "Nebius Group",   "exchange": "NASDAQ",   "currency": "USD"},
    {"symbol": "005930.KS", "name": "三星电子",       "exchange": "KRX",      "currency": "KRW"},
    {"symbol": "000660.KS", "name": "SK海力士",       "exchange": "KRX",      "currency": "KRW"},
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
def fetch_ai_news(max_per_feed=8):
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
                summary = re.sub(r'<[^>]+>', '', summary)[:500]
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

# ============ 股价数据获取（多源容错）============
def fetch_stock_via_yahoo_api(symbol, max_retries=3):
    """直接使用Yahoo Finance Chart API获取股票数据（最可靠的方式）"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {
        "interval": "1d",
        "range": "5d",
        "includePrePost": "false",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            if resp.status_code == 429:
                print(f"    Yahoo API限流 {symbol}, 等待重试 ({attempt+1}/{max_retries})...")
                time.sleep(2 ** (attempt + 1))
                continue
            resp.raise_for_status()
            data = resp.json()

            result = data["chart"]["result"][0]
            meta = result.get("meta", {})
            timestamps = result.get("timestamp", [])
            quotes = result.get("indicators", {}).get("quote", [{}])[0]

            closes = quotes.get("close", [])
            opens = quotes.get("open", [])
            highs = quotes.get("high", [])
            lows = quotes.get("low", [])
            volumes = quotes.get("volume", [])

            # 获取最新有效数据
            current_price = meta.get("regularMarketPrice", 0)
            prev_close = meta.get("chartPreviousClose", meta.get("previousClose", 0))

            # 如果meta没有，从历史数据取
            if not current_price and closes:
                for i in range(len(closes) - 1, -1, -1):
                    if closes[i] is not None:
                        current_price = closes[i]
                        break

            if not prev_close and len(closes) >= 2:
                for i in range(len(closes) - 2, -1, -1):
                    if closes[i] is not None:
                        prev_close = closes[i]
                        break

            if not current_price:
                return None

            change_pct = 0
            if prev_close and prev_close > 0:
                change_pct = round(((current_price - prev_close) / prev_close) * 100, 2)

            direction = "up" if change_pct > 0 else ("down" if change_pct < 0 else "flat")

            # 获取OHLCV
            open_price = opens[-1] if opens and opens[-1] is not None else None
            high_price = highs[-1] if highs and highs[-1] is not None else None
            low_price = lows[-1] if lows and lows[-1] is not None else None
            volume = volumes[-1] if volumes and volumes[-1] is not None else 0

            # 从meta获取基本面数据
            market_cap = meta.get("marketCap", 0)
            currency = meta.get("currency", "USD")
            exchange = meta.get("exchangeName", "")
            fifty_two_week_high = meta.get("fiftyTwoWeekHigh", 0)
            fifty_two_week_low = meta.get("fiftyTwoWeekLow", 0)
            symbol_raw = meta.get("symbol", symbol)

            # 尝试获取PE ratio（Chart API通常不提供，需要额外请求）
            pe_ratio = 0

            return {
                "symbol": symbol,
                "price": round(current_price, 2),
                "prev_close": round(prev_close, 2) if prev_close else None,
                "change_pct": change_pct,
                "direction": direction,
                "open": round(open_price, 2) if open_price else None,
                "high": round(high_price, 2) if high_price else None,
                "low": round(low_price, 2) if low_price else None,
                "volume": int(volume) if volume else 0,
                "market_cap": market_cap,
                "currency": currency,
                "exchange": exchange,
                "fifty_two_week_high": round(fifty_two_week_high, 2) if fifty_two_week_high else None,
                "fifty_two_week_low": round(fifty_two_week_low, 2) if fifty_two_week_low else None,
                "pe_ratio": pe_ratio,
                "data_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            }
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"    Yahoo API {symbol} 第{attempt+1}次失败: {e}, 重试中...")
                time.sleep(1.5 * (attempt + 1))
            else:
                print(f"    Yahoo API {symbol} 最终失败: {e}")
    return None

def fetch_stock_via_yfinance(symbol):
    """使用yfinance库作为备选方案"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="5d")
        if hist.empty:
            return None

        current_close = float(hist['Close'].iloc[-1])
        if len(hist) >= 2:
            prev_close = float(hist['Close'].iloc[-2])
        else:
            prev_close = current_close

        change_pct = round(((current_close - prev_close) / prev_close) * 100, 2) if prev_close else 0
        direction = "up" if change_pct > 0 else ("down" if change_pct < 0 else "flat")

        open_price = float(hist['Open'].iloc[-1]) if 'Open' in hist else None
        high_price = float(hist['High'].iloc[-1]) if 'High' in hist else None
        low_price = float(hist['Low'].iloc[-1]) if 'Low' in hist else None
        volume = int(hist['Volume'].iloc[-1]) if 'Volume' in hist else 0

        # 获取info
        market_cap = 0
        pe_ratio = 0
        fifty_two_week_high = 0
        fifty_two_week_low = 0
        try:
            info = ticker.info
            market_cap = info.get("marketCap", 0)
            pe_ratio = info.get("trailingPE", 0)
            fifty_two_week_high = info.get("fiftyTwoWeekHigh", 0)
            fifty_two_week_low = info.get("fiftyTwoWeekLow", 0)
        except:
            pass

        return {
            "symbol": symbol,
            "price": round(current_close, 2),
            "prev_close": round(prev_close, 2),
            "change_pct": change_pct,
            "direction": direction,
            "open": round(open_price, 2) if open_price else None,
            "high": round(high_price, 2) if high_price else None,
            "low": round(low_price, 2) if low_price else None,
            "volume": volume,
            "market_cap": market_cap,
            "currency": "USD",
            "exchange": "",
            "fifty_two_week_high": round(fifty_two_week_high, 2) if fifty_two_week_high else None,
            "fifty_two_week_low": round(fifty_two_week_low, 2) if fifty_two_week_low else None,
            "pe_ratio": pe_ratio,
            "data_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
    except Exception as e:
        print(f"    yfinance {symbol} 失败: {e}")
        return None

def fetch_stock_data():
    """批量获取所有股票数据，使用多源容错策略"""
    stocks_data = []
    success_count = 0
    fail_count = 0

    for stock_info in STOCKS:
        symbol = stock_info["symbol"]
        name = stock_info["name"]
        print(f"  获取 {symbol} ({name})...", end=" ")

        sd = None

        # 方案1: Yahoo Finance Chart API（最可靠）
        sd = fetch_stock_via_yahoo_api(symbol)
        if sd:
            print(f"✅ ${sd['price']} ({sd['change_pct']}%)")
            success_count += 1
        else:
            # 方案2: yfinance库
            print("Yahoo API失败，尝试yfinance...", end=" ")
            sd = fetch_stock_via_yfinance(symbol)
            if sd:
                print(f"✅ ${sd['price']} ({sd['change_pct']}%)")
                success_count += 1
            else:
                print("❌ 全部失败")
                fail_count += 1
                sd = {
                    "symbol": symbol,
                    "name": name,
                    "price": None,
                    "prev_close": None,
                    "change_pct": 0,
                    "direction": "flat",
                    "open": None,
                    "high": None,
                    "low": None,
                    "volume": 0,
                    "market_cap": 0,
                    "currency": stock_info["currency"],
                    "exchange": stock_info["exchange"],
                    "fifty_two_week_high": None,
                    "fifty_two_week_low": None,
                    "pe_ratio": 0,
                    "data_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                }

        # 补充名称等信息
        sd["name"] = name
        sd["exchange"] = sd.get("exchange") or stock_info["exchange"]
        sd["currency"] = sd.get("currency") or stock_info["currency"]
        stocks_data.append(sd)

        # 请求间隔，避免限流
        time.sleep(0.5)

    print(f"\n📈 股价数据获取完成: 成功{success_count}/失败{fail_count}（共{len(stocks_data)}只）")
    return stocks_data

# ============ 辅助：格式化数字 ============
def format_volume(vol):
    """格式化成交量"""
    if not vol or vol == 0:
        return "N/A"
    if vol >= 1e8:
        return f"{vol/1e8:.2f}亿"
    elif vol >= 1e4:
        return f"{vol/1e4:.1f}万"
    else:
        return str(vol)

def format_market_cap(cap, currency="USD"):
    """格式化市值"""
    if not cap or cap == 0:
        return "N/A"
    currency_symbol = "$" if currency == "USD" else ("₩" if currency == "KRW" else "")
    if cap >= 1e12:
        return f"{currency_symbol}{cap/1e12:.2f}万亿"
    elif cap >= 1e8:
        return f"{currency_symbol}{cap/1e8:.1f}亿"
    else:
        return f"{currency_symbol}{cap:.0f}"

def format_price(price, currency="USD"):
    """格式化价格"""
    if price is None:
        return "N/A"
    if currency == "KRW":
        return f"{price:,.0f} KRW"
    elif currency == "USD":
        return f"${price:,.2f}"
    else:
        return f"{price:,.2f}"

# ============ GLM-4-Flash API ============
def call_glm(prompt, system_prompt="", temperature=0.7, max_tokens=8192):
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
        resp = requests.post(url, headers=headers, json=data, timeout=180)
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

    # 准备新闻摘要
    news_text = ""
    for i, n in enumerate(news_items[:40], 1):
        news_text += f"\n[{i}] 标题: {n['title']}\n    摘要: {n['summary'][:300]}\n    来源: {n['source']}\n    链接: {n.get('link', '')}\n"

    system_prompt = """你是资深AI行业分析师，负责编写高质量的每日AI行业早报。你的分析必须深入、专业、信息量大。
每条新闻的分析不得少于150字，需要包含：事件背景、技术/商业细节、行业影响分析、相关公司或技术名称。
你必须严格按照JSON格式输出，不要输出其他任何内容。"""

    prompt = f"""基于以下今日({date_str} {weekday})RSS抓取的AI行业新闻，生成一份高质量、结构化的中文AI行业早报。

原始新闻数据：
{news_text}

请将新闻整理为以下8个章节，每个章节包含2-5条新闻条目。如果某个章节没有直接相关新闻，请根据行业知识写1-2条综合分析。

章节：
1. AI行业全景（重大事件、融资、并购、监管政策等）
2. AI编程工具生态（CodeBuddy/WorkBuddy/Cursor/Copilot/OpenClaw等AI Agent工具）
3. 主流大模型进展（GPT/Claude/Gemini/GLM/Llama/Qwen/DeepSeek等模型发布和能力更新）
4. 大厂AI产品动态（Google/Microsoft/Apple/Meta/OpenAI/Amazon/百度/阿里/腾讯等）
5. AI基础设施（芯片、数据中心、能源、算力、光模块、散热等）
6. 半导体行业（芯片制造、设备、材料、存储、先进制程等，与股票报告呼应）
7. 今日摘要（5-8条核心要点，每条一句话总结最重要的信息）
8. 信息来源（列出5-8个主要来源URL）

要求：
- 每条新闻的body字段必须150-300字的详细分析，包含事件背景、技术细节、行业影响
- 如果新闻涉及具体数字（金额、百分比、参数量等），必须在分析中引用
- title字段应该是精炼的新闻标题（15-30字）
- 如果原始新闻不够详细，可以基于行业知识补充合理分析

请严格输出以下JSON格式（不要输出其他任何内容）：
```json
{{
  "chapters": [
    {{
      "title": "一、AI行业全景",
      "items": [
        {{
          "tag": "重磅",
          "tag_class": "tag-red",
          "title": "新闻标题",
          "body": "150-300字的详细分析，包含事件背景、技术/商业细节、行业影响分析",
          "source": "来源名称 日期"
        }}
      ]
    }}
  ],
  "summary": ["要点1", "要点2", "要点3", "要点4", "要点5"],
  "sources": [
    {{"url": "https://...", "text": "来源名称"}}
  ]
}}
```

tag_class可选值: "tag-red"(重磅/突发), "tag-blue"(今日首发/新品), "tag-gray"(政策/行业/生态)
tag可选值: 重磅, 突发, 今日首发, 新品, 政策, 行业, 生态, 趋势"""

    result = call_glm_json(prompt, system_prompt)
    if not result:
        print("  ⚠️ GLM AI报告生成失败，使用降级方案（纯RSS数据）")
        return generate_ai_report_fallback(news_items, beijing_dt)
    return result

def generate_ai_report_fallback(news_items, beijing_dt):
    """GLM失败时的降级方案：直接用RSS数据组装"""
    chapters = []
    items = []
    for n in news_items[:30]:
        items.append({
            "tag": "今日",
            "tag_class": "tag-blue",
            "title": n["title"],
            "body": n["summary"][:300] if n["summary"] else "暂无详细摘要。",
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

    # 准备详细的股价数据
    stock_text = ""
    for s in stocks_data:
        price = format_price(s.get("price"), s.get("currency", "USD"))
        pct = s.get("change_pct", 0)
        direction = "涨" if s.get("direction") == "up" else ("跌" if s.get("direction") == "down" else "平")
        cap = format_market_cap(s.get("market_cap", 0), s.get("currency", "USD"))
        vol = format_volume(s.get("volume", 0))

        open_p = format_price(s.get("open"), s.get("currency", "USD")) if s.get("open") else "N/A"
        high_p = format_price(s.get("high"), s.get("currency", "USD")) if s.get("high") else "N/A"
        low_p = format_price(s.get("low"), s.get("currency", "USD")) if s.get("low") else "N/A"
        wk_high = format_price(s.get("fifty_two_week_high"), s.get("currency", "USD")) if s.get("fifty_two_week_high") else "N/A"
        wk_low = format_price(s.get("fifty_two_week_low"), s.get("currency", "USD")) if s.get("fifty_two_week_low") else "N/A"

        stock_text += f"""
{s['symbol']} ({s['name']}, 交易所:{s.get('exchange','')})
  收盘价: {price}, 涨跌幅: {direction}{pct}%
  开盘: {open_p}, 最高: {high_p}, 最低: {low_p}
  成交量: {vol}, 市值: {cap}
  52周高: {wk_high}, 52周低: {wk_low}
"""

    system_prompt = """你是资深半导体行业和科技股分析师，负责编写高质量的每日半导体科技股早报。
你的分析必须专业、深入、具有实操性。每只股票的分析不得少于150字，需要包含：
1. 技术面分析（关键支撑/阻力位、量价关系、趋势判断）
2. 基本面分析（行业地位、核心驱动力、近期催化剂）
3. 操作建议（持有/观望/关注/谨慎等，附带理由）

板块综述需要200-400字，涵盖整体走势、板块分化、资金流向、宏观背景。
风险提示每条需要100-200字的详细分析，不能只是一句话。
你必须严格按照JSON格式输出，不要输出其他任何内容。"""

    prompt = f"""基于以下今日({date_str} {weekday})的半导体科技股收盘数据，生成一份高质量、结构化的中文股票早报。

股价数据：
{stock_text}

报告分为5个章节：
1. 板块综述（整体走势分析，200-400字，需涵盖涨跌原因、板块分化、资金流向、宏观背景）
2. 行业要闻（3-5条半导体行业相关新闻和趋势分析，每条100-200字）
3. 板块风险提示（3-5条风险，每条需要100-200字详细分析，包含具体数据和逻辑）
4. 明日关注要点（3-5条，每条50-100字）
5. 信息来源（3-5个来源URL）

另外，stock_cards数组中必须覆盖全部11只股票，每只股票的detail字段必须150-300字，包含：
- 技术面分析（关键价位、量价关系、趋势）
- 基本面要点（核心驱动力、近期事件）
- 操作建议（附带理由）

注意：
- A股/中国市场涨跌颜色规则为涨红跌绿
- 如果某只股票数据为N/A，仍然需要基于行业知识给出分析
- 分析要具体到数字和价位，不要泛泛而谈

请严格输出以下JSON格式（不要输出其他任何内容）：
```json
{{
  "chapters": [
    {{
      "title": "一、板块综述",
      "items": [
        {{
          "tag": "综述",
          "tag_class": "tag-gray",
          "title": "标题",
          "body": "200-400字详细分析",
          "source": "综合分析"
        }}
      ]
    }},
    {{
      "title": "二、行业要闻",
      "items": [...]
    }},
    {{
      "title": "三、板块风险提示",
      "items": [...]
    }},
    {{
      "title": "四、明日关注要点",
      "items": [...]
    }}
  ],
  "stock_cards": [
    {{
      "symbol": "NVDA",
      "name": "英伟达",
      "detail": "150-300字个股分析，包含技术面、基本面、操作建议"
    }}
  ],
  "summary": ["要点1", "要点2", "要点3", "要点4", "要点5"],
  "sources": [{{"url": "https://...", "text": "来源"}}]
}}
```

tag_class可选: "tag-red"(利好/重要), "tag-gray"(综述/中性), "tag-blue"(新品/首发), "tag-risk"(风险)"""

    result = call_glm_json(prompt, system_prompt)
    if not result:
        print("  ⚠️ GLM股票报告生成失败，使用降级方案")
        return generate_stock_report_fallback(stocks_data, beijing_dt)
    return result

def generate_stock_report_fallback(stocks_data, beijing_dt):
    """GLM失败时的降级方案 - 仍然提供详细数据"""
    # 构建板块综述
    up_stocks = [s for s in stocks_data if s.get("direction") == "up"]
    down_stocks = [s for s in stocks_data if s.get("direction") == "down"]
    overview_items = [{
        "tag": "综述",
        "tag_class": "tag-gray",
        "title": f"{beijing_dt.strftime('%m月%d日')}半导体板块走势概况",
        "body": f"今日追踪的11只半导体科技股中，{len(up_stocks)}只上涨，{len(down_stocks)}只下跌。" +
                "；".join([f"{s['name']}({s['symbol']}) {format_price(s['price'], s.get('currency','USD'))} ({s['change_pct']}%)" for s in stocks_data if s.get("price")]) +
                "。板块整体走势请结合宏观环境和行业基本面综合判断。",
        "source": "yfinance/Yahoo Finance"
    }]

    # 构建个股分析
    stock_cards = []
    for s in stocks_data:
        price_str = format_price(s.get("price"), s.get("currency", "USD"))
        pct = s.get("change_pct", 0)
        direction = "涨" if s.get("direction") == "up" else ("跌" if s.get("direction") == "down" else "平")
        vol = format_volume(s.get("volume", 0))
        cap = format_market_cap(s.get("market_cap", 0), s.get("currency", "USD"))

        detail = f"{s['name']}（{s['symbol']}）收盘价{price_str}，{direction}{pct}%。"
        if s.get("open"):
            detail += f" 开盘{format_price(s['open'], s.get('currency','USD'))}"
        if s.get("high"):
            detail += f"，最高{format_price(s['high'], s.get('currency','USD'))}"
        if s.get("low"):
            detail += f"，最低{format_price(s['low'], s.get('currency','USD'))}"
        if s.get("volume"):
            detail += f"。成交量{vol}"
        if s.get("market_cap"):
            detail += f"，市值{cap}"
        if s.get("fifty_two_week_high"):
            detail += f"。52周高{format_price(s['fifty_two_week_high'], s.get('currency','USD'))}"
        detail += "。建议结合行业趋势和基本面综合判断操作策略。"

        stock_cards.append({
            "symbol": s["symbol"],
            "name": s["name"],
            "detail": detail,
        })

    return {
        "chapters": [{"title": "一、板块综述", "items": overview_items}],
        "stock_cards": stock_cards,
        "summary": [f"{s['name']} {s['change_pct']}%" for s in stocks_data[:5]],
        "sources": [{"url": "https://finance.yahoo.com", "text": "Yahoo Finance"}],
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
.header{{background:linear-gradient(135deg,#1a56db,#2563eb);color:#fff;padding:36px 24px;text-align:center}}
.header h1{{font-size:26px;margin-bottom:8px;font-weight:700}}
.header .sub{{font-size:17px;margin:8px 0}}
.header .meta{{font-size:13px;opacity:.85;margin-top:10px;line-height:1.9}}
.header .meta strong{{font-weight:600}}
.container{{max-width:960px;margin:0 auto;padding:20px}}
.section{{background:#fff;border-radius:14px;padding:28px 24px;margin-bottom:20px;box-shadow:0 1px 4px rgba(0,0,0,.07);border:1px solid #e5e7eb}}
.section h2{{font-size:19px;color:#1a56db;border-bottom:2px solid #2563eb;padding-bottom:10px;margin-bottom:16px;font-weight:700}}
.news-item{{padding:14px 0;border-bottom:1px solid #f1f5f9}}
.news-item:last-child{{border-bottom:none}}
.news-tag{{display:inline-block;font-size:11px;padding:2px 8px;border-radius:4px;margin-right:8px;font-weight:700;vertical-align:middle}}
.tag-red{{background:#fef2f2;color:#dc2626}}
.tag-blue{{background:#eff6ff;color:#2563eb}}
.tag-gray{{background:#f3f4f6;color:#6b7280}}
.news-title{{font-size:15.5px;font-weight:600;margin:6px 0 8px;color:#1e293b;line-height:1.5}}
.news-body{{font-size:13.5px;color:#475569;line-height:1.9;padding-left:0}}
.news-body strong{{color:#1e293b;font-weight:600}}
.news-body code{{background:#f1f5f9;padding:1px 5px;border-radius:3px;color:#dc2626;font-size:12.5px}}
.news-source{{font-size:12px;color:#94a3b8;margin-top:6px}}
.summary-list{{list-style:none;padding:0}}
.summary-item{{padding:10px 0;font-size:14px;border-bottom:1px solid #f1f5f9;display:flex;align-items:flex-start}}
.summary-item:last-child{{border-bottom:none}}
.summary-num{{display:inline-block;width:24px;height:24px;background:#2563eb;color:#fff;border-radius:50%;text-align:center;line-height:24px;font-size:12px;font-weight:700;margin-right:10px;flex-shrink:0;margin-top:2px}}
.sources a{{color:#2563eb;text-decoration:none;font-size:13px;display:block;padding:4px 0}}
.sources a:hover{{text-decoration:underline}}
.footer{{text-align:center;padding:24px;color:#94a3b8;font-size:12px;line-height:1.8}}
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
<div class="footer">由 GitHub Actions + GLM-4-Flash 自动生成 | 数据来源：RSS Feeds<br>覆盖8大章节：AI全景 / 编程工具 / 大模型 / 大厂产品 / 基础设施 / 半导体 / 摘要 / 来源</div>
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
:root{{
  --bg:#f0f4f8;--card-bg:#fff;--text:#1a1a2e;--text-sec:#555;
  --accent:#1a56db;--red:#dc2626;--red-bg:#fef2f2;
  --green:#059669;--green-bg:#ecfdf5;
  --border:#e5e7eb;--shadow:0 1px 3px rgba(0,0,0,.06);--radius:10px;
}}
body{{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);line-height:1.7;padding:20px}}
.header{{background:linear-gradient(135deg,#1e3a5f,#2563eb);color:#fff;padding:36px 24px;border-radius:14px;margin-bottom:24px;text-align:center}}
.header h1{{font-size:26px;font-weight:700;margin-bottom:8px}}
.header .sub{{font-size:17px;margin:8px 0}}
.header .meta{{font-size:13px;opacity:.85;margin-top:10px;line-height:1.9}}
.header .meta strong{{font-weight:600}}
.container{{max-width:960px;margin:0 auto}}
.card{{background:var(--card-bg);border-radius:var(--radius);box-shadow:var(--shadow);padding:28px 24px;margin-bottom:20px;border:1px solid var(--border)}}
.card h2{{font-size:19px;color:var(--accent);border-bottom:2px solid #2563eb;padding-bottom:10px;margin-bottom:20px;font-weight:700}}
.stock-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}}
.stock-card{{background:var(--card-bg);border:1px solid var(--border);border-radius:var(--radius);padding:20px;transition:box-shadow .2s}}
.stock-card:hover{{box-shadow:0 4px 12px rgba(0,0,0,.1)}}
.stock-card .name{{font-size:15px;font-weight:700;color:var(--text)}}
.stock-card .code{{font-size:12px;color:#9ca3af;margin-bottom:8px}}
.stock-card .price{{font-size:24px;font-weight:700;margin:6px 0}}
.stock-card .change{{font-size:14px;font-weight:600;padding:2px 10px;border-radius:4px;display:inline-block}}
.up{{color:var(--red);background:var(--red-bg)}}
.down{{color:var(--green);background:var(--green-bg)}}
.flat{{color:#6b7280;background:#f3f4f6}}
.stock-card .info{{font-size:12px;color:#6b7280;margin-top:8px;line-height:1.6}}
.stock-card .info span{{display:inline-block;margin-right:12px}}
.stock-card .analysis{{font-size:12.5px;color:var(--text-sec);margin-top:10px;padding-top:10px;border-top:1px solid #f3f4f6;line-height:1.8}}
.stock-card .analysis strong{{color:var(--text)}}
.news-item{{padding:12px 0;border-bottom:1px solid #f1f5f9}}
.news-item:last-child{{border-bottom:none}}
.news-tag{{display:inline-block;font-size:11px;padding:2px 8px;border-radius:4px;margin-right:8px;font-weight:700}}
.tag-red{{background:#fef2f2;color:#dc2626}}
.tag-blue{{background:#eff6ff;color:#2563eb}}
.tag-gray{{background:#f3f4f6;color:#6b7280}}
.tag-risk{{background:#fef2f2;color:#dc2626}}
.news-title{{font-size:14.5px;font-weight:600;margin:6px 0 8px;color:var(--text)}}
.news-body{{font-size:13px;color:#475569;line-height:1.9}}
.news-body strong{{color:var(--text)}}
.news-source{{font-size:12px;color:#94a3b8;margin-top:5px}}
.summary-list{{list-style:none;padding:0}}
.summary-item{{padding:10px 0;font-size:14px;border-bottom:1px solid #f1f5f9;display:flex;align-items:flex-start}}
.summary-item:last-child{{border-bottom:none}}
.summary-num{{display:inline-block;width:24px;height:24px;background:#2563eb;color:#fff;border-radius:50%;text-align:center;line-height:24px;font-size:12px;font-weight:700;margin-right:10px;flex-shrink:0;margin-top:2px}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:16px}}
th{{background:#2563eb;color:#fff;padding:10px 12px;text-align:left;font-weight:600}}
td{{padding:10px 12px;border-bottom:1px solid #e5e7eb}}
tr:nth-child(even) td{{background:#f8fafc}}
td .pos{{color:var(--red);font-weight:600}}
td .neg{{color:var(--green);font-weight:600}}
.sources a{{color:#2563eb;text-decoration:none;font-size:13px;display:block;padding:4px 0}}
.sources a:hover{{text-decoration:underline}}
.footer{{text-align:center;padding:24px;color:#94a3b8;font-size:12px;line-height:1.8}}
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
<div class="footer">由 GitHub Actions + GLM-4-Flash 自动生成 | 数据来源：Yahoo Finance<br>覆盖11只标的：NVDA / AMD / TSM / MRVL / MU / SOXL / DELL / IREN / NBIS / 三星电子 / SK海力士</div>
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

def build_section(title, items_html, extra_class=""):
    return f"""  <div class="card{extra_class}">
    <h2>{title}</h2>
{chr(10).join(items_html)}
  </div>"""

def build_stock_card_v2(sd, detail_text):
    """构建高质量股票卡片，包含丰富的数据字段"""
    symbol = sd["symbol"]
    name = sd["name"]
    price = sd.get("price")
    change_pct = sd.get("change_pct", 0)
    direction = sd.get("direction", "flat")
    currency = sd.get("currency", "USD")
    exchange = sd.get("exchange", "")
    volume = sd.get("volume", 0)
    market_cap = sd.get("market_cap", 0)
    open_p = sd.get("open")
    high_p = sd.get("high")
    low_p = sd.get("low")
    wk_high = sd.get("fifty_two_week_high")
    wk_low = sd.get("fifty_two_week_low")

    # 价格显示
    if price is not None:
        price_str = format_price(price, currency)
    else:
        price_str = "数据缺失"

    # 涨跌幅
    if direction == "up":
        change_cls = "up"
        arrow = "▲"
        change_str = f"{arrow} +{change_pct}%"
    elif direction == "down":
        change_cls = "down"
        arrow = "▼"
        change_str = f"{arrow} {change_pct}%"
    else:
        change_cls = "flat"
        change_str = "— 0.00%"

    # 信息行
    info_parts = []
    if exchange:
        info_parts.append(f"<span>交易所: {exchange}</span>")
    if open_p:
        info_parts.append(f"<span>开盘: {format_price(open_p, currency)}</span>")
    if high_p:
        info_parts.append(f"<span>最高: {format_price(high_p, currency)}</span>")
    if low_p:
        info_parts.append(f"<span>最低: {format_price(low_p, currency)}</span>")
    if volume:
        info_parts.append(f"<span>成交量: {format_volume(volume)}</span>")
    if market_cap:
        info_parts.append(f"<span>市值: {format_market_cap(market_cap, currency)}</span>")
    if wk_high:
        info_parts.append(f"<span>52周高: {format_price(wk_high, currency)}</span>")
    if wk_low:
        info_parts.append(f"<span>52周低: {format_price(wk_low, currency)}</span>")

    info_html = '<br>'.join(info_parts) if info_parts else ""

    return f"""      <div class="stock-card">
        <div class="name">{name}</div>
        <div class="code">{symbol} · {exchange or 'N/A'}</div>
        <div class="price">{price_str}</div>
        <div class="change {change_cls}">{change_str}</div>
        <div class="info">{info_html}</div>
        <div class="analysis">{detail_text}</div>
      </div>"""

def build_summary_table(stocks_data):
    """构建汇总表格"""
    rows = ""
    for sd in stocks_data:
        symbol = sd["symbol"]
        name = sd["name"]
        price = sd.get("price")
        change_pct = sd.get("change_pct", 0)
        direction = sd.get("direction", "flat")
        currency = sd.get("currency", "USD")

        price_str = format_price(price, currency) if price else "N/A"

        if direction == "up":
            pct_str = f'<span class="pos">+{change_pct}%</span>'
        elif direction == "down":
            pct_str = f'<span class="neg">{change_pct}%</span>'
        else:
            pct_str = f'<span class="flat">0.00%</span>'

        rows += f"""        <tr><td>{symbol}</td><td>{name}</td><td>{price_str}</td><td>{pct_str}</td><td>{currency}</td></tr>\n"""

    return f"""    <table>
      <thead><tr><th>代码</th><th>名称</th><th>最新价</th><th>涨跌幅</th><th>币种</th></tr></thead>
      <tbody>
{rows}      </tbody>
    </table>"""

def build_summary_item(num, text):
    return f'    <div class="summary-item"><span class="summary-num">{num}</span><span>{text}</span></div>'

def build_source_link(url, text):
    return f'    <p>📌 <a href="{url}" target="_blank">{text}</a></p>'


def generate_ai_html(content, beijing_dt):
    """从GLM生成的内容组装AI报告HTML"""
    date_str = beijing_dt.strftime("%Y-%m-%d")
    weekday = WEEKDAY_CN[beijing_dt.weekday()]
    meta_line = f"自动生成 | GLM-4-Flash 智能分析 | {beijing_dt.strftime('%Y-%m-%d %H:%M')} CST<br><strong>覆盖时段</strong>：过去24小时AI行业动态"

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

    # 构建meta信息
    up_count = len([s for s in stocks_data if s.get("direction") == "up"])
    down_count = len([s for s in stocks_data if s.get("direction") == "down"])
    na_count = len([s for s in stocks_data if s.get("price") is None])
    meta_line = f"自动生成 | GLM-4-Flash 智能分析 | {beijing_dt.strftime('%Y-%m-%d %H:%M')} CST<br>"
    meta_line += f"<strong>涨跌统计</strong>：涨{up_count} / 跌{down_count} / 数据缺失{na_count}（共{len(stocks_data)}只）<br>"
    meta_line += f"<strong>数据来源</strong>：Yahoo Finance Chart API + yfinance"

    sections_html = []

    # 章节顺序：先放GLM生成的章节（板块综述、行业要闻等），再放个股卡片和汇总表

    # 1. GLM生成的文字章节（板块综述、行业要闻等）
    for ch in content.get("chapters", []):
        if isinstance(ch, str):
            sections_html.append(build_section(ch, []))
            continue
        items_html = []
        for item in ch.get("items", []):
            if isinstance(item, str):
                items_html.append(build_news_item("tag-gray", "综述", item))
            elif isinstance(item, dict):
                tag_class = item.get("tag_class", "tag-gray")
                tag_text = item.get("tag", "综述")
                items_html.append(build_news_item(
                    tag_class,
                    tag_text,
                    item.get("title", ""),
                    item.get("body", ""),
                    item.get("source", "综合分析"),
                ))
        ch_title = ch.get("title", "") if isinstance(ch, dict) else str(ch)
        sections_html.append(build_section(ch_title, items_html))

    # 2. 个股行情卡片（网格布局）
    stock_cards_html = []
    stock_details = {}
    for s in content.get("stock_cards", []):
        if isinstance(s, dict) and "symbol" in s:
            stock_details[s["symbol"]] = s

    for sd in stocks_data:
        detail = stock_details.get(sd["symbol"], {}).get("detail", "")
        if not detail:
            # 降级：用基本数据组装
            price_str = format_price(sd.get("price"), sd.get("currency", "USD"))
            detail = f"{sd['name']}（{sd['symbol']}）收盘价{price_str}。建议结合行业趋势综合判断。"
        stock_cards_html.append(build_stock_card_v2(sd, detail))

    sections_html.append(f"""  <div class="card">
    <h2>个股行情详情</h2>
    <div class="stock-grid">
{chr(10).join(stock_cards_html)}
    </div>
  </div>""")

    # 3. 汇总表格
    table_html = build_summary_table(stocks_data)
    sections_html.append(f"""  <div class="card">
    <h2>行情汇总表</h2>
{table_html}
  </div>""")

    # 4. 摘要
    if content.get("summary"):
        summary_items = [build_summary_item(i+1, s if isinstance(s, str) else str(s)) for i, s in enumerate(content["summary"])]
        sections_html.append(build_section("关注要点", summary_items))

    # 5. 来源
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
.header{{background:linear-gradient(135deg,#1a56db,#2563eb);color:#fff;padding:36px 24px;text-align:center}}
.header h1{{font-size:26px;margin-bottom:8px;font-weight:700}}
.header .sub{{font-size:14px;opacity:.85;margin-top:8px}}
.container{{max-width:960px;margin:0 auto;padding:20px}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.07)}}
th{{background:#1a56db;color:#fff;padding:12px 10px;font-size:14px;text-align:left}}
td{{padding:10px;border-bottom:1px solid #f1f5f9;font-size:14px}}
tr:hover{{background:#f8fafc}}
a{{color:#2563eb;text-decoration:none;font-weight:600}}
a:hover{{text-decoration:underline}}
.footer{{text-align:center;padding:24px;color:#94a3b8;font-size:12px;line-height:1.8}}
.stats{{display:flex;gap:16px;margin-bottom:20px}}
.stat-card{{background:#fff;border-radius:10px;padding:20px;flex:1;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.07)}}
.stat-num{{font-size:30px;font-weight:800;color:#1a56db}}
.stat-label{{font-size:13px;color:#64748b;margin-top:4px}}
</style>
</head>
<body>
<div class="header">
  <h1>AI行业早报 & 半导体科技股早报</h1>
  <div class="sub">GitHub Actions 自动生成 | 每日北京时间 09:00 更新 | GLM-4-Flash 智能分析</div>
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
<div class="footer">Powered by GitHub Actions + GLM-4-Flash | RSS Feeds + Yahoo Finance<br>覆盖：AI全景/编程工具/大模型/大厂产品/基础设施/半导体 | NVDA/AMD/TSM/MRVL/MU/SOXL/DELL/IREN/NBIS/三星/SK海力士</div>
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
