# 小红书精选改为链出原文，不再公开托管原图

日期：2026-08-14  
状态：已实现  
站点：https://krisaruz.github.io/daily-photo-coach/

## 1. 背景

Daily Photo Coach 目前会把小红书公开笔记里的图片下载到 `output/assets/xhs/`，随 GitHub Pages 长期公开展示，并在首页、每日页、小红书索引和详情页用 `<img>` 渲染这些图。

公开可见 ≠ 授权转载。个人非商业博客、署名和原帖链接，都不能单独构成明确许可。当前做法同时涉及：

- 著作权：复制并信息网络传播整张/整组照片
- 肖像权：人像写真中可识别的人未必同意二次发布
- 平台协议：小红书通常不允许站外转存和展示

Unsplash 线有可转载许可，不在本次范围。

已确认的产品决定：

- 历史一并改，不只改今后新增内容
- 新分析仍可在 CI 里临时看图；图不保存、不进 git、不上 Pages
- 公开站点只留文字分析 + 原帖链接

## 2. 目标

- 线上静态站不再托管小红书原图文件。
- 线上 HTML / Markdown 不再把小红书图当作本站图片展示（不使用本地资产，也不热链小红书 CDN 作为 `<img src>`）。
- 已有教学分析文字保留，按「第 N 张」阅读，并提供「去小红书看原图」入口。
- 新的一天仍可对笔记图片调用多模态模型生成分析；过程中的图像只存在于 CI 内存/模型请求，不写入 `output/`。
- Unsplash 抓取、展示、分析保持不变。

## 3. 非目标

- 不改写 git 历史以清除旧提交中的图片 blob。Pages 发布当前树即可先让公开站点干净。若以后要做历史清除，需单独决定并可能 force-push，本次不做。
- 不绕过小红书登录、验证码或访问控制。
- 不把分析改成只根据标题/文案臆测画面。
- 不把多张图的分析合并成一篇新的笔记级长文；沿用已有按张分析。
- 不删除小红书栏目或独立子站。
- 不处理 Unsplash / Flickr 授权策略。

## 4. 公开页面

渲染层把「小红书条目」和「可展示图片的条目」分开。判定与现有一致：`source_platform == "xhs"` 或 `source_name == "小红书"`。

### 4.1 一律禁止的输出

对小红书条目，模板和 Markdown **不得**输出：

- `assets/xhs/` 下的本地路径
- 小红书 CDN / `sns-webpic` / `xhscdn` / `ci.xiaohongshu.com` 等作为 `<img src>` 或 Markdown `![]()`
- 灯箱、封面马赛克、缩略图条里的小红书图

`_image_url()` 对小红书条目必须返回空字符串。首页 `_pick_preview_images()` 只从非小红书照片取预览；某天若只剩小红书条目，该天卡片用纯文字封面，不出图。

### 4.2 各页面形态

| 页面 | 改后 |
| --- | --- |
| 总首页 featured / 日记卡片预览 | 只用 Unsplash（或其他非 XHS）缩略图 |
| 总首页「小红书精选」 | 文字卡：日期、标题、作者、摘要；主操作链到本站 `xhs/YYYY-MM-DD/`；次操作链到 `source_url`（新窗口，`rel="noopener"`） |
| 每日页小红书 Tab | 不渲染照片框和灯箱；每张保留分析，顶部一条「在小红书查看原图」 |
| 小红书索引 | 无封面图；标题 + 作者 + 日期 + 张数 |
| 小红书详情 | 去掉大图轮播和缩略图条；hero 为标题/作者/原帖按钮；下方按张列出分析（「第 N / M 张」） |
| `daily.md` | 小红书段落只保留文字、作者、原帖链接，不嵌入图片 |

详情页和首页精选区增加固定说明（文案可微调，语义必须包含）：

> 原图在小红书。本站只保留学习笔记和原帖链接，不转载、不托管照片。

### 4.3 原帖不可用

不少笔记公开页已 404。页面仍展示已保存的标题、作者和分析，原帖链接照放，并在链接旁注明「原帖可能已无法公开浏览」。不因此重新去拉图或回退本地资产。

## 5. 生成流水线

### 5.1 停止落盘

删除 `xhs_fetcher.cache_photo_assets`（含下载逻辑），并去掉 `xhs_daily` / `xhs_import` 中的全部调用。CI / 本地都不得再把小红书图写入 `output/assets/xhs/`。该目录从当前树删除后加入 `.gitignore`，防止以后误提交。

### 5.2 分析仍看图，但不保存图

`analyzer.analyze_photo` / `prompt.build_user_message` 继续把 `photo["url_regular"]` 作为多模态 `image_url` 发给模型。该 URL 只用于当次请求。

禁止：把下载的字节写进 `output/`、临时目录提交进 git、或把 data-URI 写进 HTML。

公开页抓取失败（404 / 占位 Logo）时行为与现在一致：笔记不可用，回退历史归档里**已经有分析文字**的笔记元数据，而不是回退本地 JPEG。

### 5.3 `photos.json` 字段

归档 JSON 可以保留远程 `url_*`，供以后 `--skip-fetch` 或强制重分析。这是元数据链接，不是本站托管文件。

必须从公开渲染剥离：

- 所有 `local_url_small` / `local_url_regular` / `local_url_full`
- 模板不得把 XHS 的 `url_*` 填进 `img`

重建历史页面时，渲染器忽略已有 `local_url_*`。全量重渲染首页、每日页、Markdown 和小红书子站。重写 `photos.json` 时删除所有 `local_url_*` 字段，避免以后误用。

### 5.4 调度与完成判定

`analysis_schedule.day_is_complete` 仍然要求当天 Unsplash 与小红书都有可用分析文字。小红书是否完整看分析字段，不看本地图片是否存在。

## 6. 历史内容处理

1. 删除当前工作区 `output/assets/xhs/` 下全部文件。
2. 用现有 `photos.json` 重渲染：
   - 每个 `output/YYYY-MM-DD/index.html` 与 `daily.md`
   - `output/index.html`
   - `output/xhs/index.html` 与 `output/xhs/YYYY-MM-DD/index.html`
3. 提交后由现有 `deploy.yml`（`output/**`）发布 Pages。

不重跑 LLM，除非某条分析本身缺失。旧分析文字原样保留。

## 7. 模块边界

| 单元 | 职责 |
| --- | --- |
| `xhs_fetcher` | 解析公开笔记元数据与远程图片 URL；判断占位图/404；不再下载或写入静态资产 |
| `xhs_daily` / `xhs_import` | 选帖、调分析、写 `photos.json`；不调用缓存 |
| `renderer._image_url` / `_pick_preview_images` | 小红书条目永不返回可展示 URL |
| 模板 | 小红书走「文字 + 链出」布局；Unsplash 仍走图片布局 |
| `analyzer` / `prompt` | 仅 CI/本地分析时使用远程 URL，不参与页面展示 |

## 8. 测试

至少覆盖：

- `_image_url` 对带 `local_url_*` 和 CDN URL 的小红书条目都返回空。
- `_pick_preview_images` 跳过小红书，只留下 Unsplash。
- 小红书详情/索引渲染结果不含 `assets/xhs`、不含 `xhscdn` / `picasso-static` 作为图片地址，但含 `source_url` 与分析 HTML。
- `xhs_daily.fetch_pool` / 导入路径不再下载或写入 `output/assets/xhs/`。
- 现有占位 Logo、归档回退、选帖质量测试保持通过。

手工验收：

- 打开首页、某天每日页、`/xhs/`、某条详情：看不见小红书照片。
- Unsplash 图仍在。
- 「去原帖」链接指向 `xiaohongshu.com`。
- 仓库和 Pages 产物中无新的 `output/assets/xhs/` 文件。

## 9. 文档

同步 `docs/PRD.md` 与 README：

- 删除「小红书图片缓存到 GitHub Pages」作为产品能力。
- 写明：公开站只做学习笔记和链出；分析阶段可临时使用远程图 URL。
- 变更日志追加 2026-08-14 本项。

## 10. 风险与边界

- 抓取公开页、把图 URL 交给模型，仍可能不符合小红书用户协议；本次只降低「公开图库」风险，不是法律豁免。
- 原帖 404 时，读者只能读分析、看不到图。接受这一降级。
- git 历史仍可能含旧图；本次只保证当前树和 Pages 当前部署不含这些文件。
- 若模型所在网关无法拉取小红书 CDN，新分析会失败并走现有「分析失败」重试，不回退到本地存图。
