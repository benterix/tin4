#!/usr/bin/env python3
"""
Demo TCP Client — connects to the TIN4 TCP presence server.

Usage:
    python client.py --host 37.27.16.14.nip.io --port 9000 --token <jwt>

The client sends a heartbeat every 10 seconds and prints the server response.
Press Ctrl+C to disconnect gracefully.
"""
import argparse
import asyncio
import json
import sys


async def run(host: str, port: int, token: str):
    print(f"Connecting to TCP server at {host}:{port} …")
    reader, writer = await asyncio.open_connection(host, port)
    print("Connected!")

    async def heartbeat_loop():
        while True:
            payload = json.dumps({"action": "heartbeat", "token": token}) + "\n"
            writer.write(payload.encode())
            await writer.drain()

            response_raw = await reader.readline()
            response = json.loads(response_raw.decode().strip())
            print(f"[Server] {response}")
            await asyncio.sleep(10)

    try:
        await heartbeat_loop()
    except (asyncio.CancelledError, KeyboardInterrupt):
        print("\nDisconnecting …")
        disconnect_msg = json.dumps({"action": "disconnect"}) + "\n"
        writer.write(disconnect_msg.encode())
        await writer.drain()
        bye_raw = await reader.readline()
        bye = json.loads(bye_raw.decode().strip())
        print(f"[Server] {bye}")
    finally:
        writer.close()
        await writer.wait_closed()
        print("Disconnected.")


def main():
    parser = argparse.ArgumentParser(description="TIN4 TCP presence demo client")
    parser.add_argument("--host", default="localhost", help="TCP server host")
    parser.add_argument("--port", type=int, default=9000, help="TCP server port")
    parser.add_argument("--token", required=True, help="JWT access token")
    args = parser.parse_args()

    try:
        asyncio.run(run(args.host, args.port, args.token))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
