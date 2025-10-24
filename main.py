import telebot
from telebot import types
import sqlite3
import uuid
from datetime import datetime
import html
import re
import time
import os
import requests
import json
from bs4 import BeautifulSoup
import threading
import traceback

# Configuración
TOKEN = "8400947960:AAGGXHezQbmUqk6AOpgT1GqMLaF-rMvVp9Y"
GROUP_CHAT_ID = "-4932107704"
ADMIN_ID = 1853800972
bot = telebot.TeleBot(TOKEN)

# Configuración de la API ElToque
ELTOQUE_API_URL = "https://tasas.eltoque.com/v1/trmi"
ELTOQUE_API_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJmcmVzaCI6ZmFsc2UsImlhdCI6MTc2MTE0NzQzMSwianRpIjoiMTc4ZGIyZWYtNWIzNy00MzJhLTkwYTktNTczZDBiOGE2N2ViIiwidHlwZSI6ImFjY2VzcyIsInN1YiI6IjY4ZjgyZjM1ZTkyYmU3N2VhMzAzODJhZiIsIm5iZiI6MTc2MTE0NzQzMSwiZXhwIjoxNzkyNjgzNDMxfQ.gTIXoSudOyo99vLLBap74_5UfdSRdOLluXekb0F1cPg"

# =============================================================================
# SISTEMA DE CACHÉ SIMPLIFICADO Y FUNCIONAL
# =============================================================================

# Variables globales para el caché
rates_cache = None
last_api_call = 0
CACHE_DURATION = 300  # 5 minutos

def get_eltoque_rates_cached():
    """
    Sistema de caché simplificado y robusto
    """
    global rates_cache, last_api_call
    
    current_time = time.time()
    
    # Si hay caché y no ha expirado, usarlo
    if rates_cache and (current_time - last_api_call) < CACHE_DURATION:
        print(f"✅ Usando caché (edad: {current_time - last_api_call:.1f}s)")
        return rates_cache
    
    print("🔄 Actualizando caché desde API...")
    
    # Obtener nuevas tasas
    new_rates = get_eltoque_rates()
    
    if new_rates:
        rates_cache = new_rates
        last_api_call = current_time
        print(f"✅ Caché actualizado con {len(new_rates)} tasas")
        return rates_cache
    else:
        # Si la API falla pero tenemos caché anterior, usarlo
        if rates_cache:
            print("⚠️ API falló, usando caché anterior")
            return rates_cache
        else:
            # Si no hay caché y la API falla, usar valores por defecto
            print("⚠️ Sin caché y API falló, usando valores por defecto")
            default_rates = {
                'USD': 490,
                'USDT_TRC20': 517, 
                'MLC': 200,
                'ECU': 540,
                'BTC': 490,
                'TRX': 180
            }
            rates_cache = default_rates
            last_api_call = current_time
            return default_rates

def get_eltoque_rates():
    """
    Función simplificada para obtener tasas de la API
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        params = {
            'date_from': f"{today} 00:00:01",
            'date_to': f"{today} 23:59:01"
        }
        
        headers = {
            'accept': '*/*',
            'Authorization': f'Bearer {ELTOQUE_API_TOKEN}',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        print("🔗 Conectando a API ElToque...")
        response = requests.get(ELTOQUE_API_URL, params=params, headers=headers, timeout=10)
        
        if response.status_code != 200:
            print(f"❌ Error HTTP {response.status_code}")
            return None
            
        data = response.json()
        
        if 'tasas' not in data:
            print("❌ No se encontró campo 'tasas'")
            return None
        
        # Procesar tasas
        rates = {}
        for currency, rate in data['tasas'].items():
            try:
                rates[currency] = float(rate)
            except (ValueError, TypeError):
                continue
        
        if rates:
            print(f"✅ {len(rates)} tasas obtenidas")
            return rates
        else:
            print("❌ No se pudieron procesar las tasas")
            return None
            
    except Exception as e:
        print(f"❌ Error en API: {e}")
        return None

def get_cup_usd_rate():
    """Obtiene tasa USD de forma robusta"""
    try:
        rates = get_eltoque_rates_cached()
        return rates.get('USD') or rates.get('USDT_TRC20', 490)
    except:
        return 490

def get_cup_eur_rate():
    """Obtiene tasa EUR de forma robusta"""
    try:
        rates = get_eltoque_rates_cached()
        return rates.get('ECU') or rates.get('EUR', 540)
    except:
        return 540

# =============================================================================
# FUNCIONES PRINCIPALES CORREGIDAS
# =============================================================================

pending_deposits = {}
pending_withdrawals = {}

def send_group_notification(message, photo_id=None):
    """Envía notificación al grupo de forma segura"""
    try:
        if photo_id:
            bot.send_photo(GROUP_CHAT_ID, photo=photo_id, caption=message, parse_mode='Markdown')
        else:
            bot.send_message(GROUP_CHAT_ID, text=message, parse_mode='Markdown')
        return True
    except Exception as e:
        print(f"❌ Error enviando notificación: {e}")
        return False

def init_db():
    """Inicializa la base de datos"""
    conn = sqlite3.connect('cubawallet.db', check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance REAL DEFAULT 0.0,
            wallet_address TEXT UNIQUE,
            registered_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            transaction_id TEXT PRIMARY KEY,
            from_user INTEGER,
            to_user INTEGER,
            amount REAL,
            currency TEXT DEFAULT 'PRC',
            transaction_type TEXT,
            status TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (from_user) REFERENCES users (user_id),
            FOREIGN KEY (to_user) REFERENCES users (user_id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS deposits (
            deposit_id TEXT PRIMARY KEY,
            user_id INTEGER,
            amount_cup REAL,
            amount_prc REAL,
            exchange_rate REAL,
            method TEXT,
            status TEXT,
            screenshot_id TEXT,
            admin_approved INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS withdrawals (
            withdrawal_id TEXT PRIMARY KEY,
            user_id INTEGER,
            amount_prc REAL,
            amount_cup REAL,
            exchange_rate REAL,
            fee REAL,
            net_amount REAL,
            card_number TEXT,
            status TEXT,
            screenshot_id TEXT,
            admin_approved INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            product_id TEXT PRIMARY KEY,
            name TEXT,
            description TEXT,
            price_prc REAL,
            category TEXT,
            image_url TEXT,
            is_available BOOLEAN DEFAULT TRUE,
            created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            user_id INTEGER,
            product_id TEXT,
            quantity INTEGER,
            total_price REAL,
            status TEXT,
            order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (product_id) REFERENCES products (product_id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ Base de datos inicializada")

def escape_markdown(text):
    """Escapa texto para Markdown V2 de forma correcta"""
    if text is None:
        return ""
    
    # Para MarkdownV2, estos son los caracteres que deben escaparse
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    
    # Escapar cada carácter especial
    escaped_text = str(text)
    for char in escape_chars:
        escaped_text = escaped_text.replace(char, f'\\{char}')
    
    return escaped_text

def is_admin(user_id):
    return user_id == ADMIN_ID

def generate_wallet_address():
    return f"PRC{uuid.uuid4().hex[:12].upper()}"

def register_user(user_id, username, first_name):
    conn = sqlite3.connect('cubawallet.db', check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    
    if not user:
        wallet_address = generate_wallet_address()
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name, wallet_address, balance)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, wallet_address, 0.0))
        conn.commit()
        
        notification_text = f"""
🆕 *NUEVO USUARIO REGISTRADO* 🆕

*Información del usuario:*
• *Nombre:* {escape_markdown(first_name)}
• *Username:* @{escape_markdown(username) if username else 'N/A'}
• *User ID:* `{user_id}`
• *Wallet:* `{wallet_address}`

*¡Bienvenido a la familia ProCoin\\!*"""
        
        send_group_notification(notification_text)
        print(f"✅ Usuario registrado: {first_name}")
    
    conn.close()

def get_user_info(user_id):
    conn = sqlite3.connect('cubawallet.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def get_user_by_wallet(wallet_address):
    conn = sqlite3.connect('cubawallet.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE wallet_address = ?', (wallet_address,))
    user = cursor.fetchone()
    conn.close()
    return user

def update_balance(user_id, amount):
    conn = sqlite3.connect('cubawallet.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()

def log_transaction(transaction_id, from_user, to_user, amount, transaction_type, status):
    conn = sqlite3.connect('cubawallet.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO transactions (transaction_id, from_user, to_user, amount, transaction_type, status)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (transaction_id, from_user, to_user, amount, transaction_type, status))
    conn.commit()
    conn.close()

def log_deposit(deposit_id, user_id, amount_cup, amount_prc, exchange_rate, method, status, screenshot_id=None):
    conn = sqlite3.connect('cubawallet.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO deposits (deposit_id, user_id, amount_cup, amount_prc, exchange_rate, method, status, screenshot_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (deposit_id, user_id, amount_cup, amount_prc, exchange_rate, method, status, screenshot_id))
    conn.commit()
    conn.close()

def log_withdrawal(withdrawal_id, user_id, amount_prc, amount_cup, exchange_rate, fee, net_amount, card_number, status, screenshot_id=None):
    conn = sqlite3.connect('cubawallet.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO withdrawals (withdrawal_id, user_id, amount_prc, amount_cup, exchange_rate, fee, net_amount, card_number, status, screenshot_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (withdrawal_id, user_id, amount_prc, amount_cup, exchange_rate, fee, net_amount, card_number, status, screenshot_id))
    conn.commit()
    conn.close()

# =============================================================================
# SISTEMA DE MENÚS MEJORADO
# =============================================================================

def main_menu():
    """Menú principal con diseño mejorado"""
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    
    btn_operations = types.KeyboardButton("📊 Operaciones")
    btn_shop = types.KeyboardButton("🛍️ Tienda")
    btn_help = types.KeyboardButton("❓ Ayuda")
    
    markup.add(btn_operations, btn_shop, btn_help)
    return markup

def operations_menu():
    """Menú de operaciones"""
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    
    btn_send = types.KeyboardButton("📤 Enviar")
    btn_receive = types.KeyboardButton("📥 Recibir")
    btn_deposit = types.KeyboardButton("💵 Depositar")
    btn_withdraw = types.KeyboardButton("💸 Retirar")
    btn_balance = types.KeyboardButton("💰 Saldo")
    btn_rates = types.KeyboardButton("📈 Tasas")
    btn_back = types.KeyboardButton("🔙 Menú Principal")
    
    markup.add(btn_send, btn_receive, btn_deposit, btn_withdraw, btn_balance, btn_rates, btn_back)
    return markup

def shop_menu():
    """Menú de la tienda"""
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    
    btn_internet = types.KeyboardButton("🌐 Paquetes Internet")
    btn_gaming = types.KeyboardButton("🎮 Juegos Digitales")
    btn_software = types.KeyboardButton("💻 Software")
    btn_other = types.KeyboardButton("📱 Otros Productos")
    btn_back = types.KeyboardButton("🔙 Menú Principal")
    
    markup.add(btn_internet, btn_gaming, btn_software, btn_other, btn_back)
    return markup

def deposit_methods_menu():
    """Menú de métodos de depósito"""
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    
    btn_transfermovil = types.KeyboardButton("📱 Transfermóvil")
    btn_enzona = types.KeyboardButton("🔵 EnZona")
    btn_back = types.KeyboardButton("🔙 Atrás")
    
    markup.add(btn_transfermovil, btn_enzona, btn_back)
    return markup

# =============================================================================
# MANEJADORES DE MENSAJES MEJORADOS
# =============================================================================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        user_id = message.from_user.id
        username = message.from_user.username
        first_name = message.from_user.first_name
        
        register_user(user_id, username, first_name)
        user_info = get_user_info(user_id)
        
        cup_rate = get_cup_usd_rate()
        
        welcome_text = f"""
🎉 *¡Bienvenido a ProCoin, {escape_markdown(first_name)}!* 🎉

💎 *Tu Billetera Digital Cubana*

📊 *Resumen de tu cuenta:*
┌────────────────────────
│ 👤 *Usuario:* {escape_markdown(first_name)}
│ 💼 *Wallet:* `{user_info[4]}`
│ 💰 *Saldo:* {user_info[3]:.2f} PRC
│ 💵 *Equivalente:* {user_info[3] * cup_rate:,.0f} CUP
└────────────────────────

💱 *Tasa actual:* 1 PRC = {cup_rate:,.0f} CUP

🌟 *Selecciona una opción del menú:*"""
        
        bot.send_message(
            chat_id=message.chat.id,
            text=welcome_text,
            parse_mode='Markdown',
            reply_markup=main_menu()
        )
    except Exception as e:
        print(f"❌ Error en start: {e}")
        bot.send_message(message.chat.id, "❌ Error al iniciar. Intenta nuevamente.")

@bot.message_handler(func=lambda message: message.text == "📊 Operaciones")
def show_operations(message):
    """Muestra el menú de operaciones"""
    operations_text = """
⚡ *MENÚ DE OPERACIONES* ⚡

Selecciona la operación que deseas realizar:

📤 *Enviar* - Transferir ProCoin a otros usuarios
📥 *Recibir* - Obtener tu dirección para recibir pagos
💵 *Depositar* - Convertir CUP a ProCoin
💸 *Retirar* - Convertir ProCoin a CUP
💰 *Saldo* - Consultar tu balance actual
📈 *Tasas* - Ver tasas de cambio actualizadas

👇 *Elige una opción:*"""
    
    bot.send_message(
        message.chat.id,
        operations_text,
        parse_mode='Markdown',
        reply_markup=operations_menu()
    )

@bot.message_handler(func=lambda message: message.text == "🛍️ Tienda")
def show_shop(message):
    """Muestra el menú de la tienda"""
    shop_text = """
🛍️ *TIENDA PROCOIN* 🛍️

¡Bienvenido a nuestra tienda digital! Aquí puedes adquirir productos y servicios usando tus ProCoin.

📦 *Categorías disponibles:*

🌐 *Paquetes Internet* - Recargas y paquetes de datos
🎮 *Juegos Digitales* - Claves y suscripciones gaming
💻 *Software* - Licencias y programas
📱 *Otros Productos* - Variedad de productos digitales

👇 *Selecciona una categoría:*"""
    
    bot.send_message(
        message.chat.id,
        shop_text,
        parse_mode='Markdown',
        reply_markup=shop_menu()
    )

@bot.message_handler(func=lambda message: message.text == "❓ Ayuda")
def show_help(message):
    """Muestra ayuda"""
    help_text = """
❓ *CENTRO DE AYUDA* ❓

*Preguntas Frecuentes:*

🤔 *¿Qué es ProCoin?*
ProCoin es una moneda digital cubana respaldada por tasas reales del mercado.

💳 *¿Cómo puedo depositar?*
Usa la opción \"Depositar\" y sigue las instrucciones para Transfermóvil o EnZona.

📤 *¿Cómo envío ProCoin?*
Ve a \"Operaciones\" → \"Enviar\" e ingresa la wallet del destinatario.

🛍️ *¿Qué puedo comprar en la tienda?*
Paquetes de internet, juegos, software y diversos productos digitales.

📞 *Soporte Técnico:*
@TuUsuarioDeSoporte

⚠️ *Recuerda:* Nunca compartas tu clave privada."""
    
    bot.send_message(
        message.chat.id,
        help_text,
        parse_mode='Markdown',
        reply_markup=main_menu()
    )

@bot.message_handler(func=lambda message: message.text == "🔙 Menú Principal")
def back_to_main(message):
    """Vuelve al menú principal"""
    user_info = get_user_info(message.from_user.id)
    cup_rate = get_cup_usd_rate()
    
    main_text = f"""
🏠 *MENÚ PRINCIPAL* 🏠

📊 *Resumen rápido:*
┌────────────────────────
│ 💰 *Saldo:* {user_info[3]:.2f} PRC
│ 💵 *Equivalente:* {user_info[3] * cup_rate:,.0f} CUP
│ 💱 *Tasa:* 1 PRC = {cup_rate:,.0f} CUP
└────────────────────────

👇 *Selecciona una opción:*"""
    
    bot.send_message(
        message.chat.id,
        main_text,
        parse_mode='Markdown',
        reply_markup=main_menu()
    )

@bot.message_handler(func=lambda message: message.text == "🔙 Atrás")
def back_to_operations(message):
    """Vuelve al menú de operaciones"""
    show_operations(message)

# =============================================================================
# OPERACIONES PRINCIPALES
# =============================================================================

@bot.message_handler(func=lambda message: message.text == "💰 Saldo")
def show_balance(message):
    """Muestra el saldo del usuario"""
    try:
        user_id = message.from_user.id
        user_info = get_user_info(user_id)
        cup_rate = get_cup_usd_rate()
        
        balance_text = f"""
💰 *CONSULTA DE SALDO* 💰

📊 *Detalles de tu cuenta:*
┌────────────────────────
│ 👤 *Usuario:* {escape_markdown(user_info[2])}
│ 💼 *Wallet:* `{user_info[4]}`
│ 💎 *ProCoin:* {user_info[3]:.2f} PRC
│ 💵 *Equivalente:* {user_info[3] * cup_rate:,.0f} CUP
└────────────────────────

💱 *Tasa de cambio:* 1 PRC = {cup_rate:,.0f} CUP

💡 *¿Necesitas más ProCoin?*
Usa la opción \"Depositar\" para agregar fondos."""
        
        bot.send_message(
            message.chat.id,
            balance_text,
            parse_mode='Markdown',
            reply_markup=operations_menu()
        )
    except Exception as e:
        print(f"❌ Error en saldo: {e}")
        bot.send_message(message.chat.id, "❌ Error al consultar saldo.")

@bot.message_handler(func=lambda message: message.text == "📈 Tasas")
def show_rates(message):
    """Muestra las tasas actuales"""
    show_current_rates(message)

@bot.message_handler(func=lambda message: message.text == "📥 Recibir")
def show_receive_info(message):
    """Muestra información para recibir pagos"""
    try:
        user_id = message.from_user.id
        user_info = get_user_info(user_id)
        
        receive_text = f"""
📥 *RECIBIR PROCOIN* 📥

💼 *Tu dirección única:*
`{user_info[4]}`

📋 *Para recibir pagos:*
1️⃣ Comparte esta dirección con quien te enviará ProCoin
2️⃣ El remitente usa la opción \"Enviar\"
3️⃣ Ingresa tu dirección única
4️⃣ ¡Recibes los fondos al instante!

💡 *Consejo:* Mantén esta dirección segura y compártela solo con personas de confianza.

⚠️ *Solo acepta pagos en ProCoin*"""
        
        bot.send_message(
            message.chat.id,
            receive_text,
            parse_mode='Markdown',
            reply_markup=operations_menu()
        )
    except Exception as e:
        print(f"❌ Error en recibir: {e}")
        bot.send_message(message.chat.id, "❌ Error al cargar información.")

@bot.message_handler(func=lambda message: message.text == "💵 Depositar")
def show_deposit_options(message):
    """Muestra opciones de depósito"""
    try:
        user_id = message.from_user.id
        user_info = get_user_info(user_id)
        cup_rate = get_cup_usd_rate()
        
        deposit_text = f"""
💵 *DEPOSITAR FONDOS* 💵

💱 *Tasa actual:* 1 PRC = {cup_rate:,.0f} CUP

📊 *Tu saldo actual:* {user_info[3]:.2f} PRC

💡 *Proceso de depósito:*
1️⃣ Seleccionas método de pago
2️⃣ Realizas transferencia en CUP
3️⃣ Envías el comprobante
4️⃣ Recibes ProCoin automáticamente

👇 *Selecciona tu método de pago:*"""
        
        bot.send_message(
            message.chat.id,
            deposit_text,
            parse_mode='Markdown',
            reply_markup=deposit_methods_menu()
        )
    except Exception as e:
        print(f"❌ Error en depósito: {e}")
        bot.send_message(message.chat.id, "❌ Error al procesar depósito.")

@bot.message_handler(func=lambda message: message.text in ["📱 Transfermóvil", "🔵 EnZona"])
def handle_deposit_method(message):
    """Maneja la selección del método de depósito"""
    try:
        method = "transfermovil" if message.text == "📱 Transfermóvil" else "enzona"
        start_cup_deposit(message, method)
    except Exception as e:
        print(f"❌ Error en método depósito: {e}")
        bot.send_message(message.chat.id, "❌ Error al seleccionar método.")

# =============================================================================
# SISTEMA DE TASAS MEJORADO
# =============================================================================

def show_current_rates(message):
    """Muestra tasas de forma confiable y estética"""
    try:
        print("🔍 Obteniendo tasas para mostrar...")
        
        # Obtener tasas del caché
        all_rates = get_eltoque_rates_cached()
        
        if not all_rates:
            error_msg = "❌ *No se pudieron obtener las tasas*\n\nPor favor, intenta nuevamente en unos minutos."
            raise Exception("No se pudieron obtener tasas")
        
        # Usar USD o USDT como tasa principal
        main_rate = all_rates.get('USD') or all_rates.get('USDT_TRC20') or 490
        
        # Construir mensaje de forma estética
        rates_text = f"""
📈 *TASAS DE CAMBIO ACTUALES* 📈

💎 *Tasa Principal ProCoin:*
┌────────────────────────
│ 1 PRC = {main_rate:,} CUP
└────────────────────────

💱 *Todas las Tasas Disponibles:*
"""
        
        # Agregar todas las tasas ordenadas
        for currency, rate in sorted(all_rates.items()):
            rates_text += f"• {currency}: {rate:,} CUP\n"
        
        # Conversiones comunes
        rates_text += f"""
📊 *Conversiones ProCoin:*
┌────────────────────────
│ 10 PRC = {10 * main_rate:,} CUP
│ 50 PRC = {50 * main_rate:,} CUP  
│ 100 PRC = {100 * main_rate:,} CUP
└────────────────────────

🔄 *Actualizado:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        
        print("✅ Mensaje de tasas construido correctamente")
        
        bot.send_message(
            message.chat.id,
            rates_text,
            parse_mode='Markdown',
            reply_markup=operations_menu()
        )
            
    except Exception as e:
        print(f"❌ Error mostrando tasas: {e}")
        error_text = "❌ *Error temporal al obtener tasas*\n\n🔧 El equipo ha sido notificado.\n🔄 Intenta nuevamente en unos minutos."
        
        bot.send_message(
            message.chat.id,
            error_text,
            parse_mode='Markdown',
            reply_markup=operations_menu()
        )

# =============================================================================
# SISTEMA DE DEPÓSITOS MEJORADO
# =============================================================================

def start_cup_deposit(message, method):
    """Inicia el proceso de depósito"""
    try:
        cup_rate = get_cup_usd_rate()
        method_name = "Transfermóvil" if method == "transfermovil" else "EnZona"
        
        msg = bot.send_message(
            message.chat.id,
            f"💵 *DEPÓSITO POR {method_name}* 💵\n\n"
            f"💱 *Tasa actual:* 1 PRC = {cup_rate:,.0f} CUP\n\n"
            f"💵 *Ingresa el monto en CUP que deseas depositar:*\n\n"
            f"💡 *Ejemplo:* 1000, 5000, 10000",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_cup_deposit_amount, method)
    except Exception as e:
        print(f"❌ Error iniciando depósito: {e}")
        bot.send_message(message.chat.id, "❌ Error al iniciar depósito.")

def process_cup_deposit_amount(message, method):
    """Procesa el monto del depósito"""
    try:
        user_id = message.from_user.id
        
        # Validar monto
        try:
            amount_cup = float(message.text.replace(',', '.'))
        except:
            bot.send_message(
                message.chat.id,
                "❌ *Formato inválido*\nIngresa un número válido.\n\n*Ejemplos:* 1000, 2500.50, 5000",
                parse_mode='Markdown',
                reply_markup=operations_menu()
            )
            return
        
        if amount_cup <= 0:
            bot.send_message(
                message.chat.id,
                "❌ *Monto inválido*\nEl monto debe ser mayor a 0.",
                parse_mode='Markdown',
                reply_markup=operations_menu()
            )
            return
        
        if amount_cup < 100:
            bot.send_message(
                message.chat.id,
                "❌ *Monto muy bajo*\nEl depósito mínimo es 100 CUP.",
                parse_mode='Markdown',
                reply_markup=operations_menu()
            )
            return
        
        # Calcular conversión
        cup_rate = get_cup_usd_rate()
        amount_prc = amount_cup / cup_rate
        
        # Guardar depósito pendiente
        deposit_id = f"DEP{uuid.uuid4().hex[:8].upper()}"
        pending_deposits[user_id] = {
            'deposit_id': deposit_id,
            'amount_cup': amount_cup,
            'amount_prc': amount_prc,
            'exchange_rate': cup_rate,
            'method': method
        }
        
        # Mostrar instrucciones
        if method == "transfermovil":
            payment_text = f"""
📱 *INSTRUCCIONES TRANSFERMÓVIL* 📱

💳 *Información para transferir:*
┌────────────────────────
│ 📞 *Teléfono:* `5351234567`
│ 👤 *Nombre:* ProCoin Exchange
│ 💰 *Monto:* *{amount_cup:,.0f} CUP*
└────────────────────────

📊 *Conversión a ProCoin:*
┌────────────────────────
│ CUP depositados: {amount_cup:,.0f} CUP
│ Tasa: 1 PRC = {cup_rate:,.0f} CUP
│ Recibirás: *{amount_prc:.2f} PRC*
└────────────────────────

📋 *Pasos a seguir:*
1️⃣ Abre Transfermóvil
2️⃣ Selecciona *Transferir*
3️⃣ Ingresa teléfono: *5351234567*
4️⃣ Monto: *{amount_cup:,.0f} CUP*
5️⃣ Confirma transferencia
6️⃣ Toma captura del comprobante
7️⃣ Envíala en el siguiente mensaje

⚠️ *Importante:* 
• Monto exacto: {amount_cup:,.0f} CUP
• Solo transferencias propias
• Verificación: 5-15 minutos"""
        else:
            payment_text = f"""
🔵 *INSTRUCCIONES ENZONA* 🔵

💳 *Información para pagar:*
┌────────────────────────
│ 👤 *Nombre:* ProCoin Exchange
│ 💰 *Monto:* *{amount_cup:,.0f} CUP*
└────────────────────────

📊 *Conversión a ProCoin:*
┌────────────────────────
│ CUP depositados: {amount_cup:,.0f} CUP
│ Tasa: 1 PRC = {cup_rate:,.0f} CUP
│ Recibirás: *{amount_prc:.2f} PRC*
└────────────────────────

📋 *Pasos a seguir:*
1️⃣ Abre EnZona
2️⃣ Busca *ProCoin Exchange*
3️⃣ Monto: *{amount_cup:,.0f} CUP*
4️⃣ Realiza el pago
5️⃣ Toma captura del comprobante
6️⃣ Envíala en el siguiente mensaje

⚠️ *Importante:* 
• Monto exacto: {amount_cup:,.0f} CUP
• Solo pagos propios
• Verificación: 5-15 minutos"""
        
        # Registrar en base de datos
        log_deposit(deposit_id, user_id, amount_cup, amount_prc, cup_rate, method, "pending")
        
        bot.send_message(
            message.chat.id,
            payment_text,
            parse_mode='Markdown'
        )
        
        bot.send_message(
            message.chat.id,
            "📸 *Ahora envía la captura del comprobante de pago:*",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        print(f"❌ Error procesando depósito: {e}")
        bot.send_message(
            message.chat.id,
            "❌ Error al procesar el depósito. Intenta nuevamente.",
            parse_mode='Markdown',
            reply_markup=operations_menu()
        )

# =============================================================================
# SISTEMA DE TIENDA - PLANTILLAS
# =============================================================================

@bot.message_handler(func=lambda message: message.text in ["🌐 Paquetes Internet", "🎮 Juegos Digitales", "💻 Software", "📱 Otros Productos"])
def show_shop_category(message):
    """Muestra productos por categoría"""
    category = message.text
    category_key = {
        "🌐 Paquetes Internet": "internet",
        "🎮 Juegos Digitales": "gaming", 
        "💻 Software": "software",
        "📱 Otros Productos": "other"
    }
    
    show_products(message, category_key[category])

def show_products(message, category):
    """Muestra productos de una categoría específica"""
    # Productos de ejemplo - puedes expandir esta lista
    products = {
        "internet": [
            {"name": "🌐 Paquete 1GB", "description": "1GB de datos Nauta", "price": 5.0, "product_id": "NET-001"},
            {"name": "🌐 Paquete 3GB", "description": "3GB de datos Nauta", "price": 12.0, "product_id": "NET-002"},
            {"name": "🌐 Paquete 5GB", "description": "5GB de datos Nauta", "price": 18.0, "product_id": "NET-003"},
        ],
        "gaming": [
            {"name": "🎮 Steam $10", "description": "Tarjeta de regalo Steam $10", "price": 8.0, "product_id": "GAM-001"},
            {"name": "🎮 Xbox Live", "description": "1 mes Xbox Live Gold", "price": 6.0, "product_id": "GAM-002"},
        ],
        "software": [
            {"name": "💻 Windows 10 Pro", "description": "Licencia digital Windows 10", "price": 15.0, "product_id": "SOF-001"},
            {"name": "💻 Office 365", "description": "1 año Office 365 Personal", "price": 25.0, "product_id": "SOF-002"},
        ],
        "other": [
            {"name": "📱 Recarga Móvil", "description": "Recarga de 100 CUP a móvil", "price": 4.0, "product_id": "OTH-001"},
            {"name": "📺 Netflix 1 Mes", "description": "Cuenta Netflix premium 1 mes", "price": 12.0, "product_id": "OTH-002"},
        ]
    }
    
    category_names = {
        "internet": "🌐 Paquetes Internet",
        "gaming": "🎮 Juegos Digitales", 
        "software": "💻 Software",
        "other": "📱 Otros Productos"
    }
    
    products_list = products.get(category, [])
    
    if not products_list:
        bot.send_message(
            message.chat.id,
            f"📦 *{category_names[category]}*\n\n"
            "😔 No hay productos disponibles en esta categoría en este momento.\n\n"
            "Vuelve pronto para nuevas ofertas! 🎁",
            parse_mode='Markdown',
            reply_markup=shop_menu()
        )
        return
    
    # Crear mensaje con productos
    shop_text = f"🛍️ *{category_names[category]}* 🛍️\n\n"
    shop_text += "📦 *Productos disponibles:*\n\n"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    for product in products_list:
        shop_text += f"🔹 *{product['name']}*\n"
        shop_text += f"📝 {product['description']}\n"
        shop_text += f"💰 *Precio:* {product['price']:.1f} PRC\n\n"
        
        # Botón para comprar cada producto
        btn_buy = types.InlineKeyboardButton(
            f"🛒 Comprar {product['name'].split()[0]}", 
            callback_data=f"buy_{product['product_id']}"
        )
        markup.add(btn_buy)
    
    shop_text += "💡 *Selecciona un producto para comprar:*"
    
    btn_back = types.InlineKeyboardButton("🔙 Volver a Categorías", callback_data="back_to_categories")
    markup.add(btn_back)
    
    bot.send_message(
        message.chat.id,
        shop_text,
        parse_mode='Markdown',
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_'))
def handle_buy_product(call):
    """Maneja la compra de productos"""
    try:
        product_id = call.data[4:]  # Remover 'buy_' del callback data
        user_id = call.from_user.id
        user_info = get_user_info(user_id)
        
        # Aquí iría la lógica para obtener información del producto de la base de datos
        # Por ahora usamos datos de ejemplo
        product_info = {
            "NET-001": {"name": "🌐 Paquete 1GB", "price": 5.0},
            "NET-002": {"name": "🌐 Paquete 3GB", "price": 12.0},
            "GAM-001": {"name": "🎮 Steam $10", "price": 8.0},
            "SOF-001": {"name": "💻 Windows 10 Pro", "price": 15.0},
        }
        
        product = product_info.get(product_id)
        
        if not product:
            bot.answer_callback_query(call.id, "❌ Producto no encontrado")
            return
        
        if user_info[3] < product['price']:
            bot.answer_callback_query(
                call.id, 
                f"❌ Saldo insuficiente. Necesitas {product['price']} PRC"
            )
            return
        
        # Procesar compra
        update_balance(user_id, -product['price'])
        
        # Registrar transacción
        transaction_id = f"BUY{uuid.uuid4().hex[:8].upper()}"
        log_transaction(transaction_id, user_id, None, product['price'], "shop_purchase", "completed")
        
        # Mensaje de confirmación
        success_text = f"""
🎉 *¡COMPRA EXITOSA!* 🎉

🛍️ *Producto adquirido:*
┌────────────────────────
│ 📦 {product['name']}
│ 💰 Precio: {product['price']:.1f} PRC
│ 📋 Transacción: {transaction_id}
└────────────────────────

📊 *Detalles de tu compra:*
• Producto: {product['name']}
• Precio: {product['price']:.1f} PRC
• Nuevo saldo: {user_info[3] - product['price']:.2f} PRC
• Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}

📦 *Instrucciones de entrega:*
Tu producto será entregado en un plazo máximo de 24 horas. 
Recibirás notificación cuando esté disponible.

💌 *Para consultas:* @TuUsuarioDeSoporte"""
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=success_text,
            parse_mode='Markdown'
        )
        
        # Notificar al grupo
        send_group_notification(
            f"🛍️ *NUEVA COMPRA EN TIENDA*\n\n"
            f"👤 Usuario: {escape_markdown(user_info[2])}\n"
            f"📦 Producto: {product['name']}\n"
            f"💰 Precio: {product['price']:.1f} PRC\n"
            f"📋 Transacción: {transaction_id}"
        )
        
    except Exception as e:
        print(f"❌ Error en compra: {e}")
        bot.answer_callback_query(call.id, "❌ Error al procesar compra")

@bot.callback_query_handler(func=lambda call: call.data == "back_to_categories")
def back_to_categories(call):
    """Vuelve a las categorías de la tienda"""
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="🛍️ *Selecciona una categoría:*",
        parse_mode='Markdown',
        reply_markup=shop_menu()
    )

# =============================================================================
# MANEJADOR DE FOTOS (PARA DEPÓSITOS)
# =============================================================================

@bot.message_handler(content_types=['photo'])
def handle_screenshot(message):
    """Manejador de capturas de pantalla para depósitos"""
    try:
        user_id = message.from_user.id
        
        if user_id not in pending_deposits:
            bot.reply_to(message, "❌ No tienes un depósito pendiente. Usa el menú para iniciar un depósito.")
            return
        
        user_info = get_user_info(user_id)
        deposit_data = pending_deposits[user_id]
        
        photo_id = message.photo[-1].file_id
        
        # Actualizar base de datos
        conn = sqlite3.connect('cubawallet.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('UPDATE deposits SET screenshot_id = ? WHERE deposit_id = ?', (photo_id, deposit_data['deposit_id']))
        conn.commit()
        conn.close()
        
        method_display = "Transfermóvil" if deposit_data['method'] == "transfermovil" else "EnZona"
        
        # Notificar al grupo
        group_notification = f"""
📥 *NUEVO DEPÓSITO PENDIENTE* 📥

👤 *Usuario:* {escape_markdown(user_info[2])}
💼 *Wallet:* `{user_info[4]}`
📱 *Método:* {method_display}
💰 *CUP depositados:* {deposit_data['amount_cup']:,.0f} CUP
💎 *ProCoin a recibir:* {deposit_data['amount_prc']:.2f} PRC
💱 *Tasa:* 1 PRC = {deposit_data['exchange_rate']:,.0f} CUP
📋 *Depósito ID:* `{deposit_data['deposit_id']}`

⏳ *Esperando verificación...*

✅ *Para aprobar usa:*
`/recargar {user_info[4]} {deposit_data['amount_prc']:.2f}`"""
        
        send_group_notification(group_notification, photo_id=photo_id)
        
        # Confirmar al usuario
        bot.reply_to(message,
                    f"✅ *Captura recibida correctamente*\n\n"
                    f"📋 *Resumen de tu depósito:*\n"
                    f"• Método: {method_display}\n"
                    f"• CUP depositados: {deposit_data['amount_cup']:,.0f} CUP\n"
                    f"• ProCoin a recibir: {deposit_data['amount_prc']:.2f} PRC\n"
                    f"• Tasa: 1 PRC = {deposit_data['exchange_rate']:,.0f} CUP\n"
                    f"• ID: {deposit_data['deposit_id']}\n\n"
                    f"⏰ *Estado:* En revisión\n"
                    f"📞 *Tiempo estimado:* 5-15 minutos\n\n"
                    f"Te notificaremos cuando sea verificado.",
                    parse_mode='Markdown',
                    reply_markup=main_menu())
        
        # Limpiar depósito pendiente
        del pending_deposits[user_id]
        
    except Exception as e:
        print(f"❌ Error manejando screenshot: {e}")
        bot.reply_to(message, "❌ Error al procesar la captura. Intenta nuevamente.")

# =============================================================================
# COMANDOS DE ADMINISTRADOR (MANTENIDOS)
# =============================================================================

@bot.message_handler(commands=['recargar'])
def recharge_balance(message):
    """COMANDO RECARGAR PARA ADMINISTRADORES"""
    try:
        user_id = message.from_user.id
        
        if not is_admin(user_id):
            bot.reply_to(message, "❌ *Comando solo para administradores*", parse_mode='Markdown')
            return
        
        parts = message.text.split()
        if len(parts) != 3:
            bot.reply_to(message, 
                        "❌ *Formato incorrecto*\n\n"
                        "Uso: `/recargar WALLET CANTIDAD`\n\n"
                        "• WALLET = Dirección del usuario\n"
                        "• CANTIDAD = ProCoin a recargar\n\n"
                        "Ejemplo: `/recargar PRCABC123 100\\.50`", 
                        parse_mode='Markdown')
            return
        
        wallet_address = parts[1]
        try:
            amount = float(parts[2])
        except ValueError:
            bot.reply_to(message, "❌ *Cantidad inválida*", parse_mode='Markdown')
            return
        
        user_info = get_user_by_wallet(wallet_address)
        if not user_info:
            bot.reply_to(message, f"❌ *Wallet no encontrada:* `{wallet_address}`", parse_mode='Markdown')
            return
        
        old_balance = user_info[3]
        update_balance(user_info[0], amount)
        new_balance = old_balance + amount
        
        transaction_id = f"ADM{uuid.uuid4().hex[:8].upper()}"
        log_transaction(transaction_id, None, user_info[0], amount, "admin_recharge", "completed")
        
        # Notificar al usuario
        try:
            user_notification = f"""
💎 *RECARGA DE PROCOIN APROBADA*

✅ Se ha recargado tu cuenta con *{amount:.2f} PRC*

📊 *Detalles:*
• Wallet: `{wallet_address}`
• Transacción: {transaction_id}
• Saldo anterior: {old_balance:.2f} PRC
• Nuevo saldo: *{new_balance:.2f} PRC*

¡Gracias por usar ProCoin\\! 🎉"""
            
            bot.send_message(user_info[0], user_notification, parse_mode='Markdown')
        except Exception as e:
            print(f"No se pudo notificar al usuario: {e}")
        
        # Notificar al grupo
        group_notification = f"""
💎 *RECARGA MANUAL DE PROCOIN* 💎

*Administrador:* {escape_markdown(message.from_user.first_name)}
*Usuario:* {escape_markdown(user_info[2])}
*Wallet:* `{wallet_address}`
*ProCoin:* {amount:.2f} PRC
*Transacción:* `{transaction_id}`
*Nuevo saldo:* {new_balance:.2f} PRC

✅ *Recarga completada exitosamente*"""
        
        send_group_notification(group_notification)
        
        bot.reply_to(message, 
                    f"✅ *Recarga exitosa*\n\n"
                    f"👤 Usuario: {escape_markdown(user_info[2])}\n"
                    f"💎 ProCoin: {amount:.2f} PRC\n"
                    f"💰 Nuevo saldo: {new_balance:.2f} PRC",
                    parse_mode='Markdown')
                    
    except Exception as e:
        print(f"❌ Error en recargar: {e}")
        bot.reply_to(message, "❌ Error al procesar la recarga")

# =============================================================================
# INICIALIZACIÓN MEJORADA
# =============================================================================

def run_bot():
    """Función principal mejorada"""
    print("🚀 Iniciando Bot ProCoin Mejorado...")
    
    try:
        # Inicializar base de datos
        init_db()
        
        # Probar sistema de tasas
        print("🧪 Probando sistema de tasas...")
        initial_rates = get_eltoque_rates_cached()
        
        if initial_rates:
            print(f"✅ Sistema de tasas funcionando - {len(initial_rates)} tasas cargadas")
            send_group_notification(f"🤖 *Bot ProCoin Mejorado Iniciado*\n✅ Sistema de tasas activo\n💰 {len(initial_rates)} tasas cargadas\n🛍️ Tienda integrada")
        else:
            print("⚠️ Sistema de tasas con valores por defecto")
            send_group_notification("🤖 *Bot ProCoin Mejorado Iniciado*\n⚠️ Sistema de tasas con valores por defecto\n🛍️ Tienda integrada")
        
        print("🔄 Iniciando polling del bot...")
        bot.polling(none_stop=True, interval=1, timeout=60)
        
    except Exception as e:
        print(f"❌ Error crítico: {e}")
        send_group_notification(f"🚨 *Error crítico en el bot:* {escape_markdown(str(e))}")
        time.sleep(10)
        run_bot()  # Reiniciar

if __name__ == "__main__":
    # Ejecutar el bot en un hilo separado
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Mantener el programa principal ejecutándose
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Deteniendo bot...")
        send_group_notification("🛑 *Bot detenido manualmente*")
