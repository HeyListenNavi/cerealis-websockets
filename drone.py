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

try:
    connection_string = "/dev/ttyACM0"
    print(f"Connecting to vehicle on: {connection_string}")
    vehicle = connect(connection_string, wait_ready=True, timeout=60)
    print("Vehicle connected.")
except Exception as e:
    print(f"Failed to connect to vehicle: {e}. Exiting.")
    exit()


SERVER_IP = "s8wc004skw8s0wo8k8cc8ooc.89.116.212.214.sslip.io"
RGB_FEED_URL = f"ws://{SERVER_IP}/ws/rgb_feed"
DEPTH_FEED_URL = f"ws://{SERVER_IP}/ws/depth_feed"
CONTROL_URL = f"ws://{SERVER_IP}/ws/control"
INFO_URL = f"ws://{SERVER_IP}/ws/drone_info"

FRAME_WIDTH = 424
FRAME_HEIGHT = 240
CAMERA_FPS = 15 
SEND_INTERVAL = 0.5

pipeline = None
try:
    print("Searching for RealSense camera...")
    ctx = rs.context()
    if len(ctx.query_devices()) > 0:
        pipeline = rs.pipeline()
        config = rs.config()
        config.enable_stream(rs.stream.color, FRAME_WIDTH, FRAME_HEIGHT, rs.format.bgr8, CAMERA_FPS)
        config.enable_stream(rs.stream.depth, FRAME_WIDTH, FRAME_HEIGHT, rs.format.z16, CAMERA_FPS)

        print("Attempting to start RealSense camera pipeline...")
        pipeline.start(config)
        print(f"RealSense camera initialized successfully at {FRAME_WIDTH}x{FRAME_HEIGHT} @ {CAMERA_FPS} FPS.")
    else:
        print("No RealSense devices were found. Video streams will be unavailable.")

except RuntimeError as e:
    print(f"Failed to start RealSense camera: {e}")
    pipeline = None


async def send_rgb_video():
    if not pipeline: return
    while True:
        try:
            async with websockets.connect(RGB_FEED_URL, max_size=None, ping_interval=None) as ws:
                print("Connected to RGB feed")
                while True:
                    frames = await asyncio.to_thread(pipeline.wait_for_frames, 5000)
                    color_frame = frames.get_color_frame()
                    if not color_frame:
                        continue
                    color_image = np.asanyarray(color_frame.get_data())
                    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
                    _, buffer = cv2.imencode('.jpg', color_image, encode_param)
                    await ws.send(buffer.tobytes())
                    print(f"Sent RGB frame ({len(buffer)} bytes)")
                    await asyncio.sleep(SEND_INTERVAL)
        except (websockets.ConnectionClosed, ConnectionRefusedError) as e:
            print(f"RGB feed connection error: {e}. Retrying...")
            await asyncio.sleep(SEND_INTERVAL)
        except Exception as e:
            print(f"An unexpected error occurred in RGB feed: {e}. Retrying...")
            await asyncio.sleep(SEND_INTERVAL)


async def send_depth_video():
    if not pipeline: return
    while True:
        try:
            async with websockets.connect(DEPTH_FEED_URL, max_size=None, ping_interval=None) as ws:
                print("Connected to Depth feed")
                while True:
                    frames = await asyncio.to_thread(pipeline.wait_for_frames, 5000)
                    depth_frame = frames.get_depth_frame()
                    if not depth_frame:
                        continue
                    depth_image = np.asanyarray(depth_frame.get_data())
                    depth_clip = np.clip(depth_image, 0, 3000)
                    depth_norm = cv2.normalize(depth_clip, None, 0, 255, cv2.NORM_MINMAX)
                    depth_color = cv2.applyColorMap(depth_norm.astype(np.uint8), cv2.COLORMAP_JET)
                    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
                    _, buffer = cv2.imencode('.jpg', depth_color, encode_param)
                    await ws.send(buffer.tobytes())
                    print(f"Sent Depth frame ({len(buffer)} bytes)")
                    await asyncio.sleep(SEND_INTERVAL)
        except (websockets.ConnectionClosed, ConnectionRefusedError) as e:
            print(f"Depth feed connection error: {e}. Retrying...")
            await asyncio.sleep(SEND_INTERVAL)
        except Exception as e:
            print(f"An unexpected error occurred in Depth feed: {e}. Retrying...")
            await asyncio.sleep(SEND_INTERVAL)

async def send_drone_info():
    while True:
        try:
            async with websockets.connect(INFO_URL, ping_interval=None) as ws:
                print("Connected to drone info channel")
                while True:
                    home_loc = vehicle.home_location
                    info_payload = {
                        "location": {"lat": vehicle.location.global_relative_frame.lat, "lon": vehicle.location.global_relative_frame.lon, "alt": vehicle.location.global_relative_frame.alt},
                        "attitude": {"pitch": vehicle.attitude.pitch, "yaw": vehicle.attitude.yaw, "roll": vehicle.attitude.roll},
                        "battery": {"voltage": vehicle.battery.voltage, "level": vehicle.battery.level},
                        "gps_fix": vehicle.gps_0.fix_type,
                        "satellites": vehicle.gps_0.satellites_visible,
                        "velocity": vehicle.velocity,
                        "system_status": vehicle.system_status.state,
                        "armed": vehicle.armed,
                        "is_armable": vehicle.is_armable,
                        "mode": vehicle.mode.name,
                        "groundspeed": vehicle.groundspeed,
                        "heading": vehicle.heading,
                        "home_location": {"lat": home_loc.lat, "lon": home_loc.lon} if home_loc else None,
                        "last_heartbeat": vehicle.last_heartbeat,
                    }
                    await ws.send(json.dumps(info_payload))
                    await asyncio.sleep(1) 
        except Exception as e:
            print(f"Drone info channel error: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)


def handle_movement_command_sync(command, motor_configs):
    for motor_num, throttle in motor_configs.get(command, []):
        msg = vehicle.message_factory.command_long_encode(0, 0, mavutil.mavlink.MAV_CMD_DO_MOTOR_TEST, 0, motor_num, mavutil.mavlink.MOTOR_TEST_THROTTLE_PERCENT, throttle, 2, 1, 0, 0)
        vehicle.send_mavlink(msg)
        time.sleep(0.05)


async def listen_for_commands():
    motor_configs = {
        "forward": [(1, 0), (4, 0), (2, 30), (3, 30)],
        "backward": [(1, 30), (4, 30), (2, 0), (3, 0)],
        "left": [(3, 30), (4, 30), (1, 0), (2, 0)],
        "right": [(1, 30), (2, 30), (3, 0), (4, 0)],
        "up": [(1, 30), (2, 30), (3, 30), (4, 30)],
        "stop": [(1, 0), (2, 0), (3, 0), (4, 0)],
    }
    while True:
        try:
            async with websockets.connect(CONTROL_URL, ping_interval=None) as ws:
                print("Connected to control channel")
                async for message in ws:
                    command = message.lower().strip()
                    if command in motor_configs:
                        print(f"Command received: {command}")
                        await asyncio.to_thread(handle_movement_command_sync, command, motor_configs)
                    else:
                        print(f"Unknown command: {command}")
        except Exception as e:
            print(f"Control channel error: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)

async def main():
    tasks = [
        listen_for_commands(),
        send_drone_info(),
    ]
    if pipeline:
        tasks.extend([send_rgb_video(), send_depth_video()])
    
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScript interrupted by user.")
    finally:
        if pipeline:
            pipeline.stop()
        vehicle.close()
        print("Vehicle and resources cleaned up.")

