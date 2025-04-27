# app.py
from flask import Flask, request, jsonify
import hmac
import hashlib
import base64
import requests
import time
import json
import os
import math

app = Flask(__name__)

# ✅ 환경변수 로딩
OKX_API_KEY = os.getenv('OKX_API_KEY')
OKX_API_SECRET = os.getenv('OKX_API_SECRET')
OKX_API_PASSPHRASE = os.getenv('OKX_PASSPHRASE')
SYMBOL = os.getenv('SYMBOL', 'SUI-USDT-SWAP')
POSITION_SIDE = os.getenv('POSITION_SIDE', 'long')
TRADE_PERCENT = float(os.getenv('TRADE_PERCENT', '0.001'))
LEVERAGE = int(os.getenv('LEVERAGE', '50'))
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET')

OKX_API_URL = "https://www.okx.com"
HEADERS = {"Content-Type": "application/json"}

# ✅ 심볼별 최소 주문 수량 & 소수점 절삭 설정
MIN_ORDER_SIZES = {
    'BTC-USDT-SWAP': (0.001, 3),
    'ETH-USDT-SWAP': (0.01, 2),
    'DOGE-USDT-SWAP': (1, 0),
    'SOL-USDT-SWAP': (0.01, 2),
    'SUI-USDT-SWAP': (1, 0),
    'XRP-USDT-SWAP': (1, 0)
}

# ✅ OKX API 서명 생성 함수
def generate_signature(timestamp, method, request_path, body, secret_key):
    body = body or ""
    message = f"{timestamp}{method}{request_path}{body}"
    mac = hmac.new(secret_key.encode('utf-8'), message.encode('utf-8'), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

# ✅ 현재가 조회
def get_current_price(symbol):
    res = requests.get(f"{OKX_API_URL}/api/v5/market/ticker?instId={symbol}")
    price = float(res.json()['data'][0]['last'])
    return price

# ✅ 주문 수량 계산 + 최소 수량 맞춤 + 소수점 절삭
def calculate_order_size(symbol, usdt_amount):
    price = get_current_price(symbol)
    size = usdt_amount / price

    min_size, decimals = MIN_ORDER_SIZES.get(symbol, (0.01, 4))  # 기본값
    factor = 10 ** decimals
    size = math.floor(size * factor) / factor

    if size < min_size:
        size = min_size

    return round(size, decimals)

# ✅ 시장가 주문 실행
def send_market_order(symbol, side, sz, leverage):
    timestamp = str(time.time())
    method = "POST"
    request_path = "/api/v5/trade/order"

    body_dict = {
        "instId": symbol,
        "tdMode": "cross",
        "side": side,
        "ordType": "market",
        "sz": str(sz),
        "lever": str(leverage)
    }
    body = json.dumps(body_dict)

    signature = generate_signature(timestamp, method, request_path, body, OKX_API_SECRET)

    headers = {
        "Content-Type": "application/json",
        "OK-ACCESS-KEY": OKX_API_KEY,
        "OK-ACCESS-SIGN": signature,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": OKX_API_PASSPHRASE
    }

    res = requests.post(OKX_API_URL + request_path, headers=headers, data=body)
    return res.json()

# ✅ webhook 수신 엔드포인트
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json

    # 시크릿 검증
    if data.get('secret') != WEBHOOK_SECRET:
        return jsonify({"code": 401, "msg": "Unauthorized"}), 401

    # 보유 USDT 잔액 조회
    balance_res = requests.get(f"{OKX_API_URL}/api/v5/account/balance", headers={
        "OK-ACCESS-KEY": OKX_API_KEY,
        "OK-ACCESS-SIGN": generate_signature(str(time.time()), "GET", "/api/v5/account/balance", "", OKX_API_SECRET),
        "OK-ACCESS-TIMESTAMP": str(time.time()),
        "OK-ACCESS-PASSPHRASE": OKX_API_PASSPHRASE
    })
    usdt_balance = 0
    for asset in balance_res.json()['data'][0]['details']:
        if asset['ccy'] == 'USDT':
            usdt_balance = float(asset['availBal'])
            break

    # 진입 금액 계산
    usdt_amount = usdt_balance * TRADE_PERCENT

    # 주문 수량 계산
    order_size = calculate_order_size(SYMBOL, usdt_amount)

    # 시장가 주문 실행
    result = send_market_order(SYMBOL, POSITION_SIDE, order_size, LEVERAGE)

    return jsonify(result)

# ✅ 서버 실행
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
