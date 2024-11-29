from flask import Flask, jsonify, request
from flask_cors import CORS  # Import CORS
import ccxt
import pandas as pd
import numpy as np
from flask_socketio import SocketIO
import time
import json

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Load API key and secret from config.json
with open('config.json', 'r') as file:
    config = json.load(file)

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

@socketio.on('connect')
def handle_connect():
    print("Client connected!")

# Emit real-time Bitcoin price data
@socketio.on('fetch_real_time_data')
def handle_realtime_data():
    while True:
        data = fetch_bitcoin_data()
        socketio.emit('price_update', {'data': data.to_json(orient='records')})
        time.sleep(5)  # Emit updates every 5 seconds

# Binance API Setup
api_key = config['api_key']
api_secret = config['api_secret']
exchange = ccxt.binance({
    'apiKey': api_key,
    'secret': api_secret,
    'timeout': 300000,  # Set timeout to 30 seconds
})
exchange.set_sandbox_mode(True)  # Enable Testnet Mode

# Update fetch_bitcoin_data to use the specified time frame
def fetch_bitcoin_data(symbol='BTCUSDT', timeframe='1h'):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

# Implement strategies
def apply_strategy(strategy, data, params={}):
    if strategy == "sma":
        window = params.get("window", 10)  # Default window size is 10
        data['SMA'] = data['close'].rolling(window=window).mean()
        data['Signal'] = np.where(data['close'] > data['SMA'], 'Buy', 'Sell')
    elif strategy == "rsi":
        low_threshold = params.get("low_threshold", 30)  # Default RSI low threshold
        high_threshold = params.get("high_threshold", 70)  # Default RSI high threshold
        delta = data['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        data['RSI'] = 100 - (100 / (1 + rs))
        data['Signal'] = np.where(data['RSI'] < low_threshold, 'Buy',
                                  np.where(data['RSI'] > high_threshold, 'Sell', 'Hold'))
    elif strategy == "bollinger":
        window = params.get("window", 20)  # Default SMA window
        std_dev = params.get("std_dev", 2)  # Default standard deviation multiplier
        data['SMA'] = data['close'].rolling(window=window).mean()
        data['Upper'] = data['SMA'] + (std_dev * data['close'].rolling(window=window).std())
        data['Lower'] = data['SMA'] - (std_dev * data['close'].rolling(window=window).std())
        data['Signal'] = np.where(data['close'] < data['Lower'], 'Buy',
                                  np.where(data['close'] > data['Upper'], 'Sell', 'Hold'))
    elif strategy == "macd":
        short_window = params.get("short_window", 12)  # Default short EMA span
        long_window = params.get("long_window", 26)  # Default long EMA span
        signal_window = params.get("signal_window", 9)  # Default signal line span
        data['EMA12'] = data['close'].ewm(span=short_window, adjust=False).mean()
        data['EMA26'] = data['close'].ewm(span=long_window, adjust=False).mean()
        data['MACD'] = data['EMA12'] - data['EMA26']
        data['Signal_Line'] = data['MACD'].ewm(span=signal_window, adjust=False).mean()
        data['Signal'] = np.where(data['MACD'] > data['Signal_Line'], 'Buy', 'Sell')
    return data


@app.route('/fetch_data', methods=['GET'])
def fetch_data():
    symbol = request.args.get('symbol', 'BTCUSDT')  # Default to BTCUSDT if not specified
    timeframe = request.args.get('timeframe', '1h')  # Default to 1 hour if not specified
    data = fetch_bitcoin_data(symbol, timeframe)
    return jsonify(data.to_json(orient='records'))

@app.route('/simulate', methods=['POST'])
def simulate():
    symbol = request.json.get('symbol', 'BTCUSDT')
    strategy = request.json.get('strategy')
    params = request.json.get('params', {})  # Default to empty dict if no parameters provided
    data = fetch_bitcoin_data(symbol)
    data = apply_strategy(strategy, data, params)
    profit, win_rate, balance = simulate_trading(data)

    return jsonify({
        "profit": profit,
        "win_rate": win_rate,
        "balance": balance,
        "data": data.to_json(orient='records')
    })

def simulate_trading(data, initial_balance=10000):
    balance = initial_balance
    positions = 0  # Number of units currently held
    trades = 0
    for i in range(1, len(data)):
        if data['Signal'].iloc[i-1] == 'Buy':
            # Buy as much as possible with the current balance
            price = data['close'].iloc[i]
            quantity = balance / price
            positions += quantity
            balance -= quantity * price
            trades += 1
        elif data['Signal'].iloc[i-1] == 'Sell' and positions > 0:
            # Sell all held positions
            price = data['close'].iloc[i]
            balance += positions * price
            positions = 0
            trades += 1
    
    profit = balance - initial_balance
    win_rate = (profit > 0) * 100 / trades if trades else 0
    return profit, win_rate, balance


if __name__ == '__main__':
    socketio.run(app, debug=True)
