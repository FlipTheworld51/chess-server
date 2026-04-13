import asyncio
import json
import uuid
import time
import re
from aiohttp import web
import aiohttp

BAD_WORDS = [
    # English
    'fuck', 'shit', 'ass', 'bitch', 'cock', 'dick', 'pussy', 'nigger', 'nigga',
    'faggot', 'retard', 'cunt', 'whore', 'slut', 'bastard', 'piss',
    'wank', 'twat', 'prick', 'arsehole', 'asshole', 'bollocks', 'bugger',
    # Spanish
    'puta', 'mierda', 'cono', 'joder', 'cabron', 'pendejo', 'chinga', 'culero',
    'marica', 'maricon', 'verga', 'culo', 'gilipollas', 'hostia',
    # French
    'merde', 'putain', 'connard', 'salope', 'batard', 'enculer', 'branleur',
    'fdp', 'niquer', 'nique',
    # German
    'scheisse', 'ficken', 'hurensohn', 'arschloch', 'wichser',
    'fotze', 'schlampe', 'mistkerl',
    # Polish
    'kurwa', 'chuj', 'pierdol', 'skurwysyn', 'jebac', 'dupek', 'cipa', 'pizda',
    # Portuguese
    'merda', 'porra', 'caralho', 'buceta', 'foder', 'cuzao', 'viado',
    # Russian (transliterated)
    'blyad', 'pizda', 'ebat', 'suka', 'huy', 'pidor', 'mudak', 'blyat',
    'cyka', 'zalupa', 'dolboyob',
    # Italian
    'cazzo', 'vaffanculo', 'stronzo', 'minchia', 'troia', 'porcodio',
    # Dutch
    'godverdomme', 'klootzak', 'eikel', 'kut', 'lul', 'hoer', 'kanker', 'fikker',
    # Turkish
    'orospu', 'siktir', 'amk', 'piç', 'ibne',
    # Arabic (transliterated)
    'kuss', 'sharmouta', 'kahba', 'zebi', 'ayri', 'niik',
    # Hindi (transliterated)
    'chutiya', 'madarchod', 'bhenchod', 'bhosdike', 'randi', 'gaandu', 'harami',
    # Japanese (transliterated)
    'kuso', 'kisama',
    # Chinese (transliterated)
    'caoni', 'shabi', 'wocao', 'tamade', 'ridan',
    # Swedish
    'fitta', 'kuk', 'hora', 'knulla', 'helvete',
    # Norwegian
    'faen', 'fittefaen', 'dritt',
    # Danish
    'fanden', 'lort', 'roevhul', 'kaelling',
    # Icelandic
    'fokk', 'rassgat', 'drullan', 'pika', 'typpi', 'helviti',
    # Greek (transliterated)
    'malaka', 'gamoto', 'poustis', 'arxidia',
    # Hungarian
    'kurva', 'fasz', 'bazdmeg', 'geci',
    # Czech/Slovak
    'picovina', 'jebat', 'hovno', 'vykurvat',
    # Romanian
    'pula', 'muie', 'futut', 'cacat', 'curva',
]

def is_clean(name):
    lower = name.lower()
    stripped = re.sub(r'[\s\W_]', '', lower)
    leet = lower.replace('0','o').replace('1','i').replace('3','e').replace('4','a').replace('5','s').replace('@','a').replace('$','s').replace('!','i').replace('7','t')
    leet_stripped = re.sub(r'[\s\W_]', '', leet)

    for word in BAD_WORDS:
        if word in lower: return False, 'Username contains inappropriate language'
        if word in stripped: return False, 'Username contains inappropriate language'
        if word in leet: return False, 'Username contains inappropriate language'
        if word in leet_stripped: return False, 'Username contains inappropriate language'

    if re.search(r'\d{7,}', name): return False, 'Username cannot contain phone numbers'
    if re.search(r'@\w+\.\w+', name): return False, 'Username cannot contain email addresses'
    if re.search(r'http|www\.|\.(com|net|org|io)', lower): return False, 'Username cannot contain URLs'
    if re.match(r'^[\d\W]+$', name): return False, 'Username must contain letters'
    if len(name.strip()) < 2: return False, 'Username too short'
    return True, ''

rooms = {}
players = {}

def make_room(host_name, host_ws):
    rid = str(uuid.uuid4())[:8]
    rooms[rid] = {
        'id': rid, 'host': host_name, 'host_ws': host_ws,
        'guest': None, 'guest_ws': None, 'state': 'waiting',
        'moves': [], 'created': time.time(),
    }
    return rid

async def broadcast_lobby():
    lobby_list = []
    for rid, room in rooms.items():
        if room['state'] == 'waiting':
            lobby_list.append({'id': rid, 'host': room['host']})
    msg = json.dumps({'type': 'lobby', 'rooms': lobby_list})
    for ws, p in list(players.items()):
        if p.get('state') == 'lobby':
            try: await ws.send_str(msg)
            except: pass

async def handle_ws(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    players[ws] = {'state': 'lobby', 'name': 'Anonymous', 'room': None}
    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                await handle_message(ws, data)
            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                break
    finally:
        await on_disconnect(ws)
    return ws

async def handle_message(ws, data):
    t = data.get('type')
    player = players.get(ws, {})

    if t == 'join_lobby':
        name = data.get('name', 'Anonymous')[:20].strip()
        clean, reason = is_clean(name)
        if not clean:
            await ws.send_str(json.dumps({'type': 'error', 'msg': f'Username not allowed: {reason}'}))
            return
        player['name'] = name
        player['state'] = 'lobby'
        await broadcast_lobby()

    elif t == 'create_room':
        rid = make_room(player['name'], ws)
        player['state'] = 'waiting'
        player['room'] = rid
        await ws.send_str(json.dumps({'type': 'room_created', 'room_id': rid}))
        await broadcast_lobby()

    elif t == 'join_room':
        rid = data.get('room_id')
        room = rooms.get(rid)
        if not room or room['state'] != 'waiting':
            await ws.send_str(json.dumps({'type': 'error', 'msg': 'Room not available'}))
            return
        room['guest'] = player['name']
        room['guest_ws'] = ws
        room['state'] = 'playing'
        player['state'] = 'playing'
        player['room'] = rid
        host_ws = room['host_ws']
        players[host_ws]['state'] = 'playing'
        start_msg = json.dumps({
            'type': 'game_start', 'room_id': rid,
            'white': room['host'], 'black': room['guest'],
        })
        await host_ws.send_str(start_msg)
        await ws.send_str(start_msg)
        await broadcast_lobby()

    elif t == 'move':
        rid = player.get('room')
        room = rooms.get(rid)
        if not room or room['state'] != 'playing': return
        move_uci = data.get('move')
        room['moves'].append(move_uci)
        host_ws = room['host_ws']
        guest_ws = room['guest_ws']
        opponent_ws = guest_ws if ws == host_ws else host_ws
        try: await opponent_ws.send_str(json.dumps({'type': 'move', 'move': move_uci}))
        except: pass

    elif t == 'game_over':
        rid = player.get('room')
        room = rooms.get(rid)
        if room:
            room['state'] = 'done'
            await broadcast_lobby()

    elif t == 'leave_room':
        await on_disconnect(ws, leaving_only=True)
        player['state'] = 'lobby'
        player['room'] = None
        await broadcast_lobby()

async def on_disconnect(ws, leaving_only=False):
    player = players.get(ws, {})
    rid = player.get('room')
    if rid and rid in rooms:
        room = rooms[rid]
        host_ws = room['host_ws']
        guest_ws = room['guest_ws']
        opponent_ws = guest_ws if ws == host_ws else host_ws
        if opponent_ws and opponent_ws in players:
            try: await opponent_ws.send_str(json.dumps({'type': 'opponent_left'}))
            except: pass
            players[opponent_ws]['state'] = 'lobby'
            players[opponent_ws]['room'] = None
        del rooms[rid]
    if not leaving_only and ws in players:
        del players[ws]
    await broadcast_lobby()

app = web.Application()
app.router.add_get('/ws', handle_ws)
app.router.add_get('/', lambda r: web.Response(text='Chess server running'))

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 8765))
    print(f"Server starting on port {port}")
    web.run_app(app, port=port)
    import os
    port = int(os.environ.get('PORT', 8765))
    print(f"Server starting on port {port}")
    web.run_app(app, port=port)
