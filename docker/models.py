from pydantic import BaseModel, Field
from typing import Optional
import datetime

class GetLastCandleRequest(BaseModel):
    symbol: Optional[str] = Field("XAUUSD", examples=["XAUUSD"])
    start: Optional[int] = Field(0, examples=[0, 100, 1000])
    timeframe: Optional[str] = Field("", examples=["1h"])
    count: Optional[int] = Field(100, examples=[100, 1000])


class BuyRequest(BaseModel):
    symbol: Optional[str] = Field("XAUUSD", examples=["XAUUSD"])
    magic: Optional[int] = Field(0, examples=[0])
    lot: Optional[float] = Field(0.01, examples=[0.01, 0.02])
    sl_point: Optional[int] = Field(200, examples=[200, 300])
    tp_point: Optional[int] = Field(200, examples=[200, 300])
    deviation: Optional[int] = Field(200, examples=[200, 300])
    comment: Optional[str] = Field("Buy 123", examples=["NO COMMENT"])


class SellRequest(BaseModel):
    symbol: Optional[str] = Field("XAUUSD", examples=["XAUUSD"])
    magic: Optional[int] = Field(0, examples=[0])
    lot: Optional[float] = Field(0.01, examples=[0.01, 0.02])
    sl_point: Optional[int] = Field(200, examples=[200, 300])
    tp_point: Optional[int] = Field(200, examples=[200, 300])
    deviation: Optional[int] = Field(200, examples=[200, 300])
    comment: Optional[str] = Field("Sell 123", examples=["NO COMMENT"])


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
    symbol: str
    ticket: int  # ID de la position à modifier
    tp: Optional[float] = None  # nouveau take profit (ou None pour ne pas le modifier)
    sl: Optional[float] = None  # nouveau stop loss (ou None pour ne pas le modifier)
    deviation: Optional[int] = 20
    magic: Optional[int] = 0
    comment: Optional[str] = "modify sl/tp"