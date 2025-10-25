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
# SISTEMA DE CACHÉ MEJORADO - 1 MINUTO
# =============================================================================

# Variables globales para el caché
rates_cache = None
last_api_call = 0
CACHE_DURATION = 60  # 1 MINUTO - ACTUALIZADO

def get_eltoque_rates_cached():
    """
    Sistema de caché mejorado - actualización cada 1 minuto
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
    Función mejorada para obtener tasas de la API
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
# FUNCIONES PRINCIPALES MEJORADAS
# =============================================================================

pending_deposits = {}
pending_withdrawals = {}
pending_sends = {}
pending_orders = {}

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
    """Inicializa la base de datos MEJORADA"""
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
            product_name TEXT,
            quantity INTEGER,
            total_price REAL,
            status TEXT DEFAULT 'pending',
            phone_number TEXT,
            order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            delivery_date TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (product_id) REFERENCES products (product_id)
        )
    ''')
    
    # Insertar productos de ejemplo si no existen
    products_data = [
        ('NET-001', '🌐 Paquete 1GB Nauta', '1GB de datos para navegación Nauta', 5.0, 'internet', '', 1),
        ('NET-002', '🌐 Paquete 3GB Nauta', '3GB de datos para navegación Nauta', 12.0, 'internet', '', 1),
        ('NET-003', '🌐 Paquete 5GB Nauta', '5GB de datos para navegación Nauta', 18.0, 'internet', '', 1),
        ('NET-004', '🌐 Paquete 10GB Nauta', '10GB de datos para navegación Nauta', 30.0, 'internet', '', 1),
        ('GAM-001', '🎮 Steam $10', 'Tarjeta de regalo Steam $10 USD', 8.0, 'gaming', '', 1),
        ('GAM-002', '🎮 Xbox Live 1 Mes', 'Suscripción Xbox Live Gold 1 mes', 6.0, 'gaming', '', 1),
        ('GAM-003', '🎮 Nintendo $10', 'Tarjeta de regalo Nintendo eShop $10', 8.5, 'gaming', '', 1),
        ('SOF-001', '💻 Windows 10 Pro', 'Licencia digital Windows 10 Professional', 15.0, 'software', '', 1),
        ('SOF-002', '💻 Office 365 Personal', 'Suscripción Office 365 por 1 año', 25.0, 'software', '', 1),
        ('SOF-003', '💻 Antivirus Premium', 'Licencia antivirus premium 1 año', 12.0, 'software', '', 1),
        ('OTH-001', '📱 Recarga Móvil 100 CUP', 'Recarga de 100 CUP a número móvil', 4.0, 'other', '', 1),
        ('OTH-002', '📺 Netflix Premium 1 Mes', 'Cuenta Netflix Premium 1 mes', 12.0, 'other', '', 1),
        ('OTH-003', '🎵 Spotify Premium 1 Mes', 'Suscripción Spotify Premium 1 mes', 8.0, 'other', '', 1),
        ('OTH-004', '📹 YouTube Premium 1 Mes', 'Suscripción YouTube Premium 1 mes', 10.0, 'other', '', 1),
    ]
    
    for product in products_data:
        cursor.execute('''
            INSERT OR IGNORE INTO products (product_id, name, description, price_prc, category, image_url, is_available)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', product)
    
    conn.commit()
    conn.close()
    print("✅ Base de datos inicializada y productos cargados")

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

def create_order(order_id, user_id, product_id, product_name, quantity, total_price, phone_number=None):
    conn = sqlite3.connect('cubawallet.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO orders (order_id, user_id, product_id, product_name, quantity, total_price, phone_number)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (order_id, user_id, product_id, product_name, quantity, total_price, phone_number))
    conn.commit()
    conn.close()

def update_order_status(order_id, status):
    conn = sqlite3.connect('cubawallet.db', check_same_thread=False)
    cursor = conn.cursor()
    if status == 'delivered':
        cursor.execute('UPDATE orders SET status = ?, delivery_date = CURRENT_TIMESTAMP WHERE order_id = ?', (status, order_id))
    else:
        cursor.execute('UPDATE orders SET status = ? WHERE order_id = ?', (status, order_id))
    conn.commit()
    conn.close()

def get_order_info(order_id):
    conn = sqlite3.connect('cubawallet.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT o.*, u.first_name, u.user_id 
        FROM orders o 
        JOIN users u ON o.user_id = u.user_id 
        WHERE o.order_id = ?
    ''', (order_id,))
    order = cursor.fetchone()
    conn.close()
    return order

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
# OPERACIONES PRINCIPALES - CORREGIDAS Y MEJORADAS
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
    """Muestra las tasas actuales CORREGIDAS"""
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

# =============================================================================
# SISTEMA DE ENVÍO DE DINERO - CORREGIDO Y FUNCIONAL
# =============================================================================

@bot.message_handler(func=lambda message: message.text == "📤 Enviar")
def start_send_money(message):
    """Inicia el proceso de enviar dinero - CORREGIDO"""
    try:
        user_id = message.from_user.id
        user_info = get_user_info(user_id)
        
        if user_info[3] <= 0:
            bot.send_message(
                message.chat.id,
                "❌ *No tienes saldo suficiente para enviar.*\n\n"
                "💡 *Sugerencia:* Recarga tu cuenta en la opción \"Depositar\".",
                parse_mode='Markdown',
                reply_markup=operations_menu()
            )
            return
        
        msg = bot.send_message(
            message.chat.id,
            "📤 *ENVIAR PROCOIN*\n\n"
            "💼 *Ingresa la dirección wallet del destinatario:*\n\n"
            "💡 *Ejemplo:* `PRCABC123DEF456`",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_receiver_wallet)
    except Exception as e:
        print(f"❌ Error en enviar: {e}")
        bot.send_message(message.chat.id, "❌ Error al iniciar envío.")

def process_receiver_wallet(message):
    """Procesa la wallet del destinatario"""
    try:
        user_id = message.from_user.id
        receiver_wallet = message.text.strip()
        
        # Validar formato de wallet
        if not receiver_wallet.startswith('PRC') or len(receiver_wallet) != 15:
            bot.send_message(
                message.chat.id,
                "❌ *Formato de wallet inválido.*\n\n"
                "💡 *Asegúrate de que:*\n"
                "- Comienza con 'PRC'\n"
                "- Tiene 15 caracteres\n\n"
                "*Ejemplo:* `PRCABC123DEF456`",
                parse_mode='Markdown',
                reply_markup=operations_menu()
            )
            return
        
        # Verificar que no sea la propia wallet
        user_info = get_user_info(user_id)
        if receiver_wallet == user_info[4]:
            bot.send_message(
                message.chat.id,
                "❌ *No puedes enviarte ProCoin a ti mismo.*",
                parse_mode='Markdown',
                reply_markup=operations_menu()
            )
            return
        
        # Verificar que la wallet exista
        receiver_info = get_user_by_wallet(receiver_wallet)
        if not receiver_info:
            bot.send_message(
                message.chat.id,
                "❌ *Wallet no encontrada.*\n\n"
                "💡 *Verifica la dirección e intenta nuevamente.*",
                parse_mode='Markdown',
                reply_markup=operations_menu()
            )
            return
        
        # Guardar temporalmente la wallet del receptor
        pending_sends[user_id] = {'receiver_wallet': receiver_wallet, 'receiver_id': receiver_info[0]}
        
        msg = bot.send_message(
            message.chat.id,
            f"👤 *Destinatario:* {escape_markdown(receiver_info[2])}\n"
            f"💼 *Wallet:* `{receiver_wallet}`\n\n"
            "💎 *Ingresa el monto de ProCoin a enviar:*",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_send_amount)
    except Exception as e:
        print(f"❌ Error procesando wallet: {e}")
        bot.send_message(message.chat.id, "❌ Error al procesar wallet.")

def process_send_amount(message):
    """Procesa el monto a enviar"""
    try:
        user_id = message.from_user.id
        user_info = get_user_info(user_id)
        
        # Validar monto
        try:
            amount = float(message.text.replace(',', '.'))
        except:
            bot.send_message(
                message.chat.id,
                "❌ *Formato inválido.*\n\n"
                "💡 *Ingresa un número válido.*\n"
                "*Ejemplo:* 10.50",
                parse_mode='Markdown',
                reply_markup=operations_menu()
            )
            return
        
        if amount <= 0:
            bot.send_message(
                message.chat.id,
                "❌ *El monto debe ser mayor a 0.*",
                parse_mode='Markdown',
                reply_markup=operations_menu()
            )
            return
        
        if user_info[3] < amount:
            bot.send_message(
                message.chat.id,
                f"❌ *Saldo insuficiente.*\n\n"
                f"💎 *Saldo actual:* {user_info[3]:.2f} PRC\n"
                f"💸 *Monto a enviar:* {amount:.2f} PRC",
                parse_mode='Markdown',
                reply_markup=operations_menu()
            )
            return
        
        # Obtener datos del receptor
        transfer_data = pending_sends.get(user_id)
        if not transfer_data:
            bot.send_message(
                message.chat.id,
                "❌ *Sesión expirada.*\n\n"
                "💡 *Vuelve a iniciar el proceso.*",
                parse_mode='Markdown',
                reply_markup=operations_menu()
            )
            return
        
        receiver_id = transfer_data['receiver_id']
        receiver_info = get_user_info(receiver_id)
        
        # Realizar transferencia
        update_balance(user_id, -amount)
        update_balance(receiver_id, amount)
        
        transaction_id = f"TXN{uuid.uuid4().hex[:8].upper()}"
        log_transaction(transaction_id, user_id, receiver_id, amount, "send_money", "completed")
        
        # Notificar al remitente
        bot.send_message(
            message.chat.id,
            f"✅ *¡Envío exitoso!*\n\n"
            f"📤 *Has enviado:* {amount:.2f} PRC\n"
            f"👤 *A:* {escape_markdown(receiver_info[2])}\n"
            f"💼 *Wallet:* `{receiver_info[4]}`\n"
            f"📋 *Transacción:* `{transaction_id}`\n\n"
            f"💎 *Nuevo saldo:* {user_info[3] - amount:.2f} PRC",
            parse_mode='Markdown',
            reply_markup=operations_menu()
        )
        
        # Notificar al destinatario
        try:
            bot.send_message(
                receiver_id,
                f"✅ *¡Has recibido ProCoin!*\n\n"
                f"📥 *Has recibido:* {amount:.2f} PRC\n"
                f"👤 *De:* {escape_markdown(user_info[2])}\n"
                f"💼 *Wallet:* `{user_info[4]}`\n"
                f"📋 *Transacción:* `{transaction_id}`\n\n"
                f"💎 *Nuevo saldo:* {receiver_info[3] + amount:.2f} PRC",
                parse_mode='Markdown'
            )
        except Exception as e:
            print(f"No se pudo notificar al destinatario: {e}")
        
        # Notificar al grupo
        send_group_notification(
            f"📤 *NUEVA TRANSFERENCIA*\n\n"
            f"👤 *De:* {escape_markdown(user_info[2])}\n"
            f"👤 *Para:* {escape_markdown(receiver_info[2])}\n"
            f"💎 *Monto:* {amount:.2f} PRC\n"
            f"📋 *Transacción:* `{transaction_id}`"
        )
        
        # Limpiar transferencia pendiente
        if user_id in pending_sends:
            del pending_sends[user_id]
            
    except Exception as e:
        print(f"❌ Error enviando dinero: {e}")
        bot.send_message(message.chat.id, "❌ Error al procesar el envío.")

# =============================================================================
# SISTEMA DE RETIRO DE DINERO - CORREGIDO Y FUNCIONAL
# =============================================================================

@bot.message_handler(func=lambda message: message.text == "💸 Retirar")
def start_withdraw(message):
    """Inicia el proceso de retiro - CORREGIDO"""
    try:
        user_id = message.from_user.id
        user_info = get_user_info(user_id)
        cup_rate = get_cup_usd_rate()
        
        if user_info[3] <= 0:
            bot.send_message(
                message.chat.id,
                "❌ *No tienes saldo suficiente para retirar.*\n\n"
                "💡 *Sugerencia:* Recarga tu cuenta en la opción \"Depositar\".",
                parse_mode='Markdown',
                reply_markup=operations_menu()
            )
            return
        
        withdrawal_text = f"""
💸 *RETIRAR PROCOIN*

💱 *Tasa actual:* 1 PRC = {cup_rate:,.0f} CUP
💰 *Saldo disponible:* {user_info[3]:.2f} PRC

💳 *Ingresa tu número de tarjeta para recibir el pago:*
*Formato:* 9200123456789012

⚠️ *Asegúrate de que la tarjeta esté a tu nombre.*"""
        
        msg = bot.send_message(
            message.chat.id,
            withdrawal_text,
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_withdraw_card)
    except Exception as e:
        print(f"❌ Error en retiro: {e}")
        bot.send_message(message.chat.id, "❌ Error al iniciar retiro.")

def process_withdraw_card(message):
    """Procesa el número de tarjeta para retiro"""
    try:
        user_id = message.from_user.id
        card_number = message.text.strip()
        
        # Validar número de tarjeta (16 dígitos)
        if not card_number.isdigit() or len(card_number) != 16:
            bot.send_message(
                message.chat.id,
                "❌ *Número de tarjeta inválido.*\n\n"
                "💡 *Asegúrate de:*\n"
                "- Ingresar 16 dígitos\n"
                "- Solo números, sin espacios\n\n"
                "*Ejemplo:* 9200123456789012",
                parse_mode='Markdown',
                reply_markup=operations_menu()
            )
            return
        
        # Guardar temporalmente el número de tarjeta
        pending_withdrawals[user_id] = {'card_number': card_number}
        
        msg = bot.send_message(
            message.chat.id,
            "💎 *Ingresa el monto en ProCoin a retirar:*",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_withdraw_amount)
    except Exception as e:
        print(f"❌ Error procesando tarjeta: {e}")
        bot.send_message(message.chat.id, "❌ Error al procesar tarjeta.")

def process_withdraw_amount(message):
    """Procesa el monto a retirar"""
    try:
        user_id = message.from_user.id
        user_info = get_user_info(user_id)
        
        # Validar monto
        try:
            amount_prc = float(message.text.replace(',', '.'))
        except:
            bot.send_message(
                message.chat.id,
                "❌ *Formato inválido.*\n\n"
                "💡 *Ingresa un número válido.*\n"
                "*Ejemplo:* 10.50",
                parse_mode='Markdown',
                reply_markup=operations_menu()
            )
            return
        
        if amount_prc <= 0:
            bot.send_message(
                message.chat.id,
                "❌ *El monto debe ser mayor a 0.*",
                parse_mode='Markdown',
                reply_markup=operations_menu()
            )
            return
        
        if user_info[3] < amount_prc:
            bot.send_message(
                message.chat.id,
                f"❌ *Saldo insuficiente.*\n\n"
                f"💎 *Saldo actual:* {user_info[3]:.2f} PRC\n"
                f"💸 *Monto a retirar:* {amount_prc:.2f} PRC",
                parse_mode='Markdown',
                reply_markup=operations_menu()
            )
            return
        
        # Obtener datos temporales
        withdraw_data = pending_withdrawals.get(user_id)
        if not withdraw_data:
            bot.send_message(
                message.chat.id,
                "❌ *Sesión expirada.*\n\n"
                "💡 *Vuelve a iniciar el proceso.*",
                parse_mode='Markdown',
                reply_markup=operations_menu()
            )
            return
        
        card_number = withdraw_data['card_number']
        cup_rate = get_cup_usd_rate()
        
        # Calcular montos
        amount_cup = amount_prc * cup_rate
        fee = max(amount_cup * 0.05, 50)  # 5% comisión, mínimo 50 CUP
        net_amount = amount_cup - fee
        
        if net_amount <= 0:
            bot.send_message(
                message.chat.id,
                "❌ *El monto a retirar es demasiado bajo después de la comisión.*",
                parse_mode='Markdown',
                reply_markup=operations_menu()
            )
            return
        
        # Actualizar saldo
        update_balance(user_id, -amount_prc)
        
        # Registrar retiro
        withdrawal_id = f"WD{uuid.uuid4().hex[:8].upper()}"
        log_withdrawal(withdrawal_id, user_id, amount_prc, amount_cup, cup_rate, fee, net_amount, card_number, "pending")
        
        # Notificar al usuario
        bot.send_message(
            message.chat.id,
            f"✅ *Solicitud de retiro recibida.*\n\n"
            f"📋 *Resumen de retiro:*\n"
            f"• ProCoin retirados: {amount_prc:.2f} PRC\n"
            f"• Tasa: 1 PRC = {cup_rate:,.0f} CUP\n"
            f"• Total CUP: {amount_cup:,.0f} CUP\n"
            f"• Comisión: {fee:,.0f} CUP\n"
            f"• Neto a recibir: {net_amount:,.0f} CUP\n"
            f"• Tarjeta: {card_number[-4:]}\n"
            f"• ID: {withdrawal_id}\n\n"
            f"⏰ *Tiempo de procesamiento:* 1-24 horas\n"
            f"📞 *Te notificaremos cuando sea completado.*",
            parse_mode='Markdown',
            reply_markup=operations_menu()
        )
        
        # Notificar al grupo
        group_notification = f"""
💸 *NUEVA SOLICITUD DE RETIRO*

👤 *Usuario:* {escape_markdown(user_info[2])}
💼 *Wallet:* `{user_info[4]}`
💎 *ProCoin:* {amount_prc:.2f} PRC
💵 *CUP a recibir:* {net_amount:,.0f} CUP
💳 *Tarjeta:* {card_number[-4:]}
📋 *Retiro ID:* `{withdrawal_id}`

⏳ *Esperando aprobación...*

✅ *Para aprobar usa:*
`/aprobar_retiro {withdrawal_id}`"""
        
        send_group_notification(group_notification)
        
        # Limpiar retiro pendiente
        if user_id in pending_withdrawals:
            del pending_withdrawals[user_id]
            
    except Exception as e:
        print(f"❌ Error retirando dinero: {e}")
        bot.send_message(message.chat.id, "❌ Error al procesar el retiro.")

# =============================================================================
# SISTEMA DE TASAS MEJORADO - CORREGIDO
# =============================================================================

def show_current_rates(message):
    """Muestra tasas de forma confiable y estética - CORREGIDO"""
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

🔄 *Actualizado:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
⏰ *Próxima actualización:* 1 minuto"""
        
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
# SISTEMA DE TIENDA MEJORADO - CON NÚMERO DE TELÉFONO
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
    conn = sqlite3.connect('cubawallet.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM products WHERE category = ? AND is_available = 1', (category,))
    products = cursor.fetchall()
    conn.close()
    
    category_names = {
        "internet": "🌐 Paquetes Internet",
        "gaming": "🎮 Juegos Digitales", 
        "software": "💻 Software",
        "other": "📱 Otros Productos"
    }
    
    if not products:
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
    
    for product in products:
        shop_text += f"🔹 *{product[1]}*\n"
        shop_text += f"📝 {product[2]}\n"
        shop_text += f"💰 *Precio:* {product[3]:.1f} PRC\n\n"
        
        # Botón para comprar cada producto
        btn_buy = types.InlineKeyboardButton(
            f"🛒 Comprar {product[1].split()[0]}", 
            callback_data=f"buy_{product[0]}"
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
        
        # Obtener información del producto
        conn = sqlite3.connect('cubawallet.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM products WHERE product_id = ?', (product_id,))
        product = cursor.fetchone()
        conn.close()
        
        if not product:
            bot.answer_callback_query(call.id, "❌ Producto no encontrado")
            return
        
        if user_info[3] < product[3]:
            bot.answer_callback_query(
                call.id, 
                f"❌ Saldo insuficiente. Necesitas {product[3]} PRC"
            )
            return
        
        # Si es un paquete de internet, pedir el número de teléfono
        if product[4] == 'internet':
            # Guardar la compra pendiente
            pending_orders[user_id] = {
                'product_id': product_id,
                'product_name': product[1],
                'price': product[3]
            }
            
            bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
            msg = bot.send_message(
                call.message.chat.id,
                f"📱 *COMPRA DE {product[1]}*\n\n"
                "Por favor, ingresa el número de teléfono para recargar:\n\n"
                "💡 *Formato:* 5XXXXXXXX",
                parse_mode='Markdown'
            )
            bot.register_next_step_handler(msg, process_phone_number)
        else:
            # Para otros productos, procesar directamente
            process_product_purchase(user_id, product, call.message.chat.id)
            
    except Exception as e:
        print(f"❌ Error en compra: {e}")
        bot.answer_callback_query(call.id, "❌ Error al procesar compra")

def process_phone_number(message):
    """Procesa el número de teléfono para recarga"""
    try:
        user_id = message.from_user.id
        phone = message.text.strip()
        
        # Validar número de teléfono (cubano: 5XXXXXXXX)
        if not phone.isdigit() or len(phone) != 9 or not phone.startswith('5'):
            bot.send_message(
                message.chat.id,
                "❌ *Número de teléfono inválido.*\n\n"
                "💡 *Asegúrate de:*\n"
                "- Ingresar 9 dígitos\n"
                "- Comenzar con 5\n\n"
                "*Ejemplo:* 512345678",
                parse_mode='Markdown',
                reply_markup=shop_menu()
            )
            return
        
        # Obtener la compra pendiente
        order_data = pending_orders.get(user_id)
        if not order_data:
            bot.send_message(
                message.chat.id,
                "❌ *Sesión expirada.*\n\n"
                "💡 *Vuelve a seleccionar el producto.*",
                parse_mode='Markdown',
                reply_markup=shop_menu()
            )
            return
        
        # Obtener información del producto
        conn = sqlite3.connect('cubawallet.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM products WHERE product_id = ?', (order_data['product_id'],))
        product = cursor.fetchone()
        conn.close()
        
        # Procesar la compra con el teléfono
        process_product_purchase(user_id, product, message.chat.id, phone)
        
        # Limpiar compra pendiente
        del pending_orders[user_id]
        
    except Exception as e:
        print(f"❌ Error procesando teléfono: {e}")
        bot.send_message(message.chat.id, "❌ Error al procesar el teléfono.")

def process_product_purchase(user_id, product, chat_id, phone=None):
    """Procesa la compra del producto"""
    try:
        user_info = get_user_info(user_id)
        
        # Procesar compra
        update_balance(user_id, -product[3])
        
        # Registrar transacción
        transaction_id = f"BUY{uuid.uuid4().hex[:8].upper()}"
        log_transaction(transaction_id, user_id, None, product[3], "shop_purchase", "completed")
        
        # Registrar orden
        order_id = f"ORD{uuid.uuid4().hex[:8].upper()}"
        create_order(order_id, user_id, product[0], product[1], 1, product[3], phone)
        
        # Mensaje de confirmación
        success_text = f"""
🎉 *¡COMPRA EXITOSA!* 🎉

🛍️ *Producto adquirido:*
┌────────────────────────
│ 📦 {product[1]}
│ 💰 Precio: {product[3]:.1f} PRC
│ 📋 Transacción: {transaction_id}
│ 📦 Orden: {order_id}
└────────────────────────
"""
        if phone:
            success_text += f"📱 *Teléfono:* {phone}\n\n"
        
        success_text += f"""
📊 *Detalles de tu compra:*
• Producto: {product[1]}
• Precio: {product[3]:.1f} PRC
• Nuevo saldo: {user_info[3] - product[3]:.2f} PRC
• Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}

📦 *Instrucciones de entrega:*
Tu producto será entregado en un plazo máximo de 24 horas. 
Recibirás notificación cuando esté disponible.

💌 *Para consultas:* @TuUsuarioDeSoporte"""
        
        bot.send_message(
            chat_id,
            success_text,
            parse_mode='Markdown',
            reply_markup=shop_menu()
        )
        
        # Notificar al grupo
        notification_text = f"🛍️ *NUEVA COMPRA EN TIENDA*\n\n👤 Usuario: {escape_markdown(user_info[2])}\n📦 Producto: {product[1]}\n💰 Precio: {product[3]:.1f} PRC\n📋 Transacción: {transaction_id}\n📦 Orden: {order_id}"
        if phone:
            notification_text += f"\n📱 Teléfono: {phone}"
        
        send_group_notification(notification_text)
        
    except Exception as e:
        print(f"❌ Error en process_product_purchase: {e}")
        bot.send_message(chat_id, "❌ Error al procesar la compra.")

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
# SISTEMA DE ENTREGA DE PEDIDOS - NUEVO COMANDO
# =============================================================================

@bot.message_handler(commands=['entrega'])
def deliver_order(message):
    """Marca una orden como entregada y notifica al usuario"""
    try:
        user_id = message.from_user.id
        
        if not is_admin(user_id):
            bot.reply_to(message, "❌ *Comando solo para administradores*", parse_mode='Markdown')
            return
        
        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, 
                        "❌ *Formato incorrecto*\n\n"
                        "Uso: `/entrega ORDER_ID`\n\n"
                        "• ORDER_ID = ID de la orden a marcar como entregada\n\n"
                        "Ejemplo: `/entrega ORDABC123`", 
                        parse_mode='Markdown')
            return
        
        order_id = parts[1]
        
        # Obtener información de la orden
        order_info = get_order_info(order_id)
        if not order_info:
            bot.reply_to(message, f"❌ *Orden no encontrada:* `{order_id}`", parse_mode='Markdown')
            return
        
        if order_info[6] == "delivered":
            bot.reply_to(message, f"❌ *La orden ya fue entregada*", parse_mode='Markdown')
            return
        
        # Actualizar estado a entregado
        update_order_status(order_id, "delivered")
        
        # Notificar al usuario
        user_notification = f"""
🎉 *¡TU PEDIDO HA SIDO ENTREGADO!*

✅ *Orden:* {order_id}
📦 *Producto:* {order_info[3]}
💰 *Precio:* {order_info[5]:.1f} PRC
📅 *Fecha de entrega:* {datetime.now().strftime('%Y-%m-%d %H:%M')}

¡Gracias por tu compra! 🎁

💌 *¿Problemas con tu pedido?* Contacta a @TuUsuarioDeSoporte"""
        
        try:
            bot.send_message(order_info[1], user_notification, parse_mode='Markdown')
        except Exception as e:
            print(f"No se pudo notificar al usuario: {e}")
        
        # Notificar al grupo
        send_group_notification(f"✅ *Orden entregada:* `{order_id}`\n👤 Usuario: {escape_markdown(order_info[9])}\n📦 Producto: {order_info[3]}")
        
        bot.reply_to(message, f"✅ *Orden marcada como entregada y notificada al usuario*")
        
    except Exception as e:
        print(f"❌ Error en entrega: {e}")
        bot.reply_to(message, "❌ Error al procesar la entrega")

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
# COMANDOS DE ADMINISTRADOR MEJORADOS
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

@bot.message_handler(commands=['aprobar_retiro'])
def approve_withdrawal(message):
    """Aprueba un retiro pendiente"""
    try:
        user_id = message.from_user.id
        
        if not is_admin(user_id):
            bot.reply_to(message, "❌ *Comando solo para administradores*", parse_mode='Markdown')
            return
        
        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, 
                        "❌ *Formato incorrecto*\n\n"
                        "Uso: `/aprobar_retiro RETIRO_ID`\n\n"
                        "• RETIRO_ID = ID del retiro pendiente\n\n"
                        "Ejemplo: `/aprobar_retiro WDABC123`", 
                        parse_mode='Markdown')
            return
        
        withdrawal_id = parts[1]
        
        # Obtener información del retiro
        conn = sqlite3.connect('cubawallet.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM withdrawals WHERE withdrawal_id = ?', (withdrawal_id,))
        withdrawal = cursor.fetchone()
        
        if not withdrawal:
            bot.reply_to(message, f"❌ *Retiro no encontrado:* `{withdrawal_id}`", parse_mode='Markdown')
            conn.close()
            return
        
        if withdrawal[9] != "pending":
            bot.reply_to(message, f"❌ *El retiro ya fue procesado*", parse_mode='Markdown')
            conn.close()
            return
        
        # Actualizar estado a completado
        cursor.execute('UPDATE withdrawals SET status = ? WHERE withdrawal_id = ?', ("completed", withdrawal_id))
        conn.commit()
        conn.close()
        
        # Notificar al usuario
        user_notification = f"""
✅ *RETIRO APROBADO*

Tu solicitud de retiro ha sido aprobada y procesada.

📋 *Detalles:*
• ID: {withdrawal_id}
• ProCoin retirados: {withdrawal[2]:.2f} PRC
• Monto recibido: {withdrawal[6]:,.0f} CUP
• Tarjeta: {withdrawal[7][-4:]}
• Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}

¡Gracias por usar ProCoin! 🎉"""
        
        try:
            bot.send_message(withdrawal[1], user_notification, parse_mode='Markdown')
        except Exception as e:
            print(f"No se pudo notificar al usuario: {e}")
        
        # Notificar al grupo
        send_group_notification(f"✅ *Retiro aprobado:* `{withdrawal_id}`")
        
        bot.reply_to(message, f"✅ *Retiro aprobado exitosamente*")
        
    except Exception as e:
        print(f"❌ Error aprobando retiro: {e}")
        bot.reply_to(message, "❌ Error al aprobar el retiro")

@bot.message_handler(commands=['debug_tasas'])
def debug_tasas_command(message):
    """Debug del sistema de tasas"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.reply_to(message, "❌ *Comando solo para administradores*", parse_mode='Markdown')
        return
    
    try:
        # Forzar actualización
        all_rates = get_eltoque_rates_cached()
        
        debug_text = f"""
🔧 *DEBUG TASAS - ACTUALIZACIÓN 1 MINUTO*

💰 *Tasas en caché:*
{all_rates}

💵 *Tasa USD:* {get_cup_usd_rate()}
💶 *Tasa EUR:* {get_cup_eur_rate()}

⏰ *Cache actualizado:* {datetime.fromtimestamp(last_api_call).strftime('%H:%M:%S') if last_api_call > 0 else 'Nunca'}
⏱️ *Edad del caché:* {time.time() - last_api_call:.1f}s
🔄 *Actualización cada:* {CACHE_DURATION}s"""
        
        bot.reply_to(message, debug_text, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ Error en debug: {e}")

# =============================================================================
# INICIALIZACIÓN MEJORADA
# =============================================================================

def run_bot():
    """Función principal mejorada"""
    print("🚀 Iniciando Bot ProCoin SUPER MEJORADO...")
    
    try:
        # Inicializar base de datos
        init_db()
        
        # Probar sistema de tasas
        print("🧪 Probando sistema de tasas...")
        initial_rates = get_eltoque_rates_cached()
        
        if initial_rates:
            print(f"✅ Sistema de tasas funcionando - {len(initial_rates)} tasas cargadas")
            send_group_notification(f"🤖 *Bot ProCoin SUPER MEJORADO Iniciado*\n✅ Sistema de tasas activo\n💰 {len(initial_rates)} tasas cargadas\n🛍️ Tienda integrada\n⏰ Cache: 1 minuto")
        else:
            print("⚠️ Sistema de tasas con valores por defecto")
            send_group_notification("🤖 *Bot ProCoin SUPER MEJORADO Iniciado*\n⚠️ Sistema de tasas con valores por defecto\n🛍️ Tienda integrada\n⏰ Cache: 1 minuto")
        
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
