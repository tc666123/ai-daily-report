# AI行业早报 + 半导体科技股早报 - GitHub Actions 自动生成

每日北京时间 09:00 自动生成 AI 行业早报和半导体科技股早报，部署到 GitHub Pages。

## 架构

```
GitHub Actions cron (UTC 01:00)
  → RSS 抓取 AI 新闻 (feedparser)
  → yfinance 获取股价数据
  → GLM-4-Flash 生成中文分析
  → HTML 报告输出
  → 自动 commit + push
  → GitHub Pages 自动部署
```

## 设置步骤

1. Fork 或创建此仓库
2. 在仓库 Settings → Secrets → Actions 中添加：
   - `ZHIPU_API_KEY` = 你的智谱 API Key
3. 在仓库 Settings → Pages → Source 选择 "GitHub Actions"
4. 每日自动触发，也可在 Actions 页面手动触发

## 报告说明

- **AI行业早报**：每日生成，8个章节
- **半导体科技股早报**：工作日生成（周末/美股假日跳过），覆盖11只股票
- 股票列表：NVDA/AMD/TSM/MRVL/MU/SOXL/DELL/IREN/NBIS/005930.KS/000660.KS

## 技术栈

- Python 3.11 + feedparser + yfinance + requests
- 智谱 GLM-4-Flash（免费额度）
- GitHub Actions + GitHub Pages（全免费）
