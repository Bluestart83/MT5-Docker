import logging
import threading
import time
import uvicorn
import traceback
from datetime import datetime, timedelta
from models import (
    BuyRequest,
    CloseRequest,
    SellRequest,
    GetLastCandleRequest,
    GetLastDealsHistoryRequest,
    GetHistoryCandleRequest,
    ModifyOrderRequest,
    GetHistoryTickRequest
)
import socket
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Dict
from fastapi import FastAPI, Query, HTTPException

#MT5_EXEC = "/root/.wine/drive_c/Program Files/MetaTrader 5 IC Markets Global/terminal64.exe"
MT5_EXEC = "/root/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncio

clients = []

log_file_path = "./fxscript.log"

logging.basicConfig(
    filename=log_file_path,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

logging.info("Starting api")


while True:
    try:
        from fastapi import FastAPI

        logging.warning("wait fastapi done")
        break
    except:
        logging.warning("waiting install fastapi")
        import time

        time.sleep(5)

while True:
    try:
        import MetaTrader5 as mt5

        logging.warning("waiting MetaTrader5 done")
        break
    except:
        logging.warning("waiting install MetaTrader5")
        import time

        time.sleep(5)


path = MT5_EXEC

while not os.path.exists(path):
    logging.warning(f"Waiting for file: {path}")
    time.sleep(5)  # Đợi 5 giây trước khi kiểm tra lại
logging.warning(f"Waiting  {path} done")

# tf_dic={'1d': 16408, '1h': 16385, '12h': 16396, '2h': 16386, '3h': 16387, '4h': 16388, '6h': 16390, '8h': 16392, '1m': 1, '10m': 10, '12m': 12, '15m': 15, '2m': 2, '20m': 20, '3m': 3, '30m': 30, '4m': 4, '5m': 5, '6m': 6, 'N1m': 49153, '1w': 32769}
tf_dic = {}
for v in dir(mt5):
    if v.startswith("TIMEFRAME_"):
        tf = v.replace("TIMEFRAME_", "")
        symbol, num = tf[0], tf[1:]
        tf_dic[num + symbol.lower()] = int(getattr(mt5, v))

for v in range(10):
    logging.info(f"Starting mt5")

    success = mt5.initialize(
        path,
        login=int(os.environ["ACCOUNT"]),
        password=os.environ["PASSWORD"],
        server=os.environ["SERVER"],
    )
    if not success:
        logging.warning(f"Cannot init mt5: {mt5.last_error()}")
        time.sleep(10)
        continue
    else:
        logging.info(f"Starting mt5 done")
        break

# # init kazzoo
# kazoo_client = KazooClient()
# logging.warning(f"Init ZOOKEEPER: {os.environ['ZOOKEEPER']}")
# conn_retry_policy = KazooRetry(max_tries=-1, delay=0.1, max_delay=4, ignore_expire=True)
# cmd_retry_policy = KazooRetry(max_tries=-1, delay=0.3, backoff=1, max_delay=4, ignore_expire=True)
# client = KazooClient(hosts=os.environ['ZOOKEEPER'], connection_retry=conn_retry_policy, command_retry=cmd_retry_policy)
# for _ in range(3):
#     try:
#         client.start()
#         break
#     except:
#         logging.warning(f"error when connect zk: {os.environ['ZOOKEEPER']}, {traceback.format_exc()}")


# def thread_function(name):
#     node_path = f"/account/{os.environ['ACCOUNT']}/running"
#     while True:
#         try:
#             if not client.exists(node_path):
#                 client.create(node_path, ephemeral=True)

#                 client.set(node_path, json.dumps({
#                     'service': 'http://' + socket.gethostbyname(socket.gethostname())+":8000",
#                     'wine': socket.gethostbyname(socket.gethostname())+":8080",
#                     **{x: os.environ[x] for x in ['ACCOUNT', 'PASSWORD', 'SERVER']}
#                 }, indent=3).encode())
#                 logging.warning(f"Create node: {node_path}")
#         except:
#             logging.exception("Error when create running node", exc_info=True)

#         import time
#         time.sleep(5)


# live_thread = threading.Thread(target=thread_function, args=(1,))
# live_thread.start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # node_path = f"/account/{os.environ['ACCOUNT']}/running"
    # client.delete(node_path)


app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
def healthz():
    if "login" in mt5.account_info()._asdict():
        return "ok"
    raise Exception(str(mt5.last_error()))


@app.get("/")
def read_root():
    try:
        res = mt5.account_info()._asdict()
        return res
    except:
        return mt5.last_error()


@app.post("/candle/last")
def candle_last(inp: GetLastCandleRequest):
    try:
        timeframe = tf_dic.get(inp.timeframe, None)
        assert timeframe, f"timeframe invalid: {inp.timeframe}"
        r = mt5.copy_rates_from_pos(inp.symbol, timeframe, inp.start, inp.count)
        if inp.start == 0:
            return r.tolist()[:-1]
        return r.tolist()
    except:
        raise RuntimeError(mt5.last_error())


@app.post("/deals/all")
def deals_all(inp: GetLastDealsHistoryRequest):
    """
    https://pastebin.com/raw/9QgW5yYi
    """
    try:
        from_date = datetime(2025, 1, 1)
        to_date = datetime.now() + timedelta(days=3)
        if inp.symbol:
            r = mt5.history_deals_get(from_date, to_date, group=inp.symbol)
        else:
            r = mt5.history_deals_get(from_date, to_date)

            # Convert to list of dictionaries
        if r is not None:
            return [deal._asdict() for deal in r]  # Return list of dictionaries
        else:
            print("No deals found or error occurred")
            return []
    except:
        raise RuntimeError(mt5.last_error())


@app.get("/account/login")
def account_login():
    success = mt5.initialize(
        #path="/config/.winecfg_mt5/drive_c/Program Files/MetaTrader 5 IC Markets Global/terminal64.exe",
        path=MT5_EXEC,
        login=int(os.environ["ACCOUNT"]),
        password=os.environ["PASSWORD"],
        server=os.environ["SERVER"],
    )
    if not success:
        return {"success": success, "last_error": mt5.last_error()}
    return {"success": success}


@app.get("/account/info")
def account_info():
    try:
        res = mt5.account_info()._asdict()
        return res
    except:
        return mt5.last_error()

@app.post("/trade/buy")
def trade_buy(request: BuyRequest):
    close_all(request.symbol, request.magic, request.deviation)

    try:
        symbol = request.symbol

        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).ask
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": request.symbol,
            "volume": request.lot,
            "type": mt5.ORDER_TYPE_BUY,
            "price": price,
            "sl": price - point * request.sl_point,
            "tp": price + point * request.tp_point,
            "deviation": request.deviation,
            "magic": request.magic,
            "comment": request.comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # send a trading request
        result = mt5.order_send(request)
        return result._asdict()
    except:
        return mt5.last_error()


@app.post("/trade/sell")
def trade_sell(request: SellRequest):
    close_all(request.symbol, request.magic, request.deviation)
    try:
        symbol = request.symbol

        point = mt5.symbol_info(symbol).point
        price = mt5.symbol_info_tick(symbol).bid
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": request.symbol,
            "volume": request.lot,
            "type": mt5.ORDER_TYPE_SELL,
            "price": price,
            "sl": price + point * request.sl_point,
            "tp": price - point * request.tp_point,
            "deviation": request.deviation,
            "magic": request.magic,
            "comment": request.comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # send a trading request
        result = mt5.order_send(request)
        return result._asdict()
    except:
        return mt5.last_error()


def close_all(symbol, magic, deviation):
    positions = mt5.positions_get(symbol=symbol)
    # (TradePosition(ticket=658189343, time=1716288623, time_msc=1716288623438, time_update=1716288623, time_update_msc=1716288623438, type=0, magic=0, identifier=
    # 658189343, reason=3, volume=0.01, price_open=2420.07, sl=2418.07, tp=2422.07, price_current=2419.91, swap=0.0, profit=-0.16, symbol='XAUUSD', comment='NO COM
    # MENT', external_id=''),)
    arr = []
    for p in positions:
        if p.magic == magic:
            arr.append(p)

    cur_tick = mt5.symbol_info_tick(symbol)
    res = []
    for p in arr:
        if p.type == mt5.ORDER_TYPE_BUY:
            price = cur_tick.bid
            order_type = mt5.ORDER_TYPE_SELL
        elif p.type == mt5.ORDER_TYPE_SELL:
            price = cur_tick.ask
            order_type = mt5.ORDER_TYPE_BUY
        else:
            raise Exception("order type unsupported")
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": p.volume,
            "type": order_type,
            "position": p.identifier,
            "price": price,
            "deviation": deviation,
            "magic": p.magic,
            "comment": "python script close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        tmp = mt5.order_send(request)
        res.append(tmp)
    return res


@app.post("/trade/close")
def trade_close(request: CloseRequest):
    try:
        return close_all(request.symbol, request.magic, request.deviation)
    except:
        return mt5.last_error()

@app.post(
    "/candle/history",
    summary="Get historical candle data",
    description=(
        "Returns a list of raw candles from MetaTrader 5.\n\n"
        "**Each candle is a list of values:**\n"
        "`[timestamp, open, high, low, close, volume, spread, real_volume]`\n\n"
        "- `timestamp`: Unix time in seconds\n"
        "- `open`, `high`, `low`, `close`: price data\n"
        "- `volume`: tick volume\n"
        "- `spread`: spread value\n"
        "- `real_volume`: real volume (if available)"
    ),
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "example": [
                        [1747011600, 3291.47, 3299.73, 3266.77, 3272.68, 4618, 5, 0],
                        [1747015200, 3272.68, 3288.81, 3265.95, 3287.58, 4437, 6, 0],
                        [1747018800, 3287.78, 3289.91, 3272.2, 3279.17, 4492, 14, 0]
                    ]
                }
            }
        }
    }
)
def candle_history(inp: GetHistoryCandleRequest):
    try:
        #return f"timeframe={inp.timeframe} tf_dic={tf_dic}"
        timeframe = tf_dic.get(inp.timeframe, None)
        assert timeframe, f"timeframe invalid: {inp.timeframe}"
        from_date = inp.from_date.replace(tzinfo=None)
        to_date = inp.to_date.replace(tzinfo=None)
        #return f"from_date={from_date} ({type(inp.from_date)}), to_date={inp.to_date} ({type(inp.to_date)})"

        rates = mt5.copy_rates_range(
            inp.symbol,
            timeframe,
            from_date,
            to_date
        )

        if rates is None:
            raise RuntimeError(f"No data found: {mt5.last_error()}")

        return rates.tolist()

    except Exception as e:
        logging.exception("Error in /candle/history")
        raise RuntimeError(str(e) or mt5.last_error())

from models import ModifyOrderRequest

@app.post(
    "/trade/modify",
    summary="Modify TP or SL of an open position",
    description=(
        "Modifies the Stop Loss and/or Take Profit of an open position identified by its ticket.\n\n"
        "- `ticket`: position ID\n"
        "- `tp`: new take profit price (optional)\n"
        "- `sl`: new stop loss price (optional)"
    ),
    responses={
        200: {
            "description": "Modification result",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "result": {
                            "retcode": 10009,
                            "comment": "Request completed",
                            "request": {
                                "action": 6,
                                "symbol": "XAUUSD",
                                "sl": 1925.0,
                                "tp": 1940.0
                            }
                        }
                    }
                }
            }
        }
    }
)


@app.post(
    "/tick/history",
    summary="Retrieve tick data from MT5",
    description=(
        "Returns a list of ticks between two datetime values for the specified symbol using MetaTrader 5.\n\n"
        "**Each tick includes the following values in an array:**\n"
        "- `time`: UTC timestamp in ISO 8601 format (e.g., '2025-05-12T08:35:56Z')\n"
        "- `bid`: Bid price\n"
        "- `ask`: Ask price\n"
        "- `last`: Last traded price (usually 0 for forex)\n"
        "- `volume`: Raw volume\n"
        "- `time_msc`: Timestamp in milliseconds\n"
        "- `flags`: Tick type flag (e.g., trade, bid, ask, etc.)\n"
        "- `volume_real`: Real volume (if available, otherwise 0)"
    )
)
def tick_history(inp: GetHistoryTickRequest):
    try:
        from_date = inp.from_date.replace(tzinfo=None)
        to_date = inp.to_date.replace(tzinfo=None)

        ticks = mt5.copy_ticks_range(
            inp.symbol,
            from_date,
            to_date,
            mt5.COPY_TICKS_ALL  # ou COPY_TICKS_TRADE / COPY_TICKS_INFO
        )

        if ticks is None or len(ticks) == 0:
            raise RuntimeError(f"No ticks found: {mt5.last_error()}")

        return ticks.tolist()

    except Exception as e:
        logging.exception("Error in /tick/history")
        raise RuntimeError(str(e) or mt5.last_error())

def modify_order(request: ModifyOrderRequest):
    try:
        positions = mt5.positions_get(ticket=request.ticket)
        if not positions:
            raise ValueError(f"Position with ticket {request.ticket} not found")

        position = positions[0]
        symbol_info = mt5.symbol_info(request.symbol)
        if not symbol_info:
            raise ValueError(f"Invalid symbol: {request.symbol}")

        point = symbol_info.point

        sl = request.sl if request.sl is not None else position.sl
        tp = request.tp if request.tp is not None else position.tp

        trade_request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": request.symbol,
            "position": request.ticket,
            "sl": sl,
            "tp": tp,
            "deviation": request.deviation,
            "magic": request.magic,
            "comment": request.comment,
        }

        result = mt5.order_send(trade_request)
        return {
            "success": result.retcode == mt5.TRADE_RETCODE_DONE,
            "result": result._asdict()
        }

    except Exception as e:
        logging.exception("Error in /trade/modify")
        return {"success": False, "error": str(e)}




if __name__ == "__main__":
    uvicorn.run("api:app", port=8000, host="0.0.0.0", reload=False, log_level="debug")

# Endpoint GET avec paramètre `symbol`
@app.get("/symbol-info/{symbol}")
def symbol_info(symbol: str):
    info = mt5.symbol_info(symbol)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Symbole introuvable : {symbol}")

    return info._asdict()

# TODO test it
@app.post("/trade/cancel")
def cancel_order_endpoint(order_id: int):
    try:
        result = mt5.order_check({
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": order_id
        })
        return {"success": True, "result": result._asdict()}
    except Exception as e:
        return {"success": False, "error": str(e)}

# TODO test it
@app.get("/positions")
def list_positions():
    try:
        positions = mt5.positions_get()
        if not positions:
            return []
        return [p._asdict() for p in positions]
    except Exception as e:
        return {"error": str(e)}
    
# WebSocket ticks
@app.websocket("/ws/ticks/{symbol}")
async def websocket_endpoint(websocket: WebSocket, symbol: str):
    await websocket.accept()
    last_time_msc = None
    
    # Vérification que le symbole existe et est disponible
    if not mt5.symbol_select(symbol, True):
        error_msg = {"error": f"Symbol {symbol} not found or not available"}
        await websocket.send_json(error_msg)
        return
    
    try:
        while True:
            tick = mt5.symbol_info_tick(symbol)
            if tick:
                current_tick = tick._asdict()
                current_time_msc = current_tick.get('time_msc')
                # Vérifier si c'est un nouveau tick en comparant time_msc
                if last_time_msc != current_time_msc:
                    await websocket.send_json(current_tick)
                    last_time_msc = current_time_msc
                   # print(f"Nouveau tick envoyé pour {symbol}: time_msc={current_time_msc}")
                
            await asyncio.sleep(0.01)  # Fréquence de vérification (10 fois par seconde)
            
    except WebSocketDisconnect:
        pass


# uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4 --reload --reload-include *.yml"
