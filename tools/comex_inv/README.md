# comex_inv — COMEX/上海库存 + GLD/SLV 资金流 自产线(Eco 接管, 2026-10-06)

来源: 原 Comex-Daily-AI-Report/scripts 三个脚本(原写死 Mac 路径, 且生产站 comex-inventory-charts 自 09-16 起停更)。
数据: Notion CME 库存库/SLV 库/SHFE-SGE 周库(只读) + SPDR 官方 GLD 历史 xlsx + SGE 官网周报 PDF。
**对 Notion 纯只读, 不写任何库**(避免与另一 agent 撞车)。

用法: `INV_BASE=<工作目录> python build_inventory_data.py && python build_etf_data.py && python render_inventory_html.py`
产物: `$INV_BASE/inventory_charts.html`(内含 `const CHARTS`), 由 `src/external_data.fetch_comex_inventory` 解析。
已知限制: 无 `data/sge_history.json`(2021-12+ 本地存档)→ SGE 历史靠 Eco 缓存按日期合并保住。
