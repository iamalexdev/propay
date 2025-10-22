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
from flask import Flask, render_template
import threading

# Configuración
TOKEN = "8400947960:AAGGXHezQbmUqk6AOpgT1GqMLaF-rMvVp9Y"
GROUP_CHAT_ID = "-4932107704"
ADMIN_ID = 1853800972
bot = telebot.TeleBot(TOKEN)

# Crear app Flask para Render
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 QvaPay Bot está funcionando"

@app.route('/health')
def health():
    return "✅ OK", 200

# Diccionarios para operaciones pendientes
pending_deposits = {}
pending_withdrawals = {}
pending_crypto_deposits = {}
p2p_orders = {}
p2p_trades = {}

# APIs para tasas de cambio
API_ENDPOINTS = {
    "eltoque": "https://eltoque.com/tasas-de-cambio-de-moneda-en-cuba-hoy",
    "binance": "https://api.binance.com/api/v3/ticker/price",
    "coingecko": "https://api.coingecko.com/api/v3/simple/price"
}

# Monedas soportadas
SUPPORTED_CRYPTO = {
    "BTC": "bitcoin",
    "ETH": "ethereum", 
    "USDT": "tether",
    "BNB": "binancecoin",
    "ADA": "cardano",
    "DOT": "polkadot",
    "SOL": "solana"
}

# Datos de productos para la tienda
SHOP_PRODUCTS = {
    "1": {
        "name": "🎮 Steam Wallet $10",
        "price": 2500,
        "currency": "CUP",
        "description": "Código de Steam Wallet de $10 USD",
        "stock": 50
    },
    "2": {
        "name": "📱 Recarga Móvil 5GB",
        "price": 1200,
        "currency": "CUP", 
        "description": "Paquete de datos 5GB para móvil",
        "stock": 100
    },
    "3": {
        "name": "🎵 Spotify Premium 1 Mes",
        "price": 800,
        "currency": "CUP",
        "description": "Suscripción Spotify Premium 1 mes",
        "stock": 30
    },
    "4": {
        "name": "📺 Netflix Basic 1 Mes",
        "price": 1800,
        "currency": "CUP",
        "description": "Suscripción Netflix Basic 1 mes",
        "stock": 25
    },
    "5": {
        "name": "💻 Microsoft Office 365",
        "price": 3000,
        "currency": "CUP",
        "description": "Licencia Office 365 1 año",
        "stock": 15
    },
    "6": {
        "name": "🛡️ VPN Premium 1 Año",
        "price": 2200,
        "currency": "CUP",
        "description": "Servicio VPN Premium 12 meses",
        "stock": 40
    }
}

# Función para obtener tasa CUP/USD desde ElToque
def get_cup_usd_rate():
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(API_ENDPOINTS["eltoque"], headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        elements = soup.find_all(['div', 'span'], string=re.compile(r'1\s*USD\s*=\s*[\d,.]+\s*CUP'))
        
        for element in elements:
            text = element.get_text()
            match = re.search(r'1\s*USD\s*=\s*([\d,.]+)\s*CUP', text)
            if match:
                rate = float(match.group(1).replace(',', ''))
                print(f"✅ Tasa CUP/USD obtenida: {rate}")
                return rate
        
        return 240.0
        
    except Exception as e:
        print(f"❌ Error obteniendo tasa CUP/USD: {e}")
        return 240.0

# Función para obtener precios crypto
def get_crypto_price(symbol):
    try:
        if symbol == "USDT":
            return 1.0
            
        url = f"{API_ENDPOINTS['binance']}?symbol={symbol}USDT"
        response = requests.get(url, timeout=10)
        data = response.json()
        return float(data['price'])
    except Exception as e:
        print(f"❌ Error obteniendo precio de {symbol}: {e}")
        default_prices = {
            "BTC": 50000, "ETH": 3000, "BNB": 400, 
            "ADA": 0.5, "DOT": 7, "SOL": 100
        }
        return default_prices.get(symbol, 1.0)

# Función para enviar notificaciones al grupo
def send_group_notification(message, photo_id=None):
    try:
        if photo_id:
            bot.send_photo(
                chat_id=GROUP_CHAT_ID,
                photo=photo_id,
                caption=message,
                parse_mode='Markdown'
            )
        else:
            bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=message,
                parse_mode='Markdown'
            )
        return True
    except Exception as e:
        print(f"❌ Error enviando notificación: {e}")
        return False

# Inicializar Base de Datos
def init_db():
    conn = sqlite3.connect('qvapay.db')
    cursor = conn.cursor()
    
    # Tabla de usuarios
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance REAL DEFAULT 0.0,
            qvapay_id TEXT UNIQUE,
            registered_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de transacciones
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            transaction_id TEXT PRIMARY KEY,
            from_user INTEGER,
            to_user INTEGER,
            amount REAL,
            currency TEXT DEFAULT 'QVP',
            transaction_type TEXT,
            status TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de P2P
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS p2p_orders (
            order_id TEXT PRIMARY KEY,
            user_id INTEGER,
            order_type TEXT,
            currency TEXT,
            amount REAL,
            price REAL,
            total REAL,
            payment_method TEXT,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de trades P2P
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS p2p_trades (
            trade_id TEXT PRIMARY KEY,
            order_id TEXT,
            buyer_id INTEGER,
            seller_id INTEGER,
            amount REAL,
            price REAL,
            total REAL,
            status TEXT,
            escrow_released BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    ''')
    
    # Tabla de productos comprados
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_id TEXT,
            product_name TEXT,
            price_paid REAL,
            purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active'
        )
    ''')
    
    conn.commit()
    conn.close()

# Función para escapar texto para Markdown
def escape_markdown(text):
    if text is None:
        return ""
    escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in escape_chars:
        text = str(text).replace(char, f'\\{char}')
    return text

# Verificar si es administrador
def is_admin(user_id):
    return user_id == ADMIN_ID

# Generar ID único QvaPay
def generate_qvapay_id():
    return f"QVP{uuid.uuid4().hex[:8].upper()}"

# Registrar usuario
def register_user(user_id, username, first_name):
    conn = sqlite3.connect('qvapay.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    
    if not user:
        qvapay_id = generate_qvapay_id()
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name, qvapay_id, balance)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, qvapay_id, 0.0))
        conn.commit()
    
    conn.close()

# Obtener información del usuario
def get_user_info(user_id):
    conn = sqlite3.connect('qvapay.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

# Actualizar balance
def update_balance(user_id, amount):
    conn = sqlite3.connect('qvapay.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()

# Registrar transacción
def log_transaction(transaction_id, from_user, to_user, amount, transaction_type, status):
    conn = sqlite3.connect('qvapay.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO transactions (transaction_id, from_user, to_user, amount, transaction_type, status)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (transaction_id, from_user, to_user, amount, transaction_type, status))
    conn.commit()
    conn.close()

# Registrar orden P2P
def log_p2p_order(order_id, user_id, order_type, currency, amount, price, total, payment_method, status):
    conn = sqlite3.connect('qvapay.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO p2p_orders (order_id, user_id, order_type, currency, amount, price, total, payment_method, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (order_id, user_id, order_type, currency, amount, price, total, payment_method, status))
    conn.commit()
    conn.close()

# Registrar trade P2P
def log_p2p_trade(trade_id, order_id, buyer_id, seller_id, amount, price, total, status):
    conn = sqlite3.connect('qvapay.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO p2p_trades (trade_id, order_id, buyer_id, seller_id, amount, price, total, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (trade_id, order_id, buyer_id, seller_id, amount, price, total, status))
    conn.commit()
    conn.close()

# Registrar producto comprado
def log_product_purchase(user_id, product_id, product_name, price_paid):
    conn = sqlite3.connect('qvapay.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO user_products (user_id, product_id, product_name, price_paid)
        VALUES (?, ?, ?, ?)
    ''', (user_id, product_id, product_name, price_paid))
    conn.commit()
    conn.close()

# Teclado principal estilo QvaPay
def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton('💰 Balance')
    btn2 = types.KeyboardButton('🔄 Operaciones')
    btn3 = types.KeyboardButton('🤝 Mercado P2P')
    btn4 = types.KeyboardButton('🛒 Tienda')
    btn5 = types.KeyboardButton('🎁 Regalos')
    btn6 = types.KeyboardButton('💲 Ofertas P2P')
    btn7 = types.KeyboardButton('💳 MI VISA')
    btn8 = types.KeyboardButton('🔒 VPN Gratis')
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7, btn8)
    return markup

# Teclado de operaciones
def operations_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton('📥 Depositar')
    btn2 = types.KeyboardButton('📤 Retirar')
    btn3 = types.KeyboardButton('🔄 Transferir')
    btn4 = types.KeyboardButton('💱 Convertir')
    btn5 = types.KeyboardButton('🔙 Volver al Menú')
    markup.add(btn1, btn2, btn3, btn4, btn5)
    return markup

# Teclado P2P
def p2p_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton('🛒 Comprar QVP')
    btn2 = types.KeyboardButton('💰 Vender QVP')
    btn3 = types.KeyboardButton('📊 Mis Órdenes')
    btn4 = types.KeyboardButton('🤝 Mis Trades')
    btn5 = types.KeyboardButton('🔙 Volver al Menú')
    markup.add(btn1, btn2, btn3, btn4, btn5)
    return markup

# Teclado tienda
def shop_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton('🎮 Juegos Digitales')
    btn2 = types.KeyboardButton('📱 Recargas')
    btn3 = types.KeyboardButton('🎵 Streaming')
    btn4 = types.KeyboardButton('💼 Software')
    btn5 = types.KeyboardButton('🔙 Volver al Menú')
    markup.add(btn1, btn2, btn3, btn4, btn5)
    return markup

# Teclado sí/no
def yes_no_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton('✅ Sí')
    btn2 = types.KeyboardButton('❌ No')
    btn3 = types.KeyboardButton('🔙 Volver al Menú')
    markup.add(btn1, btn2, btn3)
    return markup

# COMANDO START - Diseño similar a QvaPay
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    register_user(user_id, username, first_name)
    user_info = get_user_info(user_id)
    
    welcome_text = f"""
¡Hola {escape_markdown(first_name)}!

Bienvenido a QvaPay, la forma más fácil de recibir y enviar pagos a nivel mundial.

Tu cuenta de Telegram ya está vinculada a una cuenta de QvaPay con el usuario **{user_info[4]}**

Desde aquí podrás consultar tu balance, enviar dinero a otros usuarios, procesar operaciones P2P y hasta ganar dinero invitando a otros."""

    bot.send_message(
        chat_id=message.chat.id,
        text=welcome_text,
        parse_mode='Markdown',
        reply_markup=main_menu()
    )

# MANEJADOR DEL MENÚ PRINCIPAL
@bot.message_handler(func=lambda message: True)
def handle_main_menu(message):
    user_id = message.from_user.id
    text = message.text
    
    if text == '💰 Balance':
        show_balance(message)
    elif text == '🔄 Operaciones':
        show_operations_menu(message)
    elif text == '🤝 Mercado P2P':
        show_p2p_menu(message)
    elif text == '🛒 Tienda':
        show_shop_menu(message)
    elif text == '🎁 Regalos':
        show_gifts(message)
    elif text == '💲 Ofertas P2P':
        show_p2p_offers(message)
    elif text == '💳 MI VISA':
        show_visa_card(message)
    elif text == '🔒 VPN Gratis':
        show_vpn(message)
    elif text == '🔙 Volver al Menú':
        bot.send_message(message.chat.id, "🏠 Menú Principal:", reply_markup=main_menu())

# FUNCIÓN DE BALANCE
def show_balance(message):
    user_id = message.from_user.id
    user_info = get_user_info(user_id)
    cup_rate = get_cup_usd_rate()
    
    balance_text = f"""
💰 *BALANCE QVAPAY*

👤 Usuario: {escape_markdown(user_info[4])}
💎 Saldo QVP: *{user_info[3]:.2f} QVP*
💵 Equivalente: *{user_info[3] * cup_rate:,.0f} CUP*

💱 *Tasa actual:* 1 QVP = {cup_rate:,.0f} CUP

💳 *Disponible para operar:* {user_info[3]:.2f} QVP"""

    bot.send_message(
        message.chat.id,
        balance_text,
        parse_mode='Markdown',
        reply_markup=main_menu()
    )

# FUNCIÓN DE OPERACIONES
def show_operations_menu(message):
    operations_text = """
🔄 *MENÚ DE OPERACIONES*

Elige el tipo de operación que deseas realizar:

📥 *Depositar* - Agregar fondos a tu cuenta
📤 *Retirar* - Retirar fondos a tu cuenta bancaria
🔄 *Transferir* - Enviar dinero a otros usuarios
💱 *Convertir* - Cambiar entre diferentes monedas"""

    bot.send_message(
        message.chat.id,
        operations_text,
        parse_mode='Markdown',
        reply_markup=operations_menu()
    )

# MANEJADOR DE OPERACIONES
@bot.message_handler(func=lambda message: message.text in ['📥 Depositar', '📤 Retirar', '🔄 Transferir', '💱 Convertir', '🔙 Volver al Menú'])
def handle_operations(message):
    text = message.text
    
    if text == '📥 Depositar':
        start_deposit(message)
    elif text == '📤 Retirar':
        start_withdrawal(message)
    elif text == '🔄 Transferir':
        start_transfer(message)
    elif text == '💱 Convertir':
        start_conversion(message)
    elif text == '🔙 Volver al Menú':
        bot.send_message(message.chat.id, "🏠 Menú Principal:", reply_markup=main_menu())

# FUNCIÓN DE DEPÓSITO
def start_deposit(message):
    deposit_text = """
📥 *DEPÓSITO DE FONDOS*

Selecciona el método de depósito:

💳 *Transfermóvil* - Depósito en CUP
🔵 *EnZona* - Depósito en CUP
₿ *Criptomonedas* - Depósito en BTC, ETH, USDT, etc.

💡 *Todos los depósitos se convierten automáticamente a QVP*"""

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton('💳 Transfermóvil')
    btn2 = types.KeyboardButton('🔵 EnZona')
    btn3 = types.KeyboardButton('₿ Criptomonedas')
    btn4 = types.KeyboardButton('🔙 Volver a Operaciones')
    markup.add(btn1, btn2, btn3, btn4)
    
    bot.send_message(
        message.chat.id,
        deposit_text,
        parse_mode='Markdown',
        reply_markup=markup
    )

# FUNCIÓN DE RETIRO
def start_withdrawal(message):
    user_id = message.from_user.id
    user_info = get_user_info(user_id)
    
    withdrawal_text = f"""
📤 *RETIRO DE FONDOS*

💎 *Saldo disponible:* {user_info[3]:.2f} QVP

Selecciona el método de retiro:

💳 *Tarjeta bancaria* - Retiro en CUP
₿ *Criptomonedas* - Retiro en BTC, ETH, USDT, etc.

⚠️ *Comisión de retiro:* 2%"""

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton('💳 Retiro a Tarjeta')
    btn2 = types.KeyboardButton('₿ Retiro Crypto')
    btn3 = types.KeyboardButton('🔙 Volver a Operaciones')
    markup.add(btn1, btn2, btn3)
    
    bot.send_message(
        message.chat.id,
        withdrawal_text,
        parse_mode='Markdown',
        reply_markup=markup
    )

# FUNCIÓN DE TRANSFERENCIA
def start_transfer(message):
    transfer_text = """
🔄 *TRANSFERENCIA A OTROS USUARIOS*

Puedes transferir QVP a otros usuarios de QvaPay de forma instantánea y sin comisiones.

💡 *Para transferir:*
1. Obtén el QvaPay ID del destinatario
2. Confirma la transferencia
3. El dinero llegará instantáneamente

¿Deseas continuar con la transferencia?"""

    bot.send_message(
        message.chat.id,
        transfer_text,
        parse_mode='Markdown',
        reply_markup=yes_no_keyboard()
    )

# FUNCIÓN DE CONVERSIÓN
def start_conversion(message):
    conversion_text = """
💱 *CONVERSIÓN DE MONEDAS*

Convierte entre diferentes monedas al tipo de cambio actual:

🔄 QVP ⇄ CUP
🔄 QVP ⇄ Criptomonedas
🔄 Criptomonedas ⇄ CUP

💡 *Tipos de cambio en tiempo real*
💡 *Comisiones competitivas*

¿Qué conversión deseas realizar?"""

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton('🔄 QVP a CUP')
    btn2 = types.KeyboardButton('🔄 CUP a QVP')
    btn3 = types.KeyboardButton('₿ QVP a Crypto')
    btn4 = types.KeyboardButton('₿ Crypto a QVP')
    btn5 = types.KeyboardButton('🔙 Volver a Operaciones')
    markup.add(btn1, btn2, btn3, btn4, btn5)
    
    bot.send_message(
        message.chat.id,
        conversion_text,
        parse_mode='Markdown',
        reply_markup=markup
    )

# FUNCIÓN MERCADO P2P
def show_p2p_menu(message):
    p2p_text = """
🤝 *MERCADO P2P QVAPAY*

Compra y vende QVP directamente con otros usuarios de forma segura.

🔒 *Sistema de seguridad:*
• Depósito en garantía (escrow)
• Tiempo límite para completar
• Soporte de disputas
• Calificación de usuarios

💡 *¿Cómo funciona?*
1. Publicas tu oferta de compra/venta
2. Otro usuario acepta tu oferta
3. Realizan el trade de forma segura
4. Califican la experiencia"""

    bot.send_message(
        message.chat.id,
        p2p_text,
        parse_mode='Markdown',
        reply_markup=p2p_menu()
    )

# MANEJADOR P2P
@bot.message_handler(func=lambda message: message.text in ['🛒 Comprar QVP', '💰 Vender QVP', '📊 Mis Órdenes', '🤝 Mis Trades'])
def handle_p2p(message):
    text = message.text
    
    if text == '🛒 Comprar QVP':
        show_buy_orders(message)
    elif text == '💰 Vender QVP':
        show_sell_orders(message)
    elif text == '📊 Mis Órdenes':
        show_my_orders(message)
    elif text == '🤝 Mis Trades':
        show_my_trades(message)

# MOSTRAR ÓRDENES DE COMPRA
def show_buy_orders(message):
    # Simular órdenes de compra activas
    buy_orders_text = """
🛒 *ÓRDENES DE COMPRA ACTIVAS*

📊 *Oferta #1:*
• Usuario: QVP_Comprador1
• Compra: 100 QVP
• Precio: 245 CUP/QVP
• Método: Transfermóvil
• Límite: 15 min

📊 *Oferta #2:*
• Usuario: QVP_Comprador2  
• Compra: 50 QVP
• Precio: 248 CUP/QVP
• Método: EnZona
• Límite: 30 min

📊 *Oferta #3:*
• Usuario: QVP_Comprador3
• Compra: 200 QVP
• Precio: 242 CUP/QVP
• Método: Transfermóvil
• Límite: 10 min

💡 *Selecciona una oferta para continuar*"""

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton('✅ Aceptar Oferta #1')
    btn2 = types.KeyboardButton('✅ Aceptar Oferta #2')
    btn3 = types.KeyboardButton('✅ Aceptar Oferta #3')
    btn4 = types.KeyboardButton('🔙 Volver a P2P')
    markup.add(btn1, btn2, btn3, btn4)
    
    bot.send_message(
        message.chat.id,
        buy_orders_text,
        parse_mode='Markdown',
        reply_markup=markup
    )

# MOSTRAR ÓRDENES DE VENTA
def show_sell_orders(message):
    # Simular órdenes de venta activas
    sell_orders_text = """
💰 *ÓRDENES DE VENTA ACTIVAS*

📊 *Oferta #1:*
• Usuario: QVP_Vendedor1
• Venta: 150 QVP
• Precio: 250 CUP/QVP
• Método: Transfermóvil
• Límite: 20 min

📊 *Oferta #2:*
• Usuario: QVP_Vendedor2
• Venta: 75 QVP  
• Precio: 252 CUP/QVP
• Método: EnZona
• Límite: 25 min

📊 *Oferta #3:*
• Usuario: QVP_Vendedor3
• Venta: 300 QVP
• Precio: 248 CUP/QVP
• Método: Transfermóvil
• Límite: 15 min

💡 *Selecciona una oferta para continuar*"""

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton('✅ Aceptar Oferta #1')
    btn2 = types.KeyboardButton('✅ Aceptar Oferta #2')
    btn3 = types.KeyboardButton('✅ Aceptar Oferta #3')
    btn4 = types.KeyboardButton('🔙 Volver a P2P')
    markup.add(btn1, btn2, btn3, btn4)
    
    bot.send_message(
        message.chat.id,
        sell_orders_text,
        parse_mode='Markdown',
        reply_markup=markup
    )

# MOSTRAR MIS ÓRDENES
def show_my_orders(message):
    user_id = message.from_user.id
    
    my_orders_text = f"""
📊 *MIS ÓRDENES ACTIVAS*

Actualmente no tienes órdenes activas.

💡 *Para crear una orden:*
• Ve a *\"Comprar QVP\"* o *\"Vender QVP\"*
• Configura tu precio y cantidad
• Publica tu orden

🔒 *Tus órdenes anteriores se mostrarán aquí*"""

    bot.send_message(
        message.chat.id,
        my_orders_text,
        parse_mode='Markdown',
        reply_markup=p2p_menu()
    )

# MOSTRAR MIS TRADES
def show_my_trades(message):
    user_id = message.from_user.id
    
    my_trades_text = f"""
🤝 *MIS TRADES RECIENTES*

No hay trades recientes.

💡 *Cuando realices trades P2P:*
• Se mostrarán aquí
• Podrás calificar a los usuarios
• Tendrás historial completo

🔒 *Sistema seguro con depósito en garantía*"""

    bot.send_message(
        message.chat.id,
        my_trades_text,
        parse_mode='Markdown',
        reply_markup=p2p_menu()
    )

# FUNCIÓN TIENDA
def show_shop_menu(message):
    shop_text = """
🛒 *TIENDA QVAPAY*

Compra productos digitales y servicios con tu saldo QVP.

📦 *Categorías disponibles:*

🎮 *Juegos Digitales* - Steam, PlayStation, Xbox
📱 *Recargas* - Datos, minutos, SMS
🎵 *Streaming* - Spotify, Netflix, Disney+
💼 *Software* - Office, antivirus, herramientas

💡 *Todos los productos se entregan instantáneamente*"""

    bot.send_message(
        message.chat.id,
        shop_text,
        parse_mode='Markdown',
        reply_markup=shop_menu()
    )

# MANEJADOR TIENDA
@bot.message_handler(func=lambda message: message.text in ['🎮 Juegos Digitales', '📱 Recargas', '🎵 Streaming', '💼 Software'])
def handle_shop_categories(message):
    text = message.text
    
    if text == '🎮 Juegos Digitales':
        show_games_products(message)
    elif text == '📱 Recargas':
        show_mobile_products(message)
    elif text == '🎵 Streaming':
        show_streaming_products(message)
    elif text == '💼 Software':
        show_software_products(message)

# MOSTRAR PRODUCTOS DE JUEGOS
def show_games_products(message):
    products_text = """
🎮 *JUEGOS DIGITALES*

🛒 *Productos disponibles:*

1. 🎮 *Steam Wallet $10*
   💰 Precio: 2,500 CUP
   📦 Stock: 50 unidades

2. 🎮 *Steam Wallet $20*
   💰 Precio: 5,000 CUP  
   📦 Stock: 30 unidades

3. 🎮 *PlayStation Network $10*
   💰 Precio: 2,600 CUP
   📦 Stock: 25 unidades

4. 🎮 *Xbox Gift Card $10*
   💰 Precio: 2,550 CUP
   📦 Stock: 20 unidades

💡 *Selecciona el número del producto para comprar*"""

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton('🛒 Comprar Producto 1')
    btn2 = types.KeyboardButton('🛒 Comprar Producto 2')
    btn3 = types.KeyboardButton('🛒 Comprar Producto 3')
    btn4 = types.KeyboardButton('🛒 Comprar Producto 4')
    btn5 = types.KeyboardButton('🔙 Volver a Tienda')
    markup.add(btn1, btn2, btn3, btn4, btn5)
    
    bot.send_message(
        message.chat.id,
        products_text,
        parse_mode='Markdown',
        reply_markup=markup
    )

# MOSTRAR PRODUCTOS MÓVILES
def show_mobile_products(message):
    products_text = """
📱 *RECARGAS MÓVILES*

🛒 *Productos disponibles:*

1. 📱 *Recarga Móvil 5GB*
   💰 Precio: 1,200 CUP
   📦 Stock: 100 unidades

2. 📱 *Recarga Móvil 10GB*  
   💰 Precio: 2,200 CUP
   📦 Stock: 80 unidades

3. 📱 *Recarga Móvil 20GB*
   💰 Precio: 4,000 CUP
   📦 Stock: 60 unidades

4. 📱 *Paquete Minutos 100*
   💰 Precio: 800 CUP
   📦 Stock: 120 unidades

💡 *Selecciona el número del producto para comprar*"""

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton('🛒 Comprar Producto 1')
    btn2 = types.KeyboardButton('🛒 Comprar Producto 2')
    btn3 = types.KeyboardButton('🛒 Comprar Producto 3')
    btn4 = types.KeyboardButton('🛒 Comprar Producto 4')
    btn5 = types.KeyboardButton('🔙 Volver a Tienda')
    markup.add(btn1, btn2, btn3, btn4, btn5)
    
    bot.send_message(
        message.chat.id,
        products_text,
        parse_mode='Markdown',
        reply_markup=markup
    )

# FUNCIONES ADICIONALES (simplificadas)
def show_gifts(message):
    gifts_text = """
🎁 *SISTEMA DE REGALOS*

Envía regalos a tus amigos y familiares:

💝 *Regalo Directo* - Envía QVP como regalo
🎉 *Código Regalo* - Crea códigos canjeables
👥 *Invitaciones* - Gana comisiones por invitar

💡 *Próximamente...*"""

    bot.send_message(
        message.chat.id,
        gifts_text,
        parse_mode='Markdown',
        reply_markup=main_menu()
    )

def show_p2p_offers(message):
    offers_text = """
💲 *OFERTAS P2P DESTACADAS*

🏆 *Ofertas verificadas:*

⭐ *Vendedor Premium: QVP_Trusted1*
• Calificación: 4.9/5.0
• Trades: 1,245 completados
• Tiempo respuesta: < 5 min

⭐ *Comprador Premium: QVP_BuyerPro*
• Calificación: 4.8/5.0  
• Trades: 890 completados
• Tiempo respuesta: < 3 min

💡 *Usuarios verificados = Mayor seguridad*"""

    bot.send_message(
        message.chat.id,
        offers_text,
        parse_mode='Markdown',
        reply_markup=main_menu()
    )

def show_visa_card(message):
    visa_text = """
💳 *TARJETA VISA QVAPAY*

Próximamente podrás solicitar tu tarjeta Visa física y virtual vinculada a tu cuenta QvaPay.

🌟 *Beneficios:*
• Compras online internacionales
• Retiros en cajeros automáticos
• Pagos en establecimientos
• Seguridad avanzada

📅 *Disponible pronto...*"""

    bot.send_message(
        message.chat.id,
        visa_text,
        parse_mode='Markdown',
        reply_markup=main_menu()
    )

def show_vpn(message):
    vpn_text = """
🔒 *VPN GRATIS QVAPAY*

Protege tu privacidad y navegación con nuestro servicio VPN gratuito.

🛡️ *Características:*
• Conexión segura y encriptada
• Sin límites de ancho de banda
• Servidores en múltiples países
• Fácil configuración

🌐 *Para activar tu VPN gratuita:*
Visita: https://qvapay.com/vpn

💡 *Disponible para todos los usuarios*"""

    bot.send_message(
        message.chat.id,
        vpn_text,
        parse_mode='Markdown',
        reply_markup=main_menu()
    )

# MOSTRAR PRODUCTOS STREAMING
def show_streaming_products(message):
    products_text = """
🎵 *SERVICIOS DE STREAMING*

🛒 *Productos disponibles:*

1. 🎵 *Spotify Premium 1 Mes*
   💰 Precio: 800 CUP
   📦 Stock: 30 unidades

2. 📺 *Netflix Basic 1 Mes*
   💰 Precio: 1,800 CUP
   📦 Stock: 25 unidades

3. 🎬 *Disney+ 1 Mes*
   💰 Precio: 1,500 CUP
   📦 Stock: 20 unidades

4. 🎥 *HBO Max 1 Mes*
   💰 Precio: 1,600 CUP
   📦 Stock: 15 unidades

💡 *Selecciona el número del producto para comprar*"""

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton('🛒 Comprar Spotify')
    btn2 = types.KeyboardButton('🛒 Comprar Netflix')
    btn3 = types.KeyboardButton('🛒 Comprar Disney+')
    btn4 = types.KeyboardButton('🛒 Comprar HBO Max')
    btn5 = types.KeyboardButton('🔙 Volver a Tienda')
    markup.add(btn1, btn2, btn3, btn4, btn5)
    
    bot.send_message(
        message.chat.id,
        products_text,
        parse_mode='Markdown',
        reply_markup=markup
    )

# MOSTRAR PRODUCTOS SOFTWARE
def show_software_products(message):
    products_text = """
💼 *SOFTWARE Y HERRAMIENTAS*

🛒 *Productos disponibles:*

1. 💻 *Microsoft Office 365 1 Año*
   💰 Precio: 3,000 CUP
   📦 Stock: 15 unidades

2. 🛡️ *Antivirus Premium 1 Año*
   💰 Precio: 1,200 CUP
   📦 Stock: 40 unidades

3. 🎨 *Adobe Creative Cloud 1 Mes*
   💰 Precio: 2,500 CUP
   📦 Stock: 10 unidades

4. 🔧 *Windows 11 Pro Licencia*
   💰 Precio: 4,000 CUP
   📦 Stock: 8 unidades

💡 *Selecciona el número del producto para comprar*"""

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton('🛒 Comprar Office')
    btn2 = types.KeyboardButton('🛒 Comprar Antivirus')
    btn3 = types.KeyboardButton('🛒 Comprar Adobe')
    btn4 = types.KeyboardButton('🛒 Comprar Windows')
    btn5 = types.KeyboardButton('🔙 Volver a Tienda')
    markup.add(btn1, btn2, btn3, btn4, btn5)
    
    bot.send_message(
        message.chat.id,
        products_text,
        parse_mode='Markdown',
        reply_markup=markup
    )

# SISTEMA DE P2P CON ESCROW
def create_p2p_trade(message, order_type, amount, price, payment_method):
    user_id = message.from_user.id
    trade_id = f"TRADE{uuid.uuid4().hex[:10].upper()}"
    
    # Simular creación de trade
    p2p_trades[trade_id] = {
        'trade_id': trade_id,
        'user_id': user_id,
        'order_type': order_type,
        'amount': amount,
        'price': price,
        'total': amount * price,
        'payment_method': payment_method,
        'status': 'pending',
        'created_at': datetime.now()
    }
    
    trade_text = f"""
🤝 *TRADE P2P CREADO*

🆔 *Trade ID:* {trade_id}
💼 *Tipo:* {'Compra' if order_type == 'buy' else 'Venta'}
💎 *Cantidad:* {amount} QVP
💰 *Precio:* {price} CUP/QVP
💵 *Total:* {amount * price} CUP
💳 *Método:* {payment_method}

🔒 *Estado:* En espera de contraparte
⏰ *Tiempo límite:* 30 minutos

💡 *Instrucciones:*
1. Espera a que alguien acepte tu trade
2. Una vez aceptado, tendrás 30 min para completar
3. El pago se mantiene en garantía
4. Se libera cuando ambas partes confirman"""

    bot.send_message(
        message.chat.id,
        trade_text,
        parse_mode='Markdown',
        reply_markup=p2p_menu()
    )

# INICIALIZACIÓN Y EJECUCIÓN
def run_bot():
    print("🧠 Inicializando base de datos...")
    init_db()
    print("🤖 Iniciando bot QvaPay...")
    print(f"👑 Administrador: {ADMIN_ID}")
    
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        print(f"Error en el bot: {e}")
        time.sleep(10)
        run_bot()

if __name__ == "__main__":
    # Iniciar el bot en un hilo separado
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Iniciar el servidor web para Render
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
