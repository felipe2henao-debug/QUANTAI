# ============================================================
# 🧠 BOT DE TRADING BTC - SISTEMA QUANT CON IA v2.0
# Autor: Pipe Henao
# Entorno: GitHub Actions (cron cada hora)
# Estrategia: Multi-timeframe 1H/4H | R/R >= 2.0 | IA Gemini
# ============================================================

import ccxt
import pandas as pd
import requests
import matplotlib
matplotlib.use('Agg')          # Backend sin pantalla — DEBE ir antes de pyplot
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import os
import re
import sys
from datetime import datetime
from google import genai
 
# ============================================================
# --- 1. CONFIGURACIÓN ---
# ============================================================
 
API_KEY_GEMINI   = os.environ.get("API_KEY_GEMINI")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
 
# Token de GitHub para descargar el artifact con el historial CSV.
# Agrégalo como secret GH_TOKEN (necesita permiso: actions:read).
GH_TOKEN = os.environ.get("GH_TOKEN", "")
GH_REPO  = os.environ.get("GITHUB_REPOSITORY", "")   # Actions lo inyecta automáticamente
 
if not all([API_KEY_GEMINI, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
    print("❌ Faltan variables de entorno: API_KEY_GEMINI, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID")
    sys.exit(1)
 
client = genai.Client(api_key=API_KEY_GEMINI)
MODELO = "models/gemini-2.5-flash"
 
ARCHIVO_CSV    = "Bitacora_Trading_IA.csv"
ARCHIVO_IMAGEN = "chart_analisis.png"
MAX_HISTORIAL  = 5
SIMBOLO        = "BTC/USDT"
LIMITE_VELAS   = 210  # Suficiente para EMA 200 + margen
 
 
# ============================================================
# --- 2. HISTORIAL PERSISTENTE VÍA GITHUB ARTIFACTS ---
# ============================================================
# GitHub Actions no tiene disco persistente entre runs.
# Solución: al inicio se descarga el último artifact "bitacora-*",
# y al final el workflow.yml lo sube de nuevo con upload-artifact.
 
def descargar_historial_csv():
    """
    Descarga el artifact más reciente llamado 'bitacora-*' y lo
    extrae como Bitacora_Trading_IA.csv en el directorio de trabajo.
    Si falla o no existe, el bot arranca sin historial (OK para primera ejecución).
    """
    if not GH_TOKEN or not GH_REPO:
        print("ℹ️  GH_TOKEN o GITHUB_REPOSITORY no configurados — sin historial previo.")
        return
 
    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"https://api.github.com/repos/{GH_REPO}/actions/artifacts?per_page=10&name=bitacora"
 
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        artifacts = [a for a in resp.json().get("artifacts", []) if not a.get("expired", True)]
        if not artifacts:
            print("ℹ️  Sin artifacts previos — primera ejecución.")
            return
 
        ultimo    = sorted(artifacts, key=lambda a: a["created_at"], reverse=True)[0]
        r_zip     = requests.get(ultimo["archive_download_url"], headers=headers, timeout=30)
        r_zip.raise_for_status()
 
        import zipfile, io
        with zipfile.ZipFile(io.BytesIO(r_zip.content)) as z:
            csvs = [n for n in z.namelist() if n.endswith(".csv")]
            if not csvs:
                print("⚠️  El artifact no contiene CSV.")
                return
            with z.open(csvs[0]) as f_in, open(ARCHIVO_CSV, "wb") as f_out:
                f_out.write(f_in.read())
 
        filas = pd.read_csv(ARCHIVO_CSV, sep=";", encoding="utf-8-sig").shape[0]
        print(f"✅ Historial restaurado: {filas} registros — {ultimo['name']} ({ultimo['created_at'][:10]})")
 
    except Exception as e:
        print(f"⚠️  No se pudo restaurar historial: {e}")
 
 
def obtener_historial_para_ia():
    if not os.path.isfile(ARCHIVO_CSV):
        return "Sin historial previo."
    try:
        df = pd.read_csv(ARCHIVO_CSV, sep=";", encoding="utf-8-sig")
        if df.empty:
            return "Sin historial previo."
        cols = [c for c in ["Fecha", "Precio_BTC", "Senal_IA", "RR_Calculado"] if c in df.columns]
        return df.tail(MAX_HISTORIAL)[cols].to_string(index=False)
    except Exception as e:
        return f"Error leyendo historial: {e}"
 
 
# ============================================================
# --- 3. TELEGRAM ---
# ============================================================
 
def _telegram_post(endpoint, **kwargs):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{endpoint}"
    try:
        r = requests.post(url, timeout=20, **kwargs)
        if not r.ok:
            print(f"⚠️  Telegram {endpoint}: {r.status_code} {r.text[:120]}")
        return r.ok
    except Exception as e:
        print(f"❌ Telegram {endpoint}: {e}")
        return False
 
 
def enviar_alerta_telegram(mensaje, ruta_imagen=None):
    if ruta_imagen and os.path.exists(ruta_imagen):
        with open(ruta_imagen, "rb") as f:
            _telegram_post("sendPhoto",
                           data={"chat_id": TELEGRAM_CHAT_ID},
                           files={"photo": f})
    _telegram_post("sendMessage",
                   data={"chat_id": TELEGRAM_CHAT_ID,
                         "text": mensaje,
                         "parse_mode": "Markdown"})
 
 
def enviar_error_telegram(msg_error):
    texto = (f"🚨 *Bot Trading — Error*\n\n"
             f"`{msg_error}`\n\n"
             f"_{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC_")
    _telegram_post("sendMessage",
                   data={"chat_id": TELEGRAM_CHAT_ID,
                         "text": texto,
                         "parse_mode": "Markdown"})
 
 
# ============================================================
# --- 4. DATOS DE MERCADO E INDICADORES ---
# ============================================================
 
def calcular_indicadores(df):
    c = df["close"]
 
    # Bollinger Bands (20, 2)
    sma20        = c.rolling(20).mean()
    std20        = c.rolling(20).std()
    df["SMA_20"] = sma20
    df["Upper"]  = sma20 + std20 * 2
    df["Lower"]  = sma20 - std20 * 2
 
    # RSI (14)
    delta       = c.diff()
    gain        = delta.clip(lower=0).rolling(14).mean()
    loss        = (-delta.clip(upper=0)).rolling(14).mean()
    df["RSI"]   = 100 - 100 / (1 + gain / loss)
 
    # MACD (12, 26, 9)
    ema12             = c.ewm(span=12, adjust=False).mean()
    ema26             = c.ewm(span=26, adjust=False).mean()
    df["MACD"]        = ema12 - ema26
    df["Signal_MACD"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"]   = df["MACD"] - df["Signal_MACD"]
 
    # EMAs de tendencia
    df["EMA_50"]  = c.ewm(span=50,  adjust=False).mean()
    df["EMA_200"] = c.ewm(span=200, adjust=False).mean()
 
    # ATR (14)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - c.shift()).abs(),
        (df["low"]  - c.shift()).abs(),
    ], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(14).mean()
 
    return df
 
 
def obtener_datos():
    exchange = ccxt.kraken()
    exchange.enableRateLimit = True
 
    def _fetch(tf):
        ohlcv = exchange.fetch_ohlcv(SIMBOLO, tf, limit=LIMITE_VELAS)
        df = pd.DataFrame(ohlcv, columns=["time","open","high","low","close","vol"])
        df["time"] = pd.to_datetime(df["time"], unit="ms")
        return calcular_indicadores(df)
 
    df_1h = _fetch("1h")
    df_4h = _fetch("4h")
    print(f"✅ Datos: 1H={len(df_1h)} velas | 4H={len(df_4h)} velas")
    return df_1h, df_4h
 
 
def obtener_fear_and_greed():
    try:
        d = requests.get("https://api.alternative.me/fng/", timeout=10).json()["data"][0]
        return f"{d['value_classification']} ({d['value']}/100)"
    except:
        return "Neutral (50/100)"
 
 
# ============================================================
# --- 5. VALIDACIÓN DE R/R POR CÓDIGO ---
# ============================================================
 
def extraer_niveles_ia(texto):
    def _buscar(patron):
        m = re.search(patron, texto, re.IGNORECASE)
        if not m:
            return None
        raw    = m.group(1).replace(",", "")
        partes = raw.split(".")
        if len(partes) > 2:
            raw = "".join(partes[:-1]) + "." + partes[-1]
        try:
            return float(raw)
        except ValueError:
            return None
 
    entrada = _buscar(r"[Ee]ntrada\s*[:\*]+\s*\$?([\d,\.]+)")
    sl      = _buscar(r"(?:SL|Stop[- ]?Loss)\s*[:\*]+\s*\$?([\d,\.]+)")
    tp      = _buscar(r"(?:TP|Take[- ]?Profit)\s*[:\*]+\s*\$?([\d,\.]+)")
    return entrada, sl, tp
 
 
def calcular_rr(entrada, sl, tp, es_compra):
    if None in (entrada, sl, tp):
        return 0.0
    riesgo    = (entrada - sl) if es_compra else (sl - entrada)
    beneficio = (tp - entrada) if es_compra else (entrada - tp)
    if riesgo <= 0 or beneficio <= 0:
        return 0.0
    return round(beneficio / riesgo, 2)
 
 
# ============================================================
# --- 6. CEREBRO IA — PROMPT MULTI-TIMEFRAME ---
# ============================================================
 
def consultar_ia(df_1h, df_4h, macro):
    u1 = df_1h.iloc[-1]
    u4 = df_4h.iloc[-1]
    atr = round(float(u1["ATR"]), 0)
 
    tendencia_ema  = "ALCISTA" if u4["EMA_50"]  > u4["EMA_200"]       else "BAJISTA"
    tendencia_macd = "ALCISTA" if u4["MACD"]    > u4["Signal_MACD"]   else "BAJISTA"
    historial      = obtener_historial_para_ia()
 
    prompt = f"""
Actúa como un Senior Quant Strategist especializado en futuros de BTC/USDT.
Tu objetivo educativo: enseñar a identificar trades de alta probabilidad con R/R >= 1:2.
 
=== ANÁLISIS MULTI-TIMEFRAME ===
 
[4H — Tendencia macro]
  Precio       : ${float(u4["close"]):,.0f}
  EMA 50/200   : ${float(u4["EMA_50"]):,.0f} / ${float(u4["EMA_200"]):,.0f} → {tendencia_ema}
  RSI          : {float(u4["RSI"]):.1f}
  MACD / Signal: {float(u4["MACD"]):.1f} / {float(u4["Signal_MACD"]):.1f} → {tendencia_macd}
 
[1H — Timing de entrada]
  Precio       : ${float(u1["close"]):,.0f}
  RSI          : {float(u1["RSI"]):.1f}
  MACD / Signal: {float(u1["MACD"]):.1f} / {float(u1["Signal_MACD"]):.1f}
  Bollinger    : Upper ${float(u1["Upper"]):,.0f} / Lower ${float(u1["Lower"]):,.0f}
  ATR(14)      : ${atr:,.0f}  ← usa esto para dimensionar SL y TP
 
[Sentimiento]
  Fear & Greed : {macro}
 
[Historial reciente de señales]
{historial}
 
=== REGLAS OBLIGATORIAS ===
1. ALINEACION: Solo operar si 1H coincide con 4H.
   - 4H ALCISTA  → considerar solo [COMPRA]
   - 4H BAJISTA  → considerar solo [VENTA]
   - Contradiccion → [ESPERA]
2. R/R: Usa el ATR para calcular niveles:
   - SL  aprox 1.0x ATR desde la entrada
   - TP  aprox 2.0x ATR desde la entrada (minimo)
   - Si R/R calculado < 2.0 → [ESPERA]
3. HISTORIAL: Si la señal repite dirección sin nuevo catalizador → sé más conservador.
 
=== ESTRUCTURA DE RESPUESTA (exacta) ===
- Decision: [COMPRA] / [VENTA] / [ESPERA]
- Entrada: $PRECIO
- SL: $PRECIO
- TP: $PRECIO
- Ratio R/R: X.X
- Alineacion Timeframes: SI / NO
- Tesis: (max 3 lineas — explica el razonamiento de forma didactica)
"""
    try:
        resp = client.models.generate_content(model=MODELO, contents=prompt)
        return resp.text
    except Exception as e:
        return f"ERROR IA: {e}"
 
 
# ============================================================
# --- 7. GRÁFICO ---
# ============================================================
 
def generar_grafico(df_1h, entrada=None, sl=None, tp=None):
    df = df_1h.tail(72).copy()
 
    fig, axes = plt.subplots(
        3, 1, figsize=(14, 9),
        gridspec_kw={"height_ratios": [4, 1.5, 1.5]},
        facecolor="#0d1117"
    )
    ax1, ax2, ax3 = axes
 
    BG, GRID, TICK = "#0d1117", "#21262d", "#8b949e"
    for ax in axes:
        ax.set_facecolor(BG)
        ax.tick_params(colors=TICK, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(GRID)
        ax.grid(color=GRID, linewidth=0.5, alpha=0.7)
 
    # Panel 1 — Precio + indicadores + niveles
    ax1.plot(df["time"], df["close"],  color="#e6edf3", lw=1.2, label="BTC/USDT", zorder=5)
    ax1.plot(df["time"], df["Upper"],  color="#388bfd", lw=0.7, alpha=0.5, label="BB Superior")
    ax1.plot(df["time"], df["Lower"],  color="#388bfd", lw=0.7, alpha=0.5, label="BB Inferior")
    ax1.fill_between(df["time"], df["Upper"], df["Lower"], alpha=0.04, color="#388bfd")
    ax1.plot(df["time"], df["SMA_20"], color="#f78166", lw=0.7, alpha=0.7, ls="--", label="SMA 20")
    ax1.plot(df["time"], df["EMA_50"], color="#ffa657", lw=0.8, alpha=0.8, ls="--", label="EMA 50")
 
    if all(v is not None for v in (entrada, sl, tp)):
        ax1.axhline(entrada, color="#ffffff", lw=1.2, ls="--", alpha=0.9, label=f"Entrada ${entrada:,.0f}")
        ax1.axhline(sl,      color="#f85149", lw=1.2, ls="--", alpha=0.9, label=f"SL ${sl:,.0f}")
        ax1.axhline(tp,      color="#3fb950", lw=1.2, ls="--", alpha=0.9, label=f"TP ${tp:,.0f}")
        ax1.fill_between(df["time"], sl,      entrada, alpha=0.08, color="#f85149")
        ax1.fill_between(df["time"], entrada, tp,      alpha=0.08, color="#3fb950")
 
    ax1.set_title(f"BTC/USDT — {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC",
                  color="#e6edf3", fontsize=11, pad=10)
    ax1.legend(loc="upper left", fontsize=7, facecolor="#161b22", edgecolor=GRID, labelcolor=TICK)
    ax1.set_ylabel("Precio (USDT)", color=TICK, fontsize=8)
 
    # Panel 2 — MACD
    ax2.plot(df["time"], df["MACD"],        color="#388bfd", lw=1,   label="MACD")
    ax2.plot(df["time"], df["Signal_MACD"], color="#f78166", lw=0.8, label="Signal")
    colores = ["#3fb950" if v >= 0 else "#f85149" for v in df["MACD_Hist"]]
    ax2.bar(df["time"], df["MACD_Hist"], color=colores, alpha=0.6, width=0.03)
    ax2.axhline(0, color=TICK, lw=0.5)
    ax2.set_ylabel("MACD", color=TICK, fontsize=8)
    ax2.legend(loc="upper left", fontsize=7, facecolor="#161b22", edgecolor=GRID, labelcolor=TICK)
 
    # Panel 3 — RSI
    ax3.plot(df["time"], df["RSI"], color="#a371f7", lw=1)
    ax3.axhline(70, color="#f85149", lw=0.7, ls="--", alpha=0.7)
    ax3.axhline(30, color="#3fb950", lw=0.7, ls="--", alpha=0.7)
    ax3.fill_between(df["time"], 70, df["RSI"], where=(df["RSI"] >= 70), alpha=0.2, color="#f85149")
    ax3.fill_between(df["time"], df["RSI"], 30,  where=(df["RSI"] <= 30), alpha=0.2, color="#3fb950")
    ax3.set_ylim(0, 100)
    ax3.set_yticks([30, 70])
    ax3.set_ylabel("RSI", color=TICK, fontsize=8)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %Hh"))
    plt.xticks(rotation=30, color=TICK, fontsize=7)
 
    plt.tight_layout(pad=1.5)
    plt.savefig(ARCHIVO_IMAGEN, dpi=130, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"✅ Gráfico guardado: {ARCHIVO_IMAGEN}")
    return ARCHIVO_IMAGEN
 
 
# ============================================================
# --- 8. PERSISTENCIA CSV ---
# ============================================================
 
def guardar_en_csv(df_1h, macro, analisis, rr_calculado):
    try:
        senal = "NEUTRAL"
        if "[COMPRA]" in analisis.upper(): senal = "COMPRA"
        elif "[VENTA]" in analisis.upper(): senal = "VENTA"
 
        registro = {
            "Fecha"             : datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "Precio_BTC"        : round(float(df_1h["close"].iloc[-1]), 2),
            "RSI_1H"            : round(float(df_1h["RSI"].iloc[-1]),   2),
            "MACD_1H"           : round(float(df_1h["MACD"].iloc[-1]),  2),
            "Sentimiento_Macro" : macro,
            "Senal_IA"          : senal,
            "RR_Calculado"      : rr_calculado,
            "Analisis_Completo" : analisis.replace("\n", " ").strip(),
        }
        escribir_header = not os.path.isfile(ARCHIVO_CSV)
        pd.DataFrame([registro]).to_csv(
            ARCHIVO_CSV, mode="a", header=escribir_header,
            index=False, encoding="utf-8-sig", sep=";"
        )
        print(f"✅ CSV guardado: {senal} | R/R: {rr_calculado}")
    except Exception as e:
        print(f"❌ Error CSV: {e}")
 
 
# ============================================================
# --- 9. FLUJO PRINCIPAL (una sola ejecución) ---
# ============================================================
 
def ejecutar_analisis():
    print(f"\n{'='*55}")
    print(f"  Analisis — {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"{'='*55}")
 
    # 0. Restaurar historial desde el artifact del run anterior
    descargar_historial_csv()
 
    # 1. Datos de mercado
    try:
        df_1h, df_4h = obtener_datos()
    except Exception as e:
        msg = f"Error obteniendo datos de Kraken: {e}"
        print(f"❌ {msg}")
        enviar_error_telegram(msg)
        sys.exit(1)
 
    # 2. Sentimiento macro
    macro = obtener_fear_and_greed()
    print(f"📊 Fear & Greed: {macro}")
 
    # 3. Consulta a la IA
    analisis = consultar_ia(df_1h, df_4h, macro)
    print(f"\n🤖 IA:\n{analisis}\n")
 
    # 4. Parsear niveles y calcular R/R
    es_compra = "[COMPRA]" in analisis.upper()
    es_venta  = "[VENTA]"  in analisis.upper()
    entrada, sl, tp = extraer_niveles_ia(analisis)
    rr = calcular_rr(entrada, sl, tp, es_compra)
    print(f"📐 Entrada={entrada} | SL={sl} | TP={tp} | R/R={rr}")
 
    senal_valida = (es_compra or es_venta) and rr >= 2.0
 
    # 5. Siempre guardar CSV (el workflow lo sube como artifact al finalizar)
    guardar_en_csv(df_1h, macro, analisis, rr)
 
    # 6. Notificar por Telegram solo si la señal es válida
    if senal_valida:
        tipo = "🟢 COMPRA" if es_compra else "🔴 VENTA"
        img  = generar_grafico(df_1h, entrada, sl, tp)
        msg  = (
            f"*{tipo} — BTC/USDT*\n"
            f"🕐 `{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC`\n\n"
            f"{analisis}\n\n"
            f"📐 *R/R verificado: {rr}*\n"
            f"📊 Fear & Greed: {macro}"
        )
        enviar_alerta_telegram(msg, img)
        print(f"📨 Alerta enviada: {tipo} | R/R: {rr}")
    elif es_compra or es_venta:
        print(f"⚠️  Señal descartada — R/R={rr} < 2.0")
    else:
        print("🔕 Sin oportunidad (ESPERA)")
 
    print("\n✅ Ejecucion completada — el workflow subira el CSV como artifact.")
 
 
if __name__ == "__main__":
    ejecutar_analisis()
