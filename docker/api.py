import logging
import threading
import time
import uvicorn
import traceback
import subprocess
from datetime import datetime, timedelta
import socket
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import List, Union, Dict, Optional
from fastapi import FastAPI, Request, Query, HTTPException, Path, Response, status, Body
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import numpy as np
import MetaTrader5 as mt5

from models import (
    OrderRequest,
    CloseRequest,
    GetLastCandleRequest,
    GetLastDealsHistoryRequest,
    GetHistoryCandleRequest,
    ModifyOrderRequest,
    GetHistoryTickRequest,
    TradingViewWebhook
)

#MT5_EXEC = "/root/.wine/drive_c/Program Files/MetaTrader 5 IC Markets Global/terminal64.exe"
MT5_EXEC = "/root/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"

# Add this variable at the top of your file with other configs
MAX_LOT = float(os.environ.get("MAX_LOT", "9999.0"))  # Absolute max size from server
MAX_INIT_RETRIES = 10
INIT_RETRY_DELAY = 10

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncio

import inspect

clients = []
mt5_initialized = False
mt5_lock = threading.Lock()
mt5_init_attempts = 0

# Define missing constants in your code
SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2
SYMBOL_FILLING_RETURN = 4
FORCE_ACCOUNT_SWITCH = os.environ.get("FORCE_ACCOUNT_SWITCH", "false").lower() == "true"  # Default: false

log_file_path = "./fxscript.log"
#logging.basicConfig(
#    filename=log_file_path,
#    level=logging.INFO,
#    format="%(asctime)s - %(levelname)s - %(message)s",
#)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()  # Console/stdout
    ]
)
logger = logging.getLogger(__name__)

logger.info("API - Starting API V2.5 - Docker/Wine optimized")
logging.info(f"Configuration: FORCE_ACCOUNT_SWITCH={FORCE_ACCOUNT_SWITCH}")
logging.info(f"Configuration: MAX_LOT={MAX_LOT}")

path = MT5_EXEC

while not os.path.exists(path):
    logging.warning(f"API - Waiting for file: {path}")
    time.sleep(5)
logging.warning(f"API - Waiting {path} done")

# tf_dic={'1d': 16408, '1h': 16385, '12h': 16396, '2h': 16386, '3h': 16387, '4h': 16388, '6h': 16390, '8h': 16392, '1m': 1, '10m': 10, '12m': 12, '15m': 15, '2m': 2, '20m': 20, '3m': 3, '30m': 30, '4m': 4, '5m': 5, '6m': 6, 'N1m': 49153, '1w': 32769}
tf_dic = {}
for v in dir(mt5):
    if v.startswith("TIMEFRAME_"):
        tf = v.replace("TIMEFRAME_", "")
        symbol, num = tf[0], tf[1:]
        tf_dic[num + symbol.lower()] = int(getattr(mt5, v))

logging.info(f"API - Starting python script... (20s)")
time.sleep(20)

# Function to check if MT5 is connected
def check_mt5_connection():
    """Quickly checks if MT5 is connected"""
    try:
        account_info = mt5.account_info()
        return account_info is not None
    except:
        return False

# Initialization/reconnection function
def initialize_mt5():
    """Initializes or reconnects MT5"""
    max_retries = 10
    
    for attempt in range(max_retries):
        logging.info(f"API - Starting mt5 (attempt {attempt + 1}/{max_retries})")
        
        # First check if already connected
        if check_mt5_connection():
            logging.info(f"API - MT5 already connected")
            return True
        
        # If multiple failures, try to kill the MT5 process
        if attempt > 2:
            try:
                logging.warning("API - Attempting to kill stuck MT5 process")
                subprocess.run(["pkill", "-f", "terminal64.exe"])
                time.sleep(5)
            except Exception as e:
                logging.warning(f"API - Could not kill MT5 process: {e}")
        
        # Otherwise, initialize
        success = mt5.initialize(
            path,
            login=int(os.environ["ACCOUNT"]),
            password=os.environ["PASSWORD"],
            server=os.environ["SERVER"],
            timeout=120000  # 2 minutes for login
        )
        
        if not success:
            logging.warning(f"API - Cannot init mt5: {mt5.last_error()}")
            time.sleep(30 * (attempt + 1))
            continue
        
        # Check that it really works
        time.sleep(5)  # Wait a bit for the connection to stabilize
        if check_mt5_connection():
            account_info = mt5.account_info()
            logging.info(f"API - MT5 connected successfully!")
            logging.info(f"Account: {account_info.login}, Balance: {account_info.balance}")
            return True
        else:
            logging.warning("API - MT5 initialized but not connected")
            time.sleep(10)
    
    return False

# Startup initialization
if not initialize_mt5():
    logging.error("API - Failed to initialize MT5 after all attempts")
    logging.error("API - EXITING - MT5 will restart the script")
    exit(1)  # Terminate the script so MT5 restarts it

# Function to ensure MT5 is connected before each operation
def ensure_mt5_connection():
    """Ensures MT5 is connected, reconnects if necessary"""
    if not check_mt5_connection():
        logging.warning("API - MT5 connection lost, attempting to reconnect...")
        return initialize_mt5()
    return True

# Monitoring thread to maintain connection
def mt5_connection_monitor():
    """Periodically checks connection and reconnects if necessary"""
    while True:
        try:
            time.sleep(30)  # Check every 30 seconds
            if not check_mt5_connection():
                logging.warning("Monitor - MT5 connection lost, reconnecting...")
                initialize_mt5()  # Just try to reconnect, no kill
        except Exception as e:
            logging.error(f"Monitor - Error: {e}")
            time.sleep(10)

# Start the monitoring thread
monitor_thread = threading.Thread(target=mt5_connection_monitor, daemon=True)
monitor_thread.start()
logging.info("API - Connection monitor started")
logging.info("MT5 API ready to receive requests")


# Build mapping {code: name}
retcode_map = {
    value: name
    for name, value in inspect.getmembers(mt5)
    if name.startswith("TRADE_RETCODE_") and isinstance(value, int)
}


# 1. GLOBAL VARIABLES (add with other global variables, after running_threads and thread_flags)
trailing_triggers = {}  # key = (symbol, magic, comment) -> {"trigger_price": x, "trail_points": y, "trail_step": z, "is_long": bool}
MAX_POSITION_CHECKS = 15  
POSITION_CHECK_DELAY = 0.05  # 50ms (pour centraliser la valeur)
# 2. PRICE MONITORING FUNCTION (add AFTER the existing trailing_loop function, around line 1200)
def price_monitor_thread():
    """Monitors prices to activate pending trailing"""
    position_check_counters = {}  # Track retry counts per key
    
    while True:
        try:
            # Check MT5 connection
            if not check_mt5_connection():
                time.sleep(5)
                continue
                
            for key, trigger in list(trailing_triggers.items()):
                symbol, magic, comment = key
                
                # Initialize counter if new
                if key not in position_check_counters:
                    position_check_counters[key] = 0
                
                # Check if position exists
                positions = mt5.positions_get(symbol=symbol)
                position = None
                if positions:
                    for pos in positions:
                        if pos.magic == magic:
                            if comment and pos.comment != comment:
                                continue
                            position = pos
                            break
                
                if not position:
                    position_check_counters[key] += 1
                    if position_check_counters[key] >= MAX_POSITION_CHECKS:  # Max 10 attempts
                        trailing_triggers.pop(key, None)
                        position_check_counters.pop(key, None)
                        logging.info(f"Position not found after {MAX_POSITION_CHECKS} checks, trigger removed for {symbol}/{magic}/{comment}")
                    continue  # Skip to next trigger, check again next loop
                
                # Position exists, reset counter
                position_check_counters.pop(key, None)
                
                # Check if we need to adjust the trigger (first time finding the position)
                if trigger.get("pending_adjustment", False):
                    real_entry = position.price_open
                    theoretical_entry = trigger.get("theoretical_entry", real_entry)
                    # If no theoretical_entry was stored, use real_entry (no adjustment needed)
                    if theoretical_entry is None:
                        theoretical_entry = real_entry
                    
                    entry_delta = real_entry - theoretical_entry
                    
                    # Adjust the trigger price
                    original_trigger = trigger["trigger_price"]
                    trigger["trigger_price"] = original_trigger + entry_delta
                    trigger["pending_adjustment"] = False
                    trigger["is_long"] = position.type == mt5.ORDER_TYPE_BUY
                    
                    logging.info(f"[PRICE MONITOR] Adjusted trigger for {symbol}: {original_trigger} -> {trigger['trigger_price']} (delta: {entry_delta})")
                
                # Get current price
                tick = mt5.symbol_info_tick(symbol)
                if not tick:
                    continue
                
                current_price = tick.bid if trigger["is_long"] else tick.ask
                trigger_price = trigger["trigger_price"]
                
                # Check if trigger is reached (or if trigger_price is 0 = immediate)
                trigger_reached = False
                if trigger_price == 0:
                    trigger_reached = True
                    logging.info(f"Immediate trigger activated for {symbol}")
                elif trigger["is_long"] and current_price >= trigger_price:
                    trigger_reached = True
                    logging.info(f"LONG trigger reached: {current_price} >= {trigger_price}")
                elif not trigger["is_long"] and current_price <= trigger_price:
                    trigger_reached = True
                    logging.info(f"SHORT trigger reached: {current_price} <= {trigger_price}")
                
                if trigger_reached:
                    # Remove trigger first
                    trailing_triggers.pop(key, None)
                    
                    # Activate trailing
                    with threads_lock:
                        if key not in running_threads or not running_threads[key].is_alive():
                            t = threading.Thread(
                                target=trailing_loop,
                                args=(symbol, magic, comment, trigger["trail_points"], trigger["trail_step"]),
                                daemon=True
                            )
                            running_threads[key] = t
                            thread_flags[key] = True
                            t.start()
                            logging.info(f"Trailing started for {symbol}/{magic}/{comment} with {trigger['trail_points']} points")
                    
            time.sleep(POSITION_CHECK_DELAY)  # Check every 50ms
            
        except Exception as e:
            logging.error(f"Error in price_monitor_thread: {e}")
            logging.error(traceback.format_exc())
            time.sleep(2)


# 3. START THE MONITORING THREAD (add AFTER starting the MT5 monitor)
price_monitor = threading.Thread(target=price_monitor_thread, daemon=True)
price_monitor.start()
logging.info("Price monitor for trailing started")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    import logging
    
    if os.environ.get("API_KEY"):
        logging.warning("API Key protection ENABLED")
        logging.warning(f"API Key required: {os.environ.get('API_KEY')[:8]}...")
    else:
        logging.warning("WARNING: API Key protection DISABLED - Running in OPEN mode")
        logging.warning("WARNING: Anyone can access this API! Set API_KEY in .env for security")
    
    yield
    # Shutdown
    # node_path = f"/account/{os.environ['ACCOUNT']}/running"
    # client.delete(node_path)


app = FastAPI(lifespan=lifespan)
# Allow CORS Requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or replace "*" with ["http://localhost:8089"] to be more restrictive
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========================================
# GLOBAL MIDDLEWARE - Optional API Key
# ========================================
@app.middleware("http")
async def verify_api_key_middleware(request: Request, call_next):
    #logging.debug(f"API - verify_api_key_middleware")
    # Always public routes
    PUBLIC_ROUTES = ["/health", "/", "/docs", "/openapi.json", "/redoc"]
    
    # IMPORTANT: Let OPTIONS requests through (CORS preflight)
    if request.method == "OPTIONS":
        return await call_next(request)
    
    # If it's a public route, let it through
    if request.url.path in PUBLIC_ROUTES:
        return await call_next(request)
    
    # Check if an API_KEY is defined in the environment
    expected_api_key = os.environ.get("API_KEY")
    
    # If no API_KEY defined = open mode (no security)
    if not expected_api_key:
        return await call_next(request)
    
    # If API_KEY defined, we must verify it
    api_key = None
    
    # 1. Look in URL (query params)
    if "api_key" in request.query_params:
        api_key = request.query_params["api_key"]
    
    # 2. Or in headers
    elif "X-API-Key" in request.headers:
        api_key = request.headers["X-API-Key"]
    
    # Verify the API key
    if not api_key or api_key != expected_api_key:
        return JSONResponse(
            status_code=401,
            content={
                "detail": "Invalid or missing API Key",
                "hint": "Provide api_key in URL (?api_key=xxx) or X-API-Key header"
            }
        )
    
    # Valid API Key, continue
    response = await call_next(request)
    return response


@app.get("/health")
def health():
    try:
        account = mt5.account_info()
        if account is None:
            code, message = mt5.last_error()
            raise Exception(f"MT5 not initialized or invalid session: [{code}] {message}")

        return response_from_mt5_result({"login": "OK"})
        
    except Exception as e:
        return response_from_exception(e)

@app.get("/health-private")
def healthPrivate():
    try:
        account = mt5.account_info()
        if account is None:
            code, message = mt5.last_error()
            raise Exception(f"MT5 not initialized or invalid session: [{code}] {message}")

        return response_from_mt5_result({"login": account.login})
        
    except Exception as e:
        return response_from_exception(e)

@app.get("/")
def root():  # FIXED: Renamed from health to root to avoid duplicate
    try:
        account = mt5.account_info()
        if account is None:
            code, message = mt5.last_error()
            raise Exception(f"MT5 not initialized or invalid session: [{code}] {message}")

        return response_from_mt5_result({"RET": "OK"})
        
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

    # List -> convert each item if needed
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

    # Single object
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

    # Convert numpy structured array -> list of dicts
    data = [
        {key: numpy_to_native(r[key]) for key in rates.dtype.names}
        for r in rates
    ]

    # Remove last candle if start == 0
    if inp.start == 0 and data:
        data = data[:-1]

    return response_from_mt5_result( data)


    
# Trade History (finished and unfinished)
@app.get("/history-deals", summary="Deals (filters: symbol, magic; finished_only)")
def deals_all(
    symbol: Optional[str] = Query(None, description="e.g. XAUUSD"),
    magic: Optional[int] = Query(None, description="EA magic"),
    finished_only: bool = Query(True, description="Only closed trades (add open positions if False)")
):
    from_date = datetime(2025, 1, 1)
    to_date = datetime.utcnow() + timedelta(days=3)

    try:
        deals = mt5.history_deals_get(from_date, to_date, group=symbol) if symbol else mt5.history_deals_get(from_date, to_date)
        if deals is None:
            code, msg = mt5.last_error()
            return {"retcode": code, "status": retcode_map.get(code, "UNKNOWN_RETCODE"), "message": msg, "data": []}

        # index des ouvertures (entry=0)
        opens = {}
        for d in deals:
            if d.entry == 0 and d.position_id not in opens:
                opens[d.position_id] = {
                    "magic": d.magic,
                    "comment_open": d.comment,
                    "entry_price": d.price,
                    "time_open": d.time,
                    "symbol": d.symbol,
                    "side": "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL",
                }

        out = []
        # fermetures (entry=1)
        for d in deals:
            if d.entry != 1:
                continue
            o = opens.get(d.position_id, {})
            eff_magic = o.get("magic", d.magic)
            if magic is not None and eff_magic != magic:
                continue
            rec = d._asdict()
            rec["magic"] = eff_magic
            rec["comment_close"] = rec.pop("comment", "")
            rec["comment"] = o.get("comment_open", "")
            rec["entry_price"] = o.get("entry_price")
            rec["close_price"] = d.price
            rec["time_open"] = o.get("time_open")
            rec["time_close"] = d.time
            rec["symbol"] = o.get("symbol", d.symbol)
            rec["side"] = o.get("side", "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL")
            rec["status"] = "CLOSED"
            out.append(rec)

        if not finished_only:
            positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
            if positions:
                for p in positions:
                    if magic is not None and p.magic != magic:
                        continue
                    out.append({
                        "position_id": p.ticket,
                        "symbol": p.symbol,
                        "magic": p.magic,
                        "comment": p.comment,
                        "comment_close": None,
                        "entry_price": p.price_open,
                        "close_price": None,
                        "time_open": p.time,
                        "time_close": None,
                        "profit": p.profit,
                        "volume": p.volume,
                        "type": p.type,
                        "side": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                        "status": "OPEN",
                    })

        return response_from_mt5_result(out)

    except Exception as e:
        return response_from_exception(e)



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
    logging.debug("trade_new")
    side = request.side.lower()
    if side not in ("buy", "sell"):
        raise HTTPException(status_code=400, detail="The `side` field must be 'buy' or 'sell'.")

    return _trade_buy(request, mt5.ORDER_TYPE_BUY if request.side =="buy" else mt5.ORDER_TYPE_SELL)

def _trade_buy(request: OrderRequest, side) -> Dict:
    #close_all(request.symbol, request.magic, request.deviation)
    try:
         # Choose a valid mode
        symbol_info = mt5.symbol_info(request.symbol)
        logging.debug("get_safe_filling_mode++")
        filling_mode = get_safe_filling_mode(symbol_info)
        logging.debug(f"get_safe_filling_mode--{filling_mode}")

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
            "type_filling": filling_mode
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
    
# Define missing constants in your code
SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2
SYMBOL_FILLING_RETURN = 4

def get_safe_filling_mode(symbol_info) -> int:
    """Automatically detects the best filling mode"""
    if symbol_info is None:
        return mt5.ORDER_FILLING_RETURN
    
    filling_flags = symbol_info.filling_mode
    execution_mode = symbol_info.trade_exemode
    
    logging.debug(f"Symbol: {symbol_info.name}")
    logging.debug(f"Execution mode: {execution_mode}")
    logging.debug(f"Filling flags: {filling_flags}")
    logging.debug(f"Supports FOK: {bool(filling_flags & SYMBOL_FILLING_FOK)}")
    logging.debug(f"Supports IOC: {bool(filling_flags & SYMBOL_FILLING_IOC)}")
    logging.debug(f"Supports RETURN: {bool(filling_flags & SYMBOL_FILLING_RETURN)}")
    
    # Preference order based on execution type
    if execution_mode == 2:  # Market execution
        preferred_order = [
            (SYMBOL_FILLING_FOK, mt5.ORDER_FILLING_FOK),
            (SYMBOL_FILLING_IOC, mt5.ORDER_FILLING_IOC),
            (SYMBOL_FILLING_RETURN, mt5.ORDER_FILLING_RETURN)
        ]
    else:
        preferred_order = [
            (SYMBOL_FILLING_RETURN, mt5.ORDER_FILLING_RETURN),
            (SYMBOL_FILLING_IOC, mt5.ORDER_FILLING_IOC),
            (SYMBOL_FILLING_FOK, mt5.ORDER_FILLING_FOK)
        ]
    
    # Look for the first supported mode
    for flag, mode in preferred_order:
        if filling_flags & flag:
            logging.debug(f"Selected filling mode: {mode}")
            return mode
    
    logging.debug("Warning: No filling mode found, using FOK")
    return mt5.ORDER_FILLING_FOK
    
def _round_price(value: float, digits: int) -> float:
    return round(value, digits)



def close_all(symbol: str, magic: int, deviation: int = 10) -> List[dict]:
    #    # (TradePosition(ticket=658189343, time=1716288623, time_msc=1716288623438, time_update=1716288623, time_update_msc=1716288623438, type=0, magic=0, identifier=
    # 658189343, reason=3, volume=0.01, price_open=2420.07, sl=2418.07, tp=2422.07, price_current=2419.91, swap=0.0, profit=-0.16, symbol='XAUUSD', comment='NO COM
    # MENT', external_id=''),)
    positions = mt5.positions_get(symbol=symbol)
    if positions is None:
        code, msg = mt5.last_error()
        raise Exception(f"MT5 error in positions_get(): [{code}] {msg}")

    cur_tick = mt5.symbol_info_tick(symbol)
    if not cur_tick or cur_tick.ask == 0 or cur_tick.bid == 0:
        raise Exception(f"Invalid tick for {symbol} - ask/bid unavailable")

    symbol_info = mt5.symbol_info(symbol)
    filling_mode = get_safe_filling_mode(symbol_info)
    
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
            raise Exception(f"Unsupported order type: {p.type}")

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
            "type_filling": filling_mode
        }

        print(f"TRADE={request}")

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
            trade_request["tp"] = request.tp  # Otherwise don't include it
        if request.sl:
            trade_request["sl"] = request.sl  # Otherwise don't include it

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


# GET endpoint with `symbol` parameter
@app.get("/symbol-info/{symbol}")
def symbol_info(symbol: str):
    info = mt5.symbol_info(symbol)
    
    # If symbol not found, try to activate it
    if info is None:
        print(f"Symbol not found. Attempting to activate {symbol}...")
        if not mt5.symbol_select(symbol, True):
            raise HTTPException(status_code=404, detail=f"Symbol not found: {symbol}")
        
        info = mt5.symbol_info(symbol)
        if info is None:
            raise HTTPException(status_code=404, detail=f"Symbol not found after activation: {symbol}")
    
    # If symbol exists but not visible, activate it
    elif not info.visible:
        print(f"Symbol not visible. Activating {symbol}...")
        if not mt5.symbol_select(symbol, True):
            raise HTTPException(status_code=500, detail=f"Cannot activate {symbol}")
        info = mt5.symbol_info(symbol)

    # Wait for prices to arrive
    for _ in range(5):
        if info.ask > 0 or info.bid > 0 or info.trade_mode == 0:
            break
        time.sleep(0.1)
        info = mt5.symbol_info(symbol)

    return response_from_mt5_result(info._asdict())

@app.delete("/trade/{order_id}", summary="Close an existing position", status_code=200)
def close_position_by_id(
    order_id: int = Path(..., description="Position ID to close"),
    magic: Optional[int] = Query(None, description="Security magic number"),
    deviation: int = Query(10, description="Maximum allowed deviation (slippage)")
):
    try:
        positions = mt5.positions_get(ticket=order_id)
        if not positions:
            raise HTTPException(status_code=404, detail=f"Position {order_id} not found")

        position = positions[0]

        if magic is not None and position.magic != magic:
            raise HTTPException(
                status_code=403,
                detail=f"Incorrect magic: expected {magic}, received {position.magic}"
            )

        symbol = position.symbol
        volume = position.volume
        #print(f"Position volume: {position.volume}")

        tick = mt5.symbol_info_tick(symbol)
        if not tick or tick.ask == 0 or tick.bid == 0:
            raise HTTPException(status_code=500, detail="Invalid tick")
        
        symbol_info = mt5.symbol_info(symbol)
        filling_mode = get_safe_filling_mode(symbol_info)
        
        if position.type == mt5.ORDER_TYPE_BUY:
            price = tick.bid
            order_type = mt5.ORDER_TYPE_SELL
        elif position.type == mt5.ORDER_TYPE_SELL:
            price = tick.ask
            order_type = mt5.ORDER_TYPE_BUY
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported position type: {position.type}")

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
            "type_filling": filling_mode
        }

        result = mt5.order_send(request)
        return response_from_mt5_result(result)

    except Exception as e:
        return response_from_exception(e)


@app.get("/positions")
def list_positions(symbol: Optional[str] = Query(None), magic: Optional[int] = Query(None)):
    try:
        # Native call: filter by symbol if provided
        if symbol is not None:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()  # get all orders


        if positions is None or len(positions) == 0:
            return []

        # Additional filtering in Python for magic number
        if magic is not None:
            positions = [p for p in positions if p.magic == magic]

        result = [p._asdict() for p in positions]
        return response_from_mt5_result(result)

    except Exception as e:
        return response_from_exception(e)

@app.get("/positions/{ticket}")
def get_position_by_ticket(
    ticket: int = Path(..., description="Position ticket number"),
    magic: Optional[int] = Query(None, description="Magic number to filter")
):
    try:
        positions = mt5.positions_get(ticket=ticket)

        if not positions:
            raise HTTPException(status_code=404, detail=f"No position found for ticket {ticket}")

        position = positions[0]

        if magic is not None and position.magic != magic:
            raise HTTPException(status_code=404, detail=f"No position found for magic number != {magic}")

        return response_from_mt5_result(position)

    except Exception as e:
        return response_from_exception(e)


@app.get("/orders")
def list_orders(symbol: Optional[str] = Query(None), magic: Optional[int] = Query(None)):
    try:
        # Native call: filter by symbol if provided
        if symbol is not None:
            orders = mt5.orders_get(symbol=symbol)
        else:
            orders = mt5.orders_get()  # get all orders

        if orders is None or len(orders) == 0:
            return []

        # Additional filtering in Python for magic number
        if magic is not None:
            orders = [p for p in orders if p.magic == magic]

        result = [p._asdict() for p in orders]
        return response_from_mt5_result(result)

    except Exception as e:
        return response_from_exception(e)

@app.get("/orders/{ticket}")
def get_order_by_ticket(
    ticket: int = Path(..., description="Order ticket number"),
    magic: Optional[int] = Query(None, description="Magic number to filter")
):
    try:
        positions = mt5.orders_get(ticket=ticket)

        if not positions:
            raise HTTPException(status_code=404, detail=f"No order found for ticket {ticket}")

        position = positions[0]

        if magic is not None and position.magic != magic:
            raise HTTPException(status_code=404, detail=f"No order found for magic number != {magic}")

        return response_from_mt5_result(position)

    except Exception as e:
        return response_from_exception(e)

@app.delete("/orders/{order_id}", summary="Close an existing order", status_code=200)
def close_order_by_id(
    order_id: int = Path(..., description="Order ID to close"),
    magic: Optional[int] = Query(None, description="Security magic number"),
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
        assert timeframe, f"Invalid timeframe: {inp.timeframe}"
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
    
    # Check that symbol exists and is available
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
                # Check if it's a new tick by comparing time_msc
                if last_time_msc != current_time_msc:
                    await websocket.send_json(current_tick)
                    last_time_msc = current_time_msc
                   # print(f"New tick sent for {symbol}: time_msc={current_time_msc}")
                
            await asyncio.sleep(0.01)  # Check frequency (10 times per second)
            
    except WebSocketDisconnect:
        pass


# Part 2 - Continuation from Part 1
# This file continues from the WebSocket endpoint in Part 1

# =====================================
# TradingView Webhook - Configuration
# =====================================
running_threads = {}
# Dictionary to store pending trailing triggers
trailing_triggers = {}  # key = (symbol, magic, comment) -> {"trigger_price": x, "trail_points": y, "trail_step": z, "is_long": bool}
thread_flags = {}  # key = (symbol, magic, comment) -> bool
threads_lock = threading.Lock()  # For thread-safety
TRAILING_CHECK_INTERVAL = 0.1  # Check interval in seconds

def cleanup_dead_threads():
    """Cleans up terminated threads"""
    with threads_lock:
        dead_keys = [k for k, t in running_threads.items() if not t.is_alive()]
        for k in dead_keys:
            running_threads.pop(k, None)
            thread_flags.pop(k, None)
        if dead_keys:
            logging.info(f"Cleaned up {len(dead_keys)} terminated threads")

def check_position_exists(symbol: str, magic: int, comment: str = None) -> bool:
    """Checks if a position already exists with the given criteria"""
    try:
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return False
        
        for pos in positions:
            if pos.magic != magic:
                continue
            # If comment is specified, it must match
            if comment is not None and comment != "" and pos.comment != comment:
                continue
            return True
        return False
    except Exception as e:
        logging.error(f"Error check_position_exists: {e}")
        return False

def check_pending_order_exists(symbol: str, magic: int, comment: str = None, order_type: int = None) -> bool:
    """Checks if a pending order already exists with the given criteria"""
    try:
        orders = mt5.orders_get(symbol=symbol)
        if not orders:
            return False
        
        for order in orders:
            if order.magic != magic:
                continue
            # If comment is specified, it must match
            if comment is not None and comment != "" and order.comment != comment:
                continue
            # If order type is specified, it must match
            if order_type is not None and order.type != order_type:
                continue
            return True
        return False
    except Exception as e:
        logging.error(f"Error check_pending_order_exists: {e}")
        return False

def trailing_loop(symbol: str, magic: int, comment: str, trail_points: float = 50.0, min_step: float = 10.0):
    """Enhanced trailing stop loop with comment management and stops level validation"""
    start_time = time.time()
    pos = None
    key = (symbol, magic, comment or "")
    
    logging.info(f"Starting trailing for {symbol}/{magic}/{comment or 'no comment'} - Points: {trail_points}, Step: {min_step}")

    # Get symbol info once
    point = None
    digits = None
    stops_level = 0
    
    try:
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            logging.error(f"Symbol {symbol} not found")
            with threads_lock:
                running_threads.pop(key, None)
                thread_flags.pop(key, None)
            return
        
        point = symbol_info.point
        digits = symbol_info.digits
        stops_level = symbol_info.trade_stops_level
        
        # If broker returns 0, use a default minimum
        if stops_level == 0:
            stops_level = 10
            logging.info(f"Broker trade_stops_level is 0, using default {stops_level} points")
        
        # Ensure trailing distance respects minimum
        if trail_points < stops_level:
            logging.warning(f"Trail points {trail_points} is less than minimum stops level {stops_level}, adjusting to {stops_level}")
            trail_points = stops_level
        
        # Ensure minimum step is reasonable
        if min_step < 1:
            min_step = 1
            logging.warning(f"Minimum step adjusted to 1 point")
            
        logging.info(f"Symbol {symbol}: point={point}, digits={digits}, trade_stops_level={stops_level}, adjusted trail_points={trail_points}")
        
    except Exception as e:
        logging.error(f"Error getting symbol_info: {e}")
        with threads_lock:
            running_threads.pop(key, None)
            thread_flags.pop(key, None)
        return

    # Wait max 3s to find the position
    while time.time() - start_time < 3:
        try:
            positions = mt5.positions_get(symbol=symbol)
            if positions:
                for p in positions:
                    if p.magic == magic:
                        if comment and p.comment != comment:
                            continue
                        pos = p
                        break
            if pos:
                break
        except Exception as e:
            logging.error(f"Error searching position: {e}")
        time.sleep(TRAILING_CHECK_INTERVAL)

    if not pos:
        logging.warning(f"Position not found for trailing {symbol}/{magic}/{comment or 'no comment'}")
        with threads_lock:
            running_threads.pop(key, None)
            thread_flags.pop(key, None)
        return

    logging.info(f"Trailing thread active for position #{pos.ticket} {symbol}/{magic}/{comment or 'no comment'}")
    
    thread_flags[key] = True
    
    # Variables to track best level
    best_price = None
    last_sl_update = 0
    error_count = 0
    max_errors = 10

    while thread_flags.get(key, False):
        try:
            # Check MT5 connection
            if not check_mt5_connection():
                logging.warning("MT5 connection lost in trailing, waiting...")
                time.sleep(5)
                continue

            # Check position still exists
            positions = mt5.positions_get(symbol=symbol)
            pos = None
            if positions:
                for p in positions:
                    if p.magic == magic:
                        if comment and p.comment != comment:
                            continue
                        pos = p
                        break

            if not pos:
                logging.info(f"Position closed {symbol}/{magic}/{comment or 'no comment'} -> stopping trailing")
                break

            tick = mt5.symbol_info_tick(symbol)
            if not tick or tick.bid == 0 or tick.ask == 0:
                time.sleep(TRAILING_CHECK_INTERVAL)
                continue

            # === BUY POSITION ===
            if pos.type == mt5.POSITION_TYPE_BUY:
                current_price = tick.bid
                
                # Update best price
                if best_price is None or current_price > best_price:
                    best_price = current_price
                
                # Calculate new potential SL
                new_sl = best_price - (trail_points * point)
                
                # Verify minimum distance from current price
                min_distance = stops_level * point
                if (current_price - new_sl) < min_distance:
                    new_sl = current_price - min_distance
                
                # Round the new SL early
                new_sl = round(new_sl, digits)
                
                # Get current SL (handle None/0)
                current_sl = pos.sl if pos.sl else 0.0
                current_sl = round(current_sl, digits)  # Normalize for comparison
                
                # Check if we should update
                should_update = False
                
                # Case 1: No SL currently
                if current_sl == 0:
                    should_update = True
                    logging.info(f"BUY: No current SL, will set to {new_sl:.{digits}f}")
                
                # Case 2: SL exists, check if new one is better
                elif new_sl > current_sl:  # For BUY, higher SL is better
                    step_diff = new_sl - current_sl
                    if step_diff >= (min_step * point):
                        should_update = True
                    else:
                        logging.debug(f"BUY: New SL {new_sl:.{digits}f} only {step_diff/point:.1f} points better than current {current_sl:.{digits}f}, min step is {min_step}")
                else:
                    logging.debug(f"BUY: New SL {new_sl:.{digits}f} not better than current {current_sl:.{digits}f}")
                
                # Send update if necessary
                if should_update:
                    if time.time() - last_sl_update > 1:
                        request = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": pos.ticket,
                            "sl": new_sl,
                            "tp": pos.tp if pos.tp else 0
                        }
                        
                        result = mt5.order_send(request)
                        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                            logging.info(f"BUY SL updated {symbol}/{magic}/{comment or 'no comment'}: {current_sl:.{digits}f} -> {new_sl:.{digits}f}")
                            last_sl_update = time.time()
                            error_count = 0
                        elif result:
                            logging.warning(f"BUY trailing error [{result.retcode}]: {result.comment}")
                            error_count += 1

            # === SELL POSITION ===
            elif pos.type == mt5.POSITION_TYPE_SELL:
                current_price = tick.ask
                
                # Update best price
                if best_price is None or current_price < best_price:
                    best_price = current_price
                
                # Calculate new potential SL
                new_sl = best_price + (trail_points * point)
                
                # Verify minimum distance from current price
                min_distance = stops_level * point
                if (new_sl - current_price) < min_distance:
                    new_sl = current_price + min_distance
                
                # Round the new SL early
                new_sl = round(new_sl, digits)
                
                # Get current SL (handle None/0)
                current_sl = pos.sl if pos.sl else 0.0
                current_sl = round(current_sl, digits)  # Normalize for comparison
                
                # Check if we should update
                should_update = False
                
                # Case 1: No SL currently
                if current_sl == 0:
                    should_update = True
                    logging.info(f"SELL: No current SL, will set to {new_sl:.{digits}f}")
                
                # Case 2: SL exists, check if new one is better
                elif new_sl < current_sl:  # For SELL, lower SL is better
                    step_diff = current_sl - new_sl
                    if step_diff >= (min_step * point):
                        should_update = True
                    else:
                        logging.debug(f"SELL: New SL {new_sl:.{digits}f} only {step_diff/point:.1f} points better than current {current_sl:.{digits}f}, min step is {min_step}")
                else:
                    logging.debug(f"SELL: New SL {new_sl:.{digits}f} not better than current {current_sl:.{digits}f}")
                
                # Send update if necessary
                if should_update:
                    if time.time() - last_sl_update > 1:
                        request = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": pos.ticket,
                            "sl": new_sl,
                            "tp": pos.tp if pos.tp else 0
                        }
                        
                        result = mt5.order_send(request)
                        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                            logging.info(f"SELL SL updated {symbol}/{magic}/{comment or 'no comment'}: {current_sl:.{digits}f} -> {new_sl:.{digits}f}")
                            last_sl_update = time.time()
                            error_count = 0
                        elif result:
                            logging.warning(f"SELL trailing error [{result.retcode}]: {result.comment}")
                            error_count += 1

            # Stop if too many errors
            if error_count >= max_errors:
                logging.error(f"Too many errors ({error_count}) in trailing {symbol}/{magic}/{comment or 'no comment'}, stopping")
                break

            time.sleep(TRAILING_CHECK_INTERVAL)
            
        except Exception as e:
            logging.error(f"Error in trailing loop: {e}")
            logging.error(traceback.format_exc())
            error_count += 1
            if error_count >= max_errors:
                break
            time.sleep(1)

    logging.info(f"Trailing thread ended {symbol}/{magic}/{comment or 'no comment'}")
    with threads_lock:
        running_threads.pop(key, None)
        thread_flags.pop(key, None)

@app.post("/trailing/{symbol}/{magic}")
def start_trailing(
    symbol: str, 
    magic: int, 
    comment: str = Query("", description="Comment to filter the position"),
    trail_points: float = Query(..., description="Trailing distance in points", gt=0),
    min_step: float = Query(..., description="Minimum step in points", gt=0)
):
    """Starts trailing stop for a specific position"""
    # Clean up dead threads
    cleanup_dead_threads()
    
    # Validate required parameters
    if trail_points <= 0:
        return response_from_mt5_result({
            "retcode": 10013,
            "status": "error",
            "comment": "trail_points must be > 0"
        })
    
    if min_step <= 0:
        return response_from_mt5_result({
            "retcode": 10013,
            "status": "error",
            "comment": "min_step must be > 0"
        })
    
    key = (symbol, magic, comment)
    
    with threads_lock:
        if key in running_threads and running_threads[key].is_alive():
            return response_from_mt5_result({
                "retcode": 10040,
                "status": "error", 
                "comment": "Trailing already running for this position"
            })
    
    # Check that position exists
    if not check_position_exists(symbol, magic, comment):
        return response_from_mt5_result({
            "retcode": 10016,
            "status": "error",
            "comment": f"No position found for {symbol}/{magic}/{comment or 'no comment'}"
        })
    
    with threads_lock:
        t = threading.Thread(
            target=trailing_loop, 
            args=(symbol, magic, comment, trail_points, min_step), 
            daemon=True
        )
        running_threads[key] = t
        t.start()
    
    return response_from_mt5_result({
        "retcode": 10009,
        "status": "success",
        "comment": f"Trailing started for {symbol}/{magic}/{comment or 'no comment'}"
    })


@app.delete("/trailing/{symbol}/{magic}")
def cancel_trailing(
    symbol: str, 
    magic: int,
    comment: str = Query("", description="Comment to identify the trailing")
):
    """Cancels the running trailing stop"""
    key = (symbol, magic, comment)
    
    with threads_lock:
        if key not in running_threads:
            return response_from_mt5_result({
                "retcode": 10016,
                "status": "warning",
                "comment": "No active trailing for this position"
            })
        thread_flags[key] = False
    
    return response_from_mt5_result({
        "retcode": 10009,
        "status": "success",
        "comment": f"Trailing cancelled for {symbol}/{magic}/{comment or 'no comment'}"
    })


# Enhanced webhook main endpoint - SEE PART 3 FOR THE COMPLETE FUNCTION
# Part 3 - Webhook handler continuation
@app.post("/webhooktv", summary="Receive TradingView signals (Pine Connector compatible)")
def tradingview_webhook(
    webhook_data: TradingViewWebhook,
    ratio: Optional[float] = Query(None, description="Ratio override (0.0 → 1.0)", ge=0.0),
    magic: Optional[int]   = Query(None, description="Magic number override", ge=0),
    symbol: Optional[str] = Query(None, description="Broker symbol override (URL-encode '+' as %2B)", min_length=1, max_length=64, regex=r"^[A-Za-z0-9._\-\+]+$"),
    deviation: Optional[int] = Query(None, description="Deviation override", ge=0),
    check_duplicate: bool  = Query(True, description="Check duplicate orders")

):
    """
    Receives TradingView alerts and executes actions on MT5 (Pine Connector compatible)
    """
    
    try:
        # COMPLETE LOG OF RECEIVED DATA
        logging.info("="*60)
        logging.info("[WEBHOOK] NEW REQUEST RECEIVED")
        logging.info("="*60)
        
        # Display all received data
        webhook_dict = webhook_data.dict()
        logging.info(f"[WEBHOOK] Complete POST data received:")
        logging.info(json.dumps(webhook_dict, indent=2))
        
        # Display GET parameters
        logging.info(f"[WEBHOOK] GET parameters:")
        logging.info(f"  - ratio: {ratio}")
        logging.info(f"  - magic: {magic}")
        logging.info(f"  - check_duplicate: {check_duplicate}")
        
        # Check MT5 connection
        if not ensure_mt5_connection():
            error_msg = "MT5 connection lost, please retry"
            logging.error(f"[WEBHOOK ERROR] {error_msg}")
            return JSONResponse(
                status_code=503,
                content={
                    "retcode": -1,
                    "status": "MT5_CONNECTION_ERROR",
                    "comment": error_msg,
                    "received_data": webhook_dict
                }
            )
        
        # Clean up dead threads periodically
        cleanup_dead_threads()
        
        # Normalize
        action = webhook_data.action.lower().strip()
        symbol = symbol if symbol is not None else webhook_data.symbol
        symbol = symbol.upper()
        deviation = deviation if deviation is not None else webhook_data.deviation
        
        logging.info(f"[WEBHOOK] Normalized action: '{action}' on symbol '{symbol}'")
        
        # Override du magic number if specified
        effective_magic = magic if magic is not None else webhook_data.magic
        if magic is not None:
            logging.info(f"[WEBHOOK] Magic override: {webhook_data.magic} -> {effective_magic}")
        
        # Validate trailing parameters
        if webhook_data.trail_points is not None and webhook_data.trail_points <= 0:
            error_msg = f"Invalid trail_points ({webhook_data.trail_points}), must be > 0"
            logging.error(f"[WEBHOOK ERROR] {error_msg}")
            return JSONResponse(
                status_code=400,
                content={
                    "retcode": 10013,
                    "status": "INVALID_TRAIL_POINTS",
                    "comment": error_msg,
                    "received_data": webhook_dict
                }
            )
        
        if webhook_data.trail_step is not None and webhook_data.trail_step <= 0:
            error_msg = f"Invalid trail_step ({webhook_data.trail_step}), must be > 0"
            logging.error(f"[WEBHOOK ERROR] {error_msg}")
            return JSONResponse(
                status_code=400,
                content={
                    "retcode": 10013,
                    "status": "INVALID_TRAIL_STEP",
                    "comment": error_msg,
                    "received_data": webhook_dict
                }
            )
        
        # Check that symbol exists in MT5
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            # Try without broker prefix if present
            if ":" in symbol:
                symbol = symbol.split(":")[-1]
                symbol_info = mt5.symbol_info(symbol)
                if symbol_info is None:
                    error_msg = f"Symbol {symbol} not found in MT5"
                    logging.error(f"[WEBHOOK ERROR] {error_msg}")
                    return JSONResponse(
                        status_code=404,
                        content={
                            "retcode": 10014,
                            "status": "SYMBOL_NOT_FOUND",
                            "comment": error_msg,
                            "received_data": webhook_dict
                        }
                    )
        
        logging.info(f"[WEBHOOK] Symbol {symbol} found in MT5")
        
        # Activate symbol if not visible
        if symbol_info is not None and not symbol_info.visible:
            if not mt5.symbol_select(symbol, True):
                error_msg = f"Cannot activate symbol {symbol}"
                logging.error(f"[WEBHOOK ERROR] {error_msg}")
                return JSONResponse(
                    status_code=500,
                    content={
                        "retcode": 10014,
                        "status": "SYMBOL_ACTIVATION_FAILED",
                        "comment": error_msg,
                        "received_data": webhook_dict
                    }
                )
            symbol_info = mt5.symbol_info(symbol)
        
        # Calculate and normalize lot size
        lot_size = webhook_data.lots
        
        if ratio:
            original_lot = lot_size
            lot_size = lot_size * ratio
            logging.info(f"[WEBHOOK] Lot adjusted: {original_lot} * {ratio} = {lot_size}")
        
        # Normalize according to symbol constraints
        if symbol_info:
            lot_step = symbol_info.volume_step
            lot_min = symbol_info.volume_min
            
            if lot_step and lot_min:
                steps_from_min = round((lot_size - lot_min) / lot_step)
                steps_from_min = max(0, steps_from_min)
                lot_size = lot_min + (steps_from_min * lot_step)
                
                # Round to step precision
                step_str = str(lot_step)
                if '.' in step_str:
                    decimals = len(step_str.split('.')[1])
                    lot_size = round(lot_size, decimals)
            
            # Check limits
            if lot_size < symbol_info.volume_min:
                logging.warning(f"[WEBHOOK] Lot increased to {symbol_info.volume_min} (minimum)")
                lot_size = symbol_info.volume_min
            
            if symbol_info.volume_max and lot_size > symbol_info.volume_max:
                logging.warning(f"[WEBHOOK] Lot reduced to {symbol_info.volume_max} (maximum)")
                lot_size = symbol_info.volume_max
        
        # Apply configured limits
        if webhook_data.max_lot and lot_size > webhook_data.max_lot:
            logging.warning(f"[WEBHOOK] Lot reduced to {webhook_data.max_lot} (signal limit)")
            lot_size = webhook_data.max_lot
        
        if lot_size > MAX_LOT:
            logging.warning(f"[WEBHOOK] Lot reduced to {MAX_LOT} (server limit)")
            lot_size = MAX_LOT
        
        logging.info(f"[WEBHOOK] Final lot size: {lot_size}")
        
        # =====================================
        # CLOSING OPPOSITE POSITIONS
        # =====================================
        if webhook_data.closeoppositesignal and action in ["buy", "sell", "buylimit", "selllimit", "buystop", "sellstop"]:
            positions = mt5.positions_get(symbol=symbol)
            if positions:
                for pos in positions:
                    if pos.magic != effective_magic:
                        continue
                    # Filter by comment if specified
                    if webhook_data.comment and pos.comment != webhook_data.comment:
                        continue

                    # Close opposite positions
                    if action in ["buy", "buylimit", "buystop"] and pos.type == mt5.ORDER_TYPE_SELL:
                        # Stop trailing if active
                        key = (symbol, effective_magic, pos.comment or "")
                        with threads_lock:
                            if key in thread_flags:
                                thread_flags[key] = False
                        
                        close_result = close_position_by_id(pos.ticket, effective_magic, deviation)
                        logging.info(f"Opposite SHORT position closed: #{pos.ticket}")
                    elif action in ["sell", "selllimit", "sellstop"] and pos.type == mt5.ORDER_TYPE_BUY:
                        # Stop trailing if active
                        key = (symbol, effective_magic, pos.comment or "")
                        with threads_lock:
                            if key in thread_flags:
                                thread_flags[key] = False
                        
                        close_result = close_position_by_id(pos.ticket, effective_magic, deviation)
                        logging.info(f"Opposite LONG position closed: #{pos.ticket}")
        
        # =====================================
        # PROCESSING ACTIONS
        # =====================================
        
        logging.info(f"[WEBHOOK] Processing action: {action}")
        
        # --- MARKET ORDERS ---
        if action in ["buy", "sell"]:
            
            # CHECK IF POSITION ALREADY EXISTS
            if check_duplicate and check_position_exists(symbol, effective_magic, webhook_data.comment):
                logging.warning(f"WARNING: {action.upper()} position already exists for {symbol}/{effective_magic}/{webhook_data.comment or 'no comment'}")
                return response_from_mt5_result({
                    "retcode": 10016,  # TRADE_RETCODE_INVALID
                    "comment": f"Position {action} already exists for {symbol}/{effective_magic}/{webhook_data.comment or 'no comment'}"
                })
            
            # Calculate SL/TP
            sl_price = webhook_data.sl
            tp_price = webhook_data.tp
            
            if webhook_data.slpips or webhook_data.tppips:
                point = symbol_info.point
                
                if webhook_data.price:
                    base_price = webhook_data.price
                else:
                    tick = mt5.symbol_info_tick(symbol)
                    if not tick:
                        raise Exception(f"Cannot get tick for {symbol}")
                    base_price = tick.ask if action == "buy" else tick.bid
                
                if webhook_data.slpips and sl_price is None:
                    if action == "buy":
                        sl_price = base_price - (webhook_data.slpips * point)
                    else:
                        sl_price = base_price + (webhook_data.slpips * point)
                
                if webhook_data.tppips and tp_price is None:
                    if action == "buy":
                        tp_price = base_price + (webhook_data.tppips * point)
                    else:
                        tp_price = base_price - (webhook_data.tppips * point)
            
            # Create order
            order_request = OrderRequest(
                symbol=symbol,
                side=action,
                lot=lot_size,
                sl=sl_price,
                tp=tp_price,
                magic=effective_magic,
                comment=webhook_data.comment or "",
                deviation=deviation,
                price=webhook_data.price
            )
            
            result = trade_new(order_request)
            
            # If trailing requested and position created successfully
            if webhook_data.trail_points and isinstance(result, dict) and result.get("retcode") == mt5.TRADE_RETCODE_DONE:
                if webhook_data.trail_points <= 0:
                    logging.error(f"Invalid trail_points ({webhook_data.trail_points}), trailing not started")
                elif not webhook_data.trail_step or webhook_data.trail_step <= 0:
                    logging.error(f"Missing or invalid trail_step ({webhook_data.trail_step}), trailing not started")
                else:
                    # Start trailing automatically
                    key = (symbol, effective_magic, webhook_data.comment or "")
                    with threads_lock:
                        if key not in running_threads or not running_threads[key].is_alive():
                            t = threading.Thread(
                                target=trailing_loop,
                                args=(symbol, effective_magic, webhook_data.comment or "", 
                                      webhook_data.trail_points, webhook_data.trail_step),
                                daemon=True
                            )
                            running_threads[key] = t
                            t.start()
                            logging.info(f"Trailing auto-started for new position")
            
            return result
        
        # --- LIMIT AND STOP ORDERS ---
        elif action in ["buylimit", "selllimit", "buystop", "sellstop"]:
            
            if not webhook_data.price:
                return response_from_mt5_result({
                    "retcode": 10013,
                    "comment": f"Price required for action {action}"
                })
            
            # Determine MT5 order type
            order_type_map = {
                "buylimit": mt5.ORDER_TYPE_BUY_LIMIT,
                "selllimit": mt5.ORDER_TYPE_SELL_LIMIT,
                "buystop": mt5.ORDER_TYPE_BUY_STOP,
                "sellstop": mt5.ORDER_TYPE_SELL_STOP
            }
            
            order_type = order_type_map.get(action)
            
            # CHECK IF PENDING ORDER ALREADY EXISTS
            if check_duplicate and check_pending_order_exists(symbol, effective_magic, webhook_data.comment, order_type):
                logging.warning(f"[WARNING] {action.upper()} order already exists for {symbol}/{effective_magic}/{webhook_data.comment}")
                return response_from_mt5_result({
                    "retcode": 10016,
                    "comment": f"Pending order {action} already exists for {symbol}/{effective_magic}/{webhook_data.comment or 'no comment'}"
                })
            
            # Calculate SL/TP
            sl_price = webhook_data.sl
            tp_price = webhook_data.tp
            
            if webhook_data.slpips or webhook_data.tppips:
                point = symbol_info.point
                base_price = webhook_data.price
                
                if webhook_data.slpips and sl_price is None:
                    if action in ["buylimit", "buystop"]:
                        sl_price = base_price - (webhook_data.slpips * point)
                    else:
                        sl_price = base_price + (webhook_data.slpips * point)
                
                if webhook_data.tppips and tp_price is None:
                    if action in ["buylimit", "buystop"]:
                        tp_price = base_price + (webhook_data.tppips * point)
                    else:
                        tp_price = base_price - (webhook_data.tppips * point)
            
            # Prepare order
            filling_mode = get_safe_filling_mode(symbol_info)
            digits = symbol_info.digits
            
            pending_request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": symbol,
                "volume": lot_size,
                "type": order_type,
                "price": _round_price(webhook_data.price, digits),
                "magic": effective_magic,
                "comment": webhook_data.comment or "",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode
            }
            
            if sl_price and sl_price > 0:
                pending_request["sl"] = _round_price(sl_price, digits)
            
            if tp_price and tp_price > 0:
                pending_request["tp"] = _round_price(tp_price, digits)
            
            result = mt5.order_send(pending_request)
            
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                logging.info(f"Order {action} placed successfully: ticket={result.order}")
            else:
                logging.error(f"Failed to place {action} order: {result}")
            
            return response_from_mt5_result(result)
        
        # --- CLOSURES ---
        elif action in ["closelong", "closeshort", "closeall"]:
            
            positions_closed = []
            positions = mt5.positions_get(symbol=symbol)
            
            if positions:
                for pos in positions:
                    if pos.magic != effective_magic:
                        continue
                    # Filter by comment if specified
                    if webhook_data.comment and pos.comment != webhook_data.comment:
                        continue
                    
                    should_close = False
                    
                    if action == "closeall":
                        should_close = True
                    elif action == "closelong" and pos.type == mt5.ORDER_TYPE_BUY:
                        should_close = True
                    elif action == "closeshort" and pos.type == mt5.ORDER_TYPE_SELL:
                        should_close = True
                    
                    if should_close:
                        # Stop trailing if active
                        key = (symbol, effective_magic, pos.comment or "")
                        with threads_lock:
                            if key in thread_flags:
                                thread_flags[key] = False
                                logging.info(f"Trailing stopped for position #{pos.ticket}")
                        
                        result = close_position_by_id(pos.ticket, effective_magic, deviation)
                        positions_closed.append({
                            "ticket": pos.ticket,
                            "volume": pos.volume,
                            "type": "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL",
                            "symbol": pos.symbol,
                            "profit": pos.profit,
                            "comment": pos.comment or ""
                        })
                        logging.info(f"Position closed: #{pos.ticket}")
            
            return response_from_mt5_result({
                "action": action,
                "symbol": symbol,
                "closed_count": len(positions_closed),
                "positions": positions_closed
            })
        
        # --- CANCEL PENDING ORDERS ---
        elif action == "closepending":
            
            orders_cancelled = []
            orders = mt5.orders_get(symbol=symbol)
            
            if orders:
                for order in orders:
                    if order.magic != effective_magic:
                        continue
                    # Filter by comment if specified
                    if webhook_data.comment and order.comment != webhook_data.comment:
                        continue
                    
                    cancel_request = {
                        "action": mt5.TRADE_ACTION_REMOVE,
                        "order": order.ticket
                    }
                    
                    result = mt5.order_send(cancel_request)
                    
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        orders_cancelled.append({
                            "ticket": order.ticket,
                            "type": order.type,
                            "volume": order.volume,
                            "price": order.price_open,
                            "symbol": order.symbol,
                            "comment": order.comment or ""
                        })
                        logging.info(f"Order cancelled: #{order.ticket}")
            
            return response_from_mt5_result({
                "action": "closepending",
                "symbol": symbol,
                "cancelled_count": len(orders_cancelled),
                "orders": orders_cancelled
            })
        
        # --- MODIFICATION ---
        elif action == "modify":
            
            positions_modified = []
            positions = mt5.positions_get(symbol=symbol)
            
            if positions:
                for pos in positions:
                    if pos.magic != effective_magic:
                        continue
                    # Filter by comment if specified
                    if webhook_data.comment and pos.comment != webhook_data.comment:
                        continue
                    
                    modify_request = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "position": pos.ticket,
                        "symbol": symbol
                    }
                    
                    # Calculate SL/TP
                    if webhook_data.sl is not None:
                        modify_request["sl"] = webhook_data.sl
                    elif webhook_data.slpips is not None:
                        point = symbol_info.point
                        if pos.type == mt5.ORDER_TYPE_BUY:
                            modify_request["sl"] = pos.price_open - (webhook_data.slpips * point)
                        else:
                            modify_request["sl"] = pos.price_open + (webhook_data.slpips * point)
                    else:
                        modify_request["sl"] = pos.sl if pos.sl else 0
                    
                    if webhook_data.tp is not None:
                        modify_request["tp"] = webhook_data.tp
                    elif webhook_data.tppips is not None:
                        point = symbol_info.point
                        if pos.type == mt5.ORDER_TYPE_BUY:
                            modify_request["tp"] = pos.price_open + (webhook_data.tppips * point)
                        else:
                            modify_request["tp"] = pos.price_open - (webhook_data.tppips * point)
                    else:
                        modify_request["tp"] = pos.tp if pos.tp else 0
                    
                    result = mt5.order_send(modify_request)
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        positions_modified.append({
                            "ticket": pos.ticket,
                            "new_sl": modify_request.get("sl"),
                            "new_tp": modify_request.get("tp"),
                            "comment": pos.comment or ""
                        })
                        logging.info(f"Position modified: #{pos.ticket}")
            
            return response_from_mt5_result({
                "action": "modify",
                "symbol": symbol,
                "modified_count": len(positions_modified),
                "positions": positions_modified
            })
        
        # --- EXIT WITH TRAILING (UPDATED) ---
        elif action == "exit":
            logging.info(f"[WEBHOOK EXIT] Processing exit for {symbol}/{effective_magic}/{webhook_data.comment}")
            
            # Check that position exists
            positions = mt5.positions_get(symbol=symbol)
            position = None
            
            for pos in positions if positions else []:
                if pos.magic == effective_magic:
                    if webhook_data.comment and pos.comment != webhook_data.comment:
                        continue
                    position = pos
                    logging.info(f"[WEBHOOK EXIT] Position found: #{pos.ticket}")
                    logging.info(f"[WEBHOOK EXIT] Real entry price: {pos.price_open}")
                    break
            
            if not position:
                logging.warning(f"[WEBHOOK EXIT] Position not found yet for {symbol}/{effective_magic}/{webhook_data.comment}")
            
            # 1. MODIFY SL/TP IF PROVIDED AND POSITION EXISTS
            if position and (webhook_data.sl is not None or webhook_data.tp is not None):
                # Build modification request
                modify_request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": position.ticket,
                }
                
                # Handle SL: if null, keep existing; if provided (including 0), use it
                if webhook_data.sl is not None:
                    modify_request["sl"] = webhook_data.sl
                    logging.info(f"[WEBHOOK EXIT] Setting SL to: {webhook_data.sl}")
                else:
                    modify_request["sl"] = position.sl if position.sl else 0
                    logging.info(f"[WEBHOOK EXIT] Keeping existing SL: {position.sl}")
                
                # Handle TP: if null, keep existing; if provided (including 0), use it  
                if webhook_data.tp is not None:
                    modify_request["tp"] = webhook_data.tp
                    logging.info(f"[WEBHOOK EXIT] Setting TP to: {webhook_data.tp}")
                else:
                    modify_request["tp"] = position.tp if position.tp else 0
                    logging.info(f"[WEBHOOK EXIT] Keeping existing TP: {position.tp}")
                
                logging.info(f"[WEBHOOK EXIT] Modifying position #{position.ticket}: SL={modify_request['sl']}, TP={modify_request['tp']}")
                result = mt5.order_send(modify_request)
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    logging.info(f"[WEBHOOK EXIT] SL/TP modified successfully")
                else:
                    logging.error(f"[WEBHOOK EXIT] Failed to modify SL/TP: {result}")
            
            # 2. SET UP TRAILING WITH ADJUSTED TRIGGER
            if webhook_data.trail_points and webhook_data.trail_points > 0:
                key = (symbol, effective_magic, webhook_data.comment or "")
                
                if position:
                    # Position exists - we can calculate the real trigger
                    is_long = position.type == mt5.ORDER_TYPE_BUY
                    real_entry = position.price_open
                    
                    logging.info(f"[WEBHOOK EXIT] Position type: {'LONG' if is_long else 'SHORT'}")
                    logging.info(f"[WEBHOOK EXIT] Real entry price: {real_entry}")
                    
                    # If trigger_price provided, adjust it based on entry delta
                    if webhook_data.trigger_price:
                        # Calculate the theoretical entry price (if provided)
                        theoretical_entry = webhook_data.price if webhook_data.price else real_entry
                        
                        # Calculate the delta between real and theoretical entry
                        entry_delta = real_entry - theoretical_entry
                        
                        # Adjust the trigger price by the same delta
                        adjusted_trigger = webhook_data.trigger_price + entry_delta
                        
                        logging.info(f"[WEBHOOK EXIT] Theoretical entry: {theoretical_entry}, Real entry: {real_entry}")
                        logging.info(f"[WEBHOOK EXIT] Entry delta: {entry_delta:.5f}")
                        logging.info(f"[WEBHOOK EXIT] Original trigger: {webhook_data.trigger_price}, Adjusted trigger: {adjusted_trigger}")
                        
                        # Get current price and check if trigger already reached
                        tick = mt5.symbol_info_tick(symbol)
                        trigger_already_reached = False
                        
                        if tick:
                            current_price = tick.bid if is_long else tick.ask
                            
                            # Check if trigger already reached
                            if is_long:
                                trigger_already_reached = current_price >= adjusted_trigger
                            else:
                                trigger_already_reached = current_price <= adjusted_trigger
                            
                            logging.info(f"[WEBHOOK EXIT] Current price: {current_price}, Trigger already reached: {trigger_already_reached}")
                        
                        if trigger_already_reached:
                            # Trigger already reached - start trailing immediately
                            logging.info(f"[WEBHOOK EXIT] Trigger already reached - starting trail immediately")
                        else:
                            # Trigger not reached yet - set up monitoring
                            trailing_triggers[key] = {
                                "trigger_price": adjusted_trigger,
                                "trail_points": webhook_data.trail_points,
                                "trail_step": webhook_data.trail_step if webhook_data.trail_step else 1,
                                "is_long": is_long
                            }
                            logging.info(f"[WEBHOOK EXIT] Trailing trigger set at {adjusted_trigger} (adjusted from {webhook_data.trigger_price}) with {webhook_data.trail_points} points")
                            
                            return response_from_mt5_result({
                                "retcode": 10009,
                                "comment": f"Exit trigger configured at {adjusted_trigger} (adjusted for real entry)"
                            })
                    
                    # No trigger price OR trigger already reached - start trailing immediately
                    with threads_lock:
                        if key not in running_threads or not running_threads[key].is_alive():
                            t = threading.Thread(
                                target=trailing_loop,
                                args=(symbol, effective_magic, webhook_data.comment or "", 
                                    webhook_data.trail_points, webhook_data.trail_step if webhook_data.trail_step else 1),
                                daemon=True
                            )
                            running_threads[key] = t
                            thread_flags[key] = True
                            t.start()
                            logging.info(f"[WEBHOOK EXIT] Trailing started immediately with {webhook_data.trail_points} points")
                            
                            return response_from_mt5_result({
                                "retcode": 10009,
                                "comment": "Trailing started immediately"
                            })
                else:
                    # No position found yet - set up trigger with original (unadjusted) values
                    if webhook_data.trigger_price:
                        # We don't know if it's long or short yet, so we'll store both the trigger and detect direction later
                        trailing_triggers[key] = {
                            "trigger_price": webhook_data.trigger_price,
                            "trail_points": webhook_data.trail_points,
                            "trail_step": webhook_data.trail_step if webhook_data.trail_step else 1,
                            "is_long": None  # Will be determined when position is found
                        }
                        logging.info(f"[WEBHOOK EXIT] Position not found yet. Trailing trigger stored at {webhook_data.trigger_price} with {webhook_data.trail_points} points")
                        
                        return response_from_mt5_result({
                            "retcode": 10009,
                            "comment": f"Exit trigger configured at {webhook_data.trigger_price} (will adjust when position opens)"
                        })
                    else:
                        # No trigger and no position - can't start trailing yet
                        logging.warning(f"[WEBHOOK EXIT] No position found and no trigger price provided for {symbol}, magic {effective_magic}")
                        return response_from_mt5_result({
                            "retcode": 10004,
                            "comment": "Cannot start trailing: no position found and no trigger price"
                        })
                        
        # --- CANCEL EXIT/TRAILING ---
        elif action == "cancel_exit" or action == "cancel_trailing":  # Support both names for compatibility
            key = (symbol, effective_magic, webhook_data.comment or "")
            cancelled = False
            
            # Cancel pending trigger
            if key in trailing_triggers:
                trailing_triggers.pop(key)
                cancelled = True
                logging.info(f"Trailing trigger cancelled for {symbol}/{effective_magic}/{webhook_data.comment or 'no comment'}")
            
            # Cancel active trailing
            with threads_lock:
                if key in thread_flags:
                    thread_flags[key] = False
                    cancelled = True
                    logging.info(f"Active trailing stopped for {symbol}/{effective_magic}/{webhook_data.comment or 'no comment'}")
            
            if cancelled:
                return response_from_mt5_result({
                    "retcode": 10009,
                    "comment": f"Exit cancelled for {symbol}/{effective_magic}/{webhook_data.comment or 'no comment'}"
                })
            else:
                return response_from_mt5_result({
                    "retcode": 10016,
                    "comment": "No exit to cancel"
                })
        
        # --- UNRECOGNIZED ACTION ---
        else:
            return response_from_mt5_result({
                "retcode": 10030,
                "comment": f"Unrecognized action: {action}. Valid actions: buy, sell, buylimit, selllimit, buystop, sellstop, closeall, closelong, closeshort, closepending, modify, exit, cancel_exit"
            })
    
    except Exception as e:
        logging.error(f"[ERROR] Webhook error: {str(e)}")
        logging.error(traceback.format_exc())
        return response_from_exception(e)



# uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4 --reload --reload-include *.yml"


if __name__ == "__main__":
    uvicorn.run("api:app", port=8000, host="0.0.0.0", reload=False, log_level="debug")