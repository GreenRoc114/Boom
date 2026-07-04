# Boom V3.0 - 进阶整蛊与远程控制框架

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template)
![Boom V3.0](https://img.shields.io/badge/version-3.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.7+-green.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

Boom 是一个基于 Python 和 WebSocket 构建的高性能、高安全性的创意控制框架。它允许您通过一个美观的 Web 控制台对目标机器（Windows 系统为主）下发各种视觉和系统级别的“整蛊”指令。

**⚠️ 声明：本项目仅供学习、娱乐与网络安全防御测试之用。请勿用于任何非法或恶意的网络攻击。所有整蛊功能均不含真实破坏性代码。**

---

## ✨ 核心特性

- **🛡️ 军工级安全通信：**
  - **HMAC-SHA256 签名机制**：所有的控制指令均带有 HMAC 签名，受控端拒绝执行任何被篡改或伪造的未签名指令。
  - **白名单与防爆破**：服务端内置控制台 IP 白名单，并包含防穷举爆破锁定制（5次密码错误封禁10分钟）。
- **🚀 稳定与高可用：**
  - **统一配置驱动**：告别硬编码，支持通过 `config.json` 灵活调整。
  - **指数退避重连算法**：受控端网络断开后以 2s -> 4s -> 8s -> ... 120s 的节奏无限静默重连，保证永久在线。
- **🎮 强大的整蛊引擎：**
  - **视觉弹窗系**：无限繁殖报错窗、强迫症终结者（连环弹窗）。
  - **系统伪装系**：逼真的 Windows 升级画面、蓝屏模拟、假勒索锁屏、屏幕故障艺术（Glitch Overlay）。
  - **物理干扰系**：窗口随机跳跃、屏幕 180 度翻转、幽灵打字机。
- **🌐 现代化 Web 控制台：**
  - 全中文操控面板，响应式设计。
  - 指令分类清晰，实时掌控受控端数量和状态。
- **📦 一键傻瓜式打包 (Windows)：**
  - 提供 `.bat` 交互式脚本，自动拉取依赖并将配置写入生成的绿色无依赖单文件 `exe` 中，双击即用（无弹窗静默后台）。

---

## 🛠️ 快速开始

### 1. 启动服务端
将项目克隆到您的服务器（Linux 或 Windows 均可）：
```bash
git clone https://github.com/yourusername/boom-oss.git
cd boom-oss
```
安装依赖：
```bash
pip install websockets
```
运行服务：
```bash
python server.py
```
*(默认监听 `0.0.0.0:18765`，请确保防火墙放行该端口)*

### 2. 打开 Web 控制台
在任意设备上用浏览器打开 `index.html`。
- **连接地址**：`ws://你的服务器IP:18765/controller`
- **连接 Token**：默认为 `CHANGE_THIS_TO_YOUR_SECURE_TOKEN`（请在 `config.json` 中修改）

### 3. 打包并运行受控端 (Windows环境)
在 Windows 电脑上运行根目录下的 `build_client.bat`。
1. 按照提示输入您的服务器 IP 地址和 Token。
2. 脚本会自动使用 `pyinstaller` 编译出单一的 `.exe` 文件（位于 `dist/` 目录下）。
3. 将生成的 `.exe` 放入目标机器并双击运行，Web 控制台将立即收到上线提醒！

---

## ⚙️ 配置说明 (`config.json`)

```json
{
    "server": {
        "host": "0.0.0.0",
        "port": 18765,
        "token": "你的控制面板登录密码",
        "hmac_secret": "指令签名秘钥(服务端与客户端必须一致)",
        "controller_ip_whitelist": ["127.0.0.1", "localhost"], // 控制台白名单
        "ping_interval": 15,
        "ping_timeout": 15
    },
    "client": {
        "server_url": "ws://你的服务器IP:18765/client",
        "token": "受控端连接认证密码",
        "hmac_secret": "指令签名秘钥(服务端与客户端必须一致)",
        "reconnect_min_delay": 2,
        "reconnect_max_delay": 120
    }
}
```

---

## ☁️ 一键部署到 Railway（推荐）

Railway 是一个支持 **WebSocket + 长连接** 的云平台，每月有 $5 免费额度，部署此项目绰绰有余。

### 部署步骤

**第一步：把代码推到 GitHub**
```bash
cd boom-oss
git init
git add .
git commit -m "Boom V3.0 initial release"
git remote add origin https://github.com/你的用户名/boom.git
git push -u origin main
```

**第二步：在 Railway 部署**
1. 访问 [railway.app](https://railway.app) → 用 GitHub 登录
2. 点击 **New Project** → **Deploy from GitHub repo**
3. 选择刚才推送的仓库
4. Railway 自动识别 Python 并读取 `railway.toml`，直接开始构建

**第三步：配置环境变量（关键！）**

进入 Railway 项目 → **Variables** 标签页，添加以下变量：

| 变量名 | 示例值 | 说明 |
|---|---|---|
| `BOOM_AUTH_TOKEN` | `你的超强密码` | 控制台登录密码 |
| `BOOM_HMAC_SECRET` | `你的HMAC密钥` | 指令签名密钥（与客户端一致）|
| `CONTROLLER_WHITELIST` | 留空 | 留空则不限制控制台 IP |

> ⚠️ 不要在 `config.json` 里写真实密码后提交到公开仓库，务必通过环境变量配置！

**第四步：获取公网地址**

部署成功后，进入 **Settings → Networking → Generate Domain**，Railway 会给你一个类似 `boom-xxx.up.railway.app` 的地址。

**第五步：更新客户端配置**

打包 `prank.py` 时，在 `build_client.bat` 里输入：
```
服务端地址：wss://boom-xxx.up.railway.app/client
```
> 注意：Railway 的公网地址使用 **`wss://`**（加密 WebSocket），而不是 `ws://`

---

## 🆘 常见问题 (FAQ)

**1. 客户端运行时为什么看不到界面？**
为了达到“潜伏”效果，客户端打包时使用了 `--noconsole`，双击后仅会在后台驻留进程（可以通过任务管理器找到它）。

**2. 为什么受控端没有响应 Web 控制台下发的指令？**
请重点检查：
- `config.json` 中的 `hmac_secret` 在服务端和被控端是否完全一致？如果不一致，被控端会静默丢弃指令防止被黑客劫持。
- 确认服务端防火墙允许 18765 端口的 TCP 通讯。

**3. 如何关闭正在运行的整蛊效果？**
- 在 Web 控制面板点击对应区域的“关闭/恢复”按钮即可一键复原。
- 被控机器物理快捷键（如果安装了 keyboard 依赖）：连续双击 `Tab` 或回车，或者右下角点击鼠标10次可退出。

---

## 📜 开源协议
MIT License. 自由修改、分发与使用，后果自负。
