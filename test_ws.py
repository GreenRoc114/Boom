import asyncio
import websockets
import json

async def test_conn():
    uri = "ws://127.0.0.1:18765/controller"
    print(f"Connecting to {uri}...")
    try:
        async with websockets.connect(uri) as ws:
            print("Connected! Sending register message...")
            # We don't have AUTH_TOKEN env set, so it should be CHANGE_THIS_TO_YOUR_SECURE_TOKEN unless config.yaml is present.
            await ws.send(json.dumps({
                "type": "register",
                "client_id": "web_v2_controller",
                "token": "CHANGE_THIS_TO_YOUR_SECURE_TOKEN"
            }))
            print("Register sent, waiting for response...")
            response = await ws.recv()
            print("Response:", response)
    except Exception as e:
        print("Error:", e)

asyncio.run(test_conn())
