import os
import json
import string
import mimetypes
import argparse
import socket
import psutil
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
# vvv 这里是第一个修正：从 fastapi.responses 导入 StreamingResponse vvv
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

# --- CONFIGURATION ---
APP_NAME = "WallpaperEngineLibrary"
APP_VERSION = "4.1" # Version bump for the fix
WE_WORKSHOP_ID = "431960"
CONFIG_FILE = Path("config.json")

# --- FastAPI APP ---
app = FastAPI(title=APP_NAME)

# --- GLOBAL STATE ---
wallpapers_cache = []
all_tags = set()
config = {"selected_drive": None}

# --- HELPER FUNCTIONS (Unchanged) ---
def format_bytes(byte_count):
    if byte_count is None: return "0 B"
    power = 1024
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while byte_count >= power and n < len(power_labels):
        byte_count /= power
        n += 1
    return f"{byte_count:.1f} {power_labels[n]}B"

def save_config():
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

def load_config():
    global config
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r") as f:
            try:
                config = json.load(f)
            except json.JSONDecodeError:
                config = {"selected_drive": None}
    else:
        config = {"selected_drive": None}

# --- CORE SCANNING LOGIC (Unchanged) ---
def scan_wallpapers(drive_letter: str):
    global wallpapers_cache, all_tags
    wallpapers_cache.clear()
    all_tags.clear()
    
    steamapps_patterns = ["SteamLibrary/steamapps", "Program Files (x86)/Steam/steamapps", "Steam/steamapps", "steamapps"]
    base_path = None

    for pattern in steamapps_patterns:
        path_to_check = Path(f"{drive_letter}:\\") / pattern / "workshop" / "content"
        if (path_to_check / WE_WORKSHOP_ID).is_dir():
            base_path = path_to_check
            break
            
    if not base_path:
        print(f"Warning: Could not find Wallpaper Engine workshop folder on drive {drive_letter}")
        return False

    content_path = base_path / WE_WORKSHOP_ID
    print(f"Scanning: {content_path}")
    for item_dir in content_path.iterdir():
        if not item_dir.is_dir(): continue
        project_file = item_dir / "project.json"
        if project_file.exists():
            try:
                data = json.load(open(project_file, 'r', encoding='utf-8'))
                if data.get("type") == "video" and data.get("file"):
                    video_path = item_dir / data["file"]
                    if video_path.exists():
                        tags = data.get("tags", [])
                        all_tags.update(tags)
                        wallpapers_cache.append({
                            "id": item_dir.name, "title": data.get("title", "Untitled"),
                            "path": str(video_path.resolve()), "tags": tags,
                            "mtime": video_path.stat().st_mtime,
                            "date": datetime.fromtimestamp(video_path.stat().st_mtime).strftime("%Y-%m-%d")
                        })
            except Exception:
                continue
    print(f"Scan complete. Found {len(wallpapers_cache)} wallpapers.")
    return True

# --- VIDEO STREAMING (Corrected) ---
def stream_video(video_path: str, request: Request):
    file_size = os.path.getsize(video_path)
    range_header = request.headers.get("range")
    
    headers = {
        "Content-Type": mimetypes.guess_type(video_path)[0] or "video/mp4",
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Connection": "keep-alive",
    }

    if range_header:
        start, end = range_header.replace("bytes=", "").split("-")
        start = int(start)
        end = int(end) if end else file_size - 1
        
        if start >= file_size or end >= file_size:
             raise HTTPException(status_code=416, detail="Requested range not satisfiable")

        length = end - start + 1
        headers["Content-Length"] = str(length)
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        
        def iterfile():
            with open(video_path, "rb") as f:
                f.seek(start)
                bytes_to_read = length
                while bytes_to_read > 0:
                    chunk_size = min(bytes_to_read, 1024 * 1024)
                    data = f.read(chunk_size)
                    if not data:
                        break
                    bytes_to_read -= len(data)
                    yield data
        # vvv 这里是第二个修正：移除了错误的 'mimetypes.' 前缀 vvv
        return StreamingResponse(iterfile(), status_code=206, headers=headers)

    def iterfile_full():
        with open(video_path, "rb") as f:
            yield from f
    # vvv 这里是第三个修正：移除了错误的 'mimetypes.' 前缀 vvv
    return StreamingResponse(iterfile_full(), headers=headers)

# --- API ENDPOINTS (Unchanged) ---
@app.get("/", response_class=FileResponse)
def get_main_page():
    return FileResponse("index.html")

@app.get("/api/config-status")
def get_config_status():
    return {"configured": config.get("selected_drive") is not None}

@app.get("/api/drives")
def get_drives():
    drives = []
    for partition in psutil.disk_partitions(all=False):
        if 'cdrom' in partition.opts or partition.fstype == '': continue
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            drives.append({
                "letter": Path(partition.device).drive.replace(':', '').replace('\\', ''),
                "total": format_bytes(usage.total),
                "used": format_bytes(usage.used),
                "free": format_bytes(usage.free),
                "percent": usage.percent
            })
        except PermissionError:
            # Skip drives that we cannot access (e.g., system recovery partitions)
            continue
    return drives

class DriveSelection(BaseModel):
    drive: str

@app.post("/api/select-drive")
def select_drive(selection: DriveSelection):
    global config
    drive_letter = selection.drive.upper()
    if not (len(drive_letter) == 1 and 'A' <= drive_letter <= 'Z'):
        return JSONResponse({"status": "error", "message": "Invalid drive letter"}, status_code=400)
    
    scan_success = scan_wallpapers(drive_letter)
    if not scan_success:
         return JSONResponse({"status": "error", "message": "Could not find Wallpaper Engine folder on the selected drive."}, status_code=404)

    config["selected_drive"] = drive_letter
    save_config()
    return {"status": "success", "message": f"Drive {drive_letter} selected and scanned."}

@app.post("/api/reset-config")
def reset_config():
    global config, wallpapers_cache, all_tags
    config = {"selected_drive": None}
    if CONFIG_FILE.exists():
        os.remove(CONFIG_FILE)
    wallpapers_cache.clear()
    all_tags.clear()
    return {"status": "success"}

@app.get("/api/data")
def get_wallpaper_data():
    return {
        "wallpapers": wallpapers_cache,
        "tags": sorted(list(all_tags))
    }

@app.get("/api/video/{wallpaper_id}")
def get_video_stream(wallpaper_id: str, request: Request):
    wallpaper = next((wp for wp in wallpapers_cache if wp["id"] == wallpaper_id), None)
    if not wallpaper: raise HTTPException(status_code=404, detail="Wallpaper not found")
    return stream_video(wallpaper["path"], request)

# --- STARTUP LOGIC (Unchanged) ---
def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80)); return s.getsockname()[0]
    except Exception: return "127.0.0.1"

def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} - A web viewer for Wallpaper Engine videos.")
    parser.add_argument('--host', type=str, default='127.0.0.1', help='Host to bind (e.g., 0.0.0.0 for external access).')
    parser.add_argument('--port', type=int, default=9888, help='Port to run on.')
    args = parser.parse_args()
    
    load_config()
    if config.get("selected_drive"):
        print(f"Config found. Scanning drive {config['selected_drive']}...")
        scan_wallpapers(config['selected_drive'])

    print(f"\n{APP_NAME} Server Started!")
    print(f"  - Local Access: http://127.0.0.1:{args.port}")
    if args.host == '0.0.0.0':
        print(f"  - LAN Access:   http://{get_local_ip()}:{args.port}")
    print("Press Ctrl+C to stop the server.")

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()