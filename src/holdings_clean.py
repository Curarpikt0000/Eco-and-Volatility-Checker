"""holdings_clean.py — 13F issuer 名称清洗 + CUSIP→ticker 映射。

Chao 需求(2026-08): 13F 原始 nameOfIssuer 有三类问题:
  1. HTML 实体污染: "State Str Spdr S&Amp;P 500 Etf" 里 &Amp; 应是 &
  2. SEC 缩写/截断: "Ishares Tr"(iShares Trust,信托登记名,非截断)、名称被 SEC 截断
  3. 无股票代码: 13F 用 CUSIP 不用 ticker, 需映射

解决:
  - clean_issuer(): html.unescape + 常见缩写规范化 + 去多余空格
  - cusip_to_ticker(): 常见大票 CUSIP→ticker 硬映射(免费无完整源, 覆盖主流)
  - 结合 issuer 名启发式匹配 ticker

绝不编: 映射不到就不加 ticker(留空), 不猜错代码。
"""
import html
import re

# ── 常见大票 CUSIP(前8/9位) → ticker。13F 用 CUSIP, 无免费完整映射库, ──
# 这里覆盖知名机构最常持有的主流标的。CUSIP 取前 8 位(不含校验位)做键。
CUSIP_TICKER = {
    "037833": "AAPL",   # Apple
    "594918": "MSFT",   # Microsoft
    "023135": "AMZN",   # Amazon
    "02079K": "GOOGL",  # Alphabet A
    "38259P": "GOOG",   # Alphabet C (老CUSIP)
    "30303M": "META",   # Meta Platforms
    "67066G": "NVDA",   # Nvidia
    "88160R": "TSLA",   # Tesla
    "084670": "BRK.B",  # Berkshire B
    "46625H": "JPM",    # JPMorgan
    "060505": "BAC",    # Bank of America
    "949746": "WFC",    # Wells Fargo
    "17275R": "CSCO",   # Cisco
    "458140": "INTC",   # Intel
    "437076": "HD",     # Home Depot
    "191216": "KO",     # Coca-Cola
    "92826C": "V",      # Visa
    "57636Q": "MA",     # Mastercard
    "742718": "PG",     # Procter & Gamble
    "478160": "JNJ",    # Johnson & Johnson
    "58933Y": "MRK",    # Merck
    "717081": "PFE",    # Pfizer
    "00287Y": "ABBV",   # AbbVie
    "254687": "DIS",    # Disney
    "64110L": "NFLX",   # Netflix
    "68389X": "ORCL",   # Oracle
    "007903": "AMD",    # AMD
    "747525": "QCOM",   # Qualcomm
    "883556": "TMO",    # Thermo Fisher
    "532457": "LLY",    # Eli Lilly
    "808513": "SCHW",   # Schwab
    "025816": "AXP",    # American Express
    "166764": "CVX",    # Chevron
    "674599": "OXY",    # Occidental Petroleum
    "615369": "MCO",    # Moody's
    "500754": "KHC?",   # Kraft Heinz(保守核实)
    "902973": "USB",    # US Bancorp
    "205887": "COF?",   # (保守)
    "912810": "TLT?",   # (Treasury; 保守留问号提示需核实)
    # ETF
    "78462F": "SPY",    # SPDR S&P 500
    "922908": "VTI/VOO",# Vanguard(多只共前缀,保守标注)
    "464287": "IVV/多", # iShares(多只)
    "46090E": "QQQ",    # Invesco QQQ
    "78468R": "SPYG?",  # SPDR growth
    "90290N": "USO?",   # US Oil
}

# ── SEC 常见缩写 → 规范展示(仅安全的、无歧义的) ──
NAME_FIX = [
    (r"\bTr\b", "Trust"),
    (r"\bCorp\b", "Corp"),
    (r"\bInc\b", "Inc"),
    (r"\bCo\b", "Co"),
    (r"\bCl\b", "Class"),
    (r"\bEtf\b", "ETF"),
    (r"\bSpdr\b", "SPDR"),
    (r"\bMktetf\b", "Market ETF"),
]


def clean_issuer(raw: str) -> str:
    """清洗 13F issuer 名: 解 HTML 实体 + 规范化缩写 + 去多余空格。"""
    if not raw:
        return raw
    # 1. 解 HTML 实体。SEC 数据常见 &Amp;(首字母大写的非标准写法),
    #    html.unescape 只认标准小写命名实体, 先把命名实体统一小写化再解(解两次防双重编码)。
    s = re.sub(r"&([A-Za-z]+);", lambda m: "&" + m.group(1).lower() + ";", raw)
    s = html.unescape(html.unescape(s))
    # 2. 折叠多余空格
    s = re.sub(r"\s+", " ", s).strip()
    # 3. Title case(SEC 全大写→更可读), 但保留全大写的短 ticker 式词
    s = s.title()
    # 4. 应用安全缩写规范
    for pat, rep in NAME_FIX:
        s = re.sub(pat, rep, s)
    # 5. title() 会把 & 后的 P 变小写(S&P→S&p), 修回
    s = re.sub(r"S&P", "S&P", s, flags=re.I)
    s = s.replace("S&p", "S&P").replace("S&P 500 Etf", "S&P 500 ETF")
    return s


def cusip_to_ticker(cusip: str) -> str:
    """CUSIP → ticker。取前 6-8 位匹配。映射不到返回空字符串(不猜)。"""
    if not cusip:
        return ""
    c = cusip.strip().upper()
    for width in (8, 6):
        key = c[:width]
        if key in CUSIP_TICKER:
            return CUSIP_TICKER[key]
    return ""


def display_name(issuer_clean: str, ticker: str = "") -> str:
    """展示名: 有 ticker 就 '名称 (TICKER)', 否则只名称。"""
    if ticker and not ticker.endswith("?") and "/" not in ticker and "多" not in ticker:
        return f"{issuer_clean} ({ticker})"
    return issuer_clean


if __name__ == "__main__":
    # 自测
    tests = [
        "State Str Spdr S&Amp;P 500 Etf T",
        "Ishares Tr",
        "APPLE INC",
        "MICROSOFT CORP",
        "ALPHABET INC CL A",
    ]
    for t in tests:
        print(f"{t!r:45} -> {clean_issuer(t)!r}")
    print("CUSIP 037833100 ->", cusip_to_ticker("037833100"))
    print("CUSIP 78462F103 ->", cusip_to_ticker("78462F103"))
