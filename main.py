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
TOKEN = "7630853977:AAGrnl9XdzC-8eONDIp-8NM-uqimlYboFcc"
GROUP_CHAT_ID = "-4932107704"  # Reemplaza con el ID de tu grupo
ADMIN_ID = 1853800972  # Reemplaza con tu ID de usuario de Telegram
bot = telebot.TeleBot(TOKEN)

# Crear app Flask para Render
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 CubaWallet ProCoin Bot está funcionando"

@app.route('/health')
def health():
    return "✅ OK", 200

# Diccionarios para operaciones pendientes
pending_deposits = {}
pending_withdrawals = {}
pending_crypto_deposits = {}

# APIs para tasas de cambio
API_ENDPOINTS = {
    "eltoque": "https://eltoque.com/",
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

# Función para obtener tasa CUP/USD desde ElToque
def get_cup_usd_rate():
    """
    Obtiene la tasa de cambio CUP/USD desde ElToque.com
    Retorna: float o None si hay error
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(API_ENDPOINTS["eltoque"], headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Buscar elementos que contengan la tasa de cambio
        # Esta es una aproximación - puede necesitar ajustes según la estructura actual de ElToque
        elements = soup.find_all(['div', 'span'], string=re.compile(r'1\s*USD\s*=\s*[\d,.]+\s*CUP'))
        
        for element in elements:
            text = element.get_text()
            match = re.search(r'1\s*USD\s*=\s*([\d,.]+)\s*CUP', text)
            if match:
                rate = float(match.group(1).replace(',', ''))
                print(f"✅ Tasa CUP/USD obtenida: {rate}")
                return rate
        
        # Fallback: tasa por defecto
        print("⚠️ No se pudo obtener tasa, usando valor por defecto")
        return 240.0
        
    except Exception as e:
        print(f"❌ Error obteniendo tasa CUP/USD: {e}")
        return 240.0  # Tasa por defecto

# Función para obtener precios crypto desde Binance
def get_crypto_price(symbol):
    """
    Obtiene precio de criptomoneda desde Binance
    """
    try:
        if symbol == "USDT":
            return 1.0  # USDT siempre 1:1 con USD
            
        url = f"{API_ENDPOINTS['binance']}?symbol={symbol}USDT"
        response = requests.get(url, timeout=10)
        data = response.json()
        return float(data['price'])
    except Exception as e:
        print(f"❌ Error obteniendo precio de {symbol}: {e}")
        # Fallback a CoinGecko
        try:
            coin_id = SUPPORTED_CRYPTO.get(symbol)
            if coin_id:
                url = f"{API_ENDPOINTS['coingecko']}?ids={coin_id}&vs_currencies=usd"
                response = requests.get(url, timeout=10)
                data = response.json()
                return data[coin_id]['usd']
        except Exception as e2:
            print(f"❌ Error con CoinGecko: {e2}")
            
        # Valores por defecto
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
        print(f"✅ Notificación enviada al grupo {GROUP_CHAT_ID}")
        return True
    except Exception as e:
        print(f"❌ Error enviando notificación: {e}")
        return False

# Inicializar Base de Datos
def init_db():
    conn = sqlite3.connect('cubawallet.db')
    cursor = conn.cursor()
    
    # Tabla de usuarios
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
    
    # Tabla de transacciones
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
    
    # Tabla de depósitos
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
    
    # Tabla de retiros
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
    
    # Tabla de billeteras crypto
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS crypto_wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            currency TEXT,
            balance REAL DEFAULT 0.0,
            address TEXT UNIQUE,
            created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    # Tabla de transacciones crypto
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS crypto_transactions (
            transaction_id TEXT PRIMARY KEY,
            user_id INTEGER,
            currency TEXT,
            amount_crypto REAL,
            amount_prc REAL,
            exchange_rate REAL,
            transaction_type TEXT,
            address TEXT,
            status TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    conn.commit()
    conn.close()

# Función para limpiar la base de datos (solo admin)
def clear_database():
    try:
        conn = sqlite3.connect('cubawallet.db')
        cursor = conn.cursor()
        
        cursor.execute('DROP TABLE IF EXISTS crypto_transactions')
        cursor.execute('DROP TABLE IF EXISTS crypto_wallets')
        cursor.execute('DROP TABLE IF EXISTS withdrawals')
        cursor.execute('DROP TABLE IF EXISTS deposits')
        cursor.execute('DROP TABLE IF EXISTS transactions')
        cursor.execute('DROP TABLE IF EXISTS users')
        
        conn.commit()
        conn.close()
        
        init_db()
        return True
    except Exception as e:
        print(f"Error limpiando base de datos: {e}")
        return False

# Función para escapar texto para Markdown
def escape_markdown(text):
    if text is None:
        return ""
    escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in escape_chars:
        text = str(text).replace(char, f'\\{char}')
    return text

# Función para verificar si es administrador
def is_admin(user_id):
    return user_id == ADMIN_ID

# Generar dirección única de wallet
def generate_wallet_address():
    return f"PRC{uuid.uuid4().hex[:12].upper()}"

# Generar dirección única para crypto
def generate_crypto_address(currency):
    prefixes = {
        "BTC": "bc1q",
        "ETH": "0x",
        "USDT": "0x",
        "BNB": "bnb1",
        "ADA": "addr1",
        "DOT": "1",
        "SOL": "So1"
    }
    prefix = prefixes.get(currency, "crypto")
    return f"{prefix}{uuid.uuid4().hex[:12]}"

# Registrar usuario en la base de datos
def register_user(user_id, username, first_name):
    conn = sqlite3.connect('cubawallet.db')
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
        
        # Crear billeteras crypto para el usuario
        for currency in SUPPORTED_CRYPTO.keys():
            crypto_address = generate_crypto_address(currency)
            cursor.execute('''
                INSERT INTO crypto_wallets (user_id, currency, balance, address)
                VALUES (?, ?, ?, ?)
            ''', (user_id, currency, 0.0, crypto_address))
        
        conn.commit()
        
        notification_text = f"""
🆕 *NUEVO USUARIO REGISTRADO* 🆕

*Información del usuario:*
• *Nombre:* {escape_markdown(first_name)}
• *Username:* @{escape_markdown(username) if username else 'N/A'}
• *User ID:* `{user_id}`
• *Wallet:* `{wallet_address}`

*¡Bienvenido a la familia ProCoin\!*"""
        
        send_group_notification(notification_text)
    
    conn.close()

# Obtener información del usuario
def get_user_info(user_id):
    conn = sqlite3.connect('cubawallet.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

# Obtener usuario por wallet address
def get_user_by_wallet(wallet_address):
    conn = sqlite3.connect('cubawallet.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE wallet_address = ?', (wallet_address,))
    user = cursor.fetchone()
    conn.close()
    return user

# Obtener billeteras crypto del usuario
def get_user_crypto_wallets(user_id):
    conn = sqlite3.connect('cubawallet.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM crypto_wallets WHERE user_id = ?', (user_id,))
    wallets = cursor.fetchall()
    conn.close()
    return wallets

# Obtener billetera crypto específica
def get_user_crypto_wallet(user_id, currency):
    conn = sqlite3.connect('cubawallet.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM crypto_wallets WHERE user_id = ? AND currency = ?', (user_id, currency))
    wallet = cursor.fetchone()
    conn.close()
    return wallet

# Actualizar balance ProCoin
def update_balance(user_id, amount):
    conn = sqlite3.connect('cubawallet.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()

# Actualizar balance crypto
def update_crypto_balance(user_id, currency, amount):
    conn = sqlite3.connect('cubawallet.db')
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE crypto_wallets 
        SET balance = balance + ? 
        WHERE user_id = ? AND currency = ?
    ''', (amount, user_id, currency))
    conn.commit()
    conn.close()

# Registrar transacción ProCoin
def log_transaction(transaction_id, from_user, to_user, amount, transaction_type, status):
    conn = sqlite3.connect('cubawallet.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO transactions (transaction_id, from_user, to_user, amount, transaction_type, status)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (transaction_id, from_user, to_user, amount, transaction_type, status))
    conn.commit()
    conn.close()

# Registrar depósito CUP
def log_deposit(deposit_id, user_id, amount_cup, amount_prc, exchange_rate, method, status, screenshot_id=None):
    conn = sqlite3.connect('cubawallet.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO deposits (deposit_id, user_id, amount_cup, amount_prc, exchange_rate, method, status, screenshot_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (deposit_id, user_id, amount_cup, amount_prc, exchange_rate, method, status, screenshot_id))
    conn.commit()
    conn.close()

# Registrar retiro
def log_withdrawal(withdrawal_id, user_id, amount_prc, amount_cup, exchange_rate, fee, net_amount, card_number, status, screenshot_id=None):
    conn = sqlite3.connect('cubawallet.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO withdrawals (withdrawal_id, user_id, amount_prc, amount_cup, exchange_rate, fee, net_amount, card_number, status, screenshot_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (withdrawal_id, user_id, amount_prc, amount_cup, exchange_rate, fee, net_amount, card_number, status, screenshot_id))
    conn.commit()
    conn.close()

# Registrar transacción crypto
def log_crypto_transaction(transaction_id, user_id, currency, amount_crypto, amount_prc, exchange_rate, transaction_type, address, status):
    conn = sqlite3.connect('cubawallet.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO crypto_transactions (transaction_id, user_id, currency, amount_crypto, amount_prc, exchange_rate, transaction_type, address, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (transaction_id, user_id, currency, amount_crypto, amount_prc, exchange_rate, transaction_type, address, status))
    conn.commit()
    conn.close()

# Menú principal con botones inline
def main_menu(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn_send = types.InlineKeyboardButton("📤 Enviar ProCoin", callback_data="send_money")
    btn_receive = types.InlineKeyboardButton("📥 Recibir ProCoin", callback_data="receive_money")
    btn_deposit = types.InlineKeyboardButton("💵 Depositar CUP", callback_data="deposit_cup")
    btn_deposit_crypto = types.InlineKeyboardButton("₿ Depositar Crypto", callback_data="deposit_crypto")
    btn_withdraw = types.InlineKeyboardButton("💸 Retirar CUP", callback_data="withdraw_cup")
    btn_withdraw_crypto = types.InlineKeyboardButton("📤 Retirar Crypto", callback_data="withdraw_crypto")
    btn_balance = types.InlineKeyboardButton("💰 Ver Saldo", callback_data="check_balance")
    btn_rates = types.InlineKeyboardButton("📈 Ver Tasas", callback_data="check_rates")
    
    markup.add(btn_send, btn_receive, btn_deposit, btn_deposit_crypto, btn_withdraw, btn_withdraw_crypto, btn_balance, btn_rates)
    
    return markup

# Menú de selección de criptomonedas
def crypto_selection_menu(action):
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    buttons = []
    for currency in SUPPORTED_CRYPTO.keys():
        btn = types.InlineKeyboardButton(f"{currency}", callback_data=f"{action}_{currency}")
        buttons.append(btn)
    
    btn_back = types.InlineKeyboardButton("🔙 Volver", callback_data="back_to_main")
    buttons.append(btn_back)
    
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.add(buttons[i], buttons[i+1])
        else:
            markup.add(buttons[i])
    
    return markup

# COMANDOS DE ADMINISTRADOR

@bot.message_handler(commands=['limpiar'])
def clear_database_command(message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.reply_to(message, "❌ *Comando solo para administradores*", parse_mode='Markdown')
        return
    
    markup = types.InlineKeyboardMarkup()
    btn_confirm = types.InlineKeyboardButton("✅ Sí, limpiar todo", callback_data="confirm_clear")
    btn_cancel = types.InlineKeyboardButton("❌ Cancelar", callback_data="cancel_clear")
    markup.add(btn_confirm, btn_cancel)
    
    bot.reply_to(message,
                "⚠️ *¿ESTÁS SEGURO DE QUE QUIERES LIMPIAR LA BASE DE DATOS?*\n\n"
                "🚨 *ESTA ACCIÓN ELIMINARÁ:*\n"
                "• Todos los usuarios registrados\n"
                "• Todas las transacciones\n" 
                "• Todos los depósitos y retiros\n"
                "• Todas las billeteras crypto\n\n"
                "🔴 *¡ESTA ACCIÓN NO SE PUEDE DESHACER!*",
                parse_mode='Markdown',
                reply_markup=markup)

@bot.message_handler(commands=['recargar'])
def recharge_balance(message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.reply_to(message, "❌ *Comando solo para administradores*", parse_mode='Markdown')
        return
    
    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, 
                    "❌ *Formato incorrecto*\n\n"
                    "Uso: `/recargar PRCABC123 100.50`\n\n"
                    "• PRCABC123 = Wallet del usuario\n"
                    "• 100.50 = Cantidad de ProCoin a recargar", 
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
    
    transaction_id = f"ADM{uuid.uuid4().hex[:10].upper()}"
    log_transaction(transaction_id, None, user_info[0], amount, "admin_recharge", "completed")
    
    try:
        user_notification = f"""
💎 *RECARGA DE PROCOIN APROBADA*

✅ Se ha recargado tu cuenta con ProCoin.

📊 *Detalles:*
• ProCoin recargados: {amount:.2f} PRC
• Wallet: `{wallet_address}`
• Transacción: {transaction_id}
• Saldo anterior: {old_balance:.2f} PRC
• Nuevo saldo: *{new_balance:.2f} PRC*

¡Gracias por usar ProCoin! 🎉"""
        
        bot.send_message(user_info[0], user_notification, parse_mode='Markdown')
    except Exception as e:
        print(f"No se pudo notificar al usuario: {e}")
    
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
                f"Usuario: {escape_markdown(user_info[2])}\n"
                f"ProCoin: {amount:.2f} PRC\n"
                f"Nuevo saldo: {new_balance:.2f} PRC",
                parse_mode='Markdown')

@bot.message_handler(commands=['tasas'])
def show_rates_command(message):
    """Comando para ver tasas actuales"""
    show_current_rates(message)

@bot.message_handler(commands=['estadisticas'])
def show_stats(message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.reply_to(message, "❌ *Comando solo para administradores*", parse_mode='Markdown')
        return
        
    conn = sqlite3.connect('cubawallet.db')
    cursor = conn.cursor()
    
    # Total de usuarios
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    # Total de transacciones
    cursor.execute('SELECT COUNT(*) FROM transactions')
    total_transactions = cursor.fetchone()[0]
    
    # Total de transacciones crypto
    cursor.execute('SELECT COUNT(*) FROM crypto_transactions')
    total_crypto_transactions = cursor.fetchone()[0]
    
    # Volumen total en ProCoin
    cursor.execute('SELECT SUM(amount) FROM transactions WHERE status = "completed"')
    total_volume_prc = cursor.fetchone()[0] or 0
    
    # Depósitos pendientes
    cursor.execute('SELECT COUNT(*) FROM deposits WHERE status = "pending"')
    pending_deposits_count = cursor.fetchone()[0]
    
    # Retiros pendientes
    cursor.execute('SELECT COUNT(*) FROM withdrawals WHERE status = "pending"')
    pending_withdrawals_count = cursor.fetchone()[0]
    
    conn.close()
    
    # Obtener tasas actuales
    cup_rate = get_cup_usd_rate()
    
    stats_text = f"""
📈 *ESTADÍSTICAS DE PROCOIN*

👥 *Usuarios registrados:* {total_users}
🔄 *Transacciones ProCoin:* {total_transactions}
₿ *Transacciones crypto:* {total_crypto_transactions}
💎 *Volumen ProCoin:* {total_volume_prc:.2f} PRC
💰 *Volumen equivalente CUP:* {total_volume_prc * cup_rate:,.0f} CUP

⏳ *Depósitos pendientes:* {pending_deposits_count}
⏳ *Retiros pendientes:* {pending_withdrawals_count}
📅 *Actualizado:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    
    bot.send_message(
        message.chat.id,
        stats_text,
        parse_mode='Markdown'
    )

# COMANDO START
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    register_user(user_id, username, first_name)
    user_info = get_user_info(user_id)
    
    # Obtener tasas actuales
    cup_rate = get_cup_usd_rate()
    
    welcome_text = f"""
👋 ¡Bienvenido a ProCoin, {escape_markdown(first_name)}!

💎 *Tu Billetera Digital con ProCoin*

📊 *Información de tu cuenta:*
• Usuario: {escape_markdown(first_name)}
• Wallet: `{user_info[4]}`
• Saldo: {user_info[3]:.2f} PRC
• Equivalente: {user_info[3] * cup_rate:,.0f} CUP

💱 *Tasa actual:* 1 PRC = {cup_rate:,.0f} CUP

🌟 *¿Qué puedes hacer?*
• 📤 Enviar ProCoin a otros usuarios
• 📥 Recibir ProCoin con tu dirección única
• 💵 Depositar CUP (se convierte a ProCoin)
• ₿ Depositar criptomonedas (se convierte a ProCoin)
• 💸 Retirar CUP (ProCoin a CUP)
• 📤 Retirar criptomonedas
• 💰 Consultar saldos y tasas

⚡ *Selecciona una opción:*"""
    
    bot.send_message(
        chat_id=message.chat.id,
        text=welcome_text,
        parse_mode='Markdown',
        reply_markup=main_menu(message.chat.id)
    )

# MANEJADOR DE CALLBACKS
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    user_info = get_user_info(user_id)
    
    if call.data == "send_money":
        msg = bot.send_message(
            call.message.chat.id,
            "💎 *ENVIAR PROCOIN*\n\n📧 Ingresa la dirección de wallet del destinatario:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_recipient)
    
    elif call.data == "receive_money":
        receive_text = f"""
📥 *RECIBIR PROCOIN*

🆔 *Tu Dirección de Wallet:*
`{user_info[4]}`

📋 *Instrucciones:*
1\. Comparte esta dirección con quien te enviará ProCoin
2\. El remitente debe usar la opción *\"Enviar ProCoin\"*
3\. Ingresa tu dirección única mostrada arriba
4\. ¡Recibirás los ProCoin instantáneamente\!

💡 *Consejo:* Copia tu dirección haciendo clic en ella\."""
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=receive_text,
            parse_mode='Markdown',
            reply_markup=main_menu(call.message.chat.id)
        )
    
    elif call.data == "deposit_cup":
        # Obtener tasa actual
        cup_rate = get_cup_usd_rate()
        
        deposit_text = f"""
💵 *DEPOSITAR CUP*

Actualmente 1 PRC = *{cup_rate:,.0f} CUP*

💡 *¿Cómo funciona?*
1. Depositas CUP via Transfermóvil/EnZona
2. Se convierte automáticamente a ProCoin
3. Recibes ProCoin en tu wallet al tipo de cambio actual

📊 *Ejemplo:*
• Si depositas {cup_rate:,.0f} CUP
• Recibirás 1.00 PRC

💎 *Selecciona el método de pago:*"""
        
        deposit_methods = types.InlineKeyboardMarkup(row_width=2)
        btn_transfermovil = types.InlineKeyboardButton("📱 Transfermóvil", callback_data="deposit_transfermovil")
        btn_enzona = types.InlineKeyboardButton("🔵 EnZona", callback_data="deposit_enzona")
        btn_back = types.InlineKeyboardButton("🔙 Volver", callback_data="back_to_main")
        deposit_methods.add(btn_transfermovil, btn_enzona, btn_back)
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=deposit_text,
            parse_mode='Markdown',
            reply_markup=deposit_methods
        )
    
    elif call.data == "deposit_crypto":
        deposit_text = """
₿ *DEPOSITAR CRIPTOMONEDAS*

Convierte tus criptomonedas a ProCoin al tipo de cambio actual.

💡 *¿Cómo funciona?*
1. Selecciona la criptomoneda
2. Recibes una dirección única
3. Envías las criptomonedas
4. Se convierten automáticamente a ProCoin
5. Recibes el equivalente en tu wallet

💎 *Selecciona la criptomoneda:*"""
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=deposit_text,
            parse_mode='Markdown',
            reply_markup=crypto_selection_menu("deposit_crypto")
        )
    
    elif call.data.startswith("deposit_crypto_"):
        currency = call.data.replace("deposit_crypto_", "")
        show_crypto_deposit_address(call, currency)
    
    elif call.data == "withdraw_cup":
        start_cup_withdrawal(call)
    
    elif call.data == "withdraw_crypto":
        withdraw_text = """
📤 *RETIRAR CRIPTOMONEDAS*

Convierte tus ProCoin a criptomonedas.

💡 *Instrucciones:*
1. Selecciona la criptomoneda
2. Ingresa la cantidad de ProCoin
3. Proporciona tu dirección de destino
4. Recibirás las criptomonedas

💎 *Selecciona la criptomoneda:*"""
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=withdraw_text,
            parse_mode='Markdown',
            reply_markup=crypto_selection_menu("withdraw_crypto")
        )
    
    elif call.data.startswith("withdraw_crypto_"):
        currency = call.data.replace("withdraw_crypto_", "")
        start_crypto_withdrawal(call, currency)
    
    elif call.data == "check_balance":
        show_complete_balance(call)
    
    elif call.data == "check_rates":
        show_current_rates(call)
    
    elif call.data == "deposit_transfermovil":
        start_cup_deposit(call, "transfermovil")
    
    elif call.data == "deposit_enzona":
        start_cup_deposit(call, "enzona")
    
    elif call.data == "back_to_main":
        user_info = get_user_info(user_id)
        cup_rate = get_cup_usd_rate()
        
        welcome_back_text = f"""
👋 ¡Hola de nuevo, {escape_markdown(user_info[2])}!

💎 *Tu Billetera ProCoin*

📊 *Información actual:*
• Saldo: {user_info[3]:.2f} PRC
• Equivalente: {user_info[3] * cup_rate:,.0f} CUP
• Wallet: `{user_info[4]}`

💱 *Tasa actual:* 1 PRC = {cup_rate:,.0f} CUP

⚡ *Selecciona una opción:*"""
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=welcome_back_text,
            parse_mode='Markdown',
            reply_markup=main_menu(call.message.chat.id)
        )
    
    elif call.data == "confirm_clear":
        if is_admin(user_id):
            success = clear_database()
            if success:
                notification_text = f"""
🗑️ *BASE DE DATOS LIMPIADA* 🗑️

*Administrador:* {escape_markdown(call.from_user.first_name)}
*Fecha:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

✅ *Todas las tablas han sido reiniciadas*
✅ *Sistema listo para nuevos usuarios*"""
                
                send_group_notification(notification_text)
                
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="✅ *Base de datos limpiada exitosamente*\n\nTodos los datos han sido eliminados y las tablas reiniciadas.",
                    parse_mode='Markdown'
                )
            else:
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="❌ *Error limpiando la base de datos*",
                    parse_mode='Markdown'
                )
    
    elif call.data == "cancel_clear":
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="❌ *Limpieza cancelada*",
            parse_mode='Markdown'
        )

# FUNCIONES PARA DEPÓSITOS CUP
def start_cup_deposit(call, method):
    cup_rate = get_cup_usd_rate()
    
    msg = bot.send_message(
        call.message.chat.id,
        f"💵 *DEPÓSITO POR {method.upper()}*\n\n"
        f"💱 *Tasa actual:* 1 PRC = {cup_rate:,.0f} CUP\n\n"
        f"💵 Ingresa el monto en CUP que vas a depositar:",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_cup_deposit_amount, method)

def process_cup_deposit_amount(message, method):
    try:
        amount_cup = float(message.text)
        user_id = message.from_user.id
        
        if amount_cup <= 0:
            bot.send_message(
                message.chat.id,
                "❌ *Monto inválido*\nEl monto debe ser mayor a 0.",
                parse_mode='Markdown',
                reply_markup=main_menu(message.chat.id)
            )
            return
        
        # Obtener tasa actual
        cup_rate = get_cup_usd_rate()
        amount_prc = amount_cup / cup_rate
        
        # Guardar depósito pendiente
        deposit_id = f"DEP{uuid.uuid4().hex[:10].upper()}"
        pending_deposits[user_id] = {
            'deposit_id': deposit_id,
            'amount_cup': amount_cup,
            'amount_prc': amount_prc,
            'exchange_rate': cup_rate,
            'method': method
        }
        
        if method == "transfermovil":
            payment_text = f"""
📱 *INSTRUCCIONES PARA PAGO POR TRANSFERMÓVIL*

💳 *Información para transferir:*
• *Teléfono:* `5351234567`
• *Nombre:* ProCoin Exchange
• *Monto a transferir:* *{amount_cup:,.0f} CUP*

📊 *Conversión:*
• CUP depositados: {amount_cup:,.0f} CUP
• Tasa: 1 PRC = {cup_rate:,.0f} CUP
• ProCoin a recibir: *{amount_prc:.2f} PRC*

📋 *Pasos a seguir:*
1\. Abre tu app de Transfermóvil
2\. Selecciona *\"Transferir\"*
3\. Ingresa el teléfono: *5351234567*
4\. Ingresa el monto: *{amount_cup:,.0f} CUP*
5\. Confirma la transferencia
6\. Toma una *captura de pantalla* del comprobante
7\. Envíala aquí

⚠️ *Importante:* 
• El monto debe ser *exactamente* {amount_cup:,.0f} CUP
• Solo se aceptan transferencias desde CUENTAS PROPIAS
• La verificación puede tomar 5-15 minutos"""
        
        else:  # enzona
            payment_text = f"""
🔵 *INSTRUCCIONES PARA PAGO POR ENZONA*

💳 *Información para pagar:*
• *Nombre:* ProCoin Exchange
• *Monto a pagar:* *{amount_cup:,.0f} CUP*

📊 *Conversión:*
• CUP depositados: {amount_cup:,.0f} CUP
• Tasa: 1 PRC = {cup_rate:,.0f} CUP
• ProCoin a recibir: *{amount_prc:.2f} PRC*

📋 *Pasos a seguir:*
1\. Abre tu app de EnZona
2\. Escanea el código QR o busca *\"ProCoin Exchange\"*
3\. Ingresa el monto: *{amount_cup:,.0f} CUP*
4\. Realiza el pago
5\. Toma una *captura de pantalla* del comprobante
6\. Envíala aquí

⚠️ *Importante:* 
• El monto debe ser *exactamente* {amount_cup:,.0f} CUP
• Solo se aceptan pagos desde CUENTAS PROPIAS
• La verificación puede tomar 5-15 minutos"""
        
        # Registrar depósito pendiente
        log_deposit(deposit_id, user_id, amount_cup, amount_prc, cup_rate, method, "pending")
        
        bot.send_message(
            message.chat.id,
            payment_text,
            parse_mode='Markdown'
        )
        
        msg = bot.send_message(
            message.chat.id,
            "📸 *Ahora envía la captura de pantalla del comprobante de pago:*",
            parse_mode='Markdown'
        )
        
    except ValueError:
        bot.send_message(
            message.chat.id,
            "❌ *Formato inválido*\nIngresa un número válido.",
            parse_mode='Markdown',
            reply_markup=main_menu(message.chat.id)
        )

# FUNCIONES PARA DEPÓSITOS CRYPTO
def show_crypto_deposit_address(call, currency):
    user_id = call.from_user.id
    wallet = get_user_crypto_wallet(user_id, currency)
    
    if not wallet:
        bot.answer_callback_query(call.id, "❌ Billetera no encontrada")
        return
    
    # Obtener precio actual
    crypto_price = get_crypto_price(currency)
    
    deposit_text = f"""
📥 *DEPOSITAR {currency}*

🆔 *Tu dirección única:*
`{wallet[4]}`

💰 *Precio actual:* 1 {currency} = {crypto_price:.2f} PRC

📋 *Instrucciones:*
1\. Copia la dirección mostrada arriba
2\. Envía *{currency}* desde tu billetera externa
3\. Espera las confirmaciones de red
4\. El equivalente en ProCoin se acreditará automáticamente

⚠️ *Importante:*
• Solo envías *{currency}* a esta dirección
• Las transacciones toman 5-60 minutos
• Mínimo de depósito: 0.0001 {currency}
• Fee de red: Cubierto por el usuario

💎 *Conversión automática a ProCoin*"""

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=deposit_text,
        parse_mode='Markdown',
        reply_markup=main_menu(call.message.chat.id)
    )

# FUNCIONES PARA RETIROS CUP
def start_cup_withdrawal(call):
    user_id = call.from_user.id
    user_info = get_user_info(user_id)
    cup_rate = get_cup_usd_rate()
    
    msg = bot.send_message(
        call.message.chat.id,
        f"💸 *RETIRAR CUP*\n\n"
        f"💎 *Saldo disponible:* {user_info[3]:.2f} PRC\n"
        f"💵 *Equivalente:* {user_info[3] * cup_rate:,.0f} CUP\n\n"
        f"💱 *Tasa actual:* 1 PRC = {cup_rate:,.0f} CUP\n\n"
        f"💎 Ingresa la cantidad de ProCoin que deseas retirar (se convertirán a CUP):",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_cup_withdraw_amount)

def process_cup_withdraw_amount(message):
    try:
        amount_prc = float(message.text)
        user_id = message.from_user.id
        user_info = get_user_info(user_id)
        
        if amount_prc <= 0:
            bot.send_message(
                message.chat.id,
                "❌ *Monto inválido*\nEl monto debe ser mayor a 0.",
                parse_mode='Markdown',
                reply_markup=main_menu(message.chat.id)
            )
            return
        
        if amount_prc > user_info[3]:
            bot.send_message(
                message.chat.id,
                f"❌ *Saldo insuficiente*\n\n"
                f"Tu saldo: {user_info[3]:.2f} PRC\n"
                f"Monto a retirar: {amount_prc:.2f} PRC",
                parse_mode='Markdown',
                reply_markup=main_menu(message.chat.id)
            )
            return
        
        # Calcular fee del 2% (puedes ajustar)
        fee = amount_prc * 0.02
        net_amount_prc = amount_prc - fee
        
        # Obtener tasa actual
        cup_rate = get_cup_usd_rate()
        amount_cup = net_amount_prc * cup_rate
        
        # Guardar retiro pendiente
        withdrawal_id = f"WDL{uuid.uuid4().hex[:10].upper()}"
        pending_withdrawals[user_id] = {
            'withdrawal_id': withdrawal_id,
            'amount_prc': amount_prc,
            'amount_cup': amount_cup,
            'exchange_rate': cup_rate,
            'fee': fee,
            'net_amount': net_amount_prc
        }
        
        bot.send_message(
            message.chat.id,
            f"💳 *INGRESA TU NÚMERO DE TARJETA*\n\n"
            f"📋 *Resumen del retiro:*\n"
            f"• ProCoin a retirar: {amount_prc:.2f} PRC\n"
            f"• Fee (2%): {fee:.2f} PRC\n"
            f"• Neto a convertir: {net_amount_prc:.2f} PRC\n"
            f"• Tasa: 1 PRC = {cup_rate:,.0f} CUP\n"
            f"• Recibirás: {amount_cup:,.0f} CUP\n\n"
            f"🔢 *Ingresa el número de tu tarjeta:*",
            parse_mode='Markdown'
        )
        
        bot.register_next_step_handler(message, process_cup_withdraw_card)
        
    except ValueError:
        bot.send_message(
            message.chat.id,
            "❌ *Formato inválido*\nIngresa un número válido.",
            parse_mode='Markdown',
            reply_markup=main_menu(message.chat.id)
        )

def process_cup_withdraw_card(message):
    user_id = message.from_user.id
    user_info = get_user_info(user_id)
    card_number = message.text.strip()
    
    if user_id not in pending_withdrawals:
        bot.send_message(
            message.chat.id,
            "❌ *No hay retiro pendiente*",
            parse_mode='Markdown',
            reply_markup=main_menu(message.chat.id)
        )
        return
    
    withdrawal_data = pending_withdrawals[user_id]
    withdrawal_id = withdrawal_data['withdrawal_id']
    
    if len(card_number) < 10:
        bot.send_message(
            message.chat.id,
            "❌ *Número de tarjeta inválido*\n\nIngresa un número de tarjeta válido.",
            parse_mode='Markdown',
            reply_markup=main_menu(message.chat.id)
        )
        return
    
    # Registrar retiro en la base de datos
    log_withdrawal(withdrawal_id, user_id, 
                  withdrawal_data['amount_prc'], withdrawal_data['amount_cup'],
                  withdrawal_data['exchange_rate'], withdrawal_data['fee'],
                  withdrawal_data['net_amount'], card_number, "pending")
    
    # Actualizar balance (congelar fondos)
    update_balance(user_id, -withdrawal_data['amount_prc'])
    
    # Notificar al grupo
    group_notification = f"""
📤 *NUEVA SOLICITUD DE RETIRO CUP* 📤

*Usuario:* {escape_markdown(user_info[2])}
*Wallet:* `{user_info[4]}`
*ProCoin a retirar:* {withdrawal_data['amount_prc']:.2f} PRC
*CUP a recibir:* {withdrawal_data['amount_cup']:,.0f} CUP
*Tasa:* 1 PRC = {withdrawal_data['exchange_rate']:,.0f} CUP
*Fee (2%):* {withdrawal_data['fee']:.2f} PRC
*Tarjeta:* `{card_number}`
*Retiro ID:* `{withdrawal_id}`

⏳ *Esperando procesamiento...*

💾 *Para aprobar usa:*
`/recargar {user_info[4]} {withdrawal_data['amount_prc']}`"""
    
    send_group_notification(group_notification)
    
    # Confirmar al usuario
    bot.send_message(
        message.chat.id,
        f"✅ *Solicitud de retiro enviada*\n\n"
        f"📋 *Detalles de tu retiro:*\n"
        f"• ProCoin: {withdrawal_data['amount_prc']:.2f} PRC\n"
        f"• Fee (2%): {withdrawal_data['fee']:.2f} PRC\n"
        f"• Neto convertido: {withdrawal_data['net_amount']:.2f} PRC\n"
        f"• CUP a recibir: {withdrawal_data['amount_cup']:,.0f} CUP\n"
        f"• Tarjeta: {card_number}\n"
        f"• Retiro ID: {withdrawal_id}\n\n"
        f"⏰ *Estado:* Pendiente de aprobación\n"
        f"📞 *Tiempo estimado:* 5-15 minutos\n\n"
        f"Te notificaremos cuando sea procesado.",
        parse_mode='Markdown',
        reply_markup=main_menu(message.chat.id)
    )
    
    # Limpiar retiro pendiente
    del pending_withdrawals[user_id]

# FUNCIONES PARA RETIROS CRYPTO
def start_crypto_withdrawal(call, currency):
    user_id = call.from_user.id
    user_info = get_user_info(user_id)
    
    # Obtener precio actual
    crypto_price = get_crypto_price(currency)
    
    msg = bot.send_message(
        call.message.chat.id,
        f"📤 *RETIRAR {currency}*\n\n"
        f"💎 *Saldo disponible:* {user_info[3]:.2f} PRC\n"
        f"💰 *Precio actual:* 1 {currency} = {crypto_price:.2f} PRC\n\n"
        f"💎 Ingresa la cantidad de ProCoin que deseas convertir a {currency}:",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_crypto_withdraw_amount, currency)

def process_crypto_withdraw_amount(message, currency):
    try:
        amount_prc = float(message.text)
        user_id = message.from_user.id
        user_info = get_user_info(user_id)
        
        if amount_prc <= 0:
            bot.send_message(
                message.chat.id,
                "❌ *Monto inválido*\nEl monto debe ser mayor a 0.",
                parse_mode='Markdown',
                reply_markup=main_menu(message.chat.id)
            )
            return
        
        if amount_prc > user_info[3]:
            bot.send_message(
                message.chat.id,
                f"❌ *Saldo insuficiente*\n\n"
                f"Tu saldo: {user_info[3]:.2f} PRC\n"
                f"Monto a retirar: {amount_prc:.2f} PRC",
                parse_mode='Markdown',
                reply_markup=main_menu(message.chat.id)
            )
            return
        
        # Obtener precio actual
        crypto_price = get_crypto_price(currency)
        amount_crypto = amount_prc / crypto_price
        
        # Calcular fee del 1% para crypto
        fee = amount_prc * 0.01
        net_amount_prc = amount_prc - fee
        net_amount_crypto = net_amount_prc / crypto_price
        
        # Guardar retiro pendiente
        withdrawal_id = f"CRYPTO_WDL{uuid.uuid4().hex[:10].upper()}"
        pending_crypto_deposits[user_id] = {
            'withdrawal_id': withdrawal_id,
            'currency': currency,
            'amount_prc': amount_prc,
            'amount_crypto': net_amount_crypto,
            'exchange_rate': crypto_price,
            'fee': fee
        }
        
        bot.send_message(
            message.chat.id,
            f"📤 *RETIRAR {currency}*\n\n"
            f"📋 *Resumen de conversión:*\n"
            f"• ProCoin a convertir: {amount_prc:.2f} PRC\n"
            f"• Fee (1%): {fee:.2f} PRC\n"
            f"• Neto a convertir: {net_amount_prc:.2f} PRC\n"
            f"• Tasa: 1 {currency} = {crypto_price:.2f} PRC\n"
            f"• Recibirás: {net_amount_crypto:.6f} {currency}\n\n"
            f"🔢 *Ingresa tu dirección de {currency}:*",
            parse_mode='Markdown'
        )
        
        bot.register_next_step_handler(message, process_crypto_withdraw_address, currency)
        
    except ValueError:
        bot.send_message(
            message.chat.id,
            "❌ *Formato inválido*\nIngresa un número válido.",
            parse_mode='Markdown',
            reply_markup=main_menu(message.chat.id)
        )

def process_crypto_withdraw_address(message, currency):
    user_id = message.from_user.id
    user_info = get_user_info(user_id)
    address = message.text.strip()
    
    if user_id not in pending_crypto_deposits:
        bot.send_message(
            message.chat.id,
            "❌ *No hay retiro pendiente*",
            parse_mode='Markdown',
            reply_markup=main_menu(message.chat.id)
        )
        return
    
    withdrawal_data = pending_crypto_deposits[user_id]
    withdrawal_id = withdrawal_data['withdrawal_id']
    
    if len(address) < 10:
        bot.send_message(
            message.chat.id,
            "❌ *Dirección inválida*\n\nIngresa una dirección válida.",
            parse_mode='Markdown',
            reply_markup=main_menu(message.chat.id)
        )
        return
    
    # Actualizar balance (congelar fondos)
    update_balance(user_id, -withdrawal_data['amount_prc'])
    
    # Registrar transacción
    log_crypto_transaction(withdrawal_id, user_id, currency, 
                          withdrawal_data['amount_crypto'], withdrawal_data['amount_prc'],
                          withdrawal_data['exchange_rate'], "withdrawal", address, "pending")
    
    # Notificar al grupo
    group_notification = f"""
📤 *NUEVO RETIRO CRYPTO PENDIENTE* 📤

*Usuario:* {escape_markdown(user_info[2])}
*Wallet:* `{user_info[4]}`
*Moneda:* {currency}
*ProCoin:* {withdrawal_data['amount_prc']:.2f} PRC
*{currency} a recibir:* {withdrawal_data['amount_crypto']:.6f}
*Tasa:* 1 {currency} = {withdrawal_data['exchange_rate']:.2f} PRC
*Fee (1%):* {withdrawal_data['fee']:.2f} PRC
*Dirección destino:* `{address}`
*Retiro ID:* `{withdrawal_id}`

⏳ *Esperando procesamiento...*

💾 *Para aprobar usa:*
`/recargar {user_info[4]} {withdrawal_data['amount_prc']}`"""
    
    send_group_notification(group_notification)
    
    # Confirmar al usuario
    bot.send_message(
        message.chat.id,
        f"✅ *Solicitud de retiro crypto enviada*\n\n"
        f"📋 *Detalles de tu retiro:*\n"
        f"• Moneda: {currency}\n"
        f"• ProCoin: {withdrawal_data['amount_prc']:.2f} PRC\n"
        f"• Fee (1%): {withdrawal_data['fee']:.2f} PRC\n"
        f"• {currency} a recibir: {withdrawal_data['amount_crypto']:.6f}\n"
        f"• Dirección: {address}\n"
        f"• Retiro ID: {withdrawal_id}\n\n"
        f"⏰ *Estado:* Pendiente de aprobación\n"
        f"📞 *Tiempo estimado:* 5-15 minutos\n\n"
        f"Te notificaremos cuando sea procesado.",
        parse_mode='Markdown',
        reply_markup=main_menu(message.chat.id)
    )
    
    # Limpiar retiro pendiente
    del pending_crypto_deposits[user_id]

# FUNCIONES DE INFORMACIÓN
def show_complete_balance(call):
    user_id = call.from_user.id
    user_info = get_user_info(user_id)
    wallets = get_user_crypto_wallets(user_id)
    
    # Obtener tasas actuales
    cup_rate = get_cup_usd_rate()
    
    balance_text = f"""
💰 *BALANCE COMPLETO*

💎 *Balance ProCoin:*
• Saldo disponible: {user_info[3]:.2f} PRC
• Equivalente en CUP: {user_info[3] * cup_rate:,.0f} CUP

₿ *Balance Crypto:*"""
    
    total_crypto_value = 0
    for wallet in wallets:
        if wallet[3] > 0:  # Solo mostrar wallets con balance
            currency = wallet[2]
            balance = wallet[3]
            crypto_price = get_crypto_price(currency)
            prc_value = balance * crypto_price
            total_crypto_value += prc_value
            
            balance_text += f"\n• *{currency}:* {balance:.8f} ({prc_value:.2f} PRC)"
    
    balance_text += f"\n\n💎 *Valor total crypto:* {total_crypto_value:.2f} PRC"
    balance_text += f"\n🏦 *Valor total general:* {user_info[3] + total_crypto_value:.2f} PRC"
    balance_text += f"\n💵 *Equivalente total CUP:* {(user_info[3] + total_crypto_value) * cup_rate:,.0f} CUP"
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=balance_text,
        parse_mode='Markdown',
        reply_markup=main_menu(call.message.chat.id)
    )

def show_current_rates(call_or_message):
    """Muestra las tasas actuales de cambio"""
    # Obtener tasas
    cup_rate = get_cup_usd_rate()
    
    rates_text = f"""
📈 *TASAS DE CAMBIO ACTUALES*

💱 *ProCoin a CUP:*
• 1 PRC = {cup_rate:,.0f} CUP

₿ *Criptomonedas a ProCoin:*"""
    
    for currency in SUPPORTED_CRYPTO.keys():
        if currency != "USDT":
            price = get_crypto_price(currency)
            rates_text += f"\n• 1 {currency} = {price:.2f} PRC"
    
    rates_text += f"\n\n• 1 USDT = 1.00 PRC"
    rates_text += f"\n\n📅 *Actualizado:* {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    rates_text += f"\n🔍 *Fuentes:* ElToque.com, Binance, CoinGecko"
    
    if hasattr(call_or_message, 'message'):
        # Es un callback
        bot.edit_message_text(
            chat_id=call_or_message.message.chat.id,
            message_id=call_or_message.message.message_id,
            text=rates_text,
            parse_mode='Markdown',
            reply_markup=main_menu(call_or_message.message.chat.id)
        )
    else:
        # Es un mensaje
        bot.send_message(
            call_or_message.chat.id,
            rates_text,
            parse_mode='Markdown',
            reply_markup=main_menu(call_or_message.chat.id)
        )

# MANEJADOR DE CAPTURAS DE PANTALLA
@bot.message_handler(content_types=['photo'])
def handle_screenshot(message):
    user_id = message.from_user.id
    user_info = get_user_info(user_id)
    
    if user_id in pending_deposits:
        # Es un depósito CUP
        deposit_data = pending_deposits[user_id]
        deposit_id = deposit_data['deposit_id']
        amount_cup = deposit_data['amount_cup']
        amount_prc = deposit_data['amount_prc']
        method = deposit_data['method']
        
        photo_id = message.photo[-1].file_id
        
        conn = sqlite3.connect('cubawallet.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE deposits SET screenshot_id = ? WHERE deposit_id = ?', (photo_id, deposit_id))
        conn.commit()
        conn.close()
        
        method_display = "Transfermóvil" if method == "transfermovil" else "EnZona"
        
        group_notification = f"""
📥 *NUEVO DEPÓSITO CUP PENDIENTE* 📥

*Usuario:* {escape_markdown(user_info[2])}
*Wallet:* `{user_info[4]}`
*Método:* {method_display}
*CUP depositados:* {amount_cup:,.0f} CUP
*ProCoin a recibir:* {amount_prc:.2f} PRC
*Tasa:* 1 PRC = {deposit_data['exchange_rate']:,.0f} CUP
*Depósito ID:* `{deposit_id}`

⏳ *Esperando verificación...*

💾 *Para aprobar usa:*
`/recargar {user_info[4]} {amount_prc}`"""
        
        send_group_notification(group_notification, photo_id=photo_id)
        
        bot.reply_to(message,
                    f"✅ *Captura recibida*\n\n"
                    f"Hemos recibido tu comprobante por {amount_cup:,.0f} CUP\n\n"
                    f"📊 *Conversión:*\n"
                    f"• CUP: {amount_cup:,.0f} CUP\n"
                    f"• Tasa: 1 PRC = {deposit_data['exchange_rate']:,.0f} CUP\n"
                    f"• ProCoin a recibir: {amount_prc:.2f} PRC\n\n"
                    f"📋 *Estado:* En revisión\n"
                    f"🆔 *Depósito:* {deposit_id}\n"
                    f"⏰ *Tiempo estimado:* 5-15 minutos\n\n"
                    f"Te notificaremos cuando sea verificado.",
                    parse_mode='Markdown',
                    reply_markup=main_menu(message.chat.id))
        
        del pending_deposits[user_id]

# FUNCIONES DE TRANSFERENCIA ENTRE USUARIOS
def process_recipient(message):
    recipient_address = message.text.strip()
    user_id = message.from_user.id
    user_info = get_user_info(user_id)
    
    # Verificar si la dirección existe
    recipient_info = get_user_by_wallet(recipient_address)
    
    if not recipient_info:
        bot.send_message(
            message.chat.id,
            "❌ *Dirección no encontrada*\n\nVerifica la dirección e intenta nuevamente.",
            parse_mode='Markdown',
            reply_markup=main_menu(message.chat.id)
        )
        return
    
    if recipient_info[0] == user_id:
        bot.send_message(
            message.chat.id,
            "❌ *No puedes enviarte ProCoin a ti mismo*",
            parse_mode='Markdown',
            reply_markup=main_menu(message.chat.id)
        )
        return
    
    bot.send_message(
        message.chat.id,
        f"✅ *Destinatario encontrado:* {escape_markdown(recipient_info[2])}\n\n💎 Ingresa la cantidad de ProCoin a enviar:",
        parse_mode='Markdown'
    )
    
    bot.register_next_step_handler(message, process_amount, recipient_info)

def process_amount(message, recipient_info):
    try:
        amount = float(message.text)
        user_id = message.from_user.id
        user_info = get_user_info(user_id)
        
        if amount <= 0:
            bot.send_message(
                message.chat.id,
                "❌ *Monto inválido*\nEl monto debe ser mayor a 0.",
                parse_mode='Markdown',
                reply_markup=main_menu(message.chat.id)
            )
            return
        
        if amount > user_info[3]:
            bot.send_message(
                message.chat.id,
                f"❌ *Saldo insuficiente*\n\nTu saldo: {user_info[3]:.2f} PRC\nMonto a enviar: {amount:.2f} PRC",
                parse_mode='Markdown',
                reply_markup=main_menu(message.chat.id)
            )
            return
        
        confirm_markup = types.InlineKeyboardMarkup()
        confirm_btn = types.InlineKeyboardButton("✅ Confirmar Envío", callback_data=f"confirm_send_{amount}_{recipient_info[0]}")
        cancel_btn = types.InlineKeyboardButton("❌ Cancelar", callback_data="cancel_send")
        confirm_markup.add(confirm_btn, cancel_btn)
        
        bot.send_message(
            message.chat.id,
            f"🔍 *CONFIRMAR TRANSACCIÓN*\n\n"
            f"👤 *Destinatario:* {escape_markdown(recipient_info[2])}\n"
            f"🆔 *Wallet:* {recipient_info[4]}\n"
            f"💎 *Monto:* {amount:.2f} PRC\n\n"
            f"¿Confirmas esta transacción?",
            parse_mode='Markdown',
            reply_markup=confirm_markup
        )
        
    except ValueError:
        bot.send_message(
            message.chat.id,
            "❌ *Formato inválido*\nIngresa un número válido.",
            parse_mode='Markdown',
            reply_markup=main_menu(message.chat.id)
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_send_'))
def confirm_send(call):
    try:
        data_parts = call.data.split('_')
        amount = float(data_parts[2])
        recipient_id = int(data_parts[3])
        
        user_id = call.from_user.id
        user_info = get_user_info(user_id)
        recipient_info = get_user_info(recipient_id)
        
        if amount > user_info[3]:
            bot.answer_callback_query(call.id, "❌ Saldo insuficiente")
            return
        
        transaction_id = f"TXN{uuid.uuid4().hex[:10].upper()}"
        
        update_balance(user_id, -amount)
        update_balance(recipient_id, amount)
        
        log_transaction(transaction_id, user_id, recipient_id, amount, "transfer", "completed")
        
        success_text = f"""
✅ *TRANSACCIÓN EXITOSA*

💎 ProCoin enviados: {amount:.2f} PRC
👤 Destinatario: {escape_markdown(recipient_info[2])}
🆔 Transacción: {transaction_id}
📅 Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

💰 Nuevo saldo: *{user_info[3] - amount:.2f} PRC*"""
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=success_text,
            parse_mode='Markdown',
            reply_markup=main_menu(call.message.chat.id)
        )
        
        try:
            recipient_notification = f"""
💰 *HAS RECIBIDO PROCOIN*

💎 ProCoin recibidos: {amount:.2f} PRC
👤 Remitente: {escape_markdown(user_info[2])}
🆔 Transacción: {transaction_id}

💳 Nuevo saldo: *{recipient_info[3] + amount:.2f} PRC*"""
            
            bot.send_message(
                chat_id=recipient_id,
                text=recipient_notification,
                parse_mode='Markdown'
            )
        except:
            pass
        
    except Exception as e:
        print(f"Error en transacción: {e}")
        bot.answer_callback_query(call.id, "❌ Error en la transacción")

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_send')
def cancel_send(call):
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="❌ *Transacción cancelada*",
        parse_mode='Markdown',
        reply_markup=main_menu(call.message.chat.id)
    )

# COMANDO PARA VER SALDO
@bot.message_handler(commands=['saldo'])
def show_balance_command(message):
    user_id = message.from_user.id
    user_info = get_user_info(user_id)
    
    if user_info:
        cup_rate = get_cup_usd_rate()
        bot.send_message(
            message.chat.id,
            f"💰 *Tu saldo actual:* {user_info[3]:.2f} PRC\n💵 *Equivalente:* {user_info[3] * cup_rate:,.0f} CUP",
            parse_mode='Markdown',
            reply_markup=main_menu(message.chat.id)
        )

# INICIALIZACIÓN Y EJECUCIÓN
def run_bot():
    """Ejecuta el bot de Telegram en un hilo separado"""
    print("🧠 Inicializando base de datos...")
    init_db()
    print("🤖 Iniciando bot ProCoin...")
    print(f"👑 Administrador: {ADMIN_ID}")
    print(f"📢 Notificaciones al grupo: {GROUP_CHAT_ID}")
    print(f"₿ Criptomonedas soportadas: {', '.join(SUPPORTED_CRYPTO.keys())}")
    
    # Probar notificaciones al inicio
    test_msg = "🔔 *Bot ProCoin iniciado* - Sistema con tasas en tiempo real activo"
    send_group_notification(test_msg)
    
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
