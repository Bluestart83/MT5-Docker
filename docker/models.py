from pydantic import BaseModel, Field
from typing import Optional
import datetime

class GetLastCandleRequest(BaseModel):
    symbol: Optional[str] = Field("XAUUSD", examples=["XAUUSD"])
    start: Optional[int] = Field(0, examples=[0, 100, 1000])
    timeframe: Optional[str] = Field("", examples=["1h"])
    count: Optional[int] = Field(100, examples=[100, 1000])


class OrderRequest(BaseModel):
    side: Optional[str] = Field("side", examples=["buy", "sell"])
    symbol: Optional[str] = Field("XAUUSD", examples=["XAUUSD"])
    magic: Optional[int] = Field(0, examples=[0])
    lot: Optional[float] = Field(0.01, examples=[0.01, 0.02])
    sl: Optional[float] = Field(200, examples=[200, 300])
    tp: Optional[float] = Field(200, examples=[200, 300])
    price: Optional[float] = Field(200, examples=[200, 300])
    deviation: Optional[int] = Field(200, examples=[200, 300])
    comment: Optional[str] = Field("Buy 123", examples=["NO COMMENT"])




class CloseRequest(BaseModel):
    symbol: Optional[str] = Field("XAUUSD", examples=["XAUUSD"])
    magic: Optional[int] = Field(0, examples=[0])
    deviation: Optional[int] = Field(200, examples=[200, 300])


class GetLastDealsHistoryRequest(BaseModel):
    symbol: Optional[str] = Field("XAUUSD", examples=["XAUUSD"])

class GetHistoryCandleRequest(BaseModel):
    symbol: str = Field("XAUUSD", examples=["XAUUSD"])
    timeframe: str = Field("", examples=["1h"])
    from_date: datetime.datetime
    to_date: datetime.datetime

class GetHistoryTickRequest(BaseModel):
    symbol: str = Field("XAUUSD", examples=["XAUUSD"])
    from_date: datetime.datetime
    to_date: datetime.datetime

class ModifyOrderRequest(BaseModel):
    tp: Optional[float] = None  # nouveau take profit (ou None pour ne pas le modifier)
    sl: Optional[float] = None  # nouveau stop loss (ou None pour ne pas le modifier)
    deviation: Optional[int] = 20
    magic: Optional[int] = 0
    comment: Optional[str] = "modify sl/tp"

class TradingViewWebhook(BaseModel):
    """Modèle pour recevoir les alertes de TradingView"""
    symbol: str
    action: str  # "buy", "sell", "buylimit", "selllimit", "buystop", "sellstop", "closelong", "closeshort", "closeall", "closepending", "modify", "start_trailing", "cancel_trailing"
    interval:str
    lots: float = 0.01
    sl: Optional[float] = None
    tp: Optional[float] = None
    slpips: Optional[int] = None
    tppips: Optional[int] = None
    magic: int = None
    comment: str = ""
    deviation: int = 10
    price: Optional[float] = None
    max_lot: Optional[float] = None  # Limite spécifique pour ce signal
    closeoppositesignal: bool = False
    timestamp: Optional[str] = None
    trail_points: Optional[float] = None  # Distance du trailing en points
    trail_step: Optional[float] = None    # Step minimum du trailing
    trigger_price: Optional[float] = None  # Prix d'activation du trailing (optionnel)
