# Daily Photo Coach

> 多风格摄影作品抓取 + 多模态 AI 七维深度教学分析，生成可浏览的静态日报。

## 项目简介

Daily Photo Coach 是一个每日运行的摄影教学内容生成系统。核心流程：从 Unsplash 按风格分类抓取高质量随机摄影作品，将每张照片连同 EXIF 元数据送入多模态 LLM，输出结构化的七维度深度教学分析，最终渲染为可直接浏览的静态日报页面。

不是简单的"看图说话"——系统强制 LLM 按固定教学框架输出：从第一印象出发，经由曝光三要素、构图手法、光线运用、色彩与后期，到实操复刻步骤和学习要点，形成一篇完整的摄影课。

## 核心架构

```
Unsplash API / 小红书公开分享页 → 多风格抓取 → 多模态 LLM 教学分析 → 静态站点生成（HTML/Markdown/JSON）
```

### Phase 1: 数据采集

通过 Unsplash API 按配置中的风格标签（街拍、风光、人像等）随机拉取照片，提取：

- 多分辨率图片 URL（regular / full / small）
- 摄影师信息与原始链接
- EXIF 数据（相机型号、焦距、光圈、快门、ISO）
- 图片描述与尺寸信息

支持多种 `orientation` 轮换，`content_filter: high` 保证内容质量，ID 级去重。

也支持从小红书公开分享链接导入笔记元数据，把博主文案交给多模态模型作语境。公开站点只保留学习笔记和原帖链接，不托管、不展示小红书原图。

### Phase 2: 多模态分析

将照片 URL + EXIF 元数据组装成 OpenAI 格式的多模态请求，送入 LLM 进行流式分析。固定七维教学结构：

| 维度 | 分析内容 |
|------|---------|
| 第一印象 | 画面整体感受与情绪传达 |
| 曝光三要素 | 结合 EXIF 分析光圈/快门/ISO 的选择逻辑 |
| 构图手法 | 三分法、引导线、前景层次等技法拆解 |
| 光线运用 | 自然光/人造光的方向、质感与氛围营造 |
| 色彩与后期 | 色调倾向、调色思路、后期处理推测 |
| 实操复刻 | 如何用手头器材拍出类似效果的步骤指南 |
| 学习要点 | 这张照片最值得带走的 2-3 个技术点 |

采用流式 SSE 解析降低长回复感知延迟，指数退避重试保障稳定性。

### Phase 3: 静态站点生成

三种输出产物覆盖不同使用场景：

- **HTML 日报** — Tailwind 排版 + Tab 风格切换 + 灯箱交互，浏览器直接打开
- **Markdown 日报** — 按风格分节，嵌入图片/EXIF/分析全文，适合归档与 Git 管理
- **JSON 存档** — 结构化数据，支持二次处理与程序消费

自动扫描历史日报目录，生成按日期倒序的总索引页。

## 工程设计

| 设计决策 | 解决的问题 |
|---------|-----------|
| 七维固定教学框架 | 防止 LLM 输出泛泛而谈的"好看"评语 |
| EXIF 作为分析输入 | 让技术分析有据可查，不是猜测 |
| 流式 SSE + 指数退避 | 长回复低延迟 + 网络异常自动恢复 |
| `--skip-fetch` 增量模式 | 调 prompt 或改渲染时不重拉图，省 API 配额 |
| 内嵌轻量 Markdown 解析 | 零 heavy 依赖，`requests + PyYAML + Jinja2` 即可运行 |
| URL 引用不落盘原图 | 节省存储，Unsplash 原图长期可访问 |

## 技术栈

- Python 3.10+
- Unsplash API（高质量摄影数据源）
- 多模态 LLM（兼容 OpenAI Chat Completions，流式）
- Jinja2 模板引擎
- Tailwind CSS（CDN，零构建）
- 配置驱动（YAML）

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 复制配置
cp config.yaml.example config.yaml
# 填入 Unsplash Access Key 和 LLM API 配置

# 运行当日日报
python src/main.py

# 指定日期
python src/main.py --date 2026-05-10

# 跳过抓取，仅重新分析和渲染
python src/main.py --skip-fetch

# 指定风格子集
python src/main.py --styles 街拍,风光

# 导入小红书公开分享链接，并用 GPT-5.5 分析
python src/xhs_import.py --url "http://xhslink.com/o/6vj01FlQoGl" --style 小红书精选 --limit 6

# 每天轮换一张小红书精选；也可以一次补最近 10 天
python src/xhs_daily.py --backfill-days 10 --style "小红书｜人像自然"

# 只测试抓取和渲染，不调用 LLM
python src/xhs_import.py --url "http://xhslink.com/o/6vj01FlQoGl" --skip-analysis
```

产物输出到 `output/YYYY-MM-DD/`，浏览器打开 `index.html` 即可阅读。

## 小红书入口

静态站首页和每日页都提供“导入小红书链接”按钮。首次使用需要在浏览器里输入一个 GitHub PAT（仅需 Actions write 权限），按钮会触发 `.github/workflows/xhs.yml`，由 GitHub Actions 抓取公开页面、调用 `gpt-5.5` 分析并重新部署 Pages。

另外 `.github/workflows/daily.yml` 会在北京时间 09:20–22:20 每小时检查一次，并在当天 9–22 点中抽一个稳定随机整点生成 Unsplash 日报和小红书精选。公开搜索经常要求登录时，最稳定的方式是把你喜欢的摄影博主公开分享链接加入 `xhs.sources` 或 GitHub Secret `XHS_SEED_URLS`；直播笔记失效时，脚本会回退到已有分析文字的历史笔记。站点不保存小红书原图。`xhs-daily.yml` 仅保留手动回填。

Actions 中建议配置：

- `OPENAI_API_KEY`：OpenAI API Key；也可以用兼容网关的 `LLM_AUTH` / `LLM_URL`。
- `XHS_SEED_URLS`：可选，逗号或换行分隔的小红书公开分享/笔记链接。
- `XHS_COOKIE`：可选，仅用于你有权访问但公开页偶发需要 Cookie 的页面。脚本不会登录、解验证码或绕过访问控制。

## 源码

GitHub: [krisaruz/daily-photo-coach](https://github.com/krisaruz/daily-photo-coach)
