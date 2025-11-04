import telebot
from telebot import types
import sqlite3
import uuid
from datetime import datetime, timedelta
import html
import re
import time
import os
import requests
import json
from typing import Dict, List, Optional
import logging

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuración
TOKEN = "7630853977:AAFgZ0wfQnXQC-2w08u0FqUKtzxLajUOsMo"
GROUP_CHAT_ID = "-1002636806169"
ADMIN_ID = 1853800972
ODDS_API_KEY = "edcbefe298f5551465376966b6e1c064"
bot = telebot.TeleBot(TOKEN)

# Estados y caché
user_states = {}
pending_deposits = {}
pending_withdrawals = {}
pending_bets = {}
sports_cache = {}
events_cache = {}

# Configuración optimizada para la API
API_CONFIG = {
    'base_url': 'https://api.the-odds-api.com/v4',
    'regions': 'us,eu',
    'markets': 'h2h,spreads,totals',
    'odds_format': 'decimal',
    'date_format': 'iso'
}

# CUOTAS FIJAS - SIEMPRE 1.9
FIXED_ODDS = 1.9

# Mapeo de competiciones principales
MAIN_COMPETITIONS = {
    'soccer': [
        {'key': 'soccer_epl', 'name': 'Premier League - Inglaterra'},
        {'key': 'soccer_uefa_champs_league', 'name': 'Champions League'},
        {'key': 'soccer_spain_la_liga', 'name': 'La Liga - España'},
        {'key': 'soccer_italy_serie_a', 'name': 'Serie A - Italia'},
        {'key': 'soccer_france_ligue_one', 'name': 'Ligue 1 - Francia'},
        {'key': 'soccer_germany_bundesliga', 'name': 'Bundesliga - Alemania'},
        {'key': 'soccer_uefa_europa_league', 'name': 'Europa League'},
        {'key': 'soccer_conmebol_copa_libertadores', 'name': 'Copa Libertadores'},
        {'key': 'soccer_usa_mls', 'name': 'MLS - USA'},
        {'key': 'soccer_netherlands_eredivisie', 'name': 'Eredivisie - Holanda'}
    ],
    'basketball': [
        {'key': 'basketball_nba', 'name': 'NBA'},
        {'key': 'basketball_euroleague', 'name': 'Euroleague'},
        {'key': 'basketball_ncaab_championship_winner', 'name': 'NCAA Basketball'},
        {'key': 'basketball_nbl', 'name': 'NBL - Australia'}
    ],
    'american_football': [
        {'key': 'americanfootball_nfl', 'name': 'NFL'},
        {'key': 'americanfootball_ncaaf', 'name': 'NCAA Football'}
    ],
    'baseball': [
        {'key': 'baseball_mlb', 'name': 'MLB'},
        {'key': 'baseball_npb', 'name': 'NPB - Japón'},
        {'key': 'baseball_kbo', 'name': 'KBO - Corea'}
    ],
    'ice_hockey': [
        {'key': 'icehockey_nhl', 'name': 'NHL'},
        {'key': 'icehockey_sweden_hockey_league', 'name': 'SHL - Suecia'}
    ],
    'tennis': [
        {'key': 'tennis_atp', 'name': 'ATP Tour'},
        {'key': 'tennis_wta', 'name': 'WTA Tour'}
    ],
    'mma': [
        {'key': 'mma_mixed_martial_arts', 'name': 'MMA'}
    ],
    'boxing': [
        {'key': 'boxing_boxing', 'name': 'Boxeo'}
    ]
}

# Información de pago
PAYMENT_INFO = {
    "transfermovil": {
        "name": "CubaBet Oficial",
        "phone": "5351234567",
        "bank": "Banco Metropolitano"
    },
    "enzona": {
        "name": "CubaBet Oficial",
    }
}

# Inicializar Base de Datos
def init_db():
    conn = sqlite3.connect('cubabet.db')
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance REAL DEFAULT 0.0,
            wallet_address TEXT UNIQUE,
            registered_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_bets INTEGER DEFAULT 0,
            bets_won INTEGER DEFAULT 0,
            total_wagered REAL DEFAULT 0.0,
            total_won REAL DEFAULT 0.0
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            transaction_id TEXT PRIMARY KEY,
            user_id INTEGER,
            amount REAL,
            type TEXT,
            method TEXT,
            status TEXT DEFAULT 'pending',
            admin_approved INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sports_bets (
            bet_id TEXT PRIMARY KEY,
            user_id INTEGER,
            sport_key TEXT,
            sport_title TEXT,
            event_id TEXT,
            event_name TEXT,
            commence_time TIMESTAMP,
            market_key TEXT,
            market_name TEXT,
            outcome_name TEXT,
            odds REAL,
            amount REAL,
            potential_win REAL,
            status TEXT DEFAULT 'pending',
            result TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')

    conn.commit()
    conn.close()

# CLASE ODDS API (se mantiene pero no se usará para cuotas)
class OddsAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.the-odds-api.com/v4"
        self.session = requests.Session()
        self.usage_stats = {
            'remaining': 0,
            'used': 0,
            'last_cost': 0
        }

    def _make_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        try:
            if params is None:
                params = {}

            params['apiKey'] = self.api_key

            url = f"{self.base_url}/{endpoint}"
            response = self.session.get(url, params=params, timeout=15)

            self.usage_stats['remaining'] = int(response.headers.get('x-requests-remaining', 0))
            self.usage_stats['used'] = int(response.headers.get('x-requests-used', 0))
            self.usage_stats['last_cost'] = int(response.headers.get('x-requests-last', 0))

            if response.status_code == 200:
                return response.json()
            else:
                print(f"❌ Error HTTP {response.status_code}: {response.text}")
                return None

        except Exception as e:
            print(f"❌ Error en petición a The Odds API: {e}")
            return None

    def get_sports(self, all_sports: bool = False) -> List[Dict]:
        endpoint = "sports"
        params = {}
        if all_sports:
            params['all'] = 'true'

        return self._make_request(endpoint, params) or []

    def get_odds(self, sport_key: str, regions: str = None, markets: str = None) -> List[Dict]:
        endpoint = f"sports/{sport_key}/odds"
        params = {
            'regions': regions or API_CONFIG['regions'],
            'markets': markets or API_CONFIG['markets'],
            'oddsFormat': API_CONFIG['odds_format'],
            'dateFormat': API_CONFIG['date_format']
        }

        return self._make_request(endpoint, params) or []

    def get_usage_stats(self) -> Dict:
        return self.usage_stats

# Instancia global de la API
odds_api = OddsAPI(ODDS_API_KEY)

# SISTEMA DE CACHÉ
def cache_sports_data():
    try:
        sports = odds_api.get_sports()

        if not sports:
            sports = [
                {"key": "americanfootball_nfl", "group": "American Football", "title": "NFL", "active": True},
                {"key": "baseball_mlb", "group": "Baseball", "title": "MLB", "active": True},
                {"key": "basketball_nba", "group": "Basketball", "title": "NBA", "active": True},
                {"key": "soccer_epl", "group": "Soccer", "title": "EPL", "active": True},
                {"key": "soccer_uefa_champs_league", "group": "Soccer", "title": "UEFA Champions League", "active": True},
                {"key": "icehockey_nhl", "group": "Ice Hockey", "title": "NHL", "active": True},
            ]

        sports_cache['data'] = sports
        sports_cache['last_updated'] = datetime.now()

        return True

    except Exception as e:
        print(f"❌ Error en cache_sports_data: {e}")
        return False

def get_sports_by_category():
    if not sports_cache.get('data'):
        cache_sports_data()

    sports = sports_cache.get('data', [])
    categories = {}

    for sport in sports:
        if sport.get('active', True):
            group = sport.get('group', 'Other')
            if group not in categories:
                categories[group] = []

            name_mapping = {
                'basketball_nba': '🏀 NBA',
                'americanfootball_nfl': '🏈 NFL',
                'baseball_mlb': '⚾ MLB',
                'soccer_epl': '⚽ Premier League',
                'soccer_uefa_champs_league': '⚽ Champions League',
                'icehockey_nhl': '🏒 NHL',
            }

            sport['display_name'] = name_mapping.get(sport['key'], sport.get('title', sport['key']))
            categories[group].append(sport)

    return categories

def get_competitions_for_sport(sport_group: str):
    competition_mapping = {
        'Soccer': MAIN_COMPETITIONS['soccer'],
        'Basketball': MAIN_COMPETITIONS['basketball'],
        'American Football': MAIN_COMPETITIONS['american_football'],
        'Baseball': MAIN_COMPETITIONS['baseball'],
        'Ice Hockey': MAIN_COMPETITIONS['ice_hockey'],
        'Tennis': MAIN_COMPETITIONS['tennis'],
        'Mixed Martial Arts': MAIN_COMPETITIONS['mma'],
        'Boxing': MAIN_COMPETITIONS['boxing']
    }

    return competition_mapping.get(sport_group, [])

def get_sport_events(sport_key: str) -> List[Dict]:
    cache_key = f"{sport_key}_events"

    if cache_key in events_cache:
        cache_age = datetime.now() - events_cache[cache_key]['last_updated']
        if cache_age.total_seconds() < 300:
            return events_cache[cache_key]['data']

    try:
        events_with_odds = odds_api.get_odds(sport_key)

        if events_with_odds:
            processed_events = []
            for event in events_with_odds[:10]:
                if event.get('bookmakers') and len(event['bookmakers']) > 0:
                    processed_event = {
                        'id': event.get('id', str(uuid.uuid4())),
                        'sport_key': event.get('sport_key', sport_key),
                        'home_team': event.get('home_team', 'Equipo Local'),
                        'away_team': event.get('away_team', 'Equipo Visitante'),
                        'commence_time': event.get('commence_time', datetime.now().isoformat()),
                        'bookmakers': event.get('bookmakers', []),
                        'source': 'api'
                    }
                    processed_events.append(processed_event)

            if processed_events:
                events_cache[cache_key] = {
                    'data': processed_events,
                    'last_updated': datetime.now()
                }
                return processed_events

        return generate_sample_events(sport_key)

    except Exception as e:
        print(f"❌ Error obteniendo eventos para {sport_key}: {e}")
        return generate_sample_events(sport_key)

def get_event_with_odds(sport_key: str, event_id: str) -> Optional[Dict]:
    """Obtiene información detallada de un evento específico"""
    events = get_sport_events(sport_key)
    
    for event in events:
        if event.get('id') == event_id:
            return event
    return None

def generate_sample_events(sport_key: str) -> List[Dict]:
    """Genera eventos de ejemplo"""
    sample_events = []
    
    # Mapeo mejorado de equipos por deporte
    team_mapping = {
        'soccer_uefa_europa_league': [
            ('Basel', 'FCSB'),
            ('Roma', 'Brighton'),
            ('Liverpool', 'Sparta Prague'),
        ],
        'soccer_epl': [
            ('Manchester United', 'Liverpool'),
            ('Arsenal', 'Chelsea'),
        ],
        'basketball_nba': [
            ('Lakers', 'Warriors'),
        ],
        'default': [
            ('Equipo Local', 'Equipo Visitante'),
        ]
    }
    
    teams = team_mapping.get(sport_key, team_mapping['default'])
    
    for i, (home, away) in enumerate(teams):
        commence_time = datetime.now() + timedelta(hours=(i+1)*6)
        
        sample_events.append({
            'id': f"sample_{sport_key}_{i}",
            'sport_key': sport_key,
            'home_team': home,
            'away_team': away,
            'commence_time': commence_time.isoformat(),
            'source': 'sample'
        })
    
    cache_key = f"{sport_key}_events"
    events_cache[cache_key] = {
        'data': sample_events,
        'last_updated': datetime.now()
    }
    
    return sample_events

# FUNCIONES DE UTILIDAD
def escape_markdown(text):
    if text is None:
        return ""
    escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in escape_chars:
        text = str(text).replace(char, f'\\{char}')
    return text

def format_time(dt=None):
    """Formatea datetime en formato simple"""
    if dt is None:
        dt = datetime.now()
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def send_group_notification(message: str, reply_markup=None, photo_id: str = None) -> bool:
    try:
        if photo_id:
            bot.send_photo(GROUP_CHAT_ID, photo=photo_id, caption=message, parse_mode='Markdown', reply_markup=reply_markup)
        else:
            bot.send_message(GROUP_CHAT_ID, text=message, parse_mode='Markdown', reply_markup=reply_markup)
        return True
    except Exception as e:
        print(f"❌ Error enviando notificación: {e}")
        return False

# SISTEMA DE USUARIOS Y TRANSACCIONES
def register_user(user_id: int, username: str, first_name: str):
    conn = sqlite3.connect('cubabet.db')
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()

    if not user:
        wallet_address = f"CB{uuid.uuid4().hex[:12].upper()}"
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name, wallet_address, balance)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, wallet_address, 0.0))
        conn.commit()

        notification_text = f"🆕 *NUEVO USUARIO REGISTRADO*\n\n• Nombre: {escape_markdown(first_name)}\n• Wallet: `{wallet_address}`"
        send_group_notification(notification_text)

    conn.close()

def get_user_info(user_id: int):
    conn = sqlite3.connect('cubabet.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def update_balance(user_id: int, amount: float):
    conn = sqlite3.connect('cubabet.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()

def has_minimum_balance(user_id: int, min_balance: float = 30.0) -> bool:
    user_info = get_user_info(user_id)
    return user_info[3] >= min_balance if user_info else False

# SISTEMA DE DEPÓSITOS Y RETIROS
def log_transaction(transaction_id: str, user_id: int, amount: float, trans_type: str, method: str, status: str = 'pending'):
    conn = sqlite3.connect('cubabet.db')
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO transactions (transaction_id, user_id, amount, type, method, status)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (transaction_id, user_id, amount, trans_type, method, status))

    conn.commit()
    conn.close()

def process_deposit(user_id: int, amount: float, method: str):
    """Procesa un depósito - VERSIÓN SIMPLIFICADA"""
    transaction_id = f"DEP{uuid.uuid4().hex[:8].upper()}"

    # Registrar transacción
    log_transaction(transaction_id, user_id, amount, 'deposit', method, 'pending')

    # Guardar en pending para esperar screenshot
    pending_deposits[user_id] = {
        'transaction_id': transaction_id,
        'amount': amount,
        'method': method
    }

    return transaction_id

def process_withdrawal(user_id: int, amount: float, card_number: str):
    """Procesa un retiro - VERSIÓN SIMPLIFICADA"""
    transaction_id = f"WDL{uuid.uuid4().hex[:8].upper()}"
    fee = amount * 0.06
    net_amount = amount - fee

    # Registrar transacción
    log_transaction(transaction_id, user_id, amount, 'withdrawal', 'card', 'pending')

    # Congelar fondos
    update_balance(user_id, -amount)

    # Notificar al grupo
    user_info = get_user_info(user_id)
    notification_text = f"""
📤 *SOLICITUD DE RETIRO*

👤 Usuario: {escape_markdown(user_info[2])}
💳 Monto: ${amount:.2f} CUP
💸 Fee (6%): ${fee:.2f} CUP
💰 Neto a recibir: ${net_amount:.2f} CUP
🏦 Tarjeta: `{card_number}`
🆔 Transacción: `{transaction_id}`

⏳ Esperando aprobación..."""

    send_group_notification(notification_text)

    return transaction_id, net_amount

# SISTEMA DE APUESTAS CON CUOTAS FIJAS
def log_bet(bet_data: Dict) -> str:
    bet_id = f"BET{uuid.uuid4().hex[:8].upper()}"

    conn = sqlite3.connect('cubabet.db')
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO sports_bets (
            bet_id, user_id, sport_key, sport_title, event_id, event_name,
            commence_time, market_key, market_name, outcome_name, odds,
            amount, potential_win, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        bet_id, bet_data['user_id'], bet_data['sport_key'], bet_data['sport_title'],
        bet_data['event_id'], bet_data['event_name'], bet_data['commence_time'],
        bet_data['market_key'], bet_data['market_name'], bet_data['outcome_name'],
        FIXED_ODDS, bet_data['amount'], bet_data['potential_win'], 'pending'
    ))

    cursor.execute('''
        UPDATE users
        SET total_bets = total_bets + 1,
            total_wagered = total_wagered + ?
        WHERE user_id = ?
    ''', (bet_data['amount'], bet_data['user_id']))

    conn.commit()
    conn.close()

    return bet_id

def send_bet_ticket_notification(user_id: int, bet_data: Dict, bet_id: str):
    user_info = get_user_info(user_id)

    # Crear teclado para administradores
    admin_markup = types.InlineKeyboardMarkup()
    btn_win = types.InlineKeyboardButton("✅ Ganada", callback_data=f"admin_bet_win_{bet_id}")
    btn_lose = types.InlineKeyboardButton("❌ Perdida", callback_data=f"admin_bet_lose_{bet_id}")
    admin_markup.add(btn_win, btn_lose)

    ticket_message = f"""
🎫 *TICKET DE APUESTA REGISTRADO*

👤 *Usuario:* {escape_markdown(user_info[2])}
📊 *Evento:* {escape_markdown(bet_data['event_name'])}
🎯 *Selección:* {escape_markdown(bet_data['outcome_name'])}
💰 *Monto:* ${bet_data['amount']:.2f} CUP
🏆 *Potencial:* ${bet_data['potential_win']:.2f} CUP
📈 *Cuota:* {FIXED_ODDS}
🆔 *Ticket:* `{bet_id}`
🕒 *Fecha:* {format_time()}

⚡ *¡Buena suerte!* 🍀

👑 *Acciones Admin:*"""

    send_group_notification(ticket_message, reply_markup=admin_markup)

def update_bet_status(bet_id: str, status: str, result: str):
    """Actualiza el estado de una apuesta y procesa el pago si ganó"""
    conn = sqlite3.connect('cubabet.db')
    cursor = conn.cursor()
    
    # Obtener información de la apuesta
    cursor.execute('SELECT * FROM sports_bets WHERE bet_id = ?', (bet_id,))
    bet = cursor.fetchone()
    
    if not bet:
        conn.close()
        return False
    
    user_id = bet[1]
    amount = bet[12]  # amount apostado
    potential_win = bet[13]  # ganancia potencial
    
    # Actualizar estado de la apuesta
    cursor.execute('''
        UPDATE sports_bets 
        SET status = ?, result = ? 
        WHERE bet_id = ?
    ''', (status, result, bet_id))
    
    # Si la apuesta ganó, procesar el pago
    if status == 'won':
        # Añadir ganancias al balance del usuario
        cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (potential_win, user_id))
        
        # Actualizar estadísticas del usuario
        cursor.execute('''
            UPDATE users 
            SET bets_won = bets_won + 1, 
                total_won = total_won + ?
            WHERE user_id = ?
        ''', (potential_win - amount, user_id))  # ganancia neta
        
        # Notificar al usuario
        try:
            user_info = get_user_info(user_id)
            win_message = f"""
🎉 *¡FELICIDADES! APUESTA GANADA*

🎫 *Ticket:* `{bet_id}`
💰 *Monto apostado:* ${amount:.2f} CUP
🏆 *Ganancia:* ${potential_win:.2f} CUP
💵 *Ganancia neta:* ${potential_win - amount:.2f} CUP

¡Sigue así! 🍀"""
            bot.send_message(user_id, win_message, parse_mode='Markdown')
        except:
            pass
    
    conn.commit()
    conn.close()
    return True

# SISTEMA DE MENÚS
def main_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_bet = types.InlineKeyboardButton("🎯 Apostar", callback_data="sports_betting")
    btn_money = types.InlineKeyboardButton("💰 Dinero", callback_data="money_menu")
    btn_profile = types.InlineKeyboardButton("👤 Perfil", callback_data="profile_info")
    markup.add(btn_bet, btn_money, btn_profile)
    return markup

def sports_categories_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)

    categories = get_sports_by_category()

    for category_name in ['Soccer', 'Basketball', 'American Football', 'Baseball', 'Ice Hockey']:
        if category_name in categories and categories[category_name]:
            btn = types.InlineKeyboardButton(
                f"🏆 {category_name}",
                callback_data=f"category_{category_name.lower().replace(' ', '_')}"
            )
            markup.add(btn)

    btn_back = types.InlineKeyboardButton("🔙 Volver", callback_data="back_to_main")
    markup.add(btn_back)

    return markup

def competitions_menu(sport_group: str):
    markup = types.InlineKeyboardMarkup(row_width=2)

    competitions = get_competitions_for_sport(sport_group)

    if competitions:
        for comp in competitions[:8]:
            btn = types.InlineKeyboardButton(
                f"⚽ {comp['name']}",
                callback_data=f"competition_{comp['key']}"
            )
            markup.add(btn)

    btn_back = types.InlineKeyboardButton("🔙 Volver a Deportes", callback_data="sports_betting")
    markup.add(btn_back)

    return markup

def money_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_deposit = types.InlineKeyboardButton("💳 Depositar", callback_data="deposit_money")
    btn_withdraw = types.InlineKeyboardButton("💸 Retirar", callback_data="withdraw_money")
    btn_balance = types.InlineKeyboardButton("💰 Saldo", callback_data="check_balance")
    btn_back = types.InlineKeyboardButton("🔙 Volver", callback_data="back_to_main")
    markup.add(btn_deposit, btn_withdraw, btn_balance, btn_back)
    return markup

def deposit_methods_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_transfermovil = types.InlineKeyboardButton("📱 Transfermóvil", callback_data="deposit_transfermovil")
    btn_enzona = types.InlineKeyboardButton("🔵 EnZona", callback_data="deposit_enzona")
    btn_back = types.InlineKeyboardButton("🔙 Volver", callback_data="money_menu")
    markup.add(btn_transfermovil, btn_enzona, btn_back)
    return markup

# NUEVAS FUNCIONES PARA MOSTRAR CUOTAS FIJAS
def show_event_odds(call, sport_key: str, event_id: str):
    """Muestra las opciones de apuesta con cuotas fijas"""
    user_id = call.from_user.id
    
    # Verificar saldo mínimo
    if not has_minimum_balance(user_id):
        bot.answer_callback_query(
            call.id,
            "❌ Saldo insuficiente. Mínimo: $30.00 CUP",
            show_alert=True
        )
        return
    
    # Obtener información del evento
    event_data = get_event_with_odds(sport_key, event_id)
    if not event_data:
        bot.answer_callback_query(call.id, "❌ No se pudo cargar el evento")
        return
    
    # Formatear tiempo del evento
    commence_time = event_data.get('commence_time')
    if commence_time:
        try:
            if commence_time.endswith('Z'):
                commence_time = commence_time[:-1]
            event_dt = datetime.fromisoformat(commence_time)
            time_remaining = event_dt - datetime.now()
            
            days = time_remaining.days
            hours, remainder = divmod(time_remaining.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            time_display = f"{days}d {hours}h {minutes}m"
            event_time = event_dt.strftime("%H:%M")
            
            # Formatear día de la semana
            days_spanish = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
            day_of_week = days_spanish[event_dt.weekday()]
        except:
            time_display = "Próximamente"
            event_time = "Por definir"
            day_of_week = "Próximamente"
    else:
        time_display = "Próximamente"
        event_time = "Por definir"
        day_of_week = "Próximamente"
    
    # Construir mensaje
    home_team = escape_markdown(event_data.get('home_team', 'Local'))
    away_team = escape_markdown(event_data.get('away_team', 'Visitante'))
    
    # Determinar el deporte para el título
    sport_title = sport_key.replace('_', ' ').title()
    if 'uefa_europa_league' in sport_key:
        sport_title = "UEFA Europa League"
    elif 'uefa_champs' in sport_key:
        sport_title = "UEFA Champions League"
    elif 'epl' in sport_key:
        sport_title = "Premier League"
    
    odds_text = f"""
*{sport_title}*

*{home_team} vs {away_team}*

*{day_of_week} {event_time}*

*Comienza en {time_display}*

*1x2 (Tiempo Regular) - 3 opciones*  
*Cuota fija: {FIXED_ODDS}*
"""
    
    # Crear teclado inline con las opciones de apuesta
    markup = types.InlineKeyboardMarkup(row_width=3)
    
    # Botones de selección con cuota fija
    btn_g1 = types.InlineKeyboardButton(
        f"G1\n{FIXED_ODDS}",
        callback_data=f"bet_{sport_key}_{event_id}_h2h_home_{FIXED_ODDS}"
    )
    btn_x = types.InlineKeyboardButton(
        f"X\n{FIXED_ODDS}",
        callback_data=f"bet_{sport_key}_{event_id}_h2h_draw_{FIXED_ODDS}"
    )
    btn_g2 = types.InlineKeyboardButton(
        f"G2\n{FIXED_ODDS}",
        callback_data=f"bet_{sport_key}_{event_id}_h2h_away_{FIXED_ODDS}"
    )
    
    markup.add(btn_g1, btn_x, btn_g2)
    
    btn_back = types.InlineKeyboardButton("🔙 Volver Atras", callback_data=f"competition_{sport_key}")
    markup.add(btn_back)
    
    # Enviar mensaje
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=odds_text,
        parse_mode='Markdown',
        reply_markup=markup
    )

def process_bet_selection(call, bet_data: str):
    """Procesa cuando un usuario selecciona una opción de apuesta"""
    parts = bet_data.split('_')
    if len(parts) < 5:
        bot.answer_callback_query(call.id, "❌ Error en datos de apuesta")
        return
    
    user_id = call.from_user.id
    sport_key = parts[0]
    event_id = '_'.join(parts[1:-3])
    market_key = parts[-3]
    outcome_type = parts[-2]  # home, draw, away
    odds = float(parts[-1])
    
    # Obtener información del evento
    event_data = get_event_with_odds(sport_key, event_id)
    if not event_data:
        bot.answer_callback_query(call.id, "❌ Evento no disponible")
        return
    
    # Determinar el nombre del outcome basado en el tipo
    if outcome_type == 'home':
        outcome_name = f"Gana {event_data.get('home_team', 'Local')}"
    elif outcome_type == 'away':
        outcome_name = f"Gana {event_data.get('away_team', 'Visitante')}"
    else:  # draw
        outcome_name = 'Empate'
    
    # Guardar en estado del usuario
    user_states[user_id] = {
        'action': 'placing_bet',
        'sport_key': sport_key,
        'sport_title': sport_key.replace('_', ' ').title(),
        'event_id': event_id,
        'event_name': f"{event_data.get('home_team', 'Local')} vs {event_data.get('away_team', 'Visitante')}",
        'market_key': market_key,
        'outcome_name': outcome_name,
        'odds': FIXED_ODDS  # Siempre usar cuota fija
    }
    
    # Pedir monto de apuesta
    bet_info_text = f"""
🎯 *CONFIRMAR APUESTA*

⚽ *Evento:* {escape_markdown(event_data.get('home_team', 'Local'))} vs {escape_markdown(event_data.get('away_team', 'Visitante'))}
🎯 *Selección:* {escape_markdown(outcome_name)}
💰 *Cuota:* {FIXED_ODDS}

💵 *Ingresa el monto a apostar (CUP):*
💰 *Mínimo: $30.00*"""

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=bet_info_text,
        parse_mode='Markdown'
    )

# MANEJADORES PRINCIPALES
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    register_user(user_id, username, first_name)
    user_info = get_user_info(user_id)

    if not sports_cache.get('data'):
        cache_sports_data()

    welcome_text = f"""
🎉 *¡Bienvenido a CubaBet, {escape_markdown(first_name)}!*

💰 *Saldo:* ${user_info[3]:.2f} CUP
💳 *Wallet:* `{user_info[4]}`

⚡ *Selecciona una opción:*"""

    bot.send_message(
        chat_id=message.chat.id,
        text=welcome_text,
        parse_mode='Markdown',
        reply_markup=main_menu()
    )

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id

    try:
        if call.data == "back_to_main":
            show_main_menu(call)
        elif call.data == "sports_betting":
            show_sports_categories(call)
        elif call.data.startswith("category_"):
            category = call.data.replace("category_", "")
            show_competitions_menu(call, category)
        elif call.data.startswith("competition_"):
            competition_key = call.data.replace("competition_", "")
            show_competition_events(call, competition_key)
        elif call.data.startswith("event_"):
            event_data = call.data.replace("event_", "")
            parts = event_data.split('_')
            if len(parts) >= 2:
                sport_key = parts[0]
                event_id = '_'.join(parts[1:])
                show_event_odds(call, sport_key, event_id)
        elif call.data.startswith("bet_"):
            bet_data = call.data.replace("bet_", "")
            process_bet_selection(call, bet_data)
        elif call.data.startswith("admin_bet_win_"):
            # Manejar apuesta ganada por admin
            if call.from_user.id != ADMIN_ID:
                bot.answer_callback_query(call.id, "❌ Solo administradores")
                return
            bet_id = call.data.replace("admin_bet_win_", "")
            if update_bet_status(bet_id, 'won', 'Ganada'):
                bot.answer_callback_query(call.id, "✅ Apuesta marcada como GANADA")
                # Actualizar mensaje en el grupo
                try:
                    bot.edit_message_reply_markup(
                        chat_id=call.message.chat.id,
                        message_id=call.message.message_id,
                        reply_markup=None
                    )
                    bot.send_message(call.message.chat.id, f"✅ *APUESTA GANADA*\n\n🎫 Ticket: `{bet_id}`\n👤 Admin: {escape_markdown(call.from_user.first_name)}", parse_mode='Markdown')
                except:
                    pass
            else:
                bot.answer_callback_query(call.id, "❌ Error al actualizar apuesta")
        elif call.data.startswith("admin_bet_lose_"):
            # Manejar apuesta perdida por admin
            if call.from_user.id != ADMIN_ID:
                bot.answer_callback_query(call.id, "❌ Solo administradores")
                return
            bet_id = call.data.replace("admin_bet_lose_", "")
            if update_bet_status(bet_id, 'lost', 'Perdida'):
                bot.answer_callback_query(call.id, "✅ Apuesta marcada como PERDIDA")
                # Actualizar mensaje en el grupo
                try:
                    bot.edit_message_reply_markup(
                        chat_id=call.message.chat.id,
                        message_id=call.message.message_id,
                        reply_markup=None
                    )
                    bot.send_message(call.message.chat.id, f"❌ *APUESTA PERDIDA*\n\n🎫 Ticket: `{bet_id}`\n👤 Admin: {escape_markdown(call.from_user.first_name)}", parse_mode='Markdown')
                except:
                    pass
            else:
                bot.answer_callback_query(call.id, "❌ Error al actualizar apuesta")
        elif call.data == "money_menu":
            show_money_menu(call)
        elif call.data == "deposit_money":
            show_deposit_methods(call)
        elif call.data.startswith("deposit_"):
            method = call.data.replace("deposit_", "")
            start_deposit_process(call, method)
        elif call.data == "withdraw_money":
            start_withdrawal_process(call)
        elif call.data == "check_balance":
            show_balance(call)
        elif call.data == "profile_info":
            show_profile_info(call)

    except Exception as e:
        print(f"Error en callback: {e}")
        bot.answer_callback_query(call.id, "❌ Error procesando la solicitud")

def show_main_menu(call):
    user_info = get_user_info(call.from_user.id)

    menu_text = f"""
🎯 *Menú Principal - CubaBet*

👋 ¡Hola de nuevo, {escape_markdown(user_info[2])}!

💰 *Saldo:* ${user_info[3]:.2f} CUP
🎯 *Apuestas:* {user_info[6]}

⚡ *Selecciona una opción:*"""

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=menu_text,
        parse_mode='Markdown',
        reply_markup=main_menu()
    )

def show_sports_categories(call):
    categories_text = """
🎯 *SELECCIÓN DE DEPORTES*

🏆 *Elige una categoría:*

• ⚽ Fútbol
• 🏀 Baloncesto
• 🏈 Fútbol Americano
• ⚾ Béisbol
• 🏒 Hockey

📈 *Cuota fija: 1.9*"""

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=categories_text,
        parse_mode='Markdown',
        reply_markup=sports_categories_menu()
    )

def show_competitions_menu(call, sport_group: str):
    sport_group_display = sport_group.replace('_', ' ').title()

    competitions_text = f"""
🏆 *COMPETICIONES - {sport_group_display}*

⚽ *Selecciona una competición:*

🕒 *Eventos próximos disponibles*
📈 *Cuota fija: 1.9*"""

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=competitions_text,
        parse_mode='Markdown',
        reply_markup=competitions_menu(sport_group_display)
    )

def show_competition_events(call, competition_key: str):
    bot.answer_callback_query(call.id, "⏳ Cargando eventos...")

    loading_text = "⏳ *Cargando eventos...*"
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=loading_text,
        parse_mode='Markdown'
    )

    time.sleep(1)
    sport_events = get_sport_events(competition_key)

    if not sport_events:
        error_text = "❌ *No hay eventos disponibles*"
        markup = types.InlineKeyboardMarkup()
        btn_back = types.InlineKeyboardButton("🔙 Volver", callback_data="sports_betting")
        markup.add(btn_back)

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=error_text,
            parse_mode='Markdown',
            reply_markup=markup
        )
        return

    events_text = f"🎯 *PRÓXIMOS EVENTOS - {competition_key.replace('_', ' ').title()}*\n\n"
    markup = types.InlineKeyboardMarkup()

    for i, event in enumerate(sport_events[:8]):
        home_team = escape_markdown(event.get('home_team', 'Local'))
        away_team = escape_markdown(event.get('away_team', 'Visitante'))
        event_id = event.get('id', '')
        
        # Formatear tiempo
        commence_time = event.get('commence_time')
        if commence_time:
            try:
                if commence_time.endswith('Z'):
                    commence_time = commence_time[:-1]
                event_dt = datetime.fromisoformat(commence_time)
                time_str = event_dt.strftime("%H:%M")
                
                time_remaining = event_dt - datetime.now()
                days = time_remaining.days
                hours, remainder = divmod(time_remaining.seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                
                remaining_str = f"{days}d {hours}h {minutes}m"
                
                # Día de la semana
                days_spanish = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
                day_str = days_spanish[event_dt.weekday()]
            except:
                time_str = "Por definir"
                remaining_str = "Próximamente"
                day_str = "Próx"
        else:
            time_str = "Por definir"
            remaining_str = "Próximamente"
            day_str = "Próx"

        btn = types.InlineKeyboardButton(
            f"⚽ {home_team} vs {away_team} - {day_str} {time_str}",
            callback_data=f"event_{competition_key}_{event_id}"
        )
        markup.add(btn)

        events_text += f"*{i+1}. {home_team} vs {away_team}*\n"
        events_text += f"   🕒 {day_str} {time_str} | ⏳ {remaining_str}\n\n"

    btn_back = types.InlineKeyboardButton("🔙 Volver a Competencias", callback_data=f"category_{competition_key.split('_')[0]}")
    markup.add(btn_back)

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=events_text,
        parse_mode='Markdown',
        reply_markup=markup
    )

# MANEJADOR DE APUESTAS
@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get('action') == 'placing_bet')
def handle_bet_amount(message):
    user_id = message.from_user.id
    user_state = user_states.get(user_id, {})

    if not user_state:
        return

    try:
        amount = float(message.text)

        if amount < 30.0:
            bot.send_message(message.chat.id, "❌ *Monto mínimo: $30.00 CUP*", parse_mode='Markdown')
            return

        user_info = get_user_info(user_id)
        if amount > user_info[3]:
            bot.send_message(message.chat.id, f"❌ *Saldo insuficiente*\nTu saldo: ${user_info[3]:.2f} CUP", parse_mode='Markdown')
            return

        potential_win = amount * FIXED_ODDS

        bet_data = {
            'user_id': user_id,
            'sport_key': user_state['sport_key'],
            'sport_title': user_state['sport_title'],
            'event_id': user_state['event_id'],
            'event_name': user_state['event_name'],
            'commence_time': datetime.now().isoformat(),
            'market_key': user_state['market_key'],
            'market_name': user_state['market_key'],
            'outcome_name': user_state['outcome_name'],
            'odds': FIXED_ODDS,
            'amount': amount,
            'potential_win': potential_win
        }

        bet_id = log_bet(bet_data)
        update_balance(user_id, -amount)
        send_bet_ticket_notification(user_id, bet_data, bet_id)

        confirmation_text = f"""
✅ *APUESTA REGISTRADA*

🎫 *Ticket:* `{bet_id}`
💰 *Monto:* ${amount:.2f} CUP
🏆 *Potencial:* ${potential_win:.2f} CUP
📈 *Cuota:* {FIXED_ODDS}

⚡ *¡Buena suerte!* 🍀"""

        bot.send_message(message.chat.id, confirmation_text, parse_mode='Markdown', reply_markup=main_menu())
        del user_states[user_id]

    except ValueError:
        bot.send_message(message.chat.id, "❌ *Ingresa un número válido*", parse_mode='Markdown')

# SISTEMA DE DEPÓSITOS
def show_deposit_methods(call):
    deposit_text = """
💳 *DEPOSITAR FONDOS*

Selecciona método de pago:

📱 *Transfermóvil*
🔵 *EnZona*

💡 *Depósitos verificados manualmente*"""

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=deposit_text,
        parse_mode='Markdown',
        reply_markup=deposit_methods_menu()
    )

def start_deposit_process(call, method: str):
    user_id = call.from_user.id
    user_states[user_id] = {'action': f'deposit_{method}'}

    method_display = "Transfermóvil" if method == "transfermovil" else "EnZona"

    deposit_text = f"""
💰 *DEPÓSITO POR {method_display}*

💵 *Ingresa el monto a depositar (CUP):*

📝 *Ejemplo:* 100.00"""

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=deposit_text,
        parse_mode='Markdown'
    )

# MANEJADOR DE DEPÓSITOS
@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get('action', '').startswith('deposit_'))
def handle_deposit_amount(message):
    user_id = message.from_user.id
    user_state = user_states.get(user_id, {})

    if not user_state:
        return

    try:
        amount = float(message.text)
        method = user_state['action'].replace('deposit_', '')

        if amount <= 0:
            bot.send_message(message.chat.id, "❌ *Monto debe ser mayor a 0*", parse_mode='Markdown')
            return

        transaction_id = process_deposit(user_id, amount, method)

        if method == "transfermovil":
            payment_text = f"""
📱 *INSTRUCCIONES TRANSFERMÓVIL*

💳 *Transferir a:*
• Teléfono: `{PAYMENT_INFO['transfermovil']['phone']}`
• Nombre: {PAYMENT_INFO['transfermovil']['name']}
• Monto: *${amount:.2f} CUP*

📸 *Envía el comprobante*"""
        else:
            payment_text = f"""
🔵 *INSTRUCCIONES ENZONA*

💳 *Pagar a:*
• Nombre: {PAYMENT_INFO['enzona']['name']}
• Monto: *${amount:.2f} CUP*

📸 *Envía el comprobante*"""

        bot.send_message(message.chat.id, payment_text, parse_mode='Markdown')
        bot.send_message(message.chat.id, f"🆔 *ID de transacción:* `{transaction_id}`", parse_mode='Markdown')

        del user_states[user_id]

    except ValueError:
        bot.send_message(message.chat.id, "❌ *Ingresa un número válido*", parse_mode='Markdown')

# MANEJADOR DE FOTOS PARA DEPÓSITOS
@bot.message_handler(content_types=['photo'])
def handle_screenshot(message):
    user_id = message.from_user.id

    if user_id in pending_deposits:
        deposit_data = pending_deposits[user_id]
        photo_id = message.photo[-1].file_id

        user_info = get_user_info(user_id)

        notification_text = f"""
📥 *DEPÓSITO PENDIENTE*

👤 Usuario: {escape_markdown(user_info[2])}
💰 Monto: ${deposit_data['amount']:.2f} CUP
🏦 Método: {deposit_data['method'].title()}
🆔 Transacción: `{deposit_data['transaction_id']}`

⏳ Esperando verificación..."""

        send_group_notification(notification_text, photo_id=photo_id)

        bot.reply_to(message, "✅ *Comprobante recibido. Espera verificación.*", parse_mode='Markdown', reply_markup=main_menu())
        del pending_deposits[user_id]
    else:
        bot.reply_to(message, "❌ *No tienes depósitos pendientes*", parse_mode='Markdown')

# SISTEMA DE RETIROS
def start_withdrawal_process(call):
    user_id = call.from_user.id
    user_info = get_user_info(user_id)

    if user_info[3] < 30.0:
        bot.answer_callback_query(call.id, "❌ Saldo mínimo: $30.00 CUP", show_alert=True)
        return

    user_states[user_id] = {'action': 'withdrawal_amount'}

    withdrawal_text = f"""
💸 *RETIRAR FONDOS*

💰 *Saldo disponible:* ${user_info[3]:.2f} CUP

💵 *Ingresa el monto a retirar (CUP):*
💰 *Mínimo: $30.00*"""

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=withdrawal_text,
        parse_mode='Markdown'
    )

# MANEJADOR DE RETIROS
@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get('action') == 'withdrawal_amount')
def handle_withdrawal_amount(message):
    user_id = message.from_user.id

    try:
        amount = float(message.text)
        user_info = get_user_info(user_id)

        if amount < 30.0:
            bot.send_message(message.chat.id, "❌ *Monto mínimo: $30.00 CUP*", parse_mode='Markdown')
            return

        if amount > user_info[3]:
            bot.send_message(message.chat.id, f"❌ *Saldo insuficiente*\nDisponible: ${user_info[3]:.2f} CUP", parse_mode='Markdown')
            return

        fee = amount * 0.06
        net_amount = amount - fee

        user_states[user_id] = {
            'action': 'withdrawal_card',
            'amount': amount,
            'fee': fee,
            'net_amount': net_amount
        }

        withdrawal_info = f"""
💸 *CONFIRMAR RETIRO*

💰 *Monto a retirar:* ${amount:.2f} CUP
💸 *Fee (6%):* ${fee:.2f} CUP
💰 *Recibirás:* ${net_amount:.2f} CUP

💳 *Ingresa número de tarjeta:*"""

        bot.send_message(message.chat.id, withdrawal_info, parse_mode='Markdown')

    except ValueError:
        bot.send_message(message.chat.id, "❌ *Ingresa un número válido*", parse_mode='Markdown')

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get('action') == 'withdrawal_card')
def handle_withdrawal_card(message):
    user_id = message.from_user.id
    user_state = user_states.get(user_id, {})

    if not user_state:
        return

    card_number = message.text.strip()

    if len(card_number) < 10 or not card_number.isdigit():
        bot.send_message(message.chat.id, "❌ *Número de tarjeta inválido*", parse_mode='Markdown')
        return

    amount = user_state['amount']

    transaction_id, net_amount = process_withdrawal(user_id, amount, card_number)

    confirmation_text = f"""
✅ *RETIRO SOLICITADO*

💰 *Monto:* ${amount:.2f} CUP
💸 *Fee:* ${user_state['fee']:.2f} CUP
💰 *Neto:* ${net_amount:.2f} CUP
🏦 *Tarjeta:* {card_number}
🆔 *Transacción:* `{transaction_id}`

⏳ *Esperando aprobación...*"""

    bot.send_message(message.chat.id, confirmation_text, parse_mode='Markdown', reply_markup=main_menu())
    del user_states[user_id]

# FUNCIONES DE CONSULTA
def show_money_menu(call):
    user_info = get_user_info(call.from_user.id)

    money_text = f"""
💰 *GESTIÓN DE DINERO*

💵 *Saldo:* ${user_info[3]:.2f} CUP

💳 *Opciones disponibles:*
• Depositar fondos
• Retirar ganancias
• Consultar saldo"""

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=money_text,
        parse_mode='Markdown',
        reply_markup=money_menu()
    )

def show_balance(call):
    user_info = get_user_info(call.from_user.id)

    balance_text = f"""
💰 *SALDO ACTUAL*

👤 {escape_markdown(user_info[2])}
💵 ${user_info[3]:.2f} CUP

💳 *Wallet:* `{user_info[4]}`"""

    markup = types.InlineKeyboardMarkup()
    btn_back = types.InlineKeyboardButton("🔙 Volver", callback_data="money_menu")
    markup.add(btn_back)

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=balance_text,
        parse_mode='Markdown',
        reply_markup=markup
    )

def show_profile_info(call):
    user_info = get_user_info(call.from_user.id)

    total_bets = user_info[6] or 0
    bets_won = user_info[7] or 0
    success_rate = (bets_won / total_bets * 100) if total_bets > 0 else 0

    profile_text = f"""
👤 *PERFIL*

📊 *Información:*
• Nombre: {escape_markdown(user_info[2])}
• Wallet: `{user_info[4]}`
• Registrado: {user_info[5]}

🎯 *Estadísticas:*
• Apuestas: {total_bets}
• Ganadas: {bets_won}
• Tasa: {success_rate:.1f}%

💰 *Saldo:* ${user_info[3]:.2f} CUP"""

    markup = types.InlineKeyboardMarkup()
    btn_back = types.InlineKeyboardButton("🔙 Volver", callback_data="back_to_main")
    markup.add(btn_back)

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=profile_text,
        parse_mode='Markdown',
        reply_markup=markup
    )

# COMANDO DE RECARGA PARA ADMIN
@bot.message_handler(commands=['recargar'])
def recharge_balance(message):
    user_id = message.from_user.id

    if user_id != ADMIN_ID:
        bot.reply_to(message, "❌ *Solo administradores*", parse_mode='Markdown')
        return

    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "❌ Uso: /recargar WALLET MONTO", parse_mode='Markdown')
        return

    wallet_address = parts[1]
    try:
        amount = float(parts[2])
    except ValueError:
        bot.reply_to(message, "❌ *Monto inválido*", parse_mode='Markdown')
        return

    conn = sqlite3.connect('cubabet.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE wallet_address = ?', (wallet_address,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        bot.reply_to(message, f"❌ *Wallet no encontrada*", parse_mode='Markdown')
        return

    old_balance = user[3]
    update_balance(user[0], amount)
    new_balance = old_balance + amount

    notification_text = f"💰 *RECARGA MANUAL*\n\nUsuario: {escape_markdown(user[2])}\nMonto: ${amount:.2f} CUP\nNuevo saldo: ${new_balance:.2f} CUP"
    send_group_notification(notification_text)

    try:
        user_notification = f"💳 *RECARGA APROBADA*\n\nMonto: ${amount:.2f} CUP\nNuevo saldo: ${new_balance:.2f} CUP"
        bot.send_message(user[0], user_notification, parse_mode='Markdown')
    except:
        pass

    bot.reply_to(message, f"✅ *Recarga exitosa*\nNuevo saldo: ${new_balance:.2f} CUP", parse_mode='Markdown')

# SISTEMA DE POLLING ROBUSTO
def run_bot():
    """Función robusta para ejecutar el bot con manejo de errores"""
    logger.info("🎯 Iniciando CubaBet...")
    init_db()
    cache_sports_data()
    logger.info("✅ Sistema listo")
    
    while True:
        try:
            logger.info("🔄 Iniciando polling...")
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"❌ Error en polling: {e}")
            logger.info("🔄 Reiniciando en 10 segundos...")
            time.sleep(10)

# INICIALIZACIÓN
if __name__ == "__main__":
    run_bot()
