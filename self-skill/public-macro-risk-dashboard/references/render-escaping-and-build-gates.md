# 渲染层转义 + 构建期门禁（消灭「静默显示错误」）

2026-09-21 Eco-and-Volatility-Checker 实战。主题：**别靠记得检查，把标准写成门禁。**

## 1. HTML 里的字面 Markdown 星号

**症状**：页面上直接显示 `**BG2Pod**` 而不是粗体。HTML 不认 Markdown。
数据文件（`kol_registry.json` / `kol_store_export.json` / `kol_profiles.json`）里写的是 Markdown，
而它们是 Notion 侧 SSOT 的**单向镜像，不能改** → 只能在渲染层转。

**解法：`_esc_md()`，与既有 `_esc()` 并存**

```python
def _esc_md(s):
    if s is None:
        return ""
    t = html.escape(str(s), quote=True)          # ① 先转义
    return re.sub(r"\*\*([^*\n]{1,120}?)\*\*", r"<b>\1</b>", t)   # ② 再插 <b>
```

**顺序不可反**：先插 `<b>` 会被 `html.escape` 变成 `&lt;b&gt;`，白做。
转义后原文的真 `<` 已是 `&lt;`，此时插 `<b>` 不构成注入面。

## 2. ★打了三轮地鼠才醒悟：出口是发散的

```
25 处 → 13 → 8 → …
```
每轮都以为修完了。病根：「页面上有没有星号」**只有看产物才知道**，
而渲染出口散布在 KOL 简介 / KOL 言论 / 名录档案 / 关注焦点 / 各 section 说明文案……
靠人肉枚举必然漏一个。

**正解 = 构建期硬门禁**（与项目既有 `assert_no_missing_kwargs` 同款范式，只警告不中断）：

```python
def assert_no_literal_markdown(html_path):
    hits = re.findall(r"\*\*([^*\n]{2,80})\*\*", open(html_path, encoding="utf-8").read())
    # 报数量 + 每条往前 600 字符找最近的 class="..."，直接告诉人改哪个出口
```
在 `generate()` 写完产物后调用。下次任何人从任何新出口引入 Markdown，构建时立刻可见。

这条对应 memory 里那句：**给别人定了标准却靠「记得检查」执行，迟早在自己身上破例。** 我破了三次。

## 3. ★门禁必须先验证它真会响

三条路径都要测，缺一不可：

| 输入 | 期望 |
|---|---|
| 当前**仍有 8 处星号**的真产物 | 报警，且能指出 class 名 |
| 干净文件 | 静默通过 |
| 不存在的文件 | 不崩 |

只测成功路径的校验器 = 没有校验器。

## 4. `_esc_md` 的 XSS 反测（公网页面必做）

判据 = **除我们自己插入的 `<b>`/`</b>` 外，输出里不得有裸 `<` 或 `>`**。

```
<script>alert(1)</script>        → &lt;script&gt;…            ✅
**<img src=x onerror=alert(1)>** → <b>&lt;img…&gt;</b>        ✅
**a**<svg onload=alert(1)>**b**  → <b>a</b>&lt;svg…<b>b</b>  ✅
```

**我第一版的判据自己写错了**：拿 `onerror=` 字样当危险信号，把已转义的
`&lt;img … onerror=alert(1)&gt;` 判成「❌ 危险」。那已是纯文本，浏览器不会执行。
**检测器写错会两头骗人**：把安全的报成危险，也会把危险的报成安全。

边界也要测：单星号、不配对 `**不配对`、跨行 `行一**\n**行二` 都不应误转。

## 5. 并发门禁的匹配范围

```bash
# ❌ 匹配全机同名脚本 —— 被 Science-KOL 项目的 build_dashboard.py 误伤 exit 9
ps -eo cmd | grep -F "build_dashboard.py" | grep -v grep | wc -l

# ✅ 连项目路径一起匹配
ps -eo cmd | grep -F "Eco-and-Volatility-Checker" | grep -F "build_dashboard.py" | grep -v grep | wc -l
```
多项目机器上脚本重名是常态。另：`timeout` + `python` 会各算一个进程，
「4 个进程」可能只是 2 个构建。

## 6. 核对线上文案：不要 grep 记忆里的措辞

我 grep「没有官方单一口径」得 0，差点判定标注没上线 —— 实际页面写的是「**无**官方单一口径」，
差一个字。**正解 = 正则提取渲染出的 `<div class="...">` 内容读实际文本**，
而不是拿脑子里记的关键词去匹配产物。

（同类：`find("gms-caliber")` 命中的可能是 CSS 定义而非渲染内容，要匹配 `<div class="xxx">`。）
