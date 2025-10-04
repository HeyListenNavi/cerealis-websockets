import asyncio
import websockets
import pyrealsense2 as rs
import cv2
import numpy as np
import time
import collections
import json

collections.MutableMapping = collections.abc.MutableMapping

from dronekit import connect, VehicleMode
from pymavlink import mavutil

connection_string = "/dev/ttyACM0"
print(f"Connecting to vehicle on: {connection_string}")
vehicle = connect(connection_string, wait_ready=True, timeout=60)
print("Vehicle connected.")

SERVER_IP = "127.0.0.1"
RGB_FEED_URL = f"ws://{SERVER_IP}:8000/ws/rgb_feed"
DEPTH_FEED_URL = f"ws://{SERVER_IP}:8000/ws/depth_feed"
CONTROL_URL = f"ws://{SERVER_IP}:8000/ws/control"

PIXHAWK_CONNECTION = "/dev/ttyACM0"

SLOW_SPEED = 0
FAST_SPEED = 30
TEST_DURATION = 2 

pipeline = rs.pipeline()
config = rs.config()
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 15)
config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 15)
try:
    pipeline.start(config)
except RuntimeError:
    print("No se detectó ninguna cámara RealSense")

async def send_rgb_video():
    try:
        async with websockets.connect(RGB_FEED_URL, max_size=None, ping_interval=10, ping_timeout=20) as ws:
            print("Connected to RGB feed")
            while True:
                frames = await asyncio.to_thread(pipeline.wait_for_frames, 1000)
                color_frame = frames.get_color_frame()
                if not color_frame:
                    continue
                color_image = np.asanyarray(color_frame.get_data())
                _, buffer = cv2.imencode('.jpg', color_image)
                await ws.send(buffer.tobytes())
    except Exception as e:
        print("RGB feed error:", e)

async def send_depth_video():
    try:
        async with websockets.connect(DEPTH_FEED_URL, max_size=None, ping_interval=10, ping_timeout=20) as ws:
            print("Connected to Depth feed")
            while True:
                frames = await asyncio.to_thread(pipeline.wait_for_frames, 1000)
                depth_frame = frames.get_depth_frame()
                if not depth_frame:
                    continue
                depth_image = np.asanyarray(depth_frame.get_data())
                depth_clip = np.clip(depth_image, 0, 3000)
                depth_norm = cv2.normalize(depth_clip, None, 0, 255, cv2.NORM_MINMAX)
                depth_norm = depth_norm.astype(np.uint8)
                depth_color = cv2.applyColorMap(depth_norm, cv2.COLORMAP_JET)
                _, buffer = cv2.imencode('.jpg', depth_color)
                await ws.send(buffer.tobytes())
    except Exception as e:
        print("Depth feed error:", e)

def test_motors(motor_configs):
    for motor_num, throttle in motor_configs:
        msg = vehicle.message_factory.command_long_encode(
            0, 0,
            mavutil.mavlink.MAV_CMD_DO_MOTOR_TEST,
            0,
            motor_num,
            mavutil.mavlink.MOTOR_TEST_THROTTLE_PERCENT,
            throttle,
            TEST_DURATION,
            1,
            0,
            0
        )
        vehicle.send_mavlink(msg)
        time.sleep(0.05)

async def handle_movement_command(command):
    if command == "forward":
        test_motors([
            (1, SLOW_SPEED),
            (4, SLOW_SPEED),
            (2, FAST_SPEED),
            (3, FAST_SPEED)
        ])
    
    elif command == "backward":
        test_motors([
            (1, FAST_SPEED),
            (4, FAST_SPEED), 
            (2, SLOW_SPEED),
            (3, SLOW_SPEED)
        ])
    
    elif command == "left":
        test_motors([
            (3, FAST_SPEED), 
            (4, FAST_SPEED),
            (1, SLOW_SPEED),
            (2, SLOW_SPEED) 
        ])
    
    elif command == "right":
        test_motors([
            (1, FAST_SPEED), 
            (2, FAST_SPEED),
            (3, SLOW_SPEED), 
            (4, SLOW_SPEED)  
        ])

    elif command == "up":
        test_motors([
            (1, FAST_SPEED), 
            (2, FAST_SPEED),
            (3, FAST_SPEED), 
            (4, FAST_SPEED)  
        ])

    elif command == "stop":
        test_motors([
            (1, 0), (2, 0), (3, 0), (4, 0)
        ])
    
    else:
        print(f"Unknown command: {command}")

async def listen_for_commands():
    try:
        async with websockets.connect(CONTROL_URL, ping_interval=10, ping_timeout=20) as ws:
            print("Connected to control channel")
            async for message in ws:
                try:
                    data = json.loads(message)
                    command = data.get("command", "").lower()
                except (json.JSONDecodeError, AttributeError):
                    command = message.lower().strip()
                
                print(f"Command received: {command}")
                await handle_movement_command(command)
                
    except Exception as e:
        print("Control channel error:", e)

async def main():
    await asyncio.gather(
        send_rgb_video(),
        send_depth_video(),
        listen_for_commands()
    )

try:
    asyncio.run(main())
finally:
    if pipeline:
        pipeline.stop()