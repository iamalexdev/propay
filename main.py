import telebot
from telebot import types
import sqlite3
import uuid
from datetime import datetime
import html
import re
import time
import os

# Configuración - DEBES CONFIGURAR MANUALMENTE ESTOS VALORES
TOKEN = "8400947960:AAGGXHezQbmUqk6AOpgT1GqMLaF-rMvVp9Y"
GROUP_CHAT_ID = "-4932107704"  # Reemplaza con el ID de tu grupo
ADMIN_ID = 1853800972  # Reemplaza con tu ID de usuario de Telegram
bot = telebot.TeleBot(TOKEN)

# Diccionarios para almacenar operaciones pendientes
pending_deposits = {}
pending_withdrawals = {}

# Información de pago - CONFIGURA CON TUS DATOS REALES
PAYMENT_INFO = {
    "transfermovil": {
        "name": "Tu Nombre",
        "phone": "5351234567",
        "bank": "Banco Meitropolitano"
    },
    "enzona": {
        "name": "Tu Nombre",
    }
}

# Función para enviar notificaciones al grupo
def send_group_notification(message, photo_id=None):
    """
    Envía notificaciones al grupo configurado manualmente
    """
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
            amount REAL,
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
            amount REAL,
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

# Función para limpiar la base de datos (solo admin)
def clear_database():
    """Limpia completamente la base de datos"""
    try:
        conn = sqlite3.connect('cubawallet.db')
        cursor = conn.cursor()

        # Eliminar todas las tablas
        cursor.execute('DROP TABLE IF EXISTS withdrawals')
        cursor.execute('DROP TABLE IF EXISTS deposits')
        cursor.execute('DROP TABLE IF EXISTS transactions')
        cursor.execute('DROP TABLE IF EXISTS users')

        conn.commit()
        conn.close()

        # Recrear las tablas
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
    return f"CW{uuid.uuid4().hex[:12].upper()}"

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

        notification_text = f"""
🆕 *NUEVO USUARIO REGISTRADO* 🆕

*Información del usuario:*
• *Nombre:* {escape_markdown(first_name)}
• *Username:* @{escape_markdown(username) if username else 'N/A'}
• *User ID:* `{user_id}`
• *Wallet:* `{wallet_address}`
• *Fecha:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

*¡Bienvenido a la familia CubaWallet\!*"""

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

# Actualizar balance
def update_balance(user_id, amount):
    conn = sqlite3.connect('cubawallet.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()

# Registrar transacción
def log_transaction(transaction_id, from_user, to_user, amount, transaction_type, status):
    conn = sqlite3.connect('cubawallet.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO transactions (transaction_id, from_user, to_user, amount, transaction_type, status)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (transaction_id, from_user, to_user, amount, transaction_type, status))
    conn.commit()
    conn.close()

# Registrar depósito
def log_deposit(deposit_id, user_id, amount, method, status, screenshot_id=None):
    conn = sqlite3.connect('cubawallet.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO deposits (deposit_id, user_id, amount, method, status, screenshot_id)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (deposit_id, user_id, amount, method, status, screenshot_id))
    conn.commit()
    conn.close()

# Registrar retiro
def log_withdrawal(withdrawal_id, user_id, amount, fee, net_amount, card_number, status, screenshot_id=None):
    conn = sqlite3.connect('cubawallet.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO withdrawals (withdrawal_id, user_id, amount, fee, net_amount, card_number, status, screenshot_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (withdrawal_id, user_id, amount, fee, net_amount, card_number, status, screenshot_id))
    conn.commit()
    conn.close()

# Menú principal con botones inline
def main_menu(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=2)

    btn_send = types.InlineKeyboardButton("📤 Enviar Dinero", callback_data="send_money")
    btn_receive = types.InlineKeyboardButton("📥 Recibir Dinero", callback_data="receive_money")
    btn_deposit = types.InlineKeyboardButton("💳 Depositar", callback_data="deposit_money")
    btn_withdraw = types.InlineKeyboardButton("💸 Retirar", callback_data="withdraw_money")
    btn_balance = types.InlineKeyboardButton("💰 Ver Saldo", callback_data="check_balance")
    btn_history = types.InlineKeyboardButton("📊 Historial", callback_data="transaction_history")

    markup.add(btn_send, btn_receive, btn_deposit, btn_withdraw, btn_balance, btn_history)

    return markup

# COMANDOS DE ADMINISTRADOR

# Comando para limpiar la base de datos
@bot.message_handler(commands=['limpiar'])
def clear_database_command(message):
    user_id = message.from_user.id

    if not is_admin(user_id):
        bot.reply_to(message, "❌ *Comando solo para administradores*", parse_mode='Markdown')
        return

    # Crear teclado de confirmación
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
                "• Todos los saldos\n\n"
                "🔴 *¡ESTA ACCIÓN NO SE PUEDE DESHACER!*",
                parse_mode='Markdown',
                reply_markup=markup)

# Comando para aprobar retiros
@bot.message_handler(commands=['aprobar_retiro'])
def approve_withdrawal(message):
    user_id = message.from_user.id

    if not is_admin(user_id):
        bot.reply_to(message, "❌ *Comando solo para administradores*", parse_mode='Markdown')
        return

    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message,
                    "❌ *Formato incorrecto*\n\n"
                    "Uso: `/aprobar_retiro WDLABC123 100.50`\n\n"
                    "• WDLABC123 = ID del retiro\n"
                    "• 100.50 = Cantidad a aprobar",
                    parse_mode='Markdown')
        return

    withdrawal_id = parts[1]
    try:
        amount = float(parts[2])
    except ValueError:
        bot.reply_to(message, "❌ *Cantidad inválida*", parse_mode='Markdown')
        return

    # Buscar el retiro en la base de datos
    conn = sqlite3.connect('cubawallet.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM withdrawals WHERE withdrawal_id = ?', (withdrawal_id,))
    withdrawal = cursor.fetchone()

    if not withdrawal:
        bot.reply_to(message, f"❌ *Retiro no encontrado:* `{withdrawal_id}`", parse_mode='Markdown')
        conn.close()
        return

    user_id_withdrawal = withdrawal[1]
    user_info = get_user_info(user_id_withdrawal)

    if not user_info:
        bot.reply_to(message, "❌ *Usuario del retiro no encontrado*", parse_mode='Markdown')
        conn.close()
        return

    # Actualizar estado del retiro
    cursor.execute('UPDATE withdrawals SET status = "approved", admin_approved = ? WHERE withdrawal_id = ?',
                  (user_id, withdrawal_id))
    conn.commit()
    conn.close()

    # Notificar al usuario
    try:
        user_notification = f"""
✅ *RETIRO APROBADO*

Tu solicitud de retiro ha sido procesada.

📋 *Detalles:*
• Monto retirado: ${amount:.2f}
• Retiro ID: {withdrawal_id}
• Tarjeta: {withdrawal[5]}
• Estado: ✅ APROBADO

El dinero ha sido enviado a tu tarjeta. ¡Gracias por usar CubaWallet! 🎉"""

        bot.send_message(user_id_withdrawal, user_notification, parse_mode='Markdown')
    except Exception as e:
        print(f"No se pudo notificar al usuario: {e}")

    # Notificar al grupo
    group_notification = f"""
✅ *RETIRO APROBADO* ✅

*Administrador:* {escape_markdown(message.from_user.first_name)}
*Usuario:* {escape_markdown(user_info[2])}
*Wallet:* `{user_info[4]}`
*Monto retirado:* ${amount:.2f}
*Retiro ID:* `{withdrawal_id}`
*Tarjeta:* `{withdrawal[5]}`

💰 *Retiro procesado exitosamente*"""

    send_group_notification(group_notification)

    bot.reply_to(message,
                f"✅ *Retiro aprobado*\n\n"
                f"Usuario: {escape_markdown(user_info[2])}\n"
                f"Monto: ${amount:.2f}\n"
                f"Retiro ID: {withdrawal_id}",
                parse_mode='Markdown')

# Comando /recargar solo para administradores
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
                    "Uso: `/recargar CWABC123 100.50`\n\n"
                    "• CWABC123 = Wallet del usuario\n"
                    "• 100.50 = Cantidad a recargar",
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

    transaction_id = f"RCH{uuid.uuid4().hex[:10].upper()}"
    log_transaction(transaction_id, None, user_info[0], amount, "recharge", "completed")

    try:
        user_notification = f"""
💳 *RECARGA APROBADA*

✅ Tu depósito ha sido verificado y aprobado.

📊 *Detalles:*
• Monto recargado: ${amount:.2f}
• Wallet: `{wallet_address}`
• Transacción: {transaction_id}
• Saldo anterior: ${old_balance:.2f}
• Nuevo saldo: *${new_balance:.2f}*

¡Gracias por usar CubaWallet! 🎉"""

        bot.send_message(user_info[0], user_notification, parse_mode='Markdown')
    except Exception as e:
        print(f"No se pudo notificar al usuario: {e}")

    group_notification = f"""
💰 *RECARGA MANUAL APROBADA* 💰

*Administrador:* {escape_markdown(message.from_user.first_name)}
*Usuario:* {escape_markdown(user_info[2])}
*Wallet:* `{wallet_address}`
*Monto:* ${amount:.2f}
*Transacción:* `{transaction_id}`
*Nuevo saldo:* ${new_balance:.2f}

✅ *Recarga completada exitosamente*"""

    send_group_notification(group_notification)

    bot.reply_to(message,
                f"✅ *Recarga exitosa*\n\n"
                f"Usuario: {escape_markdown(user_info[2])}\n"
                f"Monto: ${amount:.2f}\n"
                f"Nuevo saldo: ${new_balance:.2f}",
                parse_mode='Markdown')

# Comando para estadísticas
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

    # Volumen total movido
    cursor.execute('SELECT SUM(amount) FROM transactions WHERE status = "completed"')
    total_volume = cursor.fetchone()[0] or 0

    # Depósitos pendientes
    cursor.execute('SELECT COUNT(*) FROM deposits WHERE status = "pending"')
    pending_deposits_count = cursor.fetchone()[0]

    # Retiros pendientes
    cursor.execute('SELECT COUNT(*) FROM withdrawals WHERE status = "pending"')
    pending_withdrawals_count = cursor.fetchone()[0]

    conn.close()

    stats_text = f"""
📈 *ESTADÍSTICAS DE CUBAWALLET*

👥 *Usuarios registrados:* {total_users}
🔄 *Transacciones totales:* {total_transactions}
💰 *Volumen movido:* ${total_volume:.2f}
⏳ *Depósitos pendientes:* {pending_deposits_count}
⏳ *Retiros pendientes:* {pending_withdrawals_count}
📅 *Actualizado:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""

    bot.send_message(
        message.chat.id,
        stats_text,
        parse_mode='Markdown'
    )

# Comando /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    register_user(user_id, username, first_name)
    user_info = get_user_info(user_id)

    welcome_text = f"""
👋 ¡Bienvenido a CubaWallet, {escape_markdown(first_name)}!

💼 *Tu Billetera Virtual Cubana*

📊 *Información de tu cuenta:*
• Usuario: {escape_markdown(first_name)}
• ID: `{user_info[4]}`
• Saldo: ${user_info[3]:.2f}
• Registrado: {user_info[5]}

🌟 *¿Qué puedes hacer?*
• 📤 Enviar dinero a otros usuarios
• 📥 Recibir pagos con tu dirección única
• 💳 Depositar dinero via Transfermóvil/EnZona
• 💸 Retirar dinero a tu tarjeta (6% fee)
• 💰 Consultar tu saldo en tiempo real
• 📊 Ver tu historial de transacciones

⚡ *Selecciona una opción:*"""

    bot.send_message(
        chat_id=message.chat.id,
        text=welcome_text,
        parse_mode='Markdown',
        reply_markup=main_menu(message.chat.id)
    )

# Manejar callbacks de los botones
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    user_info = get_user_info(user_id)

    if call.data == "send_money":
        msg = bot.send_message(
            call.message.chat.id,
            "💸 *ENVIAR DINERO*\n\n📧 Ingresa la dirección de wallet del destinatario:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_recipient)

    elif call.data == "receive_money":
        receive_text = f"""
📥 *RECIBIR DINERO*

🆔 *Tu Dirección de Wallet:*
`{user_info[4]}`

📋 *Instrucciones:*
1\. Comparte esta dirección con quien te enviará dinero
2\. El remitente debe usar la opción *\"Enviar Dinero\"*
3\. Ingresa tu dirección única mostrada arriba
4\. ¡Recibirás el dinero instantáneamente\!

💡 *Consejo:* Copia tu dirección haciendo clic en ella\."""

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=receive_text,
            parse_mode='Markdown',
            reply_markup=main_menu(call.message.chat.id)
        )

    elif call.data == "deposit_money":
        deposit_methods = types.InlineKeyboardMarkup(row_width=2)
        btn_transfermovil = types.InlineKeyboardButton("📱 Transfermóvil", callback_data="deposit_transfermovil")
        btn_enzona = types.InlineKeyboardButton("🔵 EnZona", callback_data="deposit_enzona")
        btn_back = types.InlineKeyboardButton("🔙 Volver", callback_data="back_to_main")
        deposit_methods.add(btn_transfermovil, btn_enzona, btn_back)

        deposit_text = """
💳 *DEPOSITAR DINERO*

Selecciona el método de pago:

📱 *Transfermóvil*:
• Pago rápido desde tu móvil
• Comisión: 0%

🔵 *EnZona*:
• Pago a través de la app
• Comisión: 0%

⚠️ *Nota:* Todos los depósitos requieren verificación manual"""

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=deposit_text,
            parse_mode='Markdown',
            reply_markup=deposit_methods
        )

    elif call.data == "withdraw_money":
        # Iniciar proceso de retiro
        msg = bot.send_message(
            call.message.chat.id,
            "💸 *RETIRAR DINERO*\n\n💵 Ingresa el monto que deseas retirar:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_withdraw_amount)

    elif call.data == "deposit_transfermovil":
        msg = bot.send_message(
            call.message.chat.id,
            "💰 *DEPÓSITO POR TRANSFERMÓVIL*\n\n💵 Ingresa el monto que vas a depositar:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_deposit_amount, "transfermovil")

    elif call.data == "deposit_enzona":
        msg = bot.send_message(
            call.message.chat.id,
            "💰 *DEPÓSITO POR ENZONA*\n\n💵 Ingresa el monto que vas a depositar:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_deposit_amount, "enzona")

    elif call.data == "back_to_main":
        user_info = get_user_info(user_id)
        welcome_back_text = f"""
👋 ¡Hola de nuevo, {escape_markdown(user_info[2])}!

💼 *Tu Billetera Virtual Cubana*

📊 *Información actual:*
• Saldo: ${user_info[3]:.2f}
• Wallet: `{user_info[4]}`

⚡ *Selecciona una opción:*"""

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=welcome_back_text,
            parse_mode='Markdown',
            reply_markup=main_menu(call.message.chat.id)
        )

    elif call.data == "check_balance":
        balance_text = f"""
💰 *SALDO ACTUAL*

👤 Usuario: {escape_markdown(user_info[2])}
🆔 Wallet: {user_info[4]}
💵 Saldo: *${user_info[3]:.2f}*

💳 Disponible para transferencias inmediatas\."""

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=balance_text,
            parse_mode='Markdown',
            reply_markup=main_menu(call.message.chat.id)
        )

    elif call.data == "transaction_history":
        conn = sqlite3.connect('cubawallet.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM transactions
            WHERE from_user = ? OR to_user = ?
            ORDER BY timestamp DESC
            LIMIT 5
        ''', (user_id, user_id))
        transactions = cursor.fetchall()
        conn.close()

        if transactions:
            history_text = "📊 *ÚLTIMAS TRANSACCIONES*\n\n"
            for trans in transactions:
                transaction_id, from_user, to_user, amount, trans_type, status, timestamp = trans

                if from_user == user_id:
                    direction = "➡️ ENVIADO"
                    other_user = to_user
                else:
                    direction = "⬅️ RECIBIDO"
                    other_user = from_user

                other_user_info = get_user_info(other_user)
                other_name = escape_markdown(other_user_info[2]) if other_user_info else "Usuario"

                history_text += f"""
{direction}
• Monto: ${amount:.2f}
• {other_name}
• {timestamp}
• {transaction_id[:8]}...

"""
        else:
            history_text = "📊 *HISTORIAL DE TRANSACCIONES*\n\nAún no has realizado transacciones\."

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=history_text,
            parse_mode='Markdown',
            reply_markup=main_menu(call.message.chat.id)
        )

    elif call.data == "confirm_clear":
        if is_admin(user_id):
            success = clear_database()
            if success:
                # Notificar al grupo
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

# Procesar monto de retiro
def process_withdraw_amount(message):
    try:
        amount = float(message.text)
        user_id = message.from_user.id
        user_info = get_user_info(user_id)

        if amount <= 0:
            bot.send_message(
                message.chat.id,
                "❌ *Monto inválido*\nEl monto debe ser mayor a 0\.",
                parse_mode='Markdown',
                reply_markup=main_menu(message.chat.id)
            )
            return

        # Calcular fee del 6%
        fee = amount * 0.06
        net_amount = amount - fee
        total_required = amount  # Se necesita el monto completo en la cuenta

        if total_required > user_info[3]:
            bot.send_message(
                message.chat.id,
                f"❌ *Saldo insuficiente*\n\n"
                f"Tu saldo: ${user_info[3]:.2f}\n"
                f"Monto a retirar: ${amount:.2f}\n"
                f"Fee (6%): ${fee:.2f}\n"
                f"Recibirás: ${net_amount:.2f}\n\n"
                f"Necesitas: ${total_required:.2f}",
                parse_mode='Markdown',
                reply_markup=main_menu(message.chat.id)
            )
            return

        # Guardar retiro pendiente
        withdrawal_id = f"WDL{uuid.uuid4().hex[:10].upper()}"
        pending_withdrawals[user_id] = {
            'withdrawal_id': withdrawal_id,
            'amount': amount,
            'fee': fee,
            'net_amount': net_amount
        }

        # Pedir número de tarjeta
        bot.send_message(
            message.chat.id,
            f"💳 *INGRESA TU NÚMERO DE TARJETA*\n\n"
            f"📋 *Resumen del retiro:*\n"
            f"• Monto a retirar: ${amount:.2f}\n"
            f"• Fee (6%): ${fee:.2f}\n"
            f"• Recibirás: ${net_amount:.2f}\n\n"
            f"🔢 *Ingresa el número de tu tarjeta:*",
            parse_mode='Markdown'
        )

        bot.register_next_step_handler(message, process_withdraw_card)

    except ValueError:
        bot.send_message(
            message.chat.id,
            "❌ *Formato inválido*\nIngresa un número válido \(ej: 10\.50\)",
            parse_mode='Markdown',
            reply_markup=main_menu(message.chat.id)
        )

# Procesar tarjeta de retiro
def process_withdraw_card(message):
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

    # Validar tarjeta (formato básico)
    if len(card_number) < 10:
        bot.send_message(
            message.chat.id,
            "❌ *Número de tarjeta inválido*\n\nIngresa un número de tarjeta válido.",
            parse_mode='Markdown',
            reply_markup=main_menu(message.chat.id)
        )
        return

    # Registrar retiro en la base de datos
    log_withdrawal(withdrawal_id, user_id, withdrawal_data['amount'],
                  withdrawal_data['fee'], withdrawal_data['net_amount'],
                  card_number, "pending")

    # Actualizar balance del usuario (congelar fondos)
    update_balance(user_id, -withdrawal_data['amount'])

    # Notificar al grupo
    group_notification = f"""
📤 *NUEVA SOLICITUD DE RETIRO* 📤

*Usuario:* {escape_markdown(user_info[2])}
*Username:* @{escape_markdown(user_info[1]) if user_info[1] else 'N/A'}
*User ID:* `{user_id}`
*Wallet:* `{user_info[4]}`
*Monto a retirar:* ${withdrawal_data['amount']:.2f}
*Fee (6%):* ${withdrawal_data['fee']:.2f}
*Neto a recibir:* ${withdrawal_data['net_amount']:.2f}
*Tarjeta:* `{card_number}`
*Retiro ID:* `{withdrawal_id}`

⏳ *Esperando procesamiento...*

💾 *Para aprobar usa:*
`/aprobar_retiro {withdrawal_id} {withdrawal_data['amount']}`"""

    send_group_notification(group_notification)

    # Confirmar al usuario
    bot.send_message(
        message.chat.id,
        f"✅ *Solicitud de retiro enviada*\n\n"
        f"📋 *Detalles de tu retiro:*\n"
        f"• Monto solicitado: ${withdrawal_data['amount']:.2f}\n"
        f"• Fee (6%): ${withdrawal_data['fee']:.2f}\n"
        f"• Recibirás: ${withdrawal_data['net_amount']:.2f}\n"
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

# Procesar monto de depósito
def process_deposit_amount(message, method):
    try:
        amount = float(message.text)
        user_id = message.from_user.id
        user_info = get_user_info(user_id)

        if amount <= 0:
            bot.send_message(
                message.chat.id,
                "❌ *Monto inválido*\nEl monto debe ser mayor a 0\.",
                parse_mode='Markdown',
                reply_markup=main_menu(message.chat.id)
            )
            return

        deposit_id = f"DEP{uuid.uuid4().hex[:10].upper()}"
        pending_deposits[user_id] = {
            'deposit_id': deposit_id,
            'amount': amount,
            'method': method
        }

        if method == "transfermovil":
            payment_text = f"""
📱 *INSTRUCCIONES PARA PAGO POR TRANSFERMÓVIL*

💳 *Información para transferir:*
• *Teléfono:* `{PAYMENT_INFO['transfermovil']['phone']}`
• *Nombre:* {PAYMENT_INFO['transfermovil']['name']}
• *Banco:* {PAYMENT_INFO['transfermovil']['bank']}
• *Monto a transferir:* *${amount:.2f}*

📋 *Pasos a seguir:*
1\. Abre tu app de Transfermóvil
2\. Selecciona *\"Transferir\"*
3\. Ingresa el teléfono: *{PAYMENT_INFO['transfermovil']['phone']}*
4\. Ingresa el monto: *${amount:.2f}*
5\. Confirma la transferencia
6\. Toma una *captura de pantalla* del comprobante
7\. Envíala aquí

⚠️ *Importante:*
• El monto debe ser *exactamente* ${amount:.2f}
• Solo se aceptan transferencias desde CUENTAS PROPIAS
• La verificación puede tomar 5-15 minutos"""

        else:
            payment_text = f"""
🔵 *INSTRUCCIONES PARA PAGO POR ENZONA*

💳 *Información para pagar:*
• *Nombre:* {PAYMENT_INFO['enzona']['name']}
• *Monto a pagar:* *${amount:.2f}*

📋 *Pasos a seguir:*
1\. Abre tu app de EnZona
2\. Escanea el código QR o busca el comercio
3\. Ingresa el monto: *${amount:.2f}*
4\. Realiza el pago
5\. Toma una *captura de pantalla* del comprobante
6\. Envíala aquí

⚠️ *Importante:*
• El monto debe ser *exactamente* ${amount:.2f}
• Solo se aceptan pagos desde CUENTAS PROPIAS
• La verificación puede tomar 5-15 minutos"""

        log_deposit(deposit_id, user_id, amount, method, "pending")

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
            "❌ *Formato inválido*\nIngresa un número válido \(ej: 10\.50\)",
            parse_mode='Markdown',
            reply_markup=main_menu(message.chat.id)
        )

# Manejar capturas de pantalla de depósitos
@bot.message_handler(content_types=['photo'])
def handle_screenshot(message):
    user_id = message.from_user.id
    user_info = get_user_info(user_id)

    if user_id in pending_deposits:
        # Es un depósito
        deposit_data = pending_deposits[user_id]
        deposit_id = deposit_data['deposit_id']
        amount = deposit_data['amount']
        method = deposit_data['method']

        photo_id = message.photo[-1].file_id

        conn = sqlite3.connect('cubawallet.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE deposits SET screenshot_id = ? WHERE deposit_id = ?', (photo_id, deposit_id))
        conn.commit()
        conn.close()

        method_display = "Transfermóvil" if method == "transfermovil" else "EnZona"

        group_notification = f"""
📥 *NUEVO DEPÓSITO PENDIENTE* 📥

*Usuario:* {escape_markdown(user_info[2])}
*Username:* @{escape_markdown(user_info[1]) if user_info[1] else 'N/A'}
*User ID:* `{user_id}`
*Wallet:* `{user_info[4]}`
*Método:* {method_display}
*Monto:* ${amount:.2f}
*Depósito ID:* `{deposit_id}`

⏳ *Esperando verificación...*

💾 *Para aprobar usa:*
`/recargar {user_info[4]} {amount}`"""

        send_group_notification(group_notification, photo_id=photo_id)

        bot.reply_to(message,
                    f"✅ *Captura recibida*\n\n"
                    f"Hemos recibido tu comprobante por ${amount:.2f}\n\n"
                    f"📋 *Estado:* En revisión\n"
                    f"🆔 *Depósito:* {deposit_id}\n"
                    f"⏰ *Tiempo estimado:* 5-15 minutos\n\n"
                    f"Te notificaremos cuando sea verificado.",
                    parse_mode='Markdown',
                    reply_markup=main_menu(message.chat.id))

        del pending_deposits[user_id]

    elif user_id in pending_withdrawals:
        # Es un retiro (por si acaso, aunque no debería necesitar screenshot)
        bot.reply_to(message,
                    "ℹ️ *Para retiros no necesitas enviar captura*\n\n"
                    "Tu solicitud de retiro ya fue procesada y está pendiente de aprobación.",
                    parse_mode='Markdown',
                    reply_markup=main_menu(message.chat.id))

# Comando para ver saldo
@bot.message_handler(commands=['saldo'])
def show_balance(message):
    user_id = message.from_user.id
    user_info = get_user_info(user_id)

    if user_info:
        bot.send_message(
            message.chat.id,
            f"💰 *Tu saldo actual:* ${user_info[3]:.2f}",
            parse_mode='Markdown',
            reply_markup=main_menu(message.chat.id)
        )

# Inicializar y ejecutar el bot
if __name__ == "__main__":
    print("🧠 Inicializando base de datos...")
    init_db()
    print("🤖 Iniciando bot CubaWallet...")
    print(f"👑 Administrador: {ADMIN_ID}")
    print(f"📢 Notificaciones al grupo: {GROUP_CHAT_ID}")

    # Probar notificaciones al inicio
    test_msg = "🔔 *Bot CubaWallet iniciado* - Sistema de notificaciones activo"
    send_group_notification(test_msg)

    bot.polling(none_stop=True)
