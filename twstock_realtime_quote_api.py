"""
台股即時報價代理服務（路徑版）
------------------------------------
用途：呼叫台灣證交所官方即時報價 API (mis.twse.com.tw)，
      並用簡單、乾淨的 JSON 格式回傳。

這次改用「路徑」而非「查詢參數」傳遞股票代號，
因為 Claude 的 web_fetch 工具對這個服務的查詢字串似乎會被忽略、
一直拿到快取過的舊回應；但不同路徑會被當成不同網址，
理論上可以繞過這個問題。

用法範例：
  /quote/2330                  查單一檔
  /quote/2330_0050             查多檔，用底線分隔
  /quote/2330_0050_2454        可以查任意多檔
"""

from flask import Flask, jsonify
import requests
import time
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

TW_TZ = timezone(timedelta(hours=8))


def build_query_string(codes):
    parts = []
    for c in codes:
        c = c.strip()
        if not c:
            continue
        parts.append(f"tse_{c}.tw")
    return "|".join(parts)


def quote_logic(codes):
    ex_ch = build_query_string(codes)

    url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
    params = {
        "ex_ch": ex_ch,
        "_": str(int(time.time() * 1000)),
    }
    headers = {
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
    return jsonify({"queried_at": now, "codes_requested": codes, "results": results})


@app.route("/quote/<codes_path>")
def quote_by_path(codes_path):
    """路徑式查詢，例如 /quote/2330_0050"""
    codes = codes_path.split("_")
    return quote_logic(codes)


@app.route("/quote")
def quote_query():
    """保留原本的查詢參數方式作為備用"""
    from flask import request
    codes_param = request.args.get("codes", "2330")
    codes = codes_param.split(",")
    return quote_logic(codes)


@app.route("/")
def home():
    return jsonify({
        "status": "ok",
        "usage": "/quote/2330_0050  (路徑式，底線分隔多檔)",
        "usage_alt": "/quote?codes=2330,0050  (查詢參數式，備用)",
        "note": "回傳台灣證交所即時報價（延遲約數秒）",
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
