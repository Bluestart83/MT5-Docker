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

# Ajoute cette variable en haut de ton fichier avec les autres configs
MAX_LOT = float(os.environ.get("MAX_LOT", "9999.0"))  # Taille max absolue du serveur
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

# Définir les constantes manquantes dans votre code
SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2
SYMBOL_FILLING_RETURN = 4
FORCE_ACCOUNT_SWITCH = os.environ.get("FORCE_ACCOUNT_SWITCH", "false").lower() == "true"  # Par défaut: true

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

# Fonction pour vérifier si MT5 est connecté
def check_mt5_connection():
    """Vérifie rapidement si MT5 est connecté"""
    try:
        account_info = mt5.account_info()
        return account_info is not None
    except:
        return False

# Fonction d'initialisation/reconnexion
def initialize_mt5():
    """Initialise ou reconnecte MT5"""
    max_retries = 10
    
    for attempt in range(max_retries):
        logging.info(f"API - Starting mt5 (attempt {attempt + 1}/{max_retries})")
        
        # D'abord vérifier si déjà connecté
        if check_mt5_connection():
            logging.info(f"API - MT5 already connected")
            return True
        
        # Si plusieurs échecs, tenter de tuer le processus MT5
        if attempt > 2:
            try:
                logging.warning("API - Attempting to kill stuck MT5 process")
                subprocess.run(["pkill", "-f", "terminal64.exe"])
                time.sleep(5)
            except Exception as e:
                logging.warning(f"API - Could not kill MT5 process: {e}")
        
        # Sinon, initialiser
        success = mt5.initialize(
            path,
            login=int(os.environ["ACCOUNT"]),
            password=os.environ["PASSWORD"],
            server=os.environ["SERVER"],
            timeout=120000  # 2 minute pour le login
        )
        
        if not success:
            logging.warning(f"API - Cannot init mt5: {mt5.last_error()}")
            time.sleep(30 * (attempt + 1))
            continue
        
        # Vérifier que ça marche vraiment
        time.sleep(5)  # Attendre un peu que la connexion se stabilise
        if check_mt5_connection():
            account_info = mt5.account_info()
            logging.info(f"API - MT5 connected successfully!")
            logging.info(f"Account: {account_info.login}, Balance: {account_info.balance}")
            return True
        else:
            logging.warning("API - MT5 initialized but not connected")
            time.sleep(10)
    
    return False

# Initialisation au démarrage
if not initialize_mt5():
    logging.error("API - Failed to initialize MT5 after all attempts")
    logging.error("API - EXITING - MT5 will restart the script")
    exit(1)  # Terminer le script pour que MT5 le relance

# Fonction pour s'assurer que MT5 est connecté avant chaque opération
def ensure_mt5_connection():
    """S'assure que MT5 est connecté, reconnecte si nécessaire"""
    if not check_mt5_connection():
        logging.warning("API - MT5 connection lost, attempting to reconnect...")
        return initialize_mt5()
    return True

# Thread de monitoring pour maintenir la connexion
def mt5_connection_monitor():
    """Vérifie périodiquement la connexion et reconnecte si nécessaire"""
    while True:
        try:
            time.sleep(30)  # Vérifier toutes les 30 secondes
            if not check_mt5_connection():
                logging.warning("Monitor - MT5 connection lost, reconnecting...")
                initialize_mt5()  # Juste essayer de reconnecter, pas de kill
        except Exception as e:
            logging.error(f"Monitor - Error: {e}")
            time.sleep(10)

# Démarrer le thread de monitoring
monitor_thread = threading.Thread(target=mt5_connection_monitor, daemon=True)
monitor_thread.start()
logging.info("API - Connection monitor started")
logger.info("🚀 MT5 API ready to receive requests")


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

# ========================================
# MIDDLEWARE GLOBAL - API Key OPTIONNELLE
# ========================================
@app.middleware("http")
async def verify_api_key_middleware(request: Request, call_next):
    #logging.debug(f"API - verify_api_key_middleware")
    # Routes toujours publiques
    PUBLIC_ROUTES = ["/health", "/", "/docs", "/openapi.json", "/redoc"]
    
    # IMPORTANT: Laisser passer les requêtes OPTIONS (CORS preflight)
    if request.method == "OPTIONS":
        return await call_next(request)
    
    # Si c'est une route publique, on laisse passer
    if request.url.path in PUBLIC_ROUTES:
        return await call_next(request)
    
    # Vérifier si une API_KEY est définie dans l'environnement
    expected_api_key = os.environ.get("API_KEY")
    
    # Si pas d'API_KEY définie = mode ouvert (pas de sécurité)
    if not expected_api_key:
        return await call_next(request)
    
    # Si API_KEY définie, on doit la vérifier
    api_key = None
    
    # 1. Chercher dans l'URL (query params)
    if "api_key" in request.query_params:
        api_key = request.query_params["api_key"]
    
    # 2. Ou dans les headers
    elif "X-API-Key" in request.headers:
        api_key = request.headers["X-API-Key"]
    
    # Vérifier l'API key
    if not api_key or api_key != expected_api_key:
        return JSONResponse(
            status_code=401,
            content={
                "detail": "Invalid or missing API Key",
                "hint": "Provide api_key in URL (?api_key=xxx) or X-API-Key header"
            }
        )
    
    # API Key valide, continuer
    response = await call_next(request)
    return response

#========================================
# LOG AU DÉMARRAGE
#========================================
@app.on_event("startup")
async def startup_event():
    import logging
    
    if os.environ.get("API_KEY"):
        logging.warning("🔒 API Key protection ENABLED")
        logging.warning(f"API Key required: {os.environ.get('API_KEY')[:8]}...")
    else:
        logging.warning("⚠️  API Key protection DISABLED - Running in OPEN mode")
        logging.warning("⚠️  Anyone can access this API! Set API_KEY in .env for security")


@app.get("/health")
def health():
    try:
        account = mt5.account_info()
        if account is None:
            code, message = mt5.last_error()
            raise Exception(f"MT5 non initialisé ou session invalide : [{code}] {message}")

        return response_from_mt5_result({"login": "OK"})
        
    except Exception as e:
        return response_from_exception(e)

@app.get("/health-private")
def healthPrivate():
    try:
        account = mt5.account_info()
        if account is None:
            code, message = mt5.last_error()
            raise Exception(f"MT5 non initialisé ou session invalide : [{code}] {message}")

        return response_from_mt5_result({"login": account.login})
        
    except Exception as e:
        return response_from_exception(e)

@app.get("/")
def health():
    try:
        account = mt5.account_info()
        if account is None:
            code, message = mt5.last_error()
            raise Exception(f"MT5 non initialisé ou session invalide : [{code}] {message}")

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
    logging.debug("trade_new")
    side = request.side.lower()
    if side not in ("buy", "sell"):
        raise HTTPException(status_code=400, detail="Le champ `side` doit être 'buy' ou 'sell'.")

    return _trade_buy(request, mt5.ORDER_TYPE_BUY if request.side =="buy" else mt5.ORDER_TYPE_SELL)

def _trade_buy(request: OrderRequest, side) -> Dict:
    #close_all(request.symbol, request.magic, request.deviation)
    try:
         # Choisir un mode valide
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
    
# Définir les constantes manquantes dans votre code
SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2
SYMBOL_FILLING_RETURN = 4

def get_safe_filling_mode(symbol_info) -> int:
    """Détecte automatiquement le meilleur mode de remplissage"""
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
    
    # Ordre de préférence selon le type d'exécution
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
    
    # Chercher le premier mode supporté
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
        raise Exception(f"Erreur MT5 lors de positions_get(): [{code}] {msg}")

    cur_tick = mt5.symbol_info_tick(symbol)
    if not cur_tick or cur_tick.ask == 0 or cur_tick.bid == 0:
        raise Exception(f"Tick invalide pour {symbol} — ask/bid indisponible")

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
    
    # Active s’il n’est pas visible
    if not info.visible:
        print(f"Activation du symbole {symbol}...")
        if not mt5.symbol_select(symbol, True):
            raise HTTPException(status_code=500, detail=f"Impossible d’activer {symbol}")
        info = mt5.symbol_info(symbol)
        if info is None:
            raise HTTPException(status_code=404, detail=f"Symbole introuvable après activation : {symbol}")

    # attend que les prix arrivent
    for _ in range(5):
        # Si prix dispo OU marché fermé (donc inutile d'attendre)
        if info.ask > 0 or info.bid > 0 or info.trade_mode == 0:
            break
        time.sleep(0.1)
        info = mt5.symbol_info(symbol)

    #if info.ask == 0 and info.bid == 0:
    #    #trade_mode == 0 => marker closed
    #    raise HTTPException(status_code=503, detail=f"No prices available for {symbol} => Market closed?")

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
        filling_mode = get_safe_filling_mode(symbol_info)
        
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
            "type_filling": filling_mode
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



# =====================================
# Webhook Trading view - Configuration
# =====================================
running_threads = {}
thread_flags = {}  # clé = (symbol, magic, comment) → bool
threads_lock = threading.Lock()  # Pour la thread-safety
TRAILING_CHECK_INTERVAL = 0.1  # Intervalle de vérification en secondes

def cleanup_dead_threads():
    """Nettoie les threads terminés"""
    with threads_lock:
        dead_keys = [k for k, t in running_threads.items() if not t.is_alive()]
        for k in dead_keys:
            running_threads.pop(k, None)
            thread_flags.pop(k, None)
        if dead_keys:
            logging.info(f"🧹 Nettoyage de {len(dead_keys)} threads terminés")

def check_position_exists(symbol: str, magic: int, comment: str = None) -> bool:
    """Vérifie si une position existe déjà avec les critères donnés"""
    try:
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return False
        
        for pos in positions:
            if pos.magic != magic:
                continue
            # Si un comment est spécifié, il doit correspondre
            if comment is not None and comment != "" and pos.comment != comment:
                continue
            return True
        return False
    except Exception as e:
        logging.error(f"Erreur check_position_exists: {e}")
        return False

def check_pending_order_exists(symbol: str, magic: int, comment: str = None, order_type: int = None) -> bool:
    """Vérifie si un ordre pending existe déjà avec les critères donnés"""
    try:
        orders = mt5.orders_get(symbol=symbol)
        if not orders:
            return False
        
        for order in orders:
            if order.magic != magic:
                continue
            # Si un comment est spécifié, il doit correspondre
            if comment is not None and comment != "" and order.comment != comment:
                continue
            # Si un type d'ordre est spécifié, il doit correspondre
            if order_type is not None and order.type != order_type:
                continue
            return True
        return False
    except Exception as e:
        logging.error(f"Erreur check_pending_order_exists: {e}")
        return False

def trailing_loop(symbol: str, magic: int, comment: str, trail_points: float = 50.0, min_step: float = 10.0):
    """Boucle de trailing stop améliorée avec gestion par comment"""
    start_time = time.time()
    pos = None
    key = (symbol, magic, comment or "")
    
    logging.info(f"Démarrage du trailing pour {symbol}/{magic}/{comment or 'no comment'} - Points: {trail_points}, Step: {min_step}")

    # Récupérer les infos du symbole une fois
    try:
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            logging.error(f"Symbole {symbol} introuvable")
            with threads_lock:
                running_threads.pop(key, None)
                thread_flags.pop(key, None)
            return
        
        point = symbol_info.point
        digits = symbol_info.digits
    except Exception as e:
        logging.error(f"Erreur récupération symbol_info: {e}")
        with threads_lock:
            running_threads.pop(key, None)
            thread_flags.pop(key, None)
        return

    # Attente max 3s pour trouver la position
    while time.time() - start_time < 3:
        try:
            positions = mt5.positions_get(symbol=symbol)
            if positions:
                # Filtrer par magic ET comment
                for p in positions:
                    if p.magic == magic:
                        # Si comment spécifié, doit correspondre exactement
                        if comment and p.comment != comment:
                            continue
                        pos = p
                        break
            if pos:
                break
        except Exception as e:
            logging.error(f"Erreur recherche position: {e}")
        time.sleep(TRAILING_CHECK_INTERVAL)

    if not pos:
        logging.warning(f"Position introuvable pour trailing {symbol}/{magic}/{comment or 'no comment'}")
        with threads_lock:
            running_threads.pop(key, None)
            thread_flags.pop(key, None)
        return

    logging.info(f"Thread trailing actif pour position #{pos.ticket} {symbol}/{magic}/{comment or 'no comment'}")
    
    thread_flags[key] = True
    
    # Variables pour suivre le meilleur niveau
    best_price = None
    last_sl_update = 0
    error_count = 0
    max_errors = 10

    while thread_flags.get(key, False):
        try:
            # Vérifier la connexion MT5
            if not check_mt5_connection():
                logging.warning("Connexion MT5 perdue dans trailing, attente...")
                time.sleep(5)
                continue

            # Vérifier que la position existe toujours
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
                logging.info(f"❌ Position fermée {symbol}/{magic}/{comment or 'no comment'} → arrêt du trailing")
                break

            tick = mt5.symbol_info_tick(symbol)
            if not tick or tick.bid == 0 or tick.ask == 0:
                time.sleep(TRAILING_CHECK_INTERVAL)
                continue

            # === POSITION BUY ===
            if pos.type == mt5.POSITION_TYPE_BUY:
                current_price = tick.bid
                
                # Mettre à jour le meilleur prix
                if best_price is None or current_price > best_price:
                    best_price = current_price
                
                # Calculer le nouveau SL potentiel
                new_sl = best_price - (trail_points * point)
                
                # Vérifier si on doit mettre à jour
                if pos.sl is None or new_sl > pos.sl:
                    # Vérifier le step minimum
                    if pos.sl is None or (new_sl - pos.sl) >= (min_step * point):
                        # Éviter les mises à jour trop fréquentes (max 1 par seconde)
                        if time.time() - last_sl_update > 1:
                            request = {
                                "action": mt5.TRADE_ACTION_SLTP,
                                "position": pos.ticket,
                                "sl": round(new_sl, digits),
                                "tp": pos.tp if pos.tp else 0,
                            }
                            result = mt5.order_send(request)
                            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                                logging.info(f"SL BUY mis à jour {symbol}/{magic}/{comment or 'no comment'}: {pos.sl:.{digits}f} -> {new_sl:.{digits}f}")
                                last_sl_update = time.time()
                                error_count = 0  # Reset error count on success
                            elif result:
                                logging.warning(f"Erreur trailing BUY [{result.retcode}]: {result.comment}")
                                error_count += 1

            # === POSITION SELL ===
            elif pos.type == mt5.POSITION_TYPE_SELL:
                current_price = tick.ask
                
                # Mettre à jour le meilleur prix
                if best_price is None or current_price < best_price:
                    best_price = current_price
                
                # Calculer le nouveau SL potentiel
                new_sl = best_price + (trail_points * point)
                
                # Vérifier si on doit mettre à jour
                if pos.sl is None or new_sl < pos.sl:
                    # Vérifier le step minimum
                    if pos.sl is None or (pos.sl - new_sl) >= (min_step * point):
                        # Éviter les mises à jour trop fréquentes
                        if time.time() - last_sl_update > 1:
                            request = {
                                "action": mt5.TRADE_ACTION_SLTP,
                                "position": pos.ticket,
                                "sl": round(new_sl, digits),
                                "tp": pos.tp if pos.tp else 0,
                            }
                            result = mt5.order_send(request)
                            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                                logging.info(f"SL SELL mis à jour {symbol}/{magic}/{comment or 'no comment'}: {pos.sl:.{digits}f} -> {new_sl:.{digits}f}")
                                last_sl_update = time.time()
                                error_count = 0  # Reset error count on success
                            elif result:
                                logging.warning(f"Erreur trailing SELL [{result.retcode}]: {result.comment}")
                                error_count += 1

            # Arrêter si trop d'erreurs
            if error_count >= max_errors:
                logging.error(f"Trop d'erreurs ({error_count}) dans trailing {symbol}/{magic}/{comment or 'no comment'}, arrêt")
                break

            time.sleep(TRAILING_CHECK_INTERVAL)  # Pause entre les vérifications
            
        except Exception as e:
            logging.error(f"Erreur dans trailing loop: {e}")
            logging.error(traceback.format_exc())
            error_count += 1
            if error_count >= max_errors:
                break
            time.sleep(1)

    logging.info(f"🛑 Thread trailing terminé {symbol}/{magic}/{comment or 'no comment'}")
    with threads_lock:
        running_threads.pop(key, None)
        thread_flags.pop(key, None)


@app.post("/trailing/{symbol}/{magic}")
def start_trailing(
    symbol: str, 
    magic: int, 
    comment: str = Query("", description="Commentaire pour filtrer la position"),
    trail_points: float = Query(..., description="Distance du trailing en points", gt=0),
    min_step: float = Query(..., description="Step minimum en points", gt=0)
):
    """Démarre le trailing stop pour une position spécifique"""
    # Nettoyer les threads morts
    cleanup_dead_threads()
    
    # Validation des paramètres obligatoires
    if trail_points <= 0:
        return response_from_mt5_result({
            "retcode": 10013,
            "status": "error",
            "comment": "trail_points doit être > 0"
        })
    
    if min_step <= 0:
        return response_from_mt5_result({
            "retcode": 10013,
            "status": "error",
            "comment": "min_step doit être > 0"
        })
    
    key = (symbol, magic, comment)
    
    with threads_lock:
        if key in running_threads and running_threads[key].is_alive():
            return response_from_mt5_result({
                "retcode": 10040,
                "status": "error", 
                "comment": "Trailing déjà en cours pour cette position"
            })
    
    # Vérifier qu'une position existe
    if not check_position_exists(symbol, magic, comment):
        return response_from_mt5_result({
            "retcode": 10016,
            "status": "error",
            "comment": f"Aucune position trouvée pour {symbol}/{magic}/{comment or 'no comment'}"
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
        "comment": f"Trailing démarré pour {symbol}/{magic}/{comment or 'no comment'}"
    })


@app.delete("/trailing/{symbol}/{magic}")
def cancel_trailing(
    symbol: str, 
    magic: int,
    comment: str = Query("", description="Commentaire pour identifier le trailing")
):
    """Annule le trailing stop en cours"""
    key = (symbol, magic, comment)
    
    with threads_lock:
        if key not in running_threads:
            return response_from_mt5_result({
                "retcode": 10016,
                "status": "warning",
                "comment": "Aucun trailing actif pour cette position"
            })
        thread_flags[key] = False
    
    return response_from_mt5_result({
        "retcode": 10009,
        "status": "success",
        "comment": f"Annulation du trailing pour {symbol}/{magic}/{comment or 'no comment'}"
    })


# Endpoint webhook principal amélioré
@app.post("/webhooktv", summary="Recevoir les signaux de TradingView (Pine Connector compatible)")
def tradingview_webhook(
    webhook_data: TradingViewWebhook,
    ratio: float = Query(None, description="Multiplicateur pour la taille du lot", gt=0),
    magic: int = Query(None, description="Override du magic number", ge=0),
    check_duplicate: bool = Query(True, description="Vérifier les positions/ordres existants")
):
    """
    Reçoit les alertes TradingView et exécute les actions sur MT5 (Pine Connector compatible)
    
    Paramètres GET:
    - ratio: Multiplicateur optionnel pour ajuster la taille du lot (doit être > 0)
    - magic: Override optionnel du magic number (doit être >= 0)
    - check_duplicate: Vérifie l'existence de positions/ordres avant création (défaut: True)
    
    Actions supportées:
    - buy: Ouvre une position long (vérifie d'abord si elle n'existe pas déjà)
    - sell: Ouvre une position short (vérifie d'abord si elle n'existe pas déjà)
    - buylimit: Place un ordre buy limit (vérifie les doublons)
    - selllimit: Place un ordre sell limit (vérifie les doublons)
    - buystop: Place un ordre buy stop (vérifie les doublons)
    - sellstop: Place un ordre sell stop (vérifie les doublons)
    - closelong: Ferme toutes les positions long
    - closeshort: Ferme toutes les positions short
    - closeall: Ferme toutes les positions
    - closepending: Annule tous les ordres en attente
    - modify: Modifie SL/TP des positions existantes
    - start_trailing: Démarre le trailing stop
    - cancel_trailing: Arrête le trailing stop
    """
    
    try:
        # Vérifier la connexion MT5
        if not ensure_mt5_connection():
            return response_from_mt5_result({
                "retcode": -1,
                "comment": "MT5 connection lost, please retry"
            })
        
        # Nettoyer les threads morts périodiquement
        cleanup_dead_threads()
        
        logging.info(f"[WEBHOOK] Reçu: {webhook_data.action} sur {webhook_data.symbol}")
        if ratio:
            logging.info(f"Ratio multiplicateur: {ratio}")
        
        # Override du magic number si spécifié
        effective_magic = magic if magic is not None else webhook_data.magic
        if magic is not None:
            logging.info(f"Magic override: {webhook_data.magic} → {effective_magic}")
        
        # Validation des paramètres de trailing
        if webhook_data.trail_points is not None and webhook_data.trail_points <= 0:
            return response_from_mt5_result({
                "retcode": 10013,
                "comment": f"trail_points invalide ({webhook_data.trail_points}), doit être > 0"
            })
        
        if webhook_data.trail_step is not None and webhook_data.trail_step <= 0:
            return response_from_mt5_result({
                "retcode": 10013,
                "comment": f"trail_step invalide ({webhook_data.trail_step}), doit être > 0"
            })
        
        # Normaliser
        action = webhook_data.action.lower().strip()
        symbol = webhook_data.symbol.upper()
        
        # Vérifier que le symbole existe dans MT5
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            # Essayer sans le préfixe broker si présent
            if ":" in symbol:
                symbol = symbol.split(":")[-1]
                symbol_info = mt5.symbol_info(symbol)
                if symbol_info is None:
                    return response_from_mt5_result({
                        "retcode": 10014,
                        "comment": f"Symbole {symbol} introuvable dans MT5"
                    })
        
        # Activer le symbole s'il n'est pas visible
        if not symbol_info.visible:
            if not mt5.symbol_select(symbol, True):
                return response_from_mt5_result({
                    "retcode": 10014,
                    "comment": f"Impossible d'activer le symbole {symbol}"
                })
            symbol_info = mt5.symbol_info(symbol)
        
        # Calculer et normaliser la taille du lot
        lot_size = webhook_data.lots
        
        if ratio:
            original_lot = lot_size
            lot_size = lot_size * ratio
            logging.info(f"Lot ajusté: {original_lot} * {ratio} = {lot_size}")
        
        # Normaliser selon les contraintes du symbole
        if symbol_info:
            lot_step = symbol_info.volume_step
            lot_min = symbol_info.volume_min
            
            if lot_step and lot_min:
                steps_from_min = round((lot_size - lot_min) / lot_step)
                steps_from_min = max(0, steps_from_min)
                lot_size = lot_min + (steps_from_min * lot_step)
                
                # Arrondir à la précision du step
                step_str = str(lot_step)
                if '.' in step_str:
                    decimals = len(step_str.split('.')[1])
                    lot_size = round(lot_size, decimals)
            
            # Vérifier les limites
            if lot_size < symbol_info.volume_min:
                logging.warning(f"Lot augmenté à {symbol_info.volume_min} (minimum)")
                lot_size = symbol_info.volume_min
            
            if symbol_info.volume_max and lot_size > symbol_info.volume_max:
                logging.warning(f"Lot réduit à {symbol_info.volume_max} (maximum)")
                lot_size = symbol_info.volume_max
        
        # Appliquer les limites configurées
        if webhook_data.max_lot and lot_size > webhook_data.max_lot:
            logging.warning(f"Lot réduit à {webhook_data.max_lot} (limite signal)")
            lot_size = webhook_data.max_lot
        
        if lot_size > MAX_LOT:
            logging.warning(f"Lot réduit à {MAX_LOT} (limite serveur)")
            lot_size = MAX_LOT
        
        logging.info(f"Taille de lot finale: {lot_size}")
        
        # =====================================
        # FERMETURE DES POSITIONS OPPOSÉES
        # =====================================
        if webhook_data.closeoppositesignal and action in ["buy", "sell", "buylimit", "selllimit", "buystop", "sellstop"]:
            positions = mt5.positions_get(symbol=symbol)
            if positions:
                for pos in positions:
                    if pos.magic != effective_magic:
                        continue
                    # Filtrer par comment si spécifié
                    if webhook_data.comment and pos.comment != webhook_data.comment:
                        continue

                    # Fermer les positions opposées
                    if action in ["buy", "buylimit", "buystop"] and pos.type == mt5.ORDER_TYPE_SELL:
                        # Arrêter le trailing si actif
                        key = (symbol, effective_magic, pos.comment or "")
                        with threads_lock:
                            if key in thread_flags:
                                thread_flags[key] = False
                        
                        close_result = close_position_by_id(pos.ticket, effective_magic, webhook_data.deviation)
                        logging.info(f"Position SHORT opposée fermée: #{pos.ticket}")
                    elif action in ["sell", "selllimit", "sellstop"] and pos.type == mt5.ORDER_TYPE_BUY:
                        # Arrêter le trailing si actif
                        key = (symbol, effective_magic, pos.comment or "")
                        with threads_lock:
                            if key in thread_flags:
                                thread_flags[key] = False
                        
                        close_result = close_position_by_id(pos.ticket, effective_magic, webhook_data.deviation)
                        logging.info(f"Position LONG opposée fermée: #{pos.ticket}")
        
        # =====================================
        # TRAITEMENT DES ACTIONS
        # =====================================
        
        # --- ORDRES MARKET ---
        if action in ["buy", "sell"]:
            
            # VÉRIFIER SI UNE POSITION EXISTE DÉJÀ
            if check_duplicate and check_position_exists(symbol, effective_magic, webhook_data.comment):
                logging.warning(f"⚠️ Position {action.upper()} existe déjà pour {symbol}/{effective_magic}/{webhook_data.comment or 'no comment'}")
                return response_from_mt5_result({
                    "retcode": 10016,  # TRADE_RETCODE_INVALID
                    "comment": f"Position {action} already exists for {symbol}/{effective_magic}/{webhook_data.comment or 'no comment'}"
                })
            
            # Calculer SL/TP
            sl_price = webhook_data.sl
            tp_price = webhook_data.tp
            
            if webhook_data.slpips or webhook_data.tppips:
                point = symbol_info.point
                
                if webhook_data.price:
                    base_price = webhook_data.price
                else:
                    tick = mt5.symbol_info_tick(symbol)
                    if not tick:
                        raise Exception(f"Impossible d'obtenir le tick pour {symbol}")
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
            
            # Créer l'ordre
            order_request = OrderRequest(
                symbol=symbol,
                side=action,
                lot=lot_size,
                sl=sl_price,
                tp=tp_price,
                magic=effective_magic,
                comment=webhook_data.comment or "",
                deviation=webhook_data.deviation,
                price=webhook_data.price
            )
            
            result = trade_new(order_request)
            
            # Si trailing demandé et position créée avec succès
            if webhook_data.trail_points and isinstance(result, dict) and result.get("retcode") == mt5.TRADE_RETCODE_DONE:
                if webhook_data.trail_points <= 0:
                    logging.error(f"trail_points invalide ({webhook_data.trail_points}), trailing non démarré")
                elif not webhook_data.trail_step or webhook_data.trail_step <= 0:
                    logging.error(f"trail_step manquant ou invalide ({webhook_data.trail_step}), trailing non démarré")
                else:
                    # Démarrer le trailing automatiquement
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
                            logging.info(f"Trailing auto-démarré pour la nouvelle position")
            
            return result
        
        # --- ORDRES LIMIT ET STOP ---
        elif action in ["buylimit", "selllimit", "buystop", "sellstop"]:
            
            if not webhook_data.price:
                return response_from_mt5_result({
                    "retcode": 10013,
                    "comment": f"Prix requis pour l'action {action}"
                })
            
            # Déterminer le type d'ordre MT5
            order_type_map = {
                "buylimit": mt5.ORDER_TYPE_BUY_LIMIT,
                "selllimit": mt5.ORDER_TYPE_SELL_LIMIT,
                "buystop": mt5.ORDER_TYPE_BUY_STOP,
                "sellstop": mt5.ORDER_TYPE_SELL_STOP
            }
            
            order_type = order_type_map.get(action)
            
            # VÉRIFIER SI UN ORDRE PENDING EXISTE DÉJÀ
            if check_duplicate and check_pending_order_exists(symbol, effective_magic, webhook_data.comment, order_type):
                logging.warning(f"[WARNING] Ordre {action.upper()} existe déjà pour {symbol}/{effective_magic}/{webhook_data.comment}")
                return response_from_mt5_result({
                    "retcode": 10016,
                    "comment": f"Pending order {action} already exists for {symbol}/{effective_magic}/{webhook_data.comment or 'no comment'}"
                })
            
            # Calculer SL/TP
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
            
            # Préparer l'ordre
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
                logging.info(f"Ordre {action} placé avec succès: ticket={result.order}")
            else:
                logging.error(f"Échec de placement de l'ordre {action}: {result}")
            
            return response_from_mt5_result(result)
        
        # --- FERMETURES ---
        elif action in ["closelong", "closeshort", "closeall"]:
            
            positions_closed = []
            positions = mt5.positions_get(symbol=symbol)
            
            if positions:
                for pos in positions:
                    if pos.magic != effective_magic:
                        continue
                    # Filtrer par comment si spécifié
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
                        # Arrêter le trailing si actif
                        key = (symbol, effective_magic, pos.comment or "")
                        with threads_lock:
                            if key in thread_flags:
                                thread_flags[key] = False
                                logging.info(f"Trailing stoppé pour position #{pos.ticket}")
                        
                        result = close_position_by_id(pos.ticket, effective_magic, webhook_data.deviation)
                        positions_closed.append({
                            "ticket": pos.ticket,
                            "volume": pos.volume,
                            "type": "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL",
                            "symbol": pos.symbol,
                            "profit": pos.profit,
                            "comment": pos.comment or ""
                        })
                        logging.info(f"Position fermée: #{pos.ticket}")
            
            return response_from_mt5_result({
                "action": action,
                "symbol": symbol,
                "closed_count": len(positions_closed),
                "positions": positions_closed
            })
        
        # --- ANNULER ORDRES PENDING ---
        elif action == "closepending":
            
            orders_cancelled = []
            orders = mt5.orders_get(symbol=symbol)
            
            if orders:
                for order in orders:
                    if order.magic != effective_magic:
                        continue
                    # Filtrer par comment si spécifié
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
                        logging.info(f"Ordre annulé: #{order.ticket}")
            
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
                    # Filtrer par comment si spécifié
                    if webhook_data.comment and pos.comment != webhook_data.comment:
                        continue
                    
                    modify_request = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "position": pos.ticket,
                        "symbol": symbol
                    }
                    
                    # Calculer SL/TP
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
                        logging.info(f"Position modifiée: #{pos.ticket}")
            
            return response_from_mt5_result({
                "action": "modify",
                "symbol": symbol,
                "modified_count": len(positions_modified),
                "positions": positions_modified
            })
        
        # --- TRAILING ---
        elif action == "start_trailing":
            # Vérifier que les paramètres requis sont présents
            if not webhook_data.trail_points or webhook_data.trail_points <= 0:
                return response_from_mt5_result({
                    "retcode": 10013,
                    "comment": "trail_points requis et doit être > 0"
                })
            
            if not webhook_data.trail_step or webhook_data.trail_step <= 0:
                return response_from_mt5_result({
                    "retcode": 10013,
                    "comment": "trail_step requis et doit être > 0"
                })
            
            key = (symbol, effective_magic, webhook_data.comment or "")
            
            # Vérifier qu'une position existe
            if not check_position_exists(symbol, effective_magic, webhook_data.comment):
                return response_from_mt5_result({
                    "retcode": 10016,
                    "comment": f"Aucune position trouvée pour démarrer le trailing"
                })
            
            # Vérifier si déjà en cours
            with threads_lock:
                if key in running_threads and running_threads[key].is_alive():
                    return response_from_mt5_result({
                        "retcode": 10040,
                        "comment": "Trailing déjà en cours"
                    })
                
                # Démarrer le trailing
                t = threading.Thread(
                    target=trailing_loop,
                    args=(symbol, effective_magic, webhook_data.comment or "", 
                          webhook_data.trail_points, webhook_data.trail_step),
                    daemon=True
                )
                running_threads[key] = t
                t.start()
            
            return response_from_mt5_result({
                "retcode": 10009,
                "comment": f"Trailing démarré pour {symbol}/{effective_magic}/{webhook_data.comment or 'no comment'}"
            })

        elif action == "cancel_trailing":
            key = (symbol, effective_magic, webhook_data.comment or "")
            
            with threads_lock:
                if key not in running_threads:
                    return response_from_mt5_result({
                        "retcode": 10016,
                        "comment": "Aucun trailing actif"
                    })
                thread_flags[key] = False
            
            return response_from_mt5_result({
                "retcode": 10009,
                "comment": f"Trailing annulé pour {symbol}/{effective_magic}/{webhook_data.comment or 'no comment'}"
            })
        
        # --- ACTION NON RECONNUE ---
        else:
            return response_from_mt5_result({
                "retcode": 10030,
                "comment": f"Action non reconnue: {action}. Actions valides: buy, sell, buylimit, selllimit, buystop, sellstop, closeall, closelong, closeshort, closepending, modify, start_trailing, cancel_trailing"
            })
    
    except Exception as e:
        logging.error(f"[ERROR] Erreur webhook: {str(e)}")
        logging.error(traceback.format_exc())
        return response_from_exception(e)


# uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4 --reload --reload-include *.yml"


if __name__ == "__main__":
    uvicorn.run("api:app", port=8000, host="0.0.0.0", reload=False, log_level="debug")

