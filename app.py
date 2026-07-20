"""
台股即時報價代理服務
------------------------------------
用途：呼叫台灣證交所官方即時報價 API (mis.twse.com.tw)，
      並用簡單、乾淨的 JSON 格式回傳，方便 Claude 用 web_fetch 讀取。

部署後，網址範例：
  https://你的網址/quote?codes=2330,0050

回傳範例：
{
  "queried_at": "2026-07-20T11:30:05+08:00",
  "results": [
    {"code": "2330", "name": "台積電", "price": 2310.0, "change": 20.0,
     "change_pct": 0.87, "open": 2300.0, "high": 2340.0, "low": 2290.0,
     "prev_close": 2290.0, "time": "11:29:58"},
    {"code": "0050", "name": "元大台灣50", "price": 100.9, ...}
  ]
}
"""

from flask import Flask, request, jsonify
import requests
import time
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

TW_TZ = timezone(timedelta(hours=8))

# 股票代碼對應交易所前綴：上市 tse_ / 上櫃 otc_
# 這裡先簡單判斷：0050、0056 這類ETF跟四碼股票大多是上市(tse)
# 若要查上櫃股票，記得改成 otc_

def build_query_string(codes):
    parts = []
    for c in codes:
        c = c.strip()
        if not c:
            continue
        parts.append(f"tse_{c}.tw")
    return "|".join(parts)


@app.route("/quote")
def quote():
    codes_param = request.args.get("codes", "2330")
    codes = codes_param.split(",")
    ex_ch = build_query_string(codes)

    url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
    params = {
        "ex_ch": ex_ch,
        # 加時間戳避免任何中間層快取回傳舊資料
        "_": str(int(time.time() * 1000)),
    }
    headers = {
        # 官方即時報價網站需要一個「看起來像瀏覽器」的 User-Agent
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://mis.twse.com.tw/stock/index.jsp",
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return jsonify({"error": f"上游證交所API呼叫失敗: {e}"}), 502

    results = []
    for item in data.get("msgArray", []):
        def to_float(v):
            try:
                if v in (None, "-", "", "0.00"):
                    return None
                return float(v)
            except (ValueError, TypeError):
                return None

        prev_close = to_float(item.get("y"))
        open_p = to_float(item.get("o"))
        high_p = to_float(item.get("h"))
        low_p = to_float(item.get("l"))

        # 現價備援順序：
        # 1. z = 成交價（正常情況下最準）
        # 2. 若剛好沒有最新成交，退而求其次用最佳買賣價(b1/a1)平均
        # 3. 最後才退回今天的開盤價，並標明來源，避免直接回傳null
        price = to_float(item.get("z"))
        price_source = "trade"

        if price is None:
            best_bid = to_float((item.get("b") or "").split("_")[0]) if item.get("b") else None
            best_ask = to_float((item.get("a") or "").split("_")[0]) if item.get("a") else None
            if best_bid and best_ask:
                price = round((best_bid + best_ask) / 2, 2)
                price_source = "bid_ask_mid"
            elif best_bid:
                price = best_bid
                price_source = "best_bid"
            elif best_ask:
                price = best_ask
                price_source = "best_ask"

        if price is None and open_p is not None:
            price = open_p
            price_source = "open_fallback"

        change = None
        change_pct = None
        if price is not None and prev_close:
            change = round(price - prev_close, 2)
            change_pct = round(change / prev_close * 100, 2)

        results.append({
            "code": item.get("c"),
            "name": item.get("n"),
            "price": price,
            "price_source": price_source,
            "prev_close": prev_close,
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "change": change,
            "change_pct": change_pct,
            "time": item.get("t"),
        })

    now = datetime.now(TW_TZ).isoformat()
    return jsonify({"queried_at": now, "results": results})


@app.route("/")
def home():
    return jsonify({
        "status": "ok",
        "usage": "/quote?codes=2330,0050",
        "note": "回傳台灣證交所即時報價（延遲約數秒）",
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
