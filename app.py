from flask import Flask, request, jsonify
from dotenv import load_dotenv
import os
import requests
import time
import hmac
import hashlib
import base64
import json
import math

load_dotenv()
app = Flask(__name__)

# 환경변수
api_key = os.getenv("OKX_API_KEY")
api_secret = os.getenv("OKX_API_SECRET")
passphrase = os.getenv("OKX_PASSPHRASE")
symbol = os.getenv("SYMBOL")
side = os.getenv("POSITION_SIDE")
percent_to_trade = float(os.getenv("TRADE_PERCENT", "0.01"))
webhook_secret = os.getenv("WEBHOOK_SECRET")
min_order_size = 0.01  # ETH 최소 주문 수량 (OKX 기준)

# 서명 생성 함수
def generate_signature(timestamp, method, path, body=""):
    message = f"{timestamp}{method}{path}{body}"
    mac = hmac.new(bytes(api_secret, encoding='utf8'), bytes(message, encoding='utf-8'), digestmod=hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

# 잔고 조회 함수
def get_balance():
    path = "/api/v5/account/balance?ccy=USDT"
    url = f"https://www.okx.com{path}"
    timestamp = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
    sign = generate_signature(timestamp, "GET", path)

    headers = {
        'OK-ACCESS-KEY': api_key,
        'OK-ACCESS-SIGN': sign,
        'OK-ACCESS-TIMESTAMP': timestamp,
        'OK-ACCESS-PASSPHRASE': passphrase,
        'Content-Type': 'application/json'
    }

    response = requests.get(url, headers=headers)
    print("[잔고 조회 응답]:", response.status_code, response.text, flush=True)
    data = response.json()

    if "data" not in data:
        raise ValueError("잔고 조회 실패: data 없음")

    return float(data["data"][0]["details"][0]["cashBal"])

# 주문 실행 함수
def place_order(action):
    try:
        usdt_balance = get_balance()
    except Exception as e:
        print("[오류] 잔고 조회 실패:", str(e))
        return

    # 진입금액 (소수점 버림)
    usdt_to_use = math.floor(usdt_balance * percent_to_trade)
    if usdt_to_use < 1:
        print("⚠️ 진입 자금이 1 USDT 미만이므로 최소값 1 USDT로 조정됨")
        usdt_to_use = 1

    # 현재가 조회
    ticker_url = f"https://www.okx.com/api/v5/market/ticker?instId={symbol}"
    last_price = float(requests.get(ticker_url).json()["data"][0]["last"])

    # 수량 계산 후, 최소 주문 수량 이상으로 반올림
    raw_qty = usdt_to_use / last_price
    order_qty = math.floor(raw_qty / min_order_size) * min_order_size

    if order_qty < min_order_size:
        print("⚠️ 주문 수량이 너무 적음. 강제로 최소 수량으로 주문")
        order_qty = min_order_size

    order_qty = f"{order_qty:.3f}"

    order_body = {
        "instId": symbol,
        "tdMode": "cross",
        "side": "buy" if action == "buy" else "sell",
        "ordType": "market",
        "posSide": side,
        "sz": order_qty
    }

    timestamp = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
    body_str = json.dumps(order_body, separators=(',', ':'))
    sign = generate_signature(timestamp, "POST", "/api/v5/trade/order", body_str)

    headers = {
        'OK-ACCESS-KEY': api_key,
        'OK-ACCESS-SIGN': sign,
        'OK-ACCESS-TIMESTAMP': timestamp,
        'OK-ACCESS-PASSPHRASE': passphrase,
        'Content-Type': 'application/json'
    }

    print(f"[Info] 잔고: {usdt_balance:.2f} USDT", flush=True)
    print(f"[Info] 진입금액: {usdt_to_use} USDT, 주문수량: {order_qty}", flush=True)
    print("[Info] 주문 바디:", json.dumps(order_body), flush=True)
    print("[Debug] Timestamp:", timestamp, flush=True)
    print("[Debug] Prehash:", f"{timestamp}POST/api/v5/trade/order{body_str}", flush=True)
    print("[Debug] Signature:", sign, flush=True)

    res = requests.post("https://www.okx.com/api/v5/trade/order", headers=headers, data=body_str)
    print("[OKX 응답]", res.status_code, res.text, flush=True)

# 웹훅 라우트
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    if not data or data.get("secret") != webhook_secret:
        print("❌ Webhook secret mismatch or missing!")
        return jsonify({"error": "unauthorized"}), 403

    signal = data.get("signal")
    print("[Webhook] Signal received:", signal)

    if signal == "BUY":
        place_order("buy")
    elif signal == "TP":
        place_order("sell")
    else:
        print("❌ Unknown signal:", signal)
        return jsonify({"error": "unknown signal"}), 400

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)