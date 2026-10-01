# KOL 深挖：一手信源取证 + 与本项目硬数据对账

> 触发场景：Chao 点名某个 KOL（"XX 近期的崩盘言论如何"、"看看他的网址和 YouTube 有没有 XX 迹象"），
> 要的不是 cron 自动判定的 direction 标签，而是**带原话引用的立场还原 + 用我们自己的数据交叉验证**。
> 首个实战样本：Martin Armstrong（2026-08-25）。

---

## 0. 结论先行的产出骨架（Chao 口径）

回复必须是三层，缺一层就是不合格：

1. **一句话立场**（且要敢于推翻提问里的预设）——例：他明确**否认**股市崩盘，崩的是债市。
2. **带原话+日期+时长的证据段**：直接引用字幕/正文原句（英文原话可保留），标出访谈频道、发布日、视频长度。
   附上他给的**具体数字**（时间点/价位/目标），这才是"可交易"的部分。
3. **原始 source link 列表**放最后一行。

外加两条硬要求：
- 提问里的假设若与证据相反，**先说"相反"再给证据**，不要为了顺着用户而含糊（本例：问"资金流出美国的迹象"，他全部是反向表述）。
- 付费墙后的内容：**只报标题/分类/日期，明说"正文读不到，不编内容"**。

---

## 1. 官网抓取：分层，别只抓首页

```
web_extract(["https://<kol-site>/", "https://<kol-site>/category/<主题>/"])
```
- 首页给**最近 10 篇标题+日期**（时序骨架）；分类页给**摘要首段**（往往就够判方向）。
- `/blog/` 和 `/tag/xxx/` 这类**分页列表页常被 JS 渲染，web_extract 只返回分页器数字**（实测 armstrongeconomics.com `/blog/` 返回 `01 02 … 2325` 什么都没有）→ 不要在这类 URL 上浪费轮次，改抓**具体分类页**或直接抓文章 URL。
- 付费墙判据：正文只剩 "Private blog posts are exclusively available to … subscribers" + Categories 列表。
  **Categories 本身是信号**（例：《The Share Market vs Debt》挂在 Dow/Nikkei/Interest Rates/Bonds 下 = 他在拿股 vs 债对比），可以引用，但不得据此推测正文论点。

## 2. YouTube：官方频道常年停更，真产出在第三方访谈频道

- 先枚举官方频道：
  ```bash
  yt-dlp --flat-playlist --dump-json --playlist-end 25 "https://www.youtube.com/@<handle>/videos"
  ```
  ⚠️ flat-playlist 的 `upload_date` 多为 `None`，**别据此判新旧**；拿到 id 后逐个 `--skip-download --print "%(upload_date)s|%(title)s|%(channel)s|%(duration)s"` 才有真日期。
- 官方频道停更（本例最新 2026-04）**不等于此人停更**。用 `web_search "<name> YouTube 2026 <主题>"` 找**第三方访谈频道**（本例：NRS World / Miles Franklin / LifeWorthLiving），这些才是他现在的实质输出通道。

## 3. ★核心技术：自动字幕当一手信源（比任何二手摘要都硬）

```bash
mkdir -p /tmp/kol_subs && cd /tmp/kol_subs
for id in <vid1> <vid2>; do
  yt-dlp --skip-download --write-auto-sub --write-sub --sub-lang "en.*" \
         --sub-format vtt -o "%(id)s.%(ext)s" "https://youtu.be/$id" >/dev/null 2>&1
done
```
- 只抓字幕**不下载音视频**，一条 86 分钟访谈约 700KB、几秒完成，不触发本 VM 的 YouTube 音频下载封锁（那条限制只针对媒体流，**元数据与字幕正常**）。
- `--sub-lang "en.*"` 同时兜住 `en` / `en-orig` / `en-US`。
- 出现 `No supported JavaScript runtime` WARNING 属正常，字幕照拿。

### VTT → 可检索纯文本（滚动重复必须去）
自动字幕是滚动字幕，每行与上一行大量重叠，直接 join 会得到 3-5 倍冗余文本：

```python
import re
def vtt_text(path):
    lines = []
    for ln in open(path, encoding='utf-8', errors='ignore'):
        ln = ln.strip()
        if not ln or '-->' in ln or ln.startswith(('WEBVTT','Kind:','Language:','NOTE')):
            continue
        ln = re.sub(r'<[^>]+>', '', ln)          # 去 <c>/<00:00:01.000> 内联标签
        lines.append(ln)
    out = []
    for l in lines:
        if out and (l == out[-1] or l in out[-1]):  # 关键：子串包含也算重复
            continue
        out.append(l)
    return ' '.join(out)
```

### 关键词窗口定位（不要整篇丢进上下文）
一条访谈 7 万字符，全量读会吃光上下文。用**词级窗口**只取命中处 ±50 词：

```python
def windows(t, pattern, w=55, maxn=14):
    words = t.split(); res = []
    for i, _ in enumerate(words):
        if re.search(pattern, ' '.join(words[max(0,i-2):i+3]), re.I):
            s = ' '.join(words[max(0,i-w):i+w])
            if res and s[:80] in res[-1]:
                continue
            res.append(s)
    out = []
    for s in res:
        if out and s[:80] in out[-1]:
            continue
        out.append(s)
    return out[:maxn]
```
配合两组 pattern：
- **正向**：`capital flow|flight to|into the united states|flowing into|dollar (rally|higher)`
- **反向（必须跑，这是诚实性保证）**：`out of (america|the us)|exodus|de-?dollariz|dollar (falls|weak|crash)|foreign(ers)? (selling|dumping)`
  反向 pattern **零命中本身就是可报告的证据**："翻遍三段访谈没有一处说资金在流出美国"。

### 精确定位主持人的关键提问
访谈里最有价值的是"主持人直接问 + 他直接答"。用短语锚点跳到那一段，前后各取几百词：

```python
w = text.split()
for i in range(len(w)):
    if ' '.join(w[i:i+4]).lower().startswith('do you predict a'):
        print(' '.join(w[i-30:i+380])); break
```
本例正是这样拿到 `Do you predict a crash? … >> **No.**` 这句决定性原话。

---

## 4. 与本项目硬数据对账（Eco 项目独有优势，必做）

KOL 说的和数据显示的常常**不是同一个口径**，把它拆开列表是最高价值的输出：

| 取数 | 命令 |
|---|---|
| 外国官方托管美债 | `data/daily/<date>.json` → `custody.history_long`（WMTSECL1 周度，10 年序列） |
| 美元指数 / 收益率 | `src.fetchers.fred.fetch_fred_history(sid, start='YYYY-MM-DD')` —— ★签名是 `(fred_id, start=...)`，**没有 `days=` 参数** |
| 指标当日值 | `data/daily/<date>.json` → `results` 是 **dict**（`{key: {value, signal, status, as_of}}`），不是 list，别写 `for r in results: r.get(...)` |
| 该 KOL 的 cron 判定 | `data/kol/daily/<date>.json` 逐日扫，看 direction 是否稳定 |

本例结论模板：**外国官方在撤（托管美债一年 -$293B / -10.2%，TIC 6月 -$72B），私人在进**——两件事同时成立，
KOL 的框架容得下，但他只讲后半段。这种"他没讲错，但只讲了一半"的判定比简单的"对/错"有用得多。

---

## 5. ★发现的产品缺陷：单一 direction 字段刻画不了跨资产分歧

本例 cron 对 Armstrong 的自动判定三天翻两次：8/21 `未找到` → 8/22 `看多` → 8/24 `看空`，且无摘要。
真实立场是**股市看多 + 债市看空 + 金看多**，单字段必然抖动。

- 遇到这类 KOL，**在回复里点出来**，并提出 `direction_by_asset`（股/债/金分列）的改法。
- ⚠️ 但**不要自作主张改 dashboard 渲染层**——Chao 铁律"不要做我没给你的任务"。提出方案，等点头。

---

## 6. 检查清单

- [ ] 官网首页 + 相关分类页都抓了（不是只抓首页）
- [ ] 付费墙文章只报标题/分类/日期，明说正文读不到
- [ ] 官方 YouTube + 第三方访谈频道都查了
- [ ] 字幕已 VTT 去重，正向 **和** 反向 pattern 都跑过
- [ ] 至少一句带日期的**原话直引**
- [ ] 与项目自有硬数据（custody / FRED / TIC）对过账，官方 vs 私人口径拆开
- [ ] source link 列在最后
- [ ] 发现的名册/字段结构问题只提议不擅改
