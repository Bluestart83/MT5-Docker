import backtrader as bt
import requests
import pandas as pd
from datetime import datetime

# === CONFIGURATION ===
API_URL = "http://localhost:8010/candle/history"
symbol = "XAUUSD"
timeframe = "1h"
from_date = "2024-05-01T00:00:00Z"
to_date = "2024-05-05T00:00:00Z"

# === STRATÉGIE SIMPLIFIÉE ===
class MAStrategy(bt.Strategy):
    def __init__(self):
        self.sma_fast = bt.ind.SMA(period=10)
        self.sma_slow = bt.ind.SMA(period=30)

    def next(self):
        if not self.position and self.sma_fast[0] > self.sma_slow[0]:
            self.buy()
        elif self.position and self.sma_fast[0] < self.sma_slow[0]:
            self.close()

# === CHARGER LES DONNÉES DEPUIS L'API ===
def fetch_candles():
    payload = {
        "symbol": symbol,
        "timeframe": timeframe,
        "from_date": from_date,
        "to_date": to_date
    }
    response = requests.post(API_URL, json=payload)
    response.raise_for_status()
    raw_data = response.json()

    if not isinstance(raw_data, list) or len(raw_data) == 0:
        raise ValueError("Données invalides ou vides reçues de l'API")

    # Définir les colonnes attendues selon le format MT5
    columns = ["timestamp", "open", "high", "low", "close", "volume", "spread", "real_volume"]
    df = pd.DataFrame(raw_data, columns=columns)

    # Conversion du timestamp en datetime
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
    df.set_index("datetime", inplace=True)

    # Sélection des colonnes nécessaires pour Backtrader
    df = df[["open", "high", "low", "close", "volume"]]
    return df


# === MAIN ===
if __name__ == "__main__":
    df = fetch_candles()

    # Convertir en format Backtrader
    data = bt.feeds.PandasData(dataname=df)

    cerebro = bt.Cerebro()
    cerebro.addstrategy(MAStrategy)
    cerebro.adddata(data)
    cerebro.broker.setcash(10000)

    print(f"Starting Portfolio Value: {cerebro.broker.getvalue():.2f}")
    cerebro.run()
    print(f"Final Portfolio Value: {cerebro.broker.getvalue():.2f}")

    cerebro.plot()
