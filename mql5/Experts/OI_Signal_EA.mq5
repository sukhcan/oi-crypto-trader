//+------------------------------------------------------------------+
//|  OI_Signal_EA.mq5                                                |
//|  Open Interest Signal Expert Advisor                             |
//|  Reads JSON signal file produced by Python OI pipeline           |
//|  and executes trades on crypto CFD / futures instruments         |
//+------------------------------------------------------------------+
#property copyright "OI Trading System"
#property version   "1.00"
#property description "Open Interest Signal EA — reads Python-generated OI signals"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\OrderInfo.mqh>

//--- Input parameters
input group "== Signal File =="
input string InpSignalFile     = "oi_signal.json"; // Signal JSON file path (in MQL5\Files\)
input int    InpPollSeconds    = 5;                 // Poll interval (seconds)
input int    InpSignalStaleSec = 120;               // Max signal age before ignoring (seconds)

input group "== Trade Execution =="
input double InpLotSize        = 0.01;              // Lot size
input int    InpSlippage       = 20;                // Slippage in points
input ulong  InpMagic          = 202401;            // Magic number

input group "== Risk Management =="
input double InpStopLossPct    = 1.5;               // Stop loss % from entry
input double InpTakeProfitPct  = 3.0;               // Take profit % from entry
input int    InpMaxPositions    = 1;                 // Max simultaneous positions
input bool   InpCloseOnReverse  = true;             // Close position on reverse signal

input group "== OI Filter =="
input double InpMinOIChangePct = 0.5;               // Minimum |OI change %| to trade
input double InpMinPxChangePct = 0.1;               // Minimum |price change %| to trade
input bool   InpRequireBullish  = false;            // Only trade BULLISH_TREND signals
input bool   InpRequireBearish  = false;            // Only trade BEARISH_TREND signals

//--- Global objects
CTrade         trade;
CPositionInfo  pos;
COrderInfo     ord;

//--- Signal structure (mirrors Python OIMetrics)
struct OISignal {
   string symbol;
   string timestamp;
   string signal;          // BUY / SELL / NEUTRAL
   string trend_label;
   double current_oi;
   double previous_oi;
   double oi_change_pct;
   double current_price;
   double price_change_pct;
   string published_at;
   int    schema_version;
   bool   valid;
};

//--- State
OISignal  g_lastSignal;
datetime  g_lastPollTime  = 0;
datetime  g_lastTradeTime = 0;
int       g_fileHandle    = INVALID_HANDLE;

//+------------------------------------------------------------------+
//| Expert initialization                                            |
//+------------------------------------------------------------------+
int OnInit() {
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippage);
   trade.SetTypeFilling(ORDER_FILLING_IOC);
   trade.SetAsyncMode(false);

   EventSetTimer(InpPollSeconds);

   Print("[OI_EA] Initialized. Polling: ", InpSignalFile, " every ", InpPollSeconds, "s");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason) {
   EventKillTimer();
   Print("[OI_EA] Deinit, reason=", reason);
}

//+------------------------------------------------------------------+
//| Timer event — main polling + decision loop                       |
//+------------------------------------------------------------------+
void OnTimer() {
   datetime now = TimeGMT();
   if(now - g_lastPollTime < InpPollSeconds) return;
   g_lastPollTime = now;

   OISignal sig = ReadSignalFile();
   if(!sig.valid) return;

   // Stale check
   datetime sigTime = StringToTime(sig.published_at);
   if(now - sigTime > InpSignalStaleSec) {
      PrintFormat("[OI_EA] Signal stale by %ds — skipping", (int)(now - sigTime));
      return;
   }

   // Filter: minimum OI / price move
   if(MathAbs(sig.oi_change_pct)    < InpMinOIChangePct ||
      MathAbs(sig.price_change_pct) < InpMinPxChangePct) {
      return;
   }

   // Optional directional filters
   if(InpRequireBullish && sig.trend_label != "BULLISH_TREND") return;
   if(InpRequireBearish && sig.trend_label != "BEARISH_TREND") return;

   // Deduplicate — don't act on the same timestamp twice
   if(sig.published_at == g_lastSignal.published_at) return;
   g_lastSignal = sig;

   int openPositions = CountMagicPositions();

   // --- Close on reverse ---
   if(InpCloseOnReverse && openPositions > 0) {
      if(sig.signal == "BUY"  && HasShortPosition()) CloseAllMagicPositions();
      if(sig.signal == "SELL" && HasLongPosition())  CloseAllMagicPositions();
      openPositions = CountMagicPositions();
   }

   // --- Open new position ---
   if(sig.signal == "NEUTRAL") return;
   if(openPositions >= InpMaxPositions) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double pipFactor = 1.0 / tickSize;

   if(sig.signal == "BUY") {
      double sl = ask * (1.0 - InpStopLossPct   / 100.0);
      double tp = ask * (1.0 + InpTakeProfitPct / 100.0);
      sl = NormalizeDouble(sl, _Digits);
      tp = NormalizeDouble(tp, _Digits);
      string comment = StringFormat("OI:%s|%.2f%%", sig.trend_label, sig.oi_change_pct);
      if(trade.Buy(InpLotSize, _Symbol, ask, sl, tp, comment)) {
         PrintFormat("[OI_EA] BUY opened | trend=%s OI_chg=%.2f%% Px_chg=%.2f%%",
                     sig.trend_label, sig.oi_change_pct, sig.price_change_pct);
      } else {
         PrintFormat("[OI_EA] BUY FAILED | error=%d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
      }

   } else if(sig.signal == "SELL") {
      double sl = bid * (1.0 + InpStopLossPct   / 100.0);
      double tp = bid * (1.0 - InpTakeProfitPct / 100.0);
      sl = NormalizeDouble(sl, _Digits);
      tp = NormalizeDouble(tp, _Digits);
      string comment = StringFormat("OI:%s|%.2f%%", sig.trend_label, sig.oi_change_pct);
      if(trade.Sell(InpLotSize, _Symbol, bid, sl, tp, comment)) {
         PrintFormat("[OI_EA] SELL opened | trend=%s OI_chg=%.2f%% Px_chg=%.2f%%",
                     sig.trend_label, sig.oi_change_pct, sig.price_change_pct);
      } else {
         PrintFormat("[OI_EA] SELL FAILED | error=%d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
      }
   }
}

//+------------------------------------------------------------------+
//| Tick event (optional: can also react on ticks for tighter fills) |
//+------------------------------------------------------------------+
void OnTick() {
   // SL/TP are handled by the broker; nothing needed here
   // Extend: trailing stop logic could go here
}

//+------------------------------------------------------------------+
//| Read and parse the JSON signal file                              |
//+------------------------------------------------------------------+
OISignal ReadSignalFile() {
   OISignal sig;
   sig.valid = false;

   int h = FileOpen(InpSignalFile, FILE_READ | FILE_TXT | FILE_COMMON);
   if(h == INVALID_HANDLE) {
      // File not yet created by Python — not an error on startup
      return sig;
   }

   string content = "";
   while(!FileIsEnding(h)) {
      content += FileReadString(h);
   }
   FileClose(h);

   if(StringLen(content) < 10) return sig;

   // Manual JSON field extraction (MQL5 has no native JSON library)
   sig.signal          = ExtractJsonString(content, "signal");
   sig.trend_label     = ExtractJsonString(content, "trend_label");
   sig.symbol          = ExtractJsonString(content, "symbol");
   sig.timestamp       = ExtractJsonString(content, "timestamp");
   sig.published_at    = ExtractJsonString(content, "published_at");
   sig.oi_change_pct   = ExtractJsonDouble(content, "oi_change_pct");
   sig.price_change_pct= ExtractJsonDouble(content, "price_change_pct");
   sig.current_oi      = ExtractJsonDouble(content, "current_oi");
   sig.previous_oi     = ExtractJsonDouble(content, "previous_oi");
   sig.current_price   = ExtractJsonDouble(content, "current_price");
   sig.schema_version  = (int)ExtractJsonDouble(content, "schema_version");

   if(sig.signal == "" || sig.published_at == "") return sig;

   sig.valid = true;
   return sig;
}

//+------------------------------------------------------------------+
//| JSON helpers — extract string value for a given key              |
//+------------------------------------------------------------------+
string ExtractJsonString(const string &json, const string key) {
   string search = "\"" + key + "\"";
   int pos = StringFind(json, search);
   if(pos < 0) return "";
   pos = StringFind(json, ":", pos);
   if(pos < 0) return "";
   pos++;
   // Skip whitespace and opening quote
   while(pos < StringLen(json) && (StringGetCharacter(json, pos) == ' ' ||
                                    StringGetCharacter(json, pos) == '\t')) pos++;
   if(StringGetCharacter(json, pos) != '"') return "";
   pos++;
   string result = "";
   while(pos < StringLen(json) && StringGetCharacter(json, pos) != '"') {
      result += ShortToString(StringGetCharacter(json, pos));
      pos++;
   }
   return result;
}

double ExtractJsonDouble(const string &json, const string key) {
   string search = "\"" + key + "\"";
   int pos = StringFind(json, search);
   if(pos < 0) return 0.0;
   pos = StringFind(json, ":", pos);
   if(pos < 0) return 0.0;
   pos++;
   while(pos < StringLen(json) && (StringGetCharacter(json, pos) == ' ' ||
                                    StringGetCharacter(json, pos) == '\t')) pos++;
   string numStr = "";
   ushort c = StringGetCharacter(json, pos);
   while(pos < StringLen(json) && (c == '-' || c == '.' ||
         (c >= '0' && c <= '9') || c == 'e' || c == 'E' || c == '+')) {
      numStr += ShortToString(c);
      pos++;
      c = StringGetCharacter(json, pos);
   }
   return StringToDouble(numStr);
}

//+------------------------------------------------------------------+
//| Position management helpers                                      |
//+------------------------------------------------------------------+
int CountMagicPositions() {
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      if(pos.SelectByIndex(i))
         if(pos.Symbol() == _Symbol && pos.Magic() == InpMagic) count++;
   }
   return count;
}

bool HasLongPosition() {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(pos.SelectByIndex(i) && pos.Symbol() == _Symbol &&
         pos.Magic() == InpMagic && pos.PositionType() == POSITION_TYPE_BUY)
         return true;
   return false;
}

bool HasShortPosition() {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(pos.SelectByIndex(i) && pos.Symbol() == _Symbol &&
         pos.Magic() == InpMagic && pos.PositionType() == POSITION_TYPE_SELL)
         return true;
   return false;
}

void CloseAllMagicPositions() {
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      if(pos.SelectByIndex(i) && pos.Symbol() == _Symbol && pos.Magic() == InpMagic) {
         if(!trade.PositionClose(pos.Ticket())) {
            PrintFormat("[OI_EA] Failed to close #%d: %d", pos.Ticket(), trade.ResultRetcode());
         } else {
            Print("[OI_EA] Closed position #", pos.Ticket());
         }
      }
   }
}
//+------------------------------------------------------------------+
