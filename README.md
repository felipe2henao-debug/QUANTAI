# 🧠 Bot de Trading BTC — Quant IA

Bot automático que analiza BTC/USDT cada hora usando Gemini AI y envía alertas por Telegram.

---

## ⚙️ Instalación en GitHub Actions (100% Gratis)

### Paso 1 — Subir archivos a GitHub

1. Ve a → https://github.com/new
2. Crea un repositorio nuevo (puede ser privado ✅)
3. Sube estos archivos:
   - `bot_trading.py`
   - `requirements.txt`
   - `.github/workflows/trading_bot.yml`

---

### Paso 2 — Agregar las claves secretas

1. En tu repositorio ve a:
   **Settings → Secrets and variables → Actions → New repository secret**

2. Agrega estos 3 secrets uno por uno:

| Nombre | Valor |
|--------|-------|
| `API_KEY_GEMINI` | Tu clave de Google AI Studio |
| `TELEGRAM_TOKEN` | Token de tu bot de Telegram |
| `TELEGRAM_CHAT_ID` | ID de tu canal/grupo |

---

### Paso 3 — Activar el workflow

1. Ve a la pestaña **Actions** en tu repositorio
2. Si aparece un aviso, haz clic en **"I understand my workflows, go ahead and enable them"**
3. El bot se ejecutará automáticamente cada hora ✅

---

### Paso 4 — Prueba manual

1. Ve a **Actions → Bot Trading BTC**
2. Haz clic en **"Run workflow"** → **"Run workflow"**
3. Verifica que llegue el mensaje a Telegram

---

## 📊 ¿Qué hace el bot?

- Obtiene datos OHLCV de BTC/USDT desde Kraken (velas de 1h)
- Calcula RSI, Bandas de Bollinger y SMA 20
- Consulta el índice Fear & Greed
- Analiza todo con Gemini 2.5 Flash
- **Solo envía alerta a Telegram si detecta COMPRA o VENTA**
- Guarda todos los análisis en `Bitacora_Trading_IA.csv`

---

## ⏰ Horario de ejecución

El cron `0 * * * *` ejecuta el bot cada hora en punto:
- 00:00, 01:00, 02:00 ... 23:00 UTC

Para cambiar el intervalo edita el archivo `.github/workflows/trading_bot.yml`:
```yaml
- cron: '0 */2 * * *'   # Cada 2 horas
- cron: '0 */4 * * *'   # Cada 4 horas
- cron: '0 9,21 * * *'  # Solo a las 9am y 9pm UTC
```

---

## 📁 Bitácora CSV

Cada ejecución guarda un registro en `Bitacora_Trading_IA.csv`.
Puedes descargarla desde **Actions → tu ejecución → Artifacts**.

---

## 🔑 Obtener las claves

- **Gemini API Key** → https://aistudio.google.com/apikey
- **Telegram Bot** → Habla con @BotFather en Telegram
- **Chat ID** → Habla con @userinfobot en Telegram

---

*Desarrollado por Pipe Henao | Powered by Gemini 2.5 Flash + Kraken*
