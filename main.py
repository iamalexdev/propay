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

# Configuración
TOKEN = "7630853977:AAHXJX6fT25RK4nfvibIA6c_za7rfmC41_Y"
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
odds_cache = {}

# Configuración optimizada para la API
API_CONFIG = {
    'base_url': 'https://api.the-odds-api.com/v4',
    'regions': 'us',
    'markets': 'h2h,spreads,totals',
    'odds_format': 'decimal',
    'date_format': 'iso'
}

# Mapeo de competiciones principales
MAIN_COMPETITIONS = {
    'soccer': [
        {'key': 'soccer_epl', 'name': 'Premier League - Inglaterra'},
        {'key': 'soccer_uefa_champs_league', 'name': 'Champions League'},
        {'key': 'soccer_uefa_europa_league', 'name': 'Europa League'},
        {'key': 'soccer_spain_la_liga', 'name': 'La Liga - España'},
        {'key': 'soccer_italy_serie_a', 'name': 'Serie A - Italia'},
        {'key': 'soccer_france_ligue_one', 'name': 'Ligue 1 - Francia'},
        {'key': 'soccer_germany_bundesliga', 'name': 'Bundesliga - Alemania'},
        {'key': 'soccer_usa_mls', 'name': 'MLS - USA'},
    ],
    'basketball': [
        {'key': 'basketball_nba', 'name': 'NBA'},
        {'key': 'basketball_euroleague', 'name': 'Euroleague'},
    ],
    'american_football': [
        {'key': 'americanfootball_nfl', 'name': 'NFL'},
    ],
    'baseball': [
        {'key': 'baseball_mlb', 'name': 'MLB'},
    ],
    'ice_hockey': [
        {'key': 'icehockey_nhl', 'name': 'NHL'},
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

# CLASE ODDS API CORREGIDA - SOLO FANDUEL
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
            print(f"🔍 Haciendo request a: {url}")
            print(f"📋 Parámetros: {params}")
            
            response = self.session.get(url, params=params, timeout=15)

            self.usage_stats['remaining'] = int(response.headers.get('x-requests-remaining', 0))
            self.usage_stats['used'] = int(response.headers.get('x-requests-used', 0))
            self.usage_stats['last_cost'] = int(response.headers.get('x-requests-last', 0))

            if response.status_code == 200:
                data = response.json()
                print(f"✅ Respuesta exitosa, {len(data) if isinstance(data, list) else '1'} eventos recibidos")
                return data
            elif response.status_code == 401:
                print("❌ Error: API Key inválida")
            elif response.status_code == 429:
                print("❌ Error: Límite de requests excedido")
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

        data = self._make_request(endpoint, params) or []
        return self._filter_fanduel_odds(data)

    def _filter_fanduel_odds(self, events_data: List[Dict]) -> List[Dict]:
        """Filtra las odds para obtener solo las de FanDuel"""
        filtered_events = []
        
        for event in events_data:
            filtered_bookmakers = []
            
            for bookmaker in event.get('bookmakers', []):
                if bookmaker.get('key') == 'fanduel':
                    filtered_bookmakers.append(bookmaker)
                    break  # Solo tomamos FanDuel
            
            if filtered_bookmakers:
                event['bookmakers'] = filtered_bookmakers
                filtered_events.append(event)
        
        print(f"📊 Eventos con FanDuel: {len(filtered_events)}")
        return filtered_events

    def get_usage_stats(self) -> Dict:
        return self.usage_stats

# Instancia global de la API
odds_api = OddsAPI(ODDS_API_KEY)

# SISTEMA DE CACHÉ MEJORADO
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
                {"key": "soccer_uefa_europa_league", "group": "Soccer", "title": "UEFA Europa League", "active": True},
                {"key": "icehockey_nhl", "group": "Ice Hockey", "title": "NHL", "active": True},
            ]

        sports_cache['data'] = sports
        sports_cache['last_updated'] = datetime.now()

        print(f"✅ Caché de deportes actualizado: {len(sports)} deportes")
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
                'soccer_uefa_europa_league': '⚽ Europa League',
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
    }

    return competition_mapping.get(sport_group, [])

# FUNCIÓN PRINCIPAL CORREGIDA - OBTIENE ODDS REALES DE FANDUEL
def get_sport_events(sport_key: str) -> List[Dict]:
    cache_key = f"{sport_key}_events"

    if cache_key in events_cache:
        cache_age = datetime.now() - events_cache[cache_key]['last_updated']
        if cache_age.total_seconds() < 300:  # 5 minutos de cache
            return events_cache[cache_key]['data']

    try:
        print(f"🔍 Obteniendo eventos para: {sport_key}")
        
        # Obtener odds reales de la API - SOLO FANDUEL
        events_with_odds = odds_api.get_odds(sport_key)
        
        print(f"📊 Eventos recibidos de API: {len(events_with_odds)}")

        if events_with_odds:
            processed_events = []
            for event in events_with_odds[:10]:  # Máximo 10 eventos
                if event.get('bookmakers') and len(event['bookmakers']) > 0:
                    # Procesar FANDUEL específicamente
                    fanduel_bookmaker = None
                    for bookmaker in event['bookmakers']:
                        if bookmaker.get('key') == 'fanduel':
                            fanduel_bookmaker = bookmaker
                            break
                    
                    if not fanduel_bookmaker:
                        continue  # Saltar si no hay FanDuel
                    
                    # Procesar mercados de FanDuel
                    markets_data = {}
                    
                    for market in fanduel_bookmaker.get('markets', []):
                        market_key = market['key']
                        outcomes = []
                        
                        for outcome in market.get('outcomes', []):
                            outcomes.append({
                                'name': outcome['name'],
                                'price': outcome.get('price', 0),
                                'point': outcome.get('point')
                            })
                        
                        markets_data[market_key] = {
                            'outcomes': outcomes,
                            'last_update': market.get('last_update', '')
                        }
                    
                    # Formatear fecha
                    commence_time = event.get('commence_time', '')
                    if commence_time:
                        try:
                            dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                            commence_time = dt.strftime('%Y-%m-%d %H:%M:%S')
                        except:
                            pass

                    processed_event = {
                        'id': event.get('id', str(uuid.uuid4())),
                        'sport_key': event.get('sport_key', sport_key),
                        'sport_title': event.get('sport_title', ''),
                        'home_team': event.get('home_team', 'Equipo Local'),
                        'away_team': event.get('away_team', 'Equipo Visitante'),
                        'commence_time': commence_time,
                        'bookmakers': [fanduel_bookmaker],
                        'markets': markets_data,
                        'source': 'api'
                    }
                    processed_events.append(processed_event)
                    print(f"✅ Evento procesado: {processed_event['home_team']} vs {processed_event['away_team']}")

            if processed_events:
                events_cache[cache_key] = {
                    'data': processed_events,
                    'last_updated': datetime.now()
                }
                print(f"🎯 {len(processed_events)} eventos procesados correctamente")
                return processed_events

        # Si no hay datos de API, usar datos de muestra
        print("⚠️ Usando datos de muestra")
        return generate_sample_events(sport_key)

    except Exception as e:
        print(f"❌ Error obteniendo eventos para {sport_key}: {e}")
        return generate_sample_events(sport_key)

def generate_sample_events(sport_key: str) -> List[Dict]:
    """Genera eventos de muestra cuando la API no responde"""
    sample_events = []

    sample_data = {
        'soccer_uefa_europa_league': [
            {
                'id': 'sample_uel_1',
                'home': 'Basel', 
                'away': 'FCSB',
                'sport_title': 'UEFA Europa League',
                'commence_time': (datetime.now() + timedelta(days=5, hours=18)).strftime('%Y-%m-%d %H:%M:%S'),
                'h2h': [
                    {'name': 'Basel', 'price': 1.57},
                    {'name': 'Draw', 'price': 4.24},
                    {'name': 'FCSB', 'price': 5.55}
                ],
                'spreads': [
                    {'name': 'Basel', 'price': 1.90, 'point': -1.5},
                    {'name': 'FCSB', 'price': 1.90, 'point': 1.5}
                ],
                'totals': [
                    {'name': 'Over', 'price': 1.85, 'point': 2.5},
                    {'name': 'Under', 'price': 1.95, 'point': 2.5}
                ]
            }
        ],
        'soccer_epl': [
            {
                'id': 'sample_epl_1',
                'home': 'Arsenal',
                'away': 'Chelsea',
                'sport_title': 'Premier League',
                'commence_time': (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S'),
                'h2h': [
                    {'name': 'Arsenal', 'price': 1.80},
                    {'name': 'Draw', 'price': 3.60},
                    {'name': 'Chelsea', 'price': 4.50}
                ]
            }
        ]
    }

    events = sample_data.get(sport_key, [])
    
    for match in events:
        markets_data = {}
        
        if 'h2h' in match:
            markets_data['h2h'] = {'outcomes': match['h2h'], 'last_update': datetime.now().isoformat()}
        if 'spreads' in match:
            markets_data['spreads'] = {'outcomes': match['spreads'], 'last_update': datetime.now().isoformat()}
        if 'totals' in match:
            markets_data['totals'] = {'outcomes': match['totals'], 'last_update': datetime.now().isoformat()}

        sample_events.append({
            'id': match['id'],
            'sport_key': sport_key,
            'sport_title': match.get('sport_title', sport_key),
            'home_team': match['home'],
            'away_team': match['away'],
            'commence_time': match['commence_time'],
            'bookmakers': [{'key': 'fanduel', 'title': 'FanDuel', 'markets': []}],
            'markets': markets_data,
            'source': 'sample'
        })

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
    if dt is None:
        dt = datetime.now()
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def send_group_notification(message: str, photo_id: str = None) -> bool:
    try:
        if photo_id:
            bot.send_photo(GROUP_CHAT_ID, photo=photo_id, caption=message, parse_mode='Markdown')
        else:
            bot.send_message(GROUP_CHAT_ID, text=message, parse_mode='Markdown')
        return True
    except Exception as e:
        print(f"❌ Error enviando notificación: {e}")
        return False

# SISTEMA DE USUARIOS
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

# SISTEMA DE TRANSACCIONES
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
    transaction_id = f"DEP{uuid.uuid4().hex[:8].upper()}"
    log_transaction(transaction_id, user_id, amount, 'deposit', method, 'pending')
    pending_deposits[user_id] = {
        'transaction_id': transaction_id,
        'amount': amount,
        'method': method
    }
    return transaction_id

def process_withdrawal(user_id: int, amount: float, card_number: str):
    transaction_id = f"WDL{uuid.uuid4().hex[:8].upper()}"
    fee = amount * 0.06
    net_amount = amount - fee

    log_transaction(transaction_id, user_id, amount, 'withdrawal', 'card', 'pending')
    update_balance(user_id, -amount)

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

# SISTEMA DE APUESTAS
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
        bet_data['odds'], bet_data['amount'], bet_data['potential_win'], 'pending'
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

    ticket_message = f"""
🎫 *TICKET DE APUESTA REGISTRADO*

👤 *Usuario:* {escape_markdown(user_info[2])}
📊 *Evento:* {escape_markdown(bet_data['event_name'])}
🎯 *Selección:* {escape_markdown(bet_data['outcome_name'])}
💰 *Monto:* ${bet_data['amount']:.2f} CUP
🏆 *Potencial:* ${bet_data['potential_win']:.2f} CUP
🆔 *Ticket:* `{bet_id}`
🕒 *Fecha:* {format_time()}

⚡ *¡Buena suerte!* 🍀"""

    send_group_notification(ticket_message)

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
            show_event_markets(call, event_data)
        elif call.data.startswith("market_"):
            market_data = call.data.replace("market_", "")
            process_market_selection(call, market_data)
        elif call.data.startswith("bet_"):
            bet_data = call.data.replace("bet_", "")
            process_bet_placement(call, bet_data)
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

📈 *Odds en tiempo real*"""

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

🕒 *Eventos próximos disponibles*"""

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

    events_text = f"🎯 *PRÓXIMOS EVENTOS - {sport_events[0].get('sport_title', competition_key.replace('_', ' ').title())}*\n\n"
    markup = types.InlineKeyboardMarkup()

    for i, event in enumerate(sport_events[:6]):
        home_team = escape_markdown(event.get('home_team', 'Local'))
        away_team = escape_markdown(event.get('away_team', 'Visitante'))
        event_id = event.get('id', '')
        commence_time = event.get('commence_time', '')

        btn = types.InlineKeyboardButton(
            f"{i+1}. {home_team} vs {away_team}",
            callback_data=f"event_{competition_key}_{event_id}"
        )
        markup.add(btn)

        events_text += f"*{i+1}. {home_team} vs {away_team}*\n"
        if commence_time:
            events_text += f"   🕒 {commence_time}\n"
        events_text += "\n"

    btn_back = types.InlineKeyboardButton("🔙 Volver", callback_data="sports_betting")
    markup.add(btn_back)

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=events_text,
        parse_mode='Markdown',
        reply_markup=markup
    )

def show_event_markets(call, event_data: str):
    parts = event_data.split('_')
    if len(parts) < 2:
        bot.answer_callback_query(call.id, "❌ Error en datos")
        return

    sport_key = parts[0]
    event_id = '_'.join(parts[1:])

    sport_events = get_sport_events(sport_key)
    current_event = None

    for event in sport_events:
        if event.get('id') == event_id:
            current_event = event
            break

    if not current_event:
        bot.answer_callback_query(call.id, "❌ Evento no encontrado")
        return

    home_team = escape_markdown(current_event.get('home_team', 'Local'))
    away_team = escape_markdown(current_event.get('away_team', 'Visitante'))
    sport_title = escape_markdown(current_event.get('sport_title', ''))
    commence_time = current_event.get('commence_time', '')

    events_text = f"""
🎯 *{sport_title}*

⚽ *{home_team} vs {away_team}*

🕒 *{commence_time}*

💡 *Selecciona un tipo de apuesta:*"""

    markup = types.InlineKeyboardMarkup(row_width=2)

    available_markets = current_event.get('markets', {})
    
    if 'h2h' in available_markets:
        btn_h2h = types.InlineKeyboardButton("🎯 1x2 (Ganador)", callback_data=f"market_{sport_key}_{event_id}_h2h")
        markup.add(btn_h2h)
    
    if 'spreads' in available_markets:
        btn_spreads = types.InlineKeyboardButton("📊 Handicap", callback_data=f"market_{sport_key}_{event_id}_spreads")
        markup.add(btn_spreads)
    
    if 'totals' in available_markets:
        btn_totals = types.InlineKeyboardButton("⚖️ Over/Under", callback_data=f"market_{sport_key}_{event_id}_totals")
        markup.add(btn_totals)

    btn_back = types.InlineKeyboardButton("🔙 Volver", callback_data=f"competition_{sport_key}")
    markup.add(btn_back)

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=events_text,
        parse_mode='Markdown',
        reply_markup=markup
    )

def process_market_selection(call, market_data: str):
    parts = market_data.split('_')
    if len(parts) < 3:
        bot.answer_callback_query(call.id, "❌ Error en datos")
        return

    sport_key = parts[0]
    event_id = '_'.join(parts[1:-1])
    market_key = parts[-1]

    user_id = call.from_user.id
    if not has_minimum_balance(user_id):
        bot.answer_callback_query(
            call.id,
            "❌ Saldo insuficiente. Mínimo: $30.00 CUP",
            show_alert=True
        )
        return

    sport_events = get_sport_events(sport_key)
    current_event = None

    for event in sport_events:
        if event.get('id') == event_id:
            current_event = event
            break

    if not current_event:
        bot.answer_callback_query(call.id, "❌ Evento no encontrado")
        return

    home_team = escape_markdown(current_event.get('home_team', 'Local'))
    away_team = escape_markdown(current_event.get('away_team', 'Visitante'))
    sport_title = escape_markdown(current_event.get('sport_title', ''))

    markets = current_event.get('markets', {})
    selected_market = markets.get(market_key, {})

    if not selected_market:
        bot.answer_callback_query(call.id, "❌ Mercado no disponible")
        return

    outcomes = selected_market.get('outcomes', [])
    
    if not outcomes:
        bot.answer_callback_query(call.id, "❌ No hay cuotas disponibles")
        return

    market_names = {
        'h2h': '1x2 (Ganador)',
        'spreads': 'Handicap Asiático',
        'totals': 'Over/Under'
    }

    market_text = f"""
🎯 *{market_names.get(market_key, market_key.upper())}*

⚽ *{sport_title}*
🏆 *{home_team} vs {away_team}*

💰 *Selecciona una opción:*"""

    markup = types.InlineKeyboardMarkup()

    for outcome in outcomes:
        outcome_name = outcome['name']
        odds = outcome['price']
        point = outcome.get('point')
        
        if market_key == 'h2h':
            if outcome_name == 'Draw':
                btn_text = f"⚖️ Empate ({odds:.2f})"
            else:
                team_display = "🏠 " if outcome_name == home_team else "✈️ "
                btn_text = f"{team_display}{outcome_name} ({odds:.2f})"
        
        elif market_key == 'spreads':
            point_display = f"{point:+.1f}" if point else ""
            btn_text = f"📊 {outcome_name} {point_display} ({odds:.2f})"
        
        elif market_key == 'totals':
            point_display = f"{point}" if point else ""
            over_under = "⬆️ Over" if outcome_name == "Over" else "⬇️ Under"
            btn_text = f"{over_under} {point_display} ({odds:.2f})"
        
        else:
            btn_text = f"{outcome_name} ({odds:.2f})"

        outcome_clean = outcome_name.replace(' ', '_')
        callback_data = f"bet_{sport_key}_{event_id}_{market_key}_{outcome_clean}_{odds}"
        if point:
            callback_data += f"_{point}"

        btn = types.InlineKeyboardButton(btn_text, callback_data=callback_data)
        markup.add(btn)

    btn_back = types.InlineKeyboardButton("🔙 Volver", callback_data=f"event_{sport_key}_{event_id}")
    markup.add(btn_back)

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=market_text,
        parse_mode='Markdown',
        reply_markup=markup
    )

def process_bet_placement(call, bet_data: str):
    parts = bet_data.split('_')
    if len(parts) < 5:
        bot.answer_callback_query(call.id, "❌ Error en datos")
        return

    user_id = call.from_user.id

    if not has_minimum_balance(user_id):
        bot.answer_callback_query(call.id, "❌ Saldo insuficiente", show_alert=True)
        return

    sport_key = parts[0]
    event_id = '_'.join(parts[1:-3])
    market_key = parts[-3]
    outcome_name = parts[-2].replace('_', ' ')
    odds = float(parts[-1])

    sport_events = get_sport_events(sport_key)
    current_event = None

    for event in sport_events:
        if event.get('id') == event_id:
            current_event = event
            break

    if not current_event:
        bot.answer_callback_query(call.id, "❌ Evento no encontrado")
        return

    home_team = current_event.get('home_team', 'Local')
    away_team = current_event.get('away_team', 'Visitante')
    event_name = f"{home_team} vs {away_team}"
    sport_title = current_event.get('sport_title', sport_key.replace('_', ' ').title())

    user_states[user_id] = {
        'action': 'placing_bet',
        'sport_key': sport_key,
        'sport_title': sport_title,
        'event_id': event_id,
        'event_name': event_name,
        'market_key': market_key,
        'outcome_name': outcome_name,
        'odds': odds
    }

    bet_info_text = f"""
🎯 *CONFIRMAR APUESTA*

🏆 *{sport_title}*
⚽ *Evento:* {escape_markdown(event_name)}
🎯 *Selección:* {escape_markdown(outcome_name)}
💰 *Cuota:* {odds:.2f}

💵 *Ingresa el monto a apostar (CUP):*
💰 *Mínimo: $30.00*"""

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=bet_info_text,
        parse_mode='Markdown'
    )

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

        potential_win = amount * user_state['odds']

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
            'odds': user_state['odds'],
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

⚡ *¡Buena suerte!* 🍀"""

        bot.send_message(message.chat.id, confirmation_text, parse_mode='Markdown', reply_markup=main_menu())
        del user_states[user_id]

    except ValueError:
        bot.send_message(message.chat.id, "❌ *Ingresa un número válido*", parse_mode='Markdown')

# SISTEMA DE DEPÓSITOS Y RETIROS (igual que antes)
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

@bot.message_handler(commands=['estadisticas'])
def show_api_stats(message):
    user_id = message.from_user.id
    
    if user_id != ADMIN_ID:
        bot.reply_to(message, "❌ *Solo administradores*", parse_mode='Markdown')
        return

    stats = odds_api.get_usage_stats()
    
    stats_text = f"""
📊 *ESTADÍSTICAS DE LA API*

🔄 *Solicitudes usadas:* {stats['used']}
📈 *Solicitudes restantes:* {stats['remaining']}
💸 *Último costo:* {stats['last_cost']}

💡 *Cache de deportes:* {'✅ Activo' if sports_cache.get('data') else '❌ Inactivo'}
📅 *Actualizado:* {sports_cache.get('last_updated', 'Nunca')}

🔧 *Estado del sistema:* ✅ OPERATIVO"""

    bot.reply_to(message, stats_text, parse_mode='Markdown')

@bot.message_handler(commands=['actualizar'])
def update_cache(message):
    user_id = message.from_user.id
    
    if user_id != ADMIN_ID:
        bot.reply_to(message, "❌ *Solo administradores*", parse_mode='Markdown')
        return

    bot.reply_to(message, "🔄 *Actualizando caché de deportes...*", parse_mode='Markdown')
    
    if cache_sports_data():
        bot.reply_to(message, "✅ *Caché actualizado correctamente*", parse_mode='Markdown')
    else:
        bot.reply_to(message, "❌ *Error actualizando caché*", parse_mode='Markdown')

@bot.message_handler(func=lambda message: True)
def handle_unknown(message):
    if message.text.startswith('/'):
        bot.reply_to(message, "❌ *Comando no reconocido*", parse_mode='Markdown')
    else:
        bot.reply_to(message, "💡 *Usa /start para comenzar*", parse_mode='Markdown')

# INICIALIZACIÓN
if __name__ == "__main__":
    print("🎯 Iniciando CubaBet...")
    print("📦 Inicializando base de datos...")
    init_db()
    print("🔧 Configurando caché de deportes...")
    cache_sports_data()
    print("✅ Sistema listo y operativo")
    print("🤖 Bot iniciado correctamente")
    
    stats = odds_api.get_usage_stats()
    print(f"📊 Estado API: {stats['remaining']} solicitudes restantes")
    
    try:
        bot.polling(none_stop=True, interval=0)
    except Exception as e:
        print(f"❌ Error en el bot: {e}")
        print("🔄 Reiniciando en 5 segundos...")
        time.sleep(5)
