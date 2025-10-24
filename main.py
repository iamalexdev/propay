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
CACHE_DURATION = 180  # 5 minutos

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
                'USD': 000,
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
        return 20

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

def main_menu(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn_send = types.InlineKeyboardButton("📤 Enviar ProCoin", callback_data="send_money")
    btn_receive = types.InlineKeyboardButton("📥 Recibir ProCoin", callback_data="receive_money")
    btn_deposit = types.InlineKeyboardButton("💵 Depositar CUP", callback_data="deposit_cup")
    btn_withdraw = types.InlineKeyboardButton("💸 Retirar CUP", callback_data="withdraw_cup")
    btn_balance = types.InlineKeyboardButton("💰 Ver Saldo", callback_data="check_balance")
    btn_rates = types.InlineKeyboardButton("📈 Ver Tasas", callback_data="check_rates")
    
    markup.add(btn_send, btn_receive, btn_deposit, btn_withdraw, btn_balance, btn_rates)
    return markup

# =============================================================================
# COMANDOS CORREGIDOS
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
👋 ¡Bienvenido a ProCoin, {escape_markdown(first_name)}!

💎 *Tu Billetera Digital con ProCoin*

📊 *Información de tu cuenta:*
• Usuario: {escape_markdown(first_name)}
• Wallet: `{user_info[4]}`
• Saldo: {user_info[3]:.2f} PRC
• Equivalente: {user_info[3] * cup_rate:,.0f} CUP

⚡ *Selecciona una opción:*"""
        
        bot.send_message(
            chat_id=message.chat.id,
            text=welcome_text,
            parse_mode='Markdown',
            reply_markup=main_menu(message.chat.id)
        )
    except Exception as e:
        print(f"❌ Error en /start: {e}")
        bot.send_message(message.chat.id, "❌ Error al iniciar. Intenta nuevamente.")

@bot.message_handler(commands=['tasas'])
def show_rates_command(message):
    """Comando para ver tasas actuales"""
    show_current_rates(message)

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
🔧 *DEBUG TASAS*

💰 *Tasas en caché:*
{all_rates}

💵 *Tasa USD:* {get_cup_usd_rate()}
💶 *Tasa EUR:* {get_cup_eur_rate()}

⏰ *Cache actualizado:* {datetime.fromtimestamp(last_api_call).strftime('%H:%M:%S') if last_api_call > 0 else 'Nunca'}"""
        
        bot.reply_to(message, debug_text, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ Error en debug: {e}")

@bot.message_handler(commands=['recargar'])
def recharge_balance(message):
    """COMANDO RECARGAR CORREGIDO"""
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

@bot.message_handler(commands=['saldo'])
def show_balance_command(message):
    """Comando para ver saldo"""
    try:
        user_id = message.from_user.id
        user_info = get_user_info(user_id)
        
        if user_info:
            cup_rate = get_cup_usd_rate()
            bot.send_message(
                message.chat.id,
                f"💰 *Tu saldo actual:* {user_info[3]:.2f} PRC\n"
                f"💵 *Equivalente:* {user_info[3] * cup_rate:,.0f} CUP\n"
                f"💱 *Tasa actual:* 1 PRC = {cup_rate:,.0f} CUP",
                parse_mode='Markdown',
                reply_markup=main_menu(message.chat.id)
            )
    except Exception as e:
        print(f"❌ Error en saldo: {e}")
        bot.send_message(message.chat.id, "❌ Error al obtener saldo")

# =============================================================================
# SISTEMA DE TASAS CORREGIDO
# =============================================================================

def show_current_rates(call_or_message):
    """FUNCIÓN CORREGIDA - Muestra tasas de forma confiable"""
    try:
        print("🔍 Obteniendo tasas para mostrar...")
        
        # Obtener tasas del caché
        all_rates = get_eltoque_rates_cached()
        
        if not all_rates:
            error_msg = "❌ *No se pudieron obtener las tasas*\n\nPor favor, intenta nuevamente en unos minutos."
            raise Exception("No se pudieron obtener tasas")
        
        # Usar USD o USDT como tasa principal
        main_rate = all_rates.get('USD') or all_rates.get('USDT_TRC20') or 490
        
        # Construir mensaje de forma segura
        rates_text = f"""
📈 *TASAS DE CAMBIO ACTUALES*

💎 *Tasa Principal ProCoin:*
• 1 PRC = {escape_markdown(main_rate)} CUP

💱 *Todas las Tasas Disponibles:*
"""
        
        # Agregar todas las tasas ordenadas
        for currency, rate in sorted(all_rates.items()):
            rates_text += f"• {escape_markdown(currency)}: {escape_markdown(rate)} CUP\n"
        
        # Conversiones comunes
        rates_text += f"""
📊 *Conversiones ProCoin:*
• 10 PRC = {escape_markdown(10 * main_rate)} CUP
• 50 PRC = {escape_markdown(50 * main_rate)} CUP  
• 100 PRC = {escape_markdown(100 * main_rate)} CUP

🔄 *Actualizado:* {escape_markdown(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}"""
        
        print("✅ Mensaje de tasas construido correctamente")
        
        # Enviar mensaje
        if hasattr(call_or_message, 'message'):
            # Callback desde botón
            chat_id = call_or_message.message.chat.id
            message_id = call_or_message.message.message_id
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=rates_text,
                parse_mode='Markdown',
                reply_markup=main_menu(chat_id)
            )
        else:
            # Comando directo
            chat_id = call_or_message.chat.id
            bot.send_message(
                chat_id,
                rates_text,
                parse_mode='Markdown',
                reply_markup=main_menu(chat_id)
            )
            
        print("✅ Tasas mostradas correctamente")
            
    except Exception as e:
        print(f"❌ Error mostrando tasas: {e}")
        error_text = "❌ *Error temporal al obtener tasas*\n\n🔧 El equipo ha sido notificado\\.\n🔄 Intenta nuevamente en unos minutos\\.\n\n*Información del error:* `" + escape_markdown(str(e)) + "`"
        
        # Notificar error al grupo
        send_group_notification(f"🚨 *Error en sistema de tasas:* {escape_markdown(str(e))}")
        
        if hasattr(call_or_message, 'message'):
            chat_id = call_or_message.message.chat.id
            message_id = call_or_message.message.message_id
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=error_text,
                parse_mode='Markdown',
                reply_markup=main_menu(chat_id)
            )
        else:
            chat_id = call_or_message.chat.id
            bot.send_message(
                chat_id,
                error_text,
                parse_mode='Markdown',
                reply_markup=main_menu(chat_id)
            )

# =============================================================================
# SISTEMA DE DEPÓSITOS CORREGIDO
# =============================================================================

@bot.callback_query_handler(func=lambda call: call.data == "deposit_cup")
def handle_deposit_cup(call):
    """Manejador corregido para depósitos"""
    try:
        user_id = call.from_user.id
        user_info = get_user_info(user_id)
        cup_rate = get_cup_usd_rate()
        
        deposit_text = f"""
💵 *DEPOSITAR CUP*

💱 *Tasa actual:* 1 PRC = {escape_markdown(cup_rate)} CUP

📊 *Tu saldo actual:* {user_info[3]:.2f} PRC

💡 *¿Cómo funciona?*
1\\. Depositas CUP via Transfermóvil/EnZona
2\\. Se convierte automáticamente a ProCoin
3\\. Recibes ProCoin en tu wallet

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
    except Exception as e:
        print(f"❌ Error en depósito: {e}")
        bot.answer_callback_query(call.id, "❌ Error al procesar depósito")

@bot.callback_query_handler(func=lambda call: call.data in ["deposit_transfermovil", "deposit_enzona"])
def handle_deposit_method(call):
    """Manejador para método de depósito"""
    try:
        method = "transfermovil" if call.data == "deposit_transfermovil" else "enzona"
        start_cup_deposit(call, method)
    except Exception as e:
        print(f"❌ Error en método depósito: {e}")
        bot.answer_callback_query(call.id, "❌ Error al seleccionar método")

def start_cup_deposit(call, method):
    """Inicia el proceso de depósito - CORREGIDO"""
    try:
        cup_rate = get_cup_usd_rate()
        method_name = "Transfermóvil" if method == "transfermovil" else "EnZona"
        
        msg = bot.send_message(
            call.message.chat.id,
            f"💵 *DEPÓSITO POR {method_name}*\n\n"
            f"💱 *Tasa actual:* 1 PRC = {escape_markdown(cup_rate)} CUP\n\n"
            f"💵 Ingresa el monto en *CUP* que vas a depositar:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_cup_deposit_amount, method)
    except Exception as e:
        print(f"❌ Error iniciando depósito: {e}")
        bot.send_message(call.message.chat.id, "❌ Error al iniciar depósito")

def process_cup_deposit_amount(message, method):
    """Procesa el monto del depósito - CORREGIDO"""
    try:
        user_id = message.from_user.id
        
        # Validar monto
        try:
            amount_cup = float(message.text.replace(',', '.'))
        except:
            bot.send_message(
                message.chat.id,
                "❌ *Formato inválido*\nIngresa un número válido\\.\n\nEjemplo: 1000 o 1000\\.50",
                parse_mode='Markdown',
                reply_markup=main_menu(message.chat.id)
            )
            return
        
        if amount_cup <= 0:
            bot.send_message(
                message.chat.id,
                "❌ *Monto inválido*\nEl monto debe ser mayor a 0\\.",
                parse_mode='Markdown',
                reply_markup=main_menu(message.chat.id)
            )
            return
        
        if amount_cup < 100:
            bot.send_message(
                message.chat.id,
                "❌ *Monto muy bajo*\nEl depósito mínimo es 100 CUP\\.",
                parse_mode='Markdown',
                reply_markup=main_menu(message.chat.id)
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
📱 *INSTRUCCIONES TRANSFERMÓVIL*

💳 *Información para transferir:*
• *Teléfono:* `5351234567`
• *Nombre:* ProCoin Exchange
• *Monto:* *{escape_markdown(amount_cup)} CUP*

📊 *Conversión a ProCoin:*
• CUP depositados: {escape_markdown(amount_cup)} CUP
• Tasa: 1 PRC = {escape_markdown(cup_rate)} CUP
• Recibirás: *{amount_prc:.2f} PRC*

📋 *Pasos:*
1\\. Abre Transfermóvil
2\\. Selecciona *Transferir*
3\\. Ingresa teléfono: *5351234567*
4\\. Monto: *{escape_markdown(amount_cup)} CUP*
5\\. Confirma transferencia
6\\. Toma captura del comprobante
7\\. Envíala aquí

⚠️ *Importante:* 
• Monto exacto: {escape_markdown(amount_cup)} CUP
• Solo transferencias propias
• Verificación: 5\\-15 minutos"""
        else:
            payment_text = f"""
🔵 *INSTRUCCIONES ENZONA*

💳 *Información para pagar:*
• *Nombre:* ProCoin Exchange
• *Monto:* *{escape_markdown(amount_cup)} CUP*

📊 *Conversión a ProCoin:*
• CUP depositados: {escape_markdown(amount_cup)} CUP
• Tasa: 1 PRC = {escape_markdown(cup_rate)} CUP
• Recibirás: *{amount_prc:.2f} PRC*

📋 *Pasos:*
1\\. Abre EnZona
2\\. Busca *ProCoin Exchange*
3\\. Monto: *{escape_markdown(amount_cup)} CUP*
4\\. Realiza el pago
5\\. Toma captura del comprobante
6\\. Envíala aquí

⚠️ *Importante:* 
• Monto exacto: {escape_markdown(amount_cup)} CUP
• Solo pagos propios
• Verificación: 5\\-15 minutos"""
        
        # Registrar en base de datos
        log_deposit(deposit_id, user_id, amount_cup, amount_prc, cup_rate, method, "pending")
        
        bot.send_message(
            message.chat.id,
            payment_text,
            parse_mode='Markdown'
        )
        
        bot.send_message(
            message.chat.id,
            "📸 *Envía la captura del comprobante de pago:*",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        print(f"❌ Error procesando depósito: {e}")
        bot.send_message(
            message.chat.id,
            "❌ Error al procesar el depósito\\. Intenta nuevamente\\.",
            parse_mode='Markdown',
            reply_markup=main_menu(message.chat.id)
        )

# =============================================================================
# MANEJADOR DE FOTOS CORREGIDO
# =============================================================================

@bot.message_handler(content_types=['photo'])
def handle_screenshot(message):
    """Manejador de capturas de pantalla - CORREGIDO"""
    try:
        user_id = message.from_user.id
        
        if user_id not in pending_deposits:
            bot.reply_to(message, "❌ No tienes un depósito pendiente\\. Usa el menú para iniciar un depósito\\.")
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
📥 *NUEVO DEPÓSITO CUP PENDIENTE* 📥

*Usuario:* {escape_markdown(user_info[2])}
*Wallet:* `{user_info[4]}`
*Método:* {method_display}
*CUP depositados:* {escape_markdown(deposit_data['amount_cup'])} CUP
*ProCoin a recibir:* {deposit_data['amount_prc']:.2f} PRC
*Tasa:* 1 PRC = {escape_markdown(deposit_data['exchange_rate'])} CUP
*Depósito ID:* `{deposit_data['deposit_id']}`

⏳ *Esperando verificación\\.\\.\\.*

💾 *Para aprobar usa:*
`/recargar {user_info[4]} {deposit_data['amount_prc']:.2f}`"""
        
        send_group_notification(group_notification, photo_id=photo_id)
        
        # Confirmar al usuario
        bot.reply_to(message,
                    f"✅ *Captura recibida correctamente*\n\n"
                    f"📋 *Resumen de tu depósito:*\n"
                    f"• Método: {method_display}\n"
                    f"• CUP depositados: {escape_markdown(deposit_data['amount_cup'])} CUP\n"
                    f"• ProCoin a recibir: {deposit_data['amount_prc']:.2f} PRC\n"
                    f"• Tasa: 1 PRC = {escape_markdown(deposit_data['exchange_rate'])} CUP\n"
                    f"• ID: {deposit_data['deposit_id']}\n\n"
                    f"⏰ *Estado:* En revisión\n"
                    f"📞 *Tiempo estimado:* 5\\-15 minutos\n\n"
                    f"Te notificaremos cuando sea verificado\\.",
                    parse_mode='Markdown',
                    reply_markup=main_menu(message.chat.id))
        
        # Limpiar depósito pendiente
        del pending_deposits[user_id]
        
    except Exception as e:
        print(f"❌ Error manejando screenshot: {e}")
        bot.reply_to(message, "❌ Error al procesar la captura\\. Intenta nuevamente\\.")

# =============================================================================
# MANEJADORES DE CALLBACK RESTANTES
# =============================================================================

@bot.callback_query_handler(func=lambda call: call.data == "check_rates")
def handle_check_rates(call):
    """Manejador para botón de tasas"""
    try:
        show_current_rates(call)
    except Exception as e:
        print(f"❌ Error en check_rates: {e}")
        bot.answer_callback_query(call.id, "❌ Error al cargar tasas")

@bot.callback_query_handler(func=lambda call: call.data == "check_balance")
def handle_check_balance(call):
    """Manejador para botón de saldo"""
    try:
        user_id = call.from_user.id
        user_info = get_user_info(user_id)
        cup_rate = get_cup_usd_rate()
        
        balance_text = f"""
💰 *BALANCE COMPLETO*

💎 *Balance ProCoin:*
• Saldo disponible: {user_info[3]:.2f} PRC
• Equivalente en CUP: {escape_markdown(user_info[3] * cup_rate)} CUP

💱 *Tasa actual:* 1 PRC = {escape_markdown(cup_rate)} CUP"""
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=balance_text,
            parse_mode='Markdown',
            reply_markup=main_menu(call.message.chat.id)
        )
    except Exception as e:
        print(f"❌ Error en check_balance: {e}")
        bot.answer_callback_query(call.id, "❌ Error al cargar saldo")

@bot.callback_query_handler(func=lambda call: call.data == "receive_money")
def handle_receive_money(call):
    """Manejador para recibir dinero"""
    try:
        user_id = call.from_user.id
        user_info = get_user_info(user_id)
        
        receive_text = f"""
📥 *RECIBIR PROCOIN*

🆔 *Tu Dirección de Wallet:*
`{user_info[4]}`

📋 *Instrucciones:*
1\\. Comparte esta dirección con quien te enviará ProCoin
2\\. El remitente debe usar la opción *\\\"Enviar ProCoin\\\"*
3\\. Ingresa tu dirección única mostrada arriba
4\\. ¡Recibirás los ProCoin instantáneamente\\!

💡 *Consejo:* Copia tu dirección haciendo clic en ella\\."""
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=receive_text,
            parse_mode='Markdown',
            reply_markup=main_menu(call.message.chat.id)
        )
    except Exception as e:
        print(f"❌ Error en receive_money: {e}")
        bot.answer_callback_query(call.id, "❌ Error al cargar información")

@bot.callback_query_handler(func=lambda call: call.data == "back_to_main")
def handle_back_to_main(call):
    """Volver al menú principal"""
    try:
        user_id = call.from_user.id
        user_info = get_user_info(user_id)
        cup_rate = get_cup_usd_rate()
        
        welcome_back_text = f"""
👋 ¡Hola de nuevo, {escape_markdown(user_info[2])}!

💎 *Tu Billetera ProCoin*

📊 *Información actual:*
• Saldo: {user_info[3]:.2f} PRC
• Equivalente: {escape_markdown(user_info[3] * cup_rate)} CUP
• Wallet: `{user_info[4]}`

💱 *Tasa actual:* 1 PRC = {escape_markdown(cup_rate)} CUP

⚡ *Selecciona una opción:*"""
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=welcome_back_text,
            parse_mode='Markdown',
            reply_markup=main_menu(call.message.chat.id)
        )
    except Exception as e:
        print(f"❌ Error en back_to_main: {e}")
        bot.answer_callback_query(call.id, "❌ Error al cargar menú")

# =============================================================================
# INICIALIZACIÓN CORREGIDA
# =============================================================================

def run_bot():
    """Función principal corregida"""
    print("🚀 Iniciando Bot ProCoin...")
    
    try:
        # Inicializar base de datos
        init_db()
        
        # Probar sistema de tasas
        print("🧪 Probando sistema de tasas...")
        initial_rates = get_eltoque_rates_cached()
        
        if initial_rates:
            print(f"✅ Sistema de tasas funcionando - {len(initial_rates)} tasas cargadas")
            send_group_notification(f"🤖 *Bot ProCoin iniciado*\n✅ Sistema de tasas activo\n💰 {len(initial_rates)} tasas cargadas")
        else:
            print("⚠️ Sistema de tasas con valores por defecto")
            send_group_notification("🤖 *Bot ProCoin iniciado*\n⚠️ Sistema de tasas con valores por defecto")
        
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
