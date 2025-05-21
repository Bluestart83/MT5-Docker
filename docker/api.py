import logging
import threading
import time
import uvicorn
import traceback
from datetime import datetime, timedelta
import socket
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import List, Union, Dict, Optional
from fastapi import FastAPI, Query, HTTPException, Path, Response, status, Body
from fastapi.middleware.cors import CORSMiddleware
import numpy as np

from models import (
    OrderRequest,
    CloseRequest,
    GetLastCandleRequest,
    GetLastDealsHistoryRequest,
    GetHistoryCandleRequest,
    ModifyOrderRequest,
    GetHistoryTickRequest
)

#MT5_EXEC = "/root/.wine/drive_c/Program Files/MetaTrader 5 IC Markets Global/terminal64.exe"
MT5_EXEC = "/root/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncio

import inspect

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


# Build mapping {code: name}
retcode_map = {
    value: name
    for name, value in inspect.getmembers(mt5)
    if name.startswith("TRADE_RETCODE_") and isinstance(value, int)
}

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
# Allow CORS Requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ou remplace "*" par ["http://localhost:8089"] pour être plus restrictif
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    try:
        account = mt5.account_info()
        if account is None:
            code, message = mt5.last_error()
            raise Exception(f"MT5 non initialisé ou session invalide : [{code}] {message}")

        return response_from_mt5_result({"login": account.login})
        
    except Exception as e:
        return response_from_exception(e)


@app.get("/")
def read_root():
    try:
        res = mt5.account_info()
        return response_from_mt5_result(res)

    except Exception as e:
        return response_from_exception(e)

def response_from_mt5_result(
    result,
    success_retcode=mt5.TRADE_RETCODE_DONE,
    partial_retcode=mt5.TRADE_RETCODE_DONE_PARTIAL
):
    if result is None:
        return JSONResponse(
            status_code=status.HTTP_204_NO_CONTENT,
            content={
                "retcode": 204,
                "status": "no_content",
                "message": "MT5 returned no result",
                "data": None
            }
        )

    # Liste → on convertit chaque item si besoin
    if isinstance(result, list):
        data = [r._asdict() if hasattr(r, "_asdict") else r for r in result]
        return JSONResponse(
            status_code=200,
            content={
                "retcode": success_retcode,
                "status": retcode_map.get(success_retcode, "UNKNOWN_RETCODE"),
                "data": data
            }
        )

    # Objet unique
    result_dict = result._asdict() if hasattr(result, "_asdict") else result
    has_retcode = "retcode" in result_dict
    retcode = result_dict.get("retcode", success_retcode)

    data = result_dict.copy()
    data.pop("retcode", None)
    data.pop("retcode_external", None)

    if not has_retcode or retcode == success_retcode:
        return JSONResponse(
            status_code=200,
            content={
                "retcode": success_retcode,
                "status":retcode_map.get(retcode, "UNKNOWN_RETCODE"),
                "data": data
            }
        )

    if partial_retcode is not None and retcode == partial_retcode:
        return JSONResponse(
            status_code=207,
            content={
                "retcode": retcode,
                "status": retcode_map.get(retcode, "UNKNOWN_RETCODE"),
                "message": result_dict.get("comment", "Partially executed"),
                "data": data
            }
        )

    return JSONResponse(
        status_code=400,
        content={
            "retcode": retcode,
            "status": retcode_map.get(retcode, "UNKNOWN_RETCODE"),
            "message": result_dict.get("comment", "MT5 error"),
            "data": data
        }
    )


def response_from_exception(e: Exception):
    code, message = mt5.last_error()
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": "error",
            "message": str(e),
            "mt5_error": {
                "code": code,
                "message": message
            }
        }
    )

def numpy_to_native(obj):
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


@app.post("/candle/last")
def candle_last(inp: GetLastCandleRequest):
    timeframe = tf_dic.get(inp.timeframe)
    if not timeframe:
        return response_from_mt5_result({"retcode": 10020, "status": "error", "message": f"Invalid timeframe: {inp.timeframe}"})

    rates = mt5.copy_rates_from_pos(inp.symbol, timeframe, inp.start, inp.count)
    if rates is None:
        code, msg = mt5.last_error()
        return response_from_mt5_result( {"retcode": code, "status": "error", "message": msg})

    # Convertir numpy structured array → liste de dicts
    data = [
        {key: numpy_to_native(r[key]) for key in rates.dtype.names}
        for r in rates
    ]

    # Supprimer la dernière bougie si start == 0
    if inp.start == 0 and data:
        data = data[:-1]

    return response_from_mt5_result( data)


    
# Trade History (finished)
@app.get("/history-deals", summary="Récupère l'historique des deals (filtrage par symbol et magic)")
def deals_all(
    symbol: Optional[str] = Query(None, description="Symbole à filtrer (ex: XAUUSD)"),
    magic: Optional[int] = Query(None, description="Magic number à filtrer")
):
    from_date = datetime(2025, 1, 1)
    to_date = datetime.utcnow() + timedelta(days=3)

    try:
        deals = mt5.history_deals_get(from_date, to_date, group=symbol) if symbol else mt5.history_deals_get(from_date, to_date)

        if deals is None:
            code, msg = mt5.last_error()
            return {
                "retcode": code,
                "status": retcode_map.get(code, "UNKNOWN_RETCODE"),
                "message": msg,
                "data": []
            }

        filtered = [d._asdict() for d in deals if magic is None or d.magic == magic]
        return response_from_mt5_result(filtered)

    except Exception as e:
        response_from_exception(e)

@app.post("/account/login")
def account_login():
    success = mt5.initialize(
        path=MT5_EXEC,
        login=int(os.environ["ACCOUNT"]),
        password=os.environ["PASSWORD"],
        server=os.environ["SERVER"],
    )

    if not success:
        code, msg = mt5.last_error()
        return JSONResponse(
            status_code=500,
            content={
                "retcode": code,
                "status": retcode_map.get(code, "UNKNOWN_RETCODE"),
                "comment": msg
            }
        )

    return response_from_mt5_result({
            "comment": "Login successful"
        })

@app.get("/account/info")
def account_info():
    try:
        res = mt5.account_info()
        return response_from_mt5_result(res)

    except Exception as e:
        return response_from_exception(e)


@app.post("/trade")
def trade_new(request: OrderRequest):
    #close_all(request.symbol, request.magic, request.deviation)
    side = request.side.lower()
    if side not in ("buy", "sell"):
        raise HTTPException(status_code=400, detail="Le champ `side` doit être 'buy' ou 'sell'.")

    return _trade_buy(request, mt5.ORDER_TYPE_BUY if request.side =="buy" else mt5.ORDER_TYPE_SELL)

def _trade_buy(request: OrderRequest, side) -> Dict:
    #close_all(request.symbol, request.magic, request.deviation)
    try:
        symbol_info = mt5.symbol_info(request.symbol)
        digits = symbol_info.digits
        body = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": request.symbol,
            "volume": request.lot,
            "type": side,
            "magic": request.magic,
            "comment": request.comment,
            "type_time": mt5.ORDER_TIME_GTC,
            #"type_filling": mt5.ORDER_FILLING_IOC,
            "type_filling": symbol_info.filling_mode
        }

        if request.price is not None:
            body["deviation"] = request.deviation

        if request.price is not None:
            body["price"] = _round_price(request.price, digits)

        if request.tp and request.tp > 0:
            body["tp"] = _round_price(request.tp, digits)

        if request.sl and request.sl > 0:
            body["sl"] = _round_price(request.sl, digits)

        # send a trading request
        ##return JSONResponse({"msg": "OK"})
        result = mt5.order_send(body)
        return response_from_mt5_result(result)

    except Exception as e:
        return response_from_exception(e)
    

def _round_price(value: float, digits: int) -> float:
    return round(value, digits)



def close_all(symbol: str, magic: int, deviation: int = 10) -> List[dict]:
    #    # (TradePosition(ticket=658189343, time=1716288623, time_msc=1716288623438, time_update=1716288623, time_update_msc=1716288623438, type=0, magic=0, identifier=
    # 658189343, reason=3, volume=0.01, price_open=2420.07, sl=2418.07, tp=2422.07, price_current=2419.91, swap=0.0, profit=-0.16, symbol='XAUUSD', comment='NO COM
    # MENT', external_id=''),)
    positions = mt5.positions_get(symbol=symbol)
    if positions is None:
        code, msg = mt5.last_error()
        raise Exception(f"Erreur MT5 lors de positions_get(): [{code}] {msg}")

    cur_tick = mt5.symbol_info_tick(symbol)
    if not cur_tick or cur_tick.ask == 0 or cur_tick.bid == 0:
        raise Exception(f"Tick invalide pour {symbol} — ask/bid indisponible")

    symbol_info = mt5.symbol_info(symbol)
    
    results = []
    for p in positions:
        if p.magic != magic:
            continue

        if p.type == mt5.ORDER_TYPE_BUY:
            price = cur_tick.bid
            order_type = mt5.ORDER_TYPE_SELL
        elif p.type == mt5.ORDER_TYPE_SELL:
            price = cur_tick.ask
            order_type = mt5.ORDER_TYPE_BUY
        else:
            raise Exception(f"Type d'ordre non supporté : {p.type}")

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": p.volume,
            "type": order_type,
            "position": p.identifier,
            "price": price,
            "deviation": deviation,
            "magic": p.magic,
            "comment": "API script close",
            "type_time": mt5.ORDER_TIME_GTC,
            #"type_filling": mt5.ORDER_FILLING_IOC,
            "type_filling": symbol_info.filling_mode
        }

        result = mt5.order_send(request)
        result_dict = result._asdict() if result is not None else {"error": "order_send failed"}
        results.append(result_dict)

    return results




@app.post("/trade-closeall")
def trade_close_all(request: CloseRequest):
    try:
        results = close_all(request.symbol, request.magic, request.deviation)
        return response_from_mt5_result(results)

    except Exception as e:
        return response_from_exception(e)



@app.put(
    "/trade/{ticket}",
    summary="Modify TP or SL of an open position",
    description=(
        "Modifies the Stop Loss and/or Take Profit of an open position identified by its ticket.\n\n"
        "- `order_id`: position ID\n"
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
def modify_order(
    ticket: int = Path(..., description="Ticket ID of the position to modify"),
    request: ModifyOrderRequest = Body(...)
):
    try:
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            raise HTTPException(status_code=404, detail=f"Position with ticket {ticket} not found")

        position = positions[0]

        #sl = request.sl if request.sl is not None else position.sl
        #tp = request.tp if request.tp is not None else position.tp
        comment = request.comment if request.comment is not None else position.comment

        trade_request = {
            "action": mt5.TRADE_ACTION_SLTP,
            #"symbol": position.symbol,
            "position": ticket,
            #"deviation": request.deviation,
            #"magic": request.magic if request.magic is not None else position.magic,
            "comment": comment,
        }

        if request.tp:
            trade_request["tp"] = request.tp  # Sinon on ne le met pas
        if request.sl:
            trade_request["sl"] = request.sl  # Sinon on ne le met pas

        result = mt5.order_send(trade_request)
        return response_from_mt5_result(result)

    except Exception as e:
        return response_from_exception(e)
    

@app.post(
    "/history/ticks",
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
            mt5.COPY_TICKS_ALL
        )

        if ticks is None or len(ticks) == 0:
            code, msg = mt5.last_error()
            raise RuntimeError(f"No ticks found: {msg}", {"code": code})

        # Convert numpy structured array to JSON-safe list of dicts
        ticks_list = [
            {key: numpy_to_native(t[key]) for key in ticks.dtype.names}
            for t in ticks
        ]

        return response_from_mt5_result(ticks_list)

    except Exception as e:
        return response_from_exception(e)


# Endpoint GET avec paramètre `symbol`
@app.get("/symbol-info/{symbol}")
def symbol_info(symbol: str):
    info = mt5.symbol_info(symbol)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Symbole introuvable : {symbol}")

    return response_from_mt5_result(info._asdict())

@app.delete("/trade/{order_id}", summary="Clôturer une position existante", status_code=200)
def close_position_by_id(
    order_id: int = Path(..., description="ID de la position à clôturer"),
    magic: Optional[int] = Query(None, description="Magic number de sécurité"),
    deviation: int = Query(10, description="Déviation maximale autorisée (slippage)")
):
    try:
        positions = mt5.positions_get(ticket=order_id)
        if not positions:
            raise HTTPException(status_code=404, detail=f"Position {order_id} introuvable")

        position = positions[0]

        if magic is not None and position.magic != magic:
            raise HTTPException(
                status_code=403,
                detail=f"Magic incorrect : attendu {magic}, reçu {position.magic}"
            )

        symbol = position.symbol
        volume = position.volume
        #print(f"Position volume: {position.volume}")

        tick = mt5.symbol_info_tick(symbol)
        if not tick or tick.ask == 0 or tick.bid == 0:
            raise HTTPException(status_code=500, detail="Tick invalide")
        
        symbol_info = mt5.symbol_info(symbol)

        if position.type == mt5.ORDER_TYPE_BUY:
            price = tick.bid
            order_type = mt5.ORDER_TYPE_SELL
        elif position.type == mt5.ORDER_TYPE_SELL:
            price = tick.ask
            order_type = mt5.ORDER_TYPE_BUY
        else:
            raise HTTPException(status_code=400, detail=f"Type de position non supporté : {position.type}")

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "position": order_id,
            "price": price,
            "deviation": deviation,
            "magic": position.magic,
            "comment": "Closed manually",
            "type_time": mt5.ORDER_TIME_GTC,
            #"type_filling": mt5.ORDER_FILLING_IOC,
            "type_filling": symbol_info.filling_mode
        }

        result = mt5.order_send(request)
        return response_from_mt5_result(result)

    except Exception as e:
        return response_from_exception(e)


@app.get("/positions")
def list_positions(symbol: Optional[str] = Query(None), magic: Optional[int] = Query(None)):
    try:
        # Appel natif : on filtre par symbol si fourni
        if symbol is not None:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()  # récupère tous les ordres


        if positions is None or len(positions) == 0:
            return []

        # Filtrage supplémentaire côté Python pour le magic number
        if magic is not None:
            positions = [p for p in positions if p.magic == magic]

        result = [p._asdict() for p in positions]
        return response_from_mt5_result(result)

    except Exception as e:
        return response_from_exception(e)

@app.get("/positions/{ticket}")
def get_position_by_ticket(
    ticket: int = Path(..., description="Numéro du ticket de la position"),
    magic: Optional[int] = Query(None, description="Magic number pour filtrer")
):
    try:
        positions = mt5.positions_get(ticket=ticket)

        if not positions:
            raise HTTPException(status_code=404, detail=f"Aucune position trouvée pour le ticket {ticket}")

        position = positions[0]

        if magic is not None and position.magic != magic:
            raise HTTPException(status_code=404, detail=f"No position found fot magic number ≠ {magic}")

        return response_from_mt5_result(position)

    except Exception as e:
        return response_from_exception(e)


@app.get("/orders")
def list_orders(symbol: Optional[str] = Query(None), magic: Optional[int] = Query(None)):
    try:
        # Appel natif : on filtre par symbol si fourni
        if symbol is not None:
            orders = mt5.orders_get(symbol=symbol)
        else:
            orders = mt5.orders_get()  # récupère tous les ordres

        if orders is None or len(orders) == 0:
            return []

        # Filtrage supplémentaire côté Python pour le magic number
        if magic is not None:
            orders = [p for p in orders if p.magic == magic]

        result = [p._asdict() for p in orders]
        return response_from_mt5_result(result)

    except Exception as e:
        return response_from_exception(e)

@app.get("/orders/{ticket}")
def get_order_by_ticket(
    ticket: int = Path(..., description="Numéro du ticket de l'ordre"),
    magic: Optional[int] = Query(None, description="Magic number pour filtrer")
):
    try:
        positions = mt5.orders_get(ticket=ticket)

        if not positions:
            raise HTTPException(status_code=404, detail=f"Aucun ordre trouvée pour le ticket {ticket}")

        position = positions[0]

        if magic is not None and position.magic != magic:
            raise HTTPException(status_code=404, detail=f"No order found for magic number ≠ {magic}")

        return response_from_mt5_result(position)

    except Exception as e:
        return response_from_exception(e)

@app.delete("/orders/{order_id}", summary="Close an existing order", status_code=200)
def close_order_by_id(
    order_id: int = Path(..., description="ID de la position à clôturer"),
    magic: Optional[int] = Query(None, description="Magic number de sécurité"),
):
    try:
        result = mt5.order_delete(ticket=order_id)
        return response_from_mt5_result(result)

    except Exception as e:
        return response_from_exception(e)


@app.post(
    "/history/candle",
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

        result = rates.tolist()
        return response_from_mt5_result(result)

    except Exception as e:
        return response_from_exception(e)


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


if __name__ == "__main__":
    uvicorn.run("api:app", port=8000, host="0.0.0.0", reload=False, log_level="debug")
