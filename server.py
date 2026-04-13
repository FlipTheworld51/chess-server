import asyncio
import json
import uuid
import time
from aiohttp import web
import aiohttp

BAD_WORDS = ['fuck', 'shit', 'ass', 'bitch', 'cock', 'dick', 'pussy', 'nigger', 'nigga', 'faggot', 'retard', 'cunt', 'whore', 'slut']

def is_clean(name):
    lower = name.lower()
    for word in BAD_WORDS:
        if word in lower:
            return False
    return True

rooms = {}
players = {}

def make_room(host_name, host_ws):
    rid = str(uuid.uuid4())[:8]
    rooms[rid] = {
        'id': rid,
        'host': host_name,
        'host_ws': host_ws,
        'guest': None,
        'guest_ws': None,
        'state': 'waiting',
        'moves': [],
        'created': time.time(),
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
            try:
                await ws.send_str(msg)
            except:
                pass

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
        if not is_clean(name):
            await ws.send_str(json.dumps({'type': 'error', 'msg': 'Username not allowed — please choose another'}))
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
            'type': 'game_start',
            'room_id': rid,
            'white': room['host'],
            'black': room['guest'],
        })
        await host_ws.send_str(start_msg)
        await ws.send_str(start_msg)
        await broadcast_lobby()

    elif t == 'move':
        rid = player.get('room')
        room = rooms.get(rid)
        if not room or room['state'] != 'playing':
            return
        move_uci = data.get('move')
        room['moves'].append(move_uci)
        host_ws = room['host_ws']
        guest_ws = room['guest_ws']
        opponent_ws = guest_ws if ws == host_ws else host_ws
        try:
            await opponent_ws.send_str(json.dumps({'type': 'move', 'move': move_uci}))
        except:
            pass

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
            try:
                await opponent_ws.send_str(json.dumps({'type': 'opponent_left'}))
            except:
                pass
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
