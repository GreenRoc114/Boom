#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import platform
import sys
from datetime import datetime
import hmac
import hashlib
import time

try:
    import websockets
except ModuleNotFoundError:
    if any(arg in ("-v", "--version") for arg in sys.argv[1:]):
        websockets = None
    else:
        raise


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load unified configuration
CONFIG_PATH = "config.json"
try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config_data = json.load(f)
except FileNotFoundError:
    config_data = {"server": {}}

HOST = os.environ.get("BOOM_HOST", config_data.get("server", {}).get("host", "0.0.0.0"))
# Railway 会自动注入 PORT 环境变量，优先读取；本地运行则用 BOOM_PORT 或 config.json
PORT = int(os.environ.get("PORT") or os.environ.get("BOOM_PORT") or config_data.get("server", {}).get("port", 18765))
AUTH_TOKEN = os.environ.get("BOOM_AUTH_TOKEN") or config_data.get("server", {}).get("token", "CHANGE_THIS_TO_YOUR_SECURE_TOKEN")
HMAC_SECRET = (os.environ.get("BOOM_HMAC_SECRET") or config_data.get("server", {}).get("hmac_secret", "CHANGE_THIS_TO_YOUR_HMAC_SECRET")).encode()
# 环境变量格式：逗号分隔，例如 "127.0.0.1,::1"
_wl_env = os.environ.get("CONTROLLER_WHITELIST", "")
CONTROLLER_WHITELIST = [ip.strip() for ip in _wl_env.split(",") if ip.strip()] or config_data.get("server", {}).get("controller_ip_whitelist", [])
PING_INTERVAL = config_data.get("server", {}).get("ping_interval", 15)
PING_TIMEOUT = config_data.get("server", {}).get("ping_timeout", 15)

SERVER_VERSION = "3.0.0"
SYSTEMD_SERVICE_NAME = "boom-server"


class ControlServer:
    def __init__(self):
        self.clients = {}
        self.controllers = {}
        self.ws_to_client_id = {}
        self.failed_attempts = {}  # ip -> (count, timestamp)

    def get_remote_ip(self, websocket):
        try:
            headers = getattr(websocket, "request_headers", {})
            forwarded = headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",")[0].strip()
            return websocket.remote_address[0] if websocket.remote_address else "Unknown"
        except Exception:
            return "Unknown"

    def build_client_record(self, websocket, client_id, client_info):
        now = datetime.now().isoformat()
        local_ip = client_info.get("local_ip") or client_info.get("ip") or "Unknown"
        return {
            "websocket": websocket,
            "id": client_id,
            "ip": local_ip,
            "local_ip": local_ip,
            "remote_ip": self.get_remote_ip(websocket),
            "system": client_info.get("system", "Unknown"),
            "platform": client_info.get("platform", "Unknown"),
            "hostname": client_info.get("hostname", "Unknown"),
            "timezone": client_info.get("timezone", "Unknown"),
            "screen": client_info.get("screen", "Unknown"),
            "pid": client_info.get("pid", "Unknown"),
            "python": client_info.get("python", "Unknown"),
            "background": bool(client_info.get("background", False)),
            "stage": client_info.get("stage", 0),
            "client_version": client_info.get("client_version", "Unknown"),
            "connected_at": now,
            "last_seen": now,
        }

    def public_client_info(self, client_id, info):
        return {
            "id": client_id,
            "ip": info.get("ip", "Unknown"),
            "local_ip": info.get("local_ip", "Unknown"),
            "remote_ip": info.get("remote_ip", "Unknown"),
            "system": info.get("system", "Unknown"),
            "platform": info.get("platform", "Unknown"),
            "hostname": info.get("hostname", "Unknown"),
            "timezone": info.get("timezone", "Unknown"),
            "screen": info.get("screen", "Unknown"),
            "pid": info.get("pid", "Unknown"),
            "python": info.get("python", "Unknown"),
            "background": info.get("background", False),
            "stage": info.get("stage", 0),
            "client_version": info.get("client_version", "Unknown"),
            "connected_at": info.get("connected_at", "Unknown"),
            "last_seen": info.get("last_seen", "Unknown"),
        }

    def read_client_info(self, data):
        client_info = data.get("client_info") or {}
        # Keep compatibility with older clients that sent fields at the top level.
        for key in ("system", "timezone", "ip", "local_ip"):
            if data.get(key) is not None:
                client_info[key] = data.get(key)
        return client_info

    async def get_systemd_status(self):
        if platform.system().lower() != "linux":
            return {"available": False, "reason": "systemd status is only checked on Linux"}

        props = [
            "ActiveState",
            "SubState",
            "MainPID",
            "NRestarts",
            "ExecMainStartTimestamp",
            "FragmentPath",
            "LoadState",
        ]
        cmd = ["systemctl", "show", SYSTEMD_SERVICE_NAME, "--no-pager", "--property=" + ",".join(props)]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3)
        except FileNotFoundError:
            return {"available": False, "reason": "systemctl not found"}
        except asyncio.TimeoutError:
            return {"available": False, "reason": "systemctl timed out"}
        except Exception as exc:
            return {"available": False, "reason": str(exc)}

        status = {"available": proc.returncode == 0, "service": SYSTEMD_SERVICE_NAME}
        if stderr:
            status["stderr"] = stderr.decode("utf-8", "replace").strip()
        for line in stdout.decode("utf-8", "replace").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                status[key] = value or "Unknown"
        return status

    async def build_server_status(self):
        try:
            websockets_version = websockets.__version__ if websockets else "Not installed"
        except Exception:
            websockets_version = "Unknown"

        return {
            "type": "server_status",
            "server_version": SERVER_VERSION,
            "service_name": SYSTEMD_SERVICE_NAME,
            "server_time": datetime.now().isoformat(),
            "host": HOST,
            "port": PORT,
            "python": sys.version.split()[0],
            "websockets": websockets_version,
            "platform": platform.platform(),
            "system": platform.system(),
            "clients_online": len(self.clients),
            "controllers_online": len(self.controllers),
            "systemd": await self.get_systemd_status(),
        }

    async def register_client(self, websocket, client_id, token=None, client_info=None):
        if token != AUTH_TOKEN:
            await websocket.send(json.dumps({"type": "error", "message": "Token verification failed"}))
            await websocket.close(1008, "Invalid token")
            return

        client_info = client_info or {}
        self.clients[client_id] = self.build_client_record(websocket, client_id, client_info)
        self.ws_to_client_id[websocket] = client_id

        record = self.clients[client_id]
        logger.info(
            "Client connected: %s (local=%s, remote=%s, system=%s, online=%s)",
            client_id,
            record["local_ip"],
            record["remote_ip"],
            record["system"],
            len(self.clients),
        )
        await websocket.send(
            json.dumps({"type": "welcome", "message": f"Client connected: {client_id}", "authorized": True})
        )
        await self.notify_controllers()

    async def register_controller(self, websocket, client_id, token=None):
        remote_ip = self.get_remote_ip(websocket)
        logger.info("Controller register attempt: client_id=%s, ip=%s", client_id, remote_ip)
        
        # 1. Check Controller IP Whitelist
        if CONTROLLER_WHITELIST and remote_ip not in CONTROLLER_WHITELIST and remote_ip != "Unknown":
            logger.warning("Controller rejected: IP %s not in whitelist", remote_ip)
            await websocket.close(1008, "IP not whitelisted")
            return
            
        # 2. Check Rate Limiting (Brute-force protection)
        now = time.time()
        # Cleanup old attempts
        self.failed_attempts = {ip: (count, t) for ip, (count, t) in self.failed_attempts.items() if now - t < 600}
        
        if remote_ip in self.failed_attempts:
            count, last_time = self.failed_attempts[remote_ip]
            if count >= 5:
                logger.warning("Controller rejected: IP %s is locked out", remote_ip)
                await websocket.close(1008, "Too many failed attempts. Locked out for 10 minutes.")
                return

        if token != AUTH_TOKEN:
            # Register fail, increment counter
            count, _ = self.failed_attempts.get(remote_ip, (0, 0))
            self.failed_attempts[remote_ip] = (count + 1, now)
            try:
                await websocket.send(json.dumps({"type": "error", "message": "Token verification failed"}))
            except Exception:
                pass
            await websocket.close(1008, "Invalid token")
            return

        self.controllers[client_id] = {"websocket": websocket}
        self.ws_to_client_id[websocket] = client_id
        logger.info("Controller connected: %s (controllers=%s)", client_id, len(self.controllers))
        await websocket.send(
            json.dumps({"type": "welcome", "message": f"Controller connected: {client_id}", "authorized": True})
        )
        await self.notify_controllers()

    async def unregister(self, websocket):
        client_id = self.ws_to_client_id.get(websocket)
        if not client_id:
            return

        if client_id in self.clients:
            del self.clients[client_id]
            logger.info("Client disconnected: %s (online=%s)", client_id, len(self.clients))
            await self.notify_controllers()
        elif client_id in self.controllers:
            del self.controllers[client_id]
            logger.info("Controller disconnected: %s", client_id)

        del self.ws_to_client_id[websocket]

    async def notify_controllers(self):
        clients_list = [self.public_client_info(cid, info) for cid, info in self.clients.items()]
        msg = json.dumps({"type": "clients_list", "clients": clients_list})
        logger.info("[notify] clients=%s, controllers=%s", len(clients_list), len(self.controllers))

        for cid_ctrl, ctrl in list(self.controllers.items()):
            try:
                await ctrl["websocket"].send(msg)
            except Exception as exc:
                logger.error("[notify] failed to send to %s: %s", cid_ctrl, exc)

    async def handle_connection(self, websocket, path=None):
        client_id = None
        try:
            try:
                path = path or (websocket.request.path if hasattr(websocket, "request") and websocket.request else websocket.path)
            except Exception:
                path = "/"
            logger.info("New connection: %s", path)

            async for message in websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type == "register":
                        client_id = data.get("client_id", "unknown")
                        token = data.get("token")
                        is_controller = client_id.startswith("controller_") or client_id.startswith("web_")
                        if is_controller:
                            await self.register_controller(websocket, client_id, token)
                        else:
                            await self.register_client(websocket, client_id, token, self.read_client_info(data))
                    elif msg_type == "heartbeat":
                        client_id = self.ws_to_client_id.get(websocket, client_id)
                        if client_id in self.clients:
                            self.clients[client_id]["last_seen"] = datetime.now().isoformat()
                            for key in ("stage", "screen", "background"):
                                if data.get(key) is not None:
                                    self.clients[client_id][key] = data.get(key)
                    elif msg_type == "list_clients":
                        await self.notify_controllers()
                    elif msg_type == "server_status":
                        await websocket.send(json.dumps(await self.build_server_status()))
                    elif msg_type == "control":
                        command = data.get("command")
                        target_client = data.get("target_client")
                        config = data.get("config")
                        
                        payload_dict = {
                            "type": "control",
                            "command": command,
                            "config": config,
                            "timestamp": datetime.now().isoformat(),
                        }
                        
                        # Generate HMAC signature
                        payload_str = json.dumps(payload_dict, sort_keys=True)
                        signature = hmac.new(HMAC_SECRET, payload_str.encode(), hashlib.sha256).hexdigest()
                        payload_dict["signature"] = signature
                        
                        payload = json.dumps(payload_dict)
                        
                        if target_client:
                            if target_client in self.clients:
                                await self.clients[target_client]["websocket"].send(payload)
                                logger.info("Command sent to %s", target_client)
                            else:
                                logger.warning("Client %s is not online", target_client)
                        else:
                            for cid in list(self.clients.keys()):
                                try:
                                    await self.clients[cid]["websocket"].send(payload)
                                except Exception:
                                    pass
                    elif msg_type == "ping":
                        await websocket.send(json.dumps({"type": "pong", "timestamp": datetime.now().isoformat()}))
                except json.JSONDecodeError:
                    logger.error("Invalid JSON: %s", message)
                except Exception as exc:
                    logger.error("Message handling error: %s", exc)
        except websockets.exceptions.ConnectionClosed:
            logger.info("Connection closed: %s", client_id)
        finally:
            if client_id or websocket in self.ws_to_client_id:
                await self.unregister(websocket)

    async def process_http_request(self, *args, **kwargs):
        # Compatible with both old (path, headers) and new (connection, request) websockets API signatures.
        path_str = ""
        connection = None
        if len(args) >= 2:
            arg0, arg1 = args[0], args[1]
            if isinstance(arg0, str):
                path_str = arg0
            else:
                connection = arg0
                path_str = getattr(arg1, "path", "")
        elif len(args) == 1:
            arg0 = args[0]
            if isinstance(arg0, str):
                path_str = arg0
            else:
                connection = arg0
                path_str = getattr(arg0, "path", "")
        else:
            path_str = kwargs.get("path", "")
            if not path_str and "request" in kwargs:
                path_str = getattr(kwargs["request"], "path", "")

        clean_path = path_str.split("?")[0] if path_str else "/"
        
        if clean_path in ("/", "/index.html"):
            try:
                if getattr(sys, "frozen", False):
                    base_path = sys._MEIPASS
                else:
                    base_path = os.path.dirname(os.path.abspath(__file__))
                html_path = os.path.join(base_path, "index.html")
                with open(html_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                logger.error("Failed to serve index.html: %s", e)
                if connection and hasattr(connection, "respond"):
                    resp = connection.respond(500, f"Internal Server Error: {e}")
                    if "Content-Type" in resp.headers:
                        del resp.headers["Content-Type"]
                    resp.headers["Content-Type"] = "text/plain; charset=utf-8"
                    return resp
                else:
                    headers = [("Content-Type", "text/plain; charset=utf-8")]
                    return 500, headers, f"Internal Server Error: {e}".encode("utf-8")

            if connection and hasattr(connection, "respond"):
                resp = connection.respond(200, content)
                if "Content-Type" in resp.headers:
                    del resp.headers["Content-Type"]
                resp.headers["Content-Type"] = "text/html; charset=utf-8"
                resp.headers["Access-Control-Allow-Origin"] = "*"
                return resp
            else:
                headers = [
                    ("Content-Type", "text/html; charset=utf-8"),
                    ("Access-Control-Allow-Origin", "*"),
                ]
                return 200, headers, content.encode("utf-8")

        if clean_path not in ("/client", "/controller"):
            if connection and hasattr(connection, "respond"):
                resp = connection.respond(404, "Not Found")
                if "Content-Type" in resp.headers:
                    del resp.headers["Content-Type"]
                resp.headers["Content-Type"] = "text/plain; charset=utf-8"
                return resp
            else:
                headers = [("Content-Type", "text/plain; charset=utf-8")]
                return 404, headers, b"Not Found"
                
        return None

    async def run(self):
        async with websockets.serve(
            self.handle_connection,
            HOST,
            PORT,
            ping_interval=PING_INTERVAL,
            ping_timeout=PING_TIMEOUT,
            origins=None,
            process_request=self.process_http_request,
        ):
            logger.info("=" * 40)
            logger.info("Boom V3.0 Server Started")
            logger.info("Listening: ws://%s:%s", HOST, PORT)
            logger.info("=" * 40)
            await asyncio.Future()


def print_version():
    print(f"boom-server {SERVER_VERSION}")


if __name__ == "__main__":
    if any(arg in ("-v", "--version") for arg in sys.argv[1:]):
        print_version()
        sys.exit(0)

    try:
        asyncio.run(ControlServer().run())
    except KeyboardInterrupt:
        print("\nServer stopped")
