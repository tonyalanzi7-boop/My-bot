"""
╔══════════════════════════════════════════════════════════════════════╗
║          Binance Spot Scanner Bot - Telegram Alerts                 ║
║          خبير التداول الآلي - ماسح بايننس الفوري                   ║
╚══════════════════════════════════════════════════════════════════════╝

المتطلبات (Requirements):
    pip install python-binance pandas pandas-ta python-telegram-bot aiohttp

إعداد المفاتيح (API Keys Setup):
    1. مفتاح بايننس: اذهب إلى binance.com → API Management → أنشئ مفتاح جديد
    2. مفتاح تليجرام: تحدث مع @BotFather على تليجرام → /newbot → احفظ الـ Token
    3. Chat ID: تحدث مع @userinfobot أو @getmyid_bot لمعرفة الـ Chat ID الخاص بك
    4. ضع المفاتيح في قسم CONFIG أدناه أو في ملف .env
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pandas_ta as ta
from binance.client import Client
from binance.exceptions import BinanceAPIException
from telegram import Bot
from telegram.error import TelegramError

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚙️  إعدادات API - ضع مفاتيحك هنا
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONFIG = {
    # 🔑 Binance API Keys
    "BINANCE_API_KEY": "YOUR_BINANCE_API_KEY_HERE",
    "BINANCE_SECRET_KEY": "YOUR_BINANCE_SECRET_KEY_HERE",

    # 🤖 Telegram Bot Settings
    "TELEGRAM_BOT_TOKEN": "YOUR_TELEGRAM_BOT_TOKEN_HERE",
    "TELEGRAM_CHAT_ID": "YOUR_CHAT_ID_HERE",  # يمكن أن يكون رقم سالب لمجموعة

    # ⏱️ إعدادات المسح (Scanning Settings)
    "SCAN_INTERVAL_SECONDS": 120,        # كل كم ثانية يتم المسح (لا تقل عن 60)
    "QUOTE_CURRENCY": "USDT",            # العملة الأساسية للمسح
    "MIN_VOLUME_USDT": 500_000,          # الحد الأدنى لحجم التداول بالـ USDT
    "TOP_PAIRS_LIMIT": 150,              # عدد العملات المراد مسحها (الأعلى حجماً)

    # 📊 إعدادات الفريمات (Timeframes)
    "TIMEFRAMES": ["5m", "15m", "1h", "4h"],

    # 🎯 إعدادات الإشارات (Signal Thresholds)
    "VOLUME_SPIKE_MULTIPLIER": 2.5,      # معامل انفجار السيولة (2.5x المتوسط)
    "RSI_OVERSOLD": 35,                  # حد التشبع البيعي
    "RSI_OVERBOUGHT": 65,                # حد التشبع الشرائي
    "BREAKOUT_CANDLES": 3,               # عدد الشموع للتأكيد
    "COOLDOWN_MINUTES": 60,              # مدة الانتظار قبل إعادة التنبيه لنفس العملة
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📝 إعداد نظام السجلات (Logging)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("scanner_bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📡 فئة الاتصال بـ Binance
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class BinanceDataFetcher:
    """مسؤول عن جلب البيانات من بايننس مع احترام حدود الـ Rate Limit"""

    TIMEFRAME_MAP = {
        "5m":  Client.KLINE_INTERVAL_5MINUTE,
        "15m": Client.KLINE_INTERVAL_15MINUTE,
        "1h":  Client.KLINE_INTERVAL_1HOUR,
        "4h":  Client.KLINE_INTERVAL_4HOUR,
    }

    CANDLES_NEEDED = {
        "5m": 100, "15m": 100, "1h": 100, "4h": 100,
    }

    def __init__(self, api_key: str, secret_key: str):
        self.client = Client(api_key, secret_key)
        logger.info("✅ تم الاتصال بـ Binance API بنجاح")

    def get_top_usdt_pairs(self, quote: str = "USDT", limit: int = 150) -> List[str]:
        """جلب أعلى العملات حجماً من بايننس"""
        try:
            tickers = self.client.get_ticker()
            usdt_pairs = [
                t for t in tickers
                if t["symbol"].endswith(quote)
                and float(t["quoteVolume"]) >= CONFIG["MIN_VOLUME_USDT"]
                and t["symbol"] not in ["USDTUSDT", "BUSDUSDT", "TUSDUSDT"]
            ]
            # ترتيب حسب حجم التداول تنازلياً
            usdt_pairs.sort(key=lambda x: float(x["quoteVolume"]), reverse=True)
            symbols = [p["symbol"] for p in usdt_pairs[:limit]]
            logger.info(f"📋 تم رصد {len(symbols)} عملة للمسح")
            return symbols
        except BinanceAPIException as e:
            logger.error(f"❌ خطأ في جلب قائمة العملات: {e}")
            return []

    def get_klines(self, symbol: str, timeframe: str, limit: int = 100) -> Optional[pd.DataFrame]:
        """جلب بيانات الشموع اليابانية"""
        try:
            interval = self.TIMEFRAME_MAP[timeframe]
            raw = self.client.get_klines(symbol=symbol, interval=interval, limit=limit)
            df = pd.DataFrame(raw, columns=[
                "timestamp", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades", "taker_buy_base",
                "taker_buy_quote", "ignore"
            ])
            # تحويل الأنواع
            for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
                df[col] = pd.to_numeric(df[col])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            return df
        except BinanceAPIException as e:
            if e.status_code == 429:
                logger.warning("⚠️ Rate Limit! انتظار 10 ثواني...")
                time.sleep(10)
            return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🔬 محرك التحليل الفني
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TechnicalAnalyzer:
    """يحسب المؤشرات الفنية ويحدد الإشارات"""

    @staticmethod
    def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """إضافة جميع المؤشرات الفنية للبيانات"""
        # RSI
        df.ta.rsi(length=14, append=True)

        # MACD
        df.ta.macd(fast=12, slow=26, signal=9, append=True)

        # Bollinger Bands
        df.ta.bbands(length=20, std=2, append=True)

        # EMA
        df.ta.ema(length=20, append=True)
        df.ta.ema(length=50, append=True)
        df.ta.ema(length=200, append=True)

        # ATR للتذبذب
        df.ta.atr(length=14, append=True)

        return df

    @staticmethod
    def detect_volume_spike(df: pd.DataFrame, multiplier: float = 2.5) -> Tuple[bool, float]:
        """
        رصد انفجار حجم التداول.
        يقارن الشمعة الأخيرة بمتوسط آخر 20 شمعة.
        """
        if len(df) < 21:
            return False, 0.0
        avg_volume = df["volume"].iloc[-21:-1].mean()
        current_volume = df["volume"].iloc[-1]
        if avg_volume == 0:
            return False, 0.0
        ratio = current_volume / avg_volume
        return ratio >= multiplier, round(ratio, 2)

    @staticmethod
    def detect_breakout(df: pd.DataFrame) -> Tuple[bool, str]:
        """
        رصد الاختراق السعري.
        يكتشف كسر مستوى المقاومة (أعلى سعر في آخر 20 شمعة).
        """
        if len(df) < 22:
            return False, ""

        resistance = df["high"].iloc[-22:-2].max()
        support = df["low"].iloc[-22:-2].min()
        current_close = df["close"].iloc[-1]
        current_open = df["open"].iloc[-1]

        # اختراق للأعلى
        if current_close > resistance and current_close > current_open:
            return True, "🚀 اختراق صعودي للمقاومة"

        # اختراق للأسفل
        if current_close < support and current_close < current_open:
            return True, "📉 اختراق هبوطي للدعم"

        return False, ""

    @staticmethod
    def detect_strong_momentum(df: pd.DataFrame) -> Tuple[bool, str]:
        """
        رصد الزخم القوي بناءً على تقاطع MACD و RSI.
        """
        if len(df) < 30:
            return False, ""

        last = df.iloc[-1]
        prev = df.iloc[-2]

        signals = []
        score = 0

        # ── RSI ──
        rsi_col = [c for c in df.columns if c.startswith("RSI_")]
        if rsi_col:
            rsi = last[rsi_col[0]]
            if not pd.isna(rsi):
                if 50 < rsi < CONFIG["RSI_OVERBOUGHT"]:
                    signals.append(f"RSI قوي ({rsi:.1f})")
                    score += 1
                elif rsi <= CONFIG["RSI_OVERSOLD"]:
                    signals.append(f"RSI تشبع بيعي ({rsi:.1f})")
                    score += 1

        # ── MACD تقاطع ──
        macd_cols = [c for c in df.columns if "MACD" in c and "h" in c.lower()]
        macd_line = [c for c in df.columns if c.startswith("MACD_") and "s" not in c.lower() and "h" not in c.lower()]
        macd_signal = [c for c in df.columns if "MACDs_" in c]

        if macd_line and macd_signal:
            curr_macd = last[macd_line[0]]
            curr_sig = last[macd_signal[0]]
            prev_macd = prev[macd_line[0]]
            prev_sig = prev[macd_signal[0]]

            if not any(pd.isna(v) for v in [curr_macd, curr_sig, prev_macd, prev_sig]):
                # تقاطع صعودي
                if prev_macd < prev_sig and curr_macd > curr_sig:
                    signals.append("MACD تقاطع صعودي 📈")
                    score += 2
                # تقاطع هبوطي
                elif prev_macd > prev_sig and curr_macd < curr_sig:
                    signals.append("MACD تقاطع هبوطي 📉")
                    score += 2

        # ── Bollinger Bands ضيق النطاق (Squeeze) ──
        bb_upper = [c for c in df.columns if "BBU_" in c]
        bb_lower = [c for c in df.columns if "BBL_" in c]
        bb_mid = [c for c in df.columns if "BBM_" in c]

        if bb_upper and bb_lower and bb_mid:
            upper = last[bb_upper[0]]
            lower = last[bb_lower[0]]
            mid = last[bb_mid[0]]
            if not any(pd.isna(v) for v in [upper, lower, mid]) and mid != 0:
                band_width = (upper - lower) / mid
                # ضيق النطاق → انفجار وشيك
                if band_width < 0.03:
                    signals.append(f"BB ضيق النطاق ({band_width:.3f}) ⚡")
                    score += 1
                # كسر الحزام العلوي
                if last["close"] > upper:
                    signals.append("كسر BB العلوي 🔥")
                    score += 2

        # ── EMA تحديد الاتجاه ──
        ema20 = [c for c in df.columns if "EMA_20" in c]
        ema50 = [c for c in df.columns if "EMA_50" in c]

        if ema20 and ema50:
            e20 = last[ema20[0]]
            e50 = last[ema50[0]]
            close = last["close"]
            if not any(pd.isna(v) for v in [e20, e50]):
                if close > e20 > e50:
                    signals.append("فوق EMA 20/50 📗")
                    score += 1
                elif close < e20 < e50:
                    signals.append("تحت EMA 20/50 📕")
                    score += 1

        if score >= 2 and signals:
            return True, " | ".join(signals)

        return False, ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📨 مرسل التنبيهات عبر تليجرام
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TelegramAlerter:
    """مسؤول عن إرسال التنبيهات لقناة أو مجموعة تليجرام"""

    def __init__(self, token: str, chat_id: str):
        self.bot = Bot(token=token)
        self.chat_id = chat_id
        # قاموس لتتبع آخر تنبيه لكل عملة (لتفادي الإرسال المتكرر)
        self.alert_cooldown: Dict[str, float] = {}

    def _is_in_cooldown(self, key: str) -> bool:
        """التحقق من أن العملة ليست في فترة الانتظار"""
        cooldown_secs = CONFIG["COOLDOWN_MINUTES"] * 60
        last_alert = self.alert_cooldown.get(key, 0)
        return (time.time() - last_alert) < cooldown_secs

    async def send_alert(self, message: str, key: str) -> bool:
        """إرسال رسالة تنبيه مع فحص الـ Cooldown"""
        if self._is_in_cooldown(key):
            return False
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            self.alert_cooldown[key] = time.time()
            return True
        except TelegramError as e:
            logger.error(f"❌ خطأ في إرسال تنبيه تليجرام: {e}")
            return False

    @staticmethod
    def format_volume_spike_message(
        symbol: str, timeframe: str, price: float,
        volume_ratio: float, change_pct: float
    ) -> str:
        emoji = "🟢" if change_pct >= 0 else "🔴"
        return (
            f"💧 <b>انفجار سيولة ضخم!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 العملة: <b>{symbol}</b>\n"
            f"💰 السعر: <code>{price:.6g} USDT</code>\n"
            f"📊 الفريم: <b>{timeframe}</b>\n"
            f"🚨 نوع الإشارة: سيولة ضخمة\n"
            f"📈 نسبة الحجم: <b>{volume_ratio:.1f}x</b> المتوسط\n"
            f"{emoji} التغير: <b>{change_pct:+.2f}%</b>\n"
            f"⏰ الوقت: {datetime.utcnow().strftime('%H:%M:%S')} UTC"
        )

    @staticmethod
    def format_breakout_message(
        symbol: str, timeframe: str, price: float,
        breakout_type: str, volume_ratio: float
    ) -> str:
        return (
            f"⚡ <b>اختراق قوي مكتشف!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 العملة: <b>{symbol}</b>\n"
            f"💰 السعر: <code>{price:.6g} USDT</code>\n"
            f"📊 الفريم: <b>{timeframe}</b>\n"
            f"🎯 نوع الإشارة: {breakout_type}\n"
            f"📦 الحجم النسبي: <b>{volume_ratio:.1f}x</b>\n"
            f"⏰ الوقت: {datetime.utcnow().strftime('%H:%M:%S')} UTC"
        )

    @staticmethod
    def format_momentum_message(
        symbol: str, timeframe: str, price: float,
        signals_desc: str, volume_ratio: float
    ) -> str:
        return (
            f"🔥 <b>زخم قوي مكتشف!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 العملة: <b>{symbol}</b>\n"
            f"💰 السعر: <code>{price:.6g} USDT</code>\n"
            f"📊 الفريم: <b>{timeframe}</b>\n"
            f"🔬 المؤشرات: {signals_desc}\n"
            f"📦 الحجم النسبي: <b>{volume_ratio:.1f}x</b>\n"
            f"⏰ الوقت: {datetime.utcnow().strftime('%H:%M:%S')} UTC"
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🔄 محرك المسح الرئيسي
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class BinanceScanner:
    """المحرك الرئيسي للمسح الدوري"""

    def __init__(self):
        self.fetcher = BinanceDataFetcher(
            CONFIG["BINANCE_API_KEY"],
            CONFIG["BINANCE_SECRET_KEY"],
        )
        self.analyzer = TechnicalAnalyzer()
        self.alerter = TelegramAlerter(
            CONFIG["TELEGRAM_BOT_TOKEN"],
            CONFIG["TELEGRAM_CHAT_ID"],
        )
        self.scan_count = 0

    async def analyze_symbol(self, symbol: str, timeframe: str):
        """تحليل عملة واحدة على فريم واحد"""
        df = self.fetcher.get_klines(symbol, timeframe, limit=210)
        if df is None or len(df) < 50:
            return

        # حساب نسبة التغير
        current_price = df["close"].iloc[-1]
        prev_price = df["close"].iloc[-2]
        change_pct = ((current_price - prev_price) / prev_price) * 100

        # إضافة المؤشرات الفنية
        try:
            df = self.analyzer.add_indicators(df)
        except Exception as e:
            logger.debug(f"خطأ في حساب مؤشرات {symbol}/{timeframe}: {e}")
            return

        # ── فحص 1: انفجار السيولة ──
        is_spike, vol_ratio = self.analyzer.detect_volume_spike(
            df, CONFIG["VOLUME_SPIKE_MULTIPLIER"]
        )
        if is_spike:
            msg = self.alerter.format_volume_spike_message(
                symbol, timeframe, current_price, vol_ratio, change_pct
            )
            key = f"volume_{symbol}_{timeframe}"
            sent = await self.alerter.send_alert(msg, key)
            if sent:
                logger.info(f"💧 تنبيه سيولة: {symbol} | {timeframe} | {vol_ratio}x")

        # ── فحص 2: اختراق سعري ──
        is_breakout, breakout_desc = self.analyzer.detect_breakout(df)
        if is_breakout:
            msg = self.alerter.format_breakout_message(
                symbol, timeframe, current_price, breakout_desc, vol_ratio if is_spike else 1.0
            )
            key = f"breakout_{symbol}_{timeframe}"
            sent = await self.alerter.send_alert(msg, key)
            if sent:
                logger.info(f"⚡ تنبيه اختراق: {symbol} | {timeframe} | {breakout_desc}")

        # ── فحص 3: زخم قوي ──
        is_momentum, momentum_desc = self.analyzer.detect_strong_momentum(df)
        if is_momentum:
            msg = self.alerter.format_momentum_message(
                symbol, timeframe, current_price, momentum_desc,
                vol_ratio if is_spike else 1.0
            )
            key = f"momentum_{symbol}_{timeframe}"
            sent = await self.alerter.send_alert(msg, key)
            if sent:
                logger.info(f"🔥 تنبيه زخم: {symbol} | {timeframe} | {momentum_desc}")

        # احترام Rate Limit (تأخير صغير بين كل طلب)
        await asyncio.sleep(0.15)

    async def run_scan_cycle(self):
        """تشغيل دورة مسح كاملة على جميع العملات والفريمات"""
        self.scan_count += 1
        logger.info(f"🔄 بدء دورة المسح #{self.scan_count}")

        symbols = self.fetcher.get_top_usdt_pairs(
            CONFIG["QUOTE_CURRENCY"],
            CONFIG["TOP_PAIRS_LIMIT"]
        )

        if not symbols:
            logger.warning("⚠️ لا توجد عملات للمسح!")
            return

        total = len(symbols) * len(CONFIG["TIMEFRAMES"])
        done = 0

        for symbol in symbols:
            for timeframe in CONFIG["TIMEFRAMES"]:
                try:
                    await self.analyze_symbol(symbol, timeframe)
                except Exception as e:
                    logger.error(f"خطأ في تحليل {symbol}/{timeframe}: {e}")
                done += 1
                if done % 50 == 0:
                    logger.info(f"📊 التقدم: {done}/{total} ({done/total*100:.1f}%)")

        logger.info(f"✅ انتهت دورة المسح #{self.scan_count} | تم فحص {done} زوج-فريم")

    async def send_startup_message(self):
        """إرسال رسالة بدء التشغيل"""
        msg = (
            f"🤖 <b>بوت المسح شغّال!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📋 عدد العملات: {CONFIG['TOP_PAIRS_LIMIT']}\n"
            f"⏱️ الفريمات: {', '.join(CONFIG['TIMEFRAMES'])}\n"
            f"🔁 فترة المسح: كل {CONFIG['SCAN_INTERVAL_SECONDS']} ثانية\n"
            f"💹 الحد الأدنى للحجم: {CONFIG['MIN_VOLUME_USDT']:,} USDT\n"
            f"📈 معامل انفجار السيولة: {CONFIG['VOLUME_SPIKE_MULTIPLIER']}x\n"
            f"⏰ وقت التشغيل: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
        )
        try:
            bot = Bot(token=CONFIG["TELEGRAM_BOT_TOKEN"])
            await bot.send_message(
                chat_id=CONFIG["TELEGRAM_CHAT_ID"],
                text=msg,
                parse_mode="HTML",
            )
            logger.info("📨 تم إرسال رسالة بدء التشغيل")
        except TelegramError as e:
            logger.error(f"❌ فشل إرسال رسالة البداية: {e}")

    async def run(self):
        """الحلقة الرئيسية للمسح المستمر"""
        logger.info("🚀 تشغيل بوت مسح بايننس...")
        await self.send_startup_message()

        while True:
            start_time = time.time()
            try:
                await self.run_scan_cycle()
            except Exception as e:
                logger.error(f"❌ خطأ في دورة المسح: {e}", exc_info=True)

            elapsed = time.time() - start_time
            wait_time = max(0, CONFIG["SCAN_INTERVAL_SECONDS"] - elapsed)

            logger.info(f"⏳ انتظار {wait_time:.0f} ثانية للدورة التالية...")
            await asyncio.sleep(wait_time)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🚀 نقطة الدخول الرئيسية
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if __name__ == "__main__":
    print("=" * 65)
    print("  🤖 Binance Spot Scanner Bot - بوت مسح بايننس الفوري")
    print("=" * 65)

    # التحقق من وجود المفاتيح
    if "YOUR_" in CONFIG["BINANCE_API_KEY"]:
        print("\n⚠️  تنبيه: يرجى إدخال مفاتيح الـ API في قسم CONFIG أعلى الكود!")
        print("   BINANCE_API_KEY    → مفتاح بايننس")
        print("   BINANCE_SECRET_KEY → المفتاح السري لبايننس")
        print("   TELEGRAM_BOT_TOKEN → توكن بوت تليجرام")
        print("   TELEGRAM_CHAT_ID   → معرف الدردشة/القناة")
        exit(1)

    scanner = BinanceScanner()
    try:
        asyncio.run(scanner.run())
    except KeyboardInterrupt:
        logger.info("🛑 تم إيقاف البوت بواسطة المستخدم")
