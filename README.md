# Daily Photo Coach — 每日摄影教练

每天自动从 Unsplash 抓取多种风格的高质量摄影作品，交给多模态 AI 做专业级摄影教学分析，生成可浏览的静态网页日报。

像一位 20 年经验的摄影导师，对每张照片从曝光、构图、光线、色彩、后期到实操复刻，逐项手把手教学。

## 工作流

```
Unsplash 随机照片 → 多模态 LLM 视觉分析 → 静态网页 + Markdown 日报
```

## 分析维度

每张照片会得到 7 个维度的深度解读：

1. **第一印象** — 故事、情绪、视觉冲击力
2. **曝光三要素推断** — 光圈 / 快门 / ISO 参数推测与 EXIF 对比
3. **构图分析** — 构图法则、主体背景关系、视觉引导路径
4. **光线解读** — 光源方向、光线性质、阴影利用、拍摄时段
5. **色彩与后期** — 色调、饱和度、后期调色方向
6. **如果你来拍** — 器材推荐、拍摄步骤、技术难点、手机替代方案
7. **学习要点** — 2-3 个可直接应用的核心技巧

## 快速开始

```bash
pip install -r requirements.txt
cp config.yaml.example config.yaml
# 编辑 config.yaml，填入 Unsplash Access Key 和 LLM API 信息

python src/main.py                       # 运行今天的分析
python src/main.py --date 2026-05-09     # 指定日期
python src/main.py --styles 风光 人像     # 只分析指定风格
python src/main.py --per-style 2         # 每种风格只抓 2 张
python src/main.py --skip-fetch          # 跳过抓取，重新分析已有照片
```

## 输出

```
output/
├── index.html              # 总索引页（所有日期）
└── 2026-05-09/
    ├── index.html           # 当日网页（Tab 分类 + 灯箱浏览）
    ├── daily.md             # Markdown 日报
    └── photos.json          # 结构化归档（含完整分析文本）
```

## 覆盖风格

风光/自然 · 人像/肖像 · 街头/人文 · 极简/建筑 · 美食/静物 · 夜景/城市 · 微距/特写 · 黑白/光影

## 技术栈

- Python 3.10+
- Unsplash API（照片源）
- 多模态 LLM（视觉分析，兼容 OpenAI Chat Completions）
- Jinja2 + Tailwind CSS（静态页面渲染）
