import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn

app = FastAPI()

class ConnectionManager:
    def __init__(self):
        self.clients_rgb: list[WebSocket] = []
        self.clients_depth: list[WebSocket] = []
        self.control_clients: list[WebSocket] = []
        self.clients_info: list[WebSocket] = []

    async def connect_drone_rgb(self, websocket: WebSocket):
        await websocket.accept()
        self.clients_rgb.append(websocket)

    async def connect_drone_depth(self, websocket: WebSocket):
        await websocket.accept()
        self.clients_depth.append(websocket)

    async def connect_control_client(self, websocket: WebSocket):
        await websocket.accept()
        self.control_clients.append(websocket)
    
    async def connect_drone_info(self, websocket: WebSocket):
        await websocket.accept()
        self.clients_info.append(websocket)

    def disconnect_client_rgb(self, websocket: WebSocket):
        self.clients_rgb.remove(websocket)

    def disconnect_client_depth(self, websocket: WebSocket):
        self.clients_depth.remove(websocket)

    def disconnect_control_client(self, websocket: WebSocket):
        self.control_clients.remove(websocket)

    def disconnect_client_info(self, websocket: WebSocket):
        self.clients_info.remove(websocket)

    async def broadcast_rgb(self, data: bytes):
        for ws in self.clients_rgb:
            try:
                await ws.send_bytes(data)
            except:
                self.clients_rgb.remove(ws)

    async def broadcast_depth(self, data: bytes):
        for ws in self.clients_depth:
            try:
                await ws.send_bytes(data)
            except:
                self.clients_depth.remove(ws)

    async def broadcast_control(self, message: str):
        for ws in self.control_clients:
            try:
                await ws.send_text(message)
            except:
                self.control_clients.remove(ws)

    async def broadcast_info(self, data: str):
        for ws in self.clients_info:
            try:
                await ws.send_text(data)
            except:
                self.clients_info.remove(ws)

manager = ConnectionManager()

@app.websocket("/ws/rgb_feed")
async def rgb_feed(websocket: WebSocket):
    await manager.connect_drone_rgb(websocket)
    print("RGB feed connected")
    try:
        while True:
            data = await websocket.receive_bytes()
            await manager.broadcast_rgb(data)
    except WebSocketDisconnect:
        manager.disconnect_client_rgb(websocket) 
        print("RGB feed disconnected")

@app.websocket("/ws/depth_feed")
async def depth_feed(websocket: WebSocket):
    await manager.connect_drone_depth(websocket)
    print("Depth feed connected")
    try:
        while True:
            data = await websocket.receive_bytes()
            await manager.broadcast_depth(data)
    except WebSocketDisconnect:
        manager.disconnect_client_depth(websocket)
        print("Depth feed disconnected")

@app.websocket("/ws/control")
async def control(websocket: WebSocket):
    await manager.connect_control_client(websocket)
    print("Control client connected")
    try:
        while True:
            message = await websocket.receive_text()
            await manager.broadcast_control(message)
    except WebSocketDisconnect:
        manager.disconnect_control_client(websocket)
        print("Control client disconnected")

@app.websocket("/ws/drone_info")
async def drone_info(websocket: WebSocket):
    await manager.connect_drone_info(websocket)
    print("Drone info client connected")
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast_info(data)
    except WebSocketDisconnect:
        manager.disconnect_client_info(websocket)
        print("Drone info client disconnected")


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        ws_ping_interval=None,
        ws_ping_timeout=None  
    )