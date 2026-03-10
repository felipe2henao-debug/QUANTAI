# ============================================================
# 🧠 BOT DE TRADING BTC - SISTEMA QUANT CON IA
# Autor: Pipe Henao
# Plataforma: GitHub Actions (ejecución automática cada hora)
# ============================================================

import ccxt
import pandas as pd
import requests
import matplotlib
matplotlib.use('Agg')  # ← Necesario en servidores sin pantalla
import matplotlib.pyplot as plt
import time
import os
from datetime import datetime
from google import genai

# --- 1. CONFIGURACIÓN — Lee desde variables de entorno (GitHub Secrets) ---
API_KEY_GEMINI   = os.environ.get("API_KEY_GEMINI")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Validar que las claves existan
if not all([API_KEY_GEMINI, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
    raise ValueError("❌ Faltan variables de entorno. Revisa los GitHub Secrets.")

client = genai.Client(api_key=API_KEY_GEMINI)
MODELO = "models/gemini-2.5-flash"

# Configuración de comportamiento
SOLO_CON_SENAL  = True   # 🔔 Telegram solo si hay COMPRA o VENTA
GUARDAR_SIEMPRE = True   # 💾 CSV siempre (incluyendo ESPERA)

# ============================================================
# --- 2. FUNCIONES DE SOPORTE ---
# ============================================================

def guardar_en_csv(datos, macro, analisis, archivo="Bitacora_Trading_IA.csv"):
    try:
        senal = "NEUTRAL"
        if "COMPRA" in analisis.upper(): senal = "COMPRA"
        elif "VENTA" in analisis.upper(): senal = "VENTA"

        registro = {
            "Fecha"             : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Precio_BTC"        : datos['close'].iloc[-1],
            "RSI"               : round(datos['RSI'].iloc[-1], 2),
            "Sentimiento_Macro" : macro,
            "Senal_IA"          : senal,
            "Analisis_Completo" : analisis.replace("\n", " ").strip()
        }

        df_log = pd.DataFrame([registro])
        if not os.path.isfile(archivo):
            df_log.to_csv(archivo, index=False, encoding='utf-8-sig', sep=';')
        else:
            df_log.to_csv(archivo, mode='a', header=False, index=False, encoding='utf-8-sig', sep=';')

        print(f"💾 Log guardado en '{archivo}'")
    except Exception as e:
        print(f"❌ Error CSV: {e}")


def enviar_alerta_telegram(mensaje_formateado, ruta_imagen=None):
    url_base = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    try:
        print("📲 Enviando a Telegram...", end=" ")

        if ruta_imagen and os.path.exists(ruta_imagen):
            with open(ruta_imagen, "rb") as f:
                requests.post(
                    f"{url_base}/sendPhoto",
                    data={"chat_id": TELEGRAM_CHAT_ID},
                    files={"photo": f},
                    timeout=15
                )

        data_msg = {
            "chat_id"    : TELEGRAM_CHAT_ID,
            "text"       : mensaje_formateado,
            "parse_mode" : "Markdown"
        }
        r = requests.post(f"{url_base}/sendMessage", data=data_msg, timeout=15)

        if r.json().get("ok"):
            print("✅ Enviado.")
        else:
            print(f"\n⚠️ Reintentando en texto plano...", end=" ")
            del data_msg["parse_mode"]
            r2 = requests.post(f"{url_base}/sendMessage", data=data_msg, timeout=15)
            print("✅" if r2.json().get("ok") else f"❌ {r2.json().get('description')}")

    except Exception as e:
        print(f"❌ Error Telegram: {e}")


def obtener_fear_and_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/", timeout=10)
        d = r.json()['data'][0]
        return f"{d['value_classification']} ({d['value']}/100)"
    except:
        return "Neutral (50/100)"

# ============================================================
# --- 3. DATOS Y CÁLCULOS TÉCNICOS ---
# ============================================================

def calcular_indicadores(df):
    df['SMA_20']  = df['close'].rolling(window=20).mean()
    df['Std_Dev'] = df['close'].rolling(window=20).std()
    df['Upper']   = df['SMA_20'] + (df['Std_Dev'] * 2)
    df['Lower']   = df['SMA_20'] - (df['Std_Dev'] * 2)

    delta = df['close'].diff()
    gain  = delta.where(delta > 0, 0).rolling(14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs    = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    return df


def obtener_datos():
    try:
        print("📡 Conectando a Kraken...", end=" ")
        exchange = ccxt.kraken()
        ohlcv    = exchange.fetch_ohlcv('BTC/USDT', '1h', limit=50)
        df       = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        print("✅")
        return calcular_indicadores(df)
    except Exception as e:
        print(f"❌ Error Kraken: {e}")
        return None

# ============================================================
# --- 4. CEREBRO IA ---
# ============================================================

def consultar_ia(df, macro):
    ultimo = df.iloc[-1]

    prompt = f"""
    Actua como un Senior Quant Strategist experto en gestion de riesgo.

    DATOS DE MERCADO (1H):
    - Precio BTC : ${ultimo['close']:,.0f}
    - RSI        : {ultimo['RSI']:.1f}
    - Bollinger  : [{ultimo['Lower']:,.0f} - {ultimo['Upper']:,.0f}]
    - SMA 20     : ${ultimo['SMA_20']:,.0f}
    - Sentimiento: {macro}

    TAREA:
    1. SINCRONIA : RSI y Bandas confirman el sentimiento {macro}?
    2. DECISION  : Define exactamente una opcion → [COMPRA | VENTA | ESPERA]
    3. TESIS     : Justifica en maximo 2 lineas tecnicas y directas.
    4. NIVELES   : Entrada, stop-loss y take-profit para riesgo medio y alto.

    REGLA ESTRICTA: Si RSI entre 40-60 y precio no toca bandas → ESPERA obligatorio.
    """

    espera = 15
    for intento in range(4):
        try:
            print(f"🤖 Consultando {MODELO}...", end=" ")
            resp = client.models.generate_content(model=MODELO, contents=prompt)
            print("✅")
            return resp.text
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "503" in error_str or "quota" in error_str.lower():
                codigo = "429" if "429" in error_str else "503"
                print(f"\n⏳ Error {codigo} — esperando {espera}s... (Intento {intento+1}/4)")
                time.sleep(espera)
                espera *= 2
            else:
                print(f"\n❌ Error IA: {e}")
                return f"ERROR IA: {e}"

    return "❌ IA no disponible tras 4 intentos."

# ============================================================
# --- 5. GRAFICO ---
# ============================================================

def generar_grafico(df, analisis):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7),
                                    gridspec_kw={'height_ratios': [3, 1]})
    plt.style.use('dark_background')
    fig.patch.set_facecolor('#0d1117')

    ax1.set_facecolor('#0d1117')
    ax1.plot(df['time'], df['close'],  color='white',   linewidth=1.5, label='BTC/USDT')
    ax1.plot(df['time'], df['Upper'],  color='#00ff88', alpha=0.5, linestyle='--', linewidth=1, label='BB Superior')
    ax1.plot(df['time'], df['Lower'],  color='#ff4444', alpha=0.5, linestyle='--', linewidth=1, label='BB Inferior')
    ax1.plot(df['time'], df['SMA_20'], color='#ffaa00', alpha=0.7, linewidth=1,   label='SMA 20')
    ax1.fill_between(df['time'], df['Upper'], df['Lower'], color='gray', alpha=0.05)
    ax1.legend(loc='upper left', fontsize=8)
    ax1.set_ylabel('Precio (USDT)', color='gray')
    ax1.tick_params(colors='gray')
    ax1.grid(color='#1e2a38', linewidth=0.5)

    ax2.set_facecolor('#0d1117')
    ax2.plot(df['time'], df['RSI'], color='#00aaff', linewidth=1.5)
    ax2.axhline(70, color='#ff4444', linestyle='--', alpha=0.6, linewidth=0.8)
    ax2.axhline(30, color='#00ff88', linestyle='--', alpha=0.6, linewidth=0.8)
    ax2.axhline(50, color='gray',    linestyle=':',  alpha=0.4, linewidth=0.8)
    ax2.fill_between(df['time'], df['RSI'], 50, where=(df['RSI'] >= 50), color='#00ff88', alpha=0.1)
    ax2.fill_between(df['time'], df['RSI'], 50, where=(df['RSI'] < 50),  color='#ff4444', alpha=0.1)
    ax2.set_ylim(0, 100)
    ax2.set_ylabel('RSI', color='gray')
    ax2.tick_params(colors='gray')
    ax2.grid(color='#1e2a38', linewidth=0.5)

    titulo = "-- NEUTRAL / ESPERA"
    color  = "yellow"
    if "COMPRA" in analisis.upper(): titulo, color = ">> SENAL DE COMPRA", "lime"
    elif "VENTA" in analisis.upper(): titulo, color = "vv SENAL DE VENTA",  "red"

    fig.suptitle(
        f"{titulo}  |  BTC: ${df['close'].iloc[-1]:,.0f}  |  RSI: {df['RSI'].iloc[-1]:.1f}",
        color=color, fontsize=13, fontweight='bold'
    )

    plt.tight_layout()
    nombre = "chart_analisis.png"
    plt.savefig(nombre, dpi=150, facecolor=fig.get_facecolor())
    plt.close()
    return nombre

# ============================================================
# --- 6. MENSAJE TELEGRAM ---
# ============================================================

def formatear_mensaje_ux(df, macro, analisis):
    precio = df['close'].iloc[-1]
    rsi    = df['RSI'].iloc[-1]

    icono  = "🟡"
    accion = "ESPERAR"
    if "COMPRA" in analisis.upper(): icono, accion = "🟢", "LONG / COMPRA"
    elif "VENTA" in analisis.upper(): icono, accion = "🔴", "SHORT / VENTA"

    clean = (analisis
             .replace("*", "").replace("#", "")
             .replace("`", "").replace("_", " ")
             .strip())

    mensaje = f"""{icono} *QUANT STRATEGY REPORT*
Hora: {datetime.now().strftime("%Y-%m-%d %H:%M")} UTC
━━━━━━━━━━━━━━━━━━
📊 *METRICAS CLAVE*
Precio BTC : `${precio:,.2f}`
RSI (1h)   : `{rsi:.1f}`
Senal      : *{accion}*
F&G Index  : _{macro}_

🧠 *ANALISIS IA*
━━━━━━━━━━━━━━━━━━
{clean}

━━━━━━━━━━━━━━━━━━
_Gemini 2.5 Flash | Kraken | Pipe Henao_"""

    return mensaje

# ============================================================
# --- 7. EJECUCION PRINCIPAL ---
# ============================================================

def ejecutar_analisis():
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*50}")
    print(f"  SISTEMA DE TRADING QUANT - BTC/USDT")
    print(f"  Hora: {ahora}")
    print(f"{'='*50}")

    df    = obtener_datos()
    macro = obtener_fear_and_greed()
    print(f"Fear & Greed: {macro}")

    if df is None:
        print("❌ Error critico: sin datos de Kraken.")
        return

    analisis = consultar_ia(df, macro)

    senal = "NEUTRAL"
    if "COMPRA" in analisis.upper(): senal = "COMPRA"
    elif "VENTA" in analisis.upper(): senal = "VENTA"

    if GUARDAR_SIEMPRE:
        guardar_en_csv(df, macro, analisis)

    if not SOLO_CON_SENAL or senal in ["COMPRA", "VENTA"]:
        img = generar_grafico(df, analisis)
        msg = formatear_mensaje_ux(df, macro, analisis)
        enviar_alerta_telegram(msg, img)
    else:
        print(f"🔕 Senal: {senal} — Telegram silenciado.")

    print(f"\n  CICLO COMPLETADO")
    print(f"{'='*50}")


if __name__ == "__main__":
    ejecutar_analisis()
