"""fetchers 包 — 每个数据源一个函数，统一返回 dict 或 None(取不到)。

铁律 (Chao 纪律):
  - 绝不编数字。取不到 → 返回 status='未找到' 或 '数据滞后至 YYYY-MM-DD'，value=None。
  - 每个源 try/except 隔离，单源失败不阻断全局。
  - 每个数据带 as_of 日期。

统一返回格式:
  {"key":..., "value": float|None, "as_of": "YYYY-MM-DD"|None,
   "status": "ok"|"未找到"|"数据滞后", "raw": 原始文本(可选)}
"""
