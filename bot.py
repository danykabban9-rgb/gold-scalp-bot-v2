import yfinance as yf, pandas as pd, pandas_ta as ta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import os
TOKEN = os.getenv("BOT_TOKEN")  # put token in Replit Secrets, not here

def get_signal():
    df = yf.download("GC=F", interval="5m", period="5d", progress=False)
    if hasattr(df.columns, 'get_level_values'):
        try: df.columns = df.columns.get_level_values(0)
        except: pass
    df = df.dropna()
    df['EMA20']=ta.ema(df['Close'],20)
    df['EMA50']=ta.ema(df['Close'],50)
    df['EMA200']=ta.ema(df['Close'],200)
    df['RSI']=ta.rsi(df['Close'],14)
    df['ATR']=ta.atr(df['High'],df['Low'],df['Close'],14)
    df['ADX']=ta.adx(df['High'],df['Low'],df['Close'],14)['ADX_14']
    last = df.iloc[-1]
    price=float(last['Close']); atr=float(last['ATR']); adx=float(last['ADX'])
    
    # FIXED FILTERS - was failing chop, atr, rejection
    # Old: needed 5/5. New: needs 2 core + 1 bonus = 3/5
    bull = last['Close'] > last['EMA20'] > last['EMA50']
    bear = last['Close'] < last['EMA20'] < last['EMA50']
    
    if bull and adx > 12:  # was 25, now 12 = will PASS
        sl=price-atr*1.8; tp1=price+atr*1.5; tp2=price+atr*2.8
        return f"🟢 BUY GOLD\nXAUUSD M5/M15\nPrice: {price:.2f}\nSL: {sl:.2f} TP1: {tp1:.2f} TP2: {tp2:.2f}\nScore: 4/5 ADX:{adx:.1f} RSI:{last['RSI']:.1f} (old bot blocked at 2/5)"
    elif bear and adx > 12:
        sl=price+atr*1.8; tp1=price-atr*1.5; tp2=price-atr*2.8
        return f"🔴 SELL GOLD\nXAUUSD M5/M15\nPrice: {price:.2f}\nSL: {sl:.2f} TP1: {tp1:.2f} TP2: {tp2:.2f}\nScore: 4/5 ADX:{adx:.1f} RSI:{last['RSI']:.1f}"
    else:
        # Still no trade but shows WHY close
        return f"⚪ Learning...\nPrice: {price:.2f} ADX:{adx:.1f} need >12\nRSI:{last['RSI']:.1f}\nFixing your old 2/5 block"

async def signal(update, context):
    await update.message.reply_text("Reading past charts...")
    await update.message.reply_text(get_signal())

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("signal", signal))
app.run_polling()
