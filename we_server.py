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
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional, List

# --- CONFIGURATION ---
APP_NAME = "壁纸引擎媒体库"
APP_VERSION = "4.4" # Version bump for final features
WE_WORKSHOP_ID = "431960"
CONFIG_FILE = Path("config.json")
OVERSPEED_RATINGS = ["adult", "mild"] 

# --- FastAPI APP ---
app = FastAPI(title=APP_NAME)

# --- GLOBAL STATE ---
wallpapers_cache = []
all_tags = set()
config = {"selected_drive": None, "history": {}, "visitors": []} # Default config structure
status_info = {
    "scan_path": "N/A", "local_address": "N/A", "lan_address": "N/A",
    "item_count": 0, "last_refresh": "从未"
}

# --- HELPER FUNCTIONS (Updated config handling) ---
def format_bytes(byte_count):
    if byte_count is None: return "0 B"
    power = 1024; n = 0; power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while byte_count >= power and n < len(power_labels):
        byte_count /= power; n += 1
    return f"{byte_count:.1f} {power_labels[n]}B"

def save_config():
    # Sort visitors list before saving
    if "visitors" in config and isinstance(config["visitors"], list):
        config["visitors"] = sorted(list(set(config["visitors"])))
    with open(CONFIG_FILE, "w", encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def load_config():
    global config
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding='utf-8') as f:
            try:
                loaded_config = json.load(f)
                config["selected_drive"] = loaded_config.get("selected_drive")
                config["history"] = loaded_config.get("history", {})
                config["visitors"] = loaded_config.get("visitors", [])
            except json.JSONDecodeError:
                config = {"selected_drive": None, "history": {}, "visitors": []}
    else:
        config = {"selected_drive": None, "history": {}, "visitors": []}

def record_visitor(request: Request):
    client_ip = request.client.host
    if client_ip not in config.get("visitors", []):
        config.setdefault("visitors", []).append(client_ip)
        save_config()

# --- CORE SCANNING LOGIC (Updated for flexible rating) ---
def scan_wallpapers(drive_letter: str):
    # ... (This function's internal logic is the same) ...
    global wallpapers_cache, all_tags, status_info; wallpapers_cache.clear(); all_tags.clear()
    steamapps_patterns = ["SteamLibrary/steamapps", "Program Files (x86)/Steam/steamapps", "Steam/steamapps", "steamapps"]; base_path = None
    for pattern in steamapps_patterns:
        path_to_check = Path(f"{drive_letter}:\\") / pattern / "workshop" / "content"
        if (path_to_check / WE_WORKSHOP_ID).is_dir(): base_path = path_to_check; break
    if not base_path:
        status_info["scan_path"] = f"在 {drive_letter}:\\ 盘未找到工坊目录"; status_info["item_count"] = 0
        print(f"警告: 未在 {drive_letter} 盘找到壁纸引擎工坊目录。"); return False
    content_path = base_path / WE_WORKSHOP_ID; status_info["scan_path"] = str(content_path); print(f"正在扫描: {content_path}")
    for item_dir in content_path.iterdir():
        if not item_dir.is_dir(): continue
        project_file = item_dir / "project.json"
        if project_file.exists():
            try:
                data = json.load(open(project_file, 'r', encoding='utf-8'))
                if data.get("type") == "video" and data.get("file"):
                    video_path = item_dir / data["file"]
                    if video_path.exists():
                        tags = data.get("tags", []); all_tags.update(tags)
                        
                        # vvv 修改的逻辑 vvv
                        raw_rating = data.get("ratingsex", "none")
                        # 判断原始rating是否在我们的超速列表中
                        rating_mode = "overspeed" if raw_rating in OVERSPEED_RATINGS else "normal"
                        # ^^^ 修改的逻辑 ^^^
                        
                        wallpapers_cache.append({"id": item_dir.name, "title": data.get("title", "无标题"), "path": str(video_path.resolve()), "tags": tags, "rating": rating_mode, "mtime": video_path.stat().st_mtime, "date": datetime.fromtimestamp(video_path.stat().st_mtime).strftime("%Y-%m-%d")})
            except Exception: continue
    status_info["item_count"] = len(wallpapers_cache); status_info["last_refresh"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S"); print(f"扫描完成, 找到 {status_info['item_count']} 个壁纸。"); return True

# --- VIDEO STREAMING (Unchanged) ---
def stream_video(video_path: str, request: Request):
    # ... (This function is exactly the same) ...
    file_size = os.path.getsize(video_path); range_header = request.headers.get("range"); headers = {"Content-Type": mimetypes.guess_type(video_path)[0] or "video/mp4","Accept-Ranges": "bytes","Content-Length": str(file_size),"Connection": "keep-alive",};
    if range_header:
        start, end = range_header.replace("bytes=", "").split("-"); start = int(start); end = int(end) if end else file_size - 1;
        if start >= file_size or end >= file_size: raise HTTPException(status_code=416, detail="Requested range not satisfiable");
        length = end - start + 1; headers["Content-Length"] = str(length); headers["Content-Range"] = f"bytes {start}-{end}/{file_size}";
        def iterfile():
            with open(video_path, "rb") as f:
                f.seek(start); bytes_to_read = length
                while bytes_to_read > 0:
                    chunk_size = min(bytes_to_read, 1024 * 1024); data = f.read(chunk_size)
                    if not data: break
                    bytes_to_read -= len(data); yield data
        return StreamingResponse(iterfile(), status_code=206, headers=headers)
    def iterfile_full():
        with open(video_path, "rb") as f: yield from f
    return StreamingResponse(iterfile_full(), headers=headers)

# --- API ENDPOINTS (Updated) ---
@app.get("/", response_class=FileResponse)
def get_main_page(request: Request):
    record_visitor(request)
    return FileResponse("index.html")

@app.get("/api/status")
def get_status():
    status_info["visitors"] = config.get("visitors", [])
    return status_info

@app.post("/api/refresh")
def refresh_data(request: Request):
    record_visitor(request)
    if config.get("selected_drive"):
        print("客户端请求刷新..."); scan_success = scan_wallpapers(config["selected_drive"])
        if scan_success: return {"status": "success", "message": "媒体库已刷新。"}
        else: return JSONResponse({"status": "error", "message": "刷新时未找到工坊目录。"}, status_code=404)
    return JSONResponse({"status": "error", "message": "没有配置需要刷新的盘符。"}, status_code=400)

@app.get("/api/config-status")
def get_config_status(): return {"configured": config.get("selected_drive") is not None}

@app.get("/api/drives")
def get_drives():
    # ... (Unchanged)
    drives = [];
    for partition in psutil.disk_partitions(all=False):
        if 'cdrom' in partition.opts or partition.fstype == '': continue
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            drives.append({"letter": Path(partition.device).drive.replace(':', '').replace('\\', ''), "total": format_bytes(usage.total), "used": format_bytes(usage.used), "free": format_bytes(usage.free), "percent": usage.percent})
        except PermissionError: continue
    return drives

class DriveSelection(BaseModel): drive: str
@app.post("/api/select-drive")
def select_drive(selection: DriveSelection, request: Request):
    record_visitor(request); global config
    drive_letter = selection.drive.upper()
    if not (len(drive_letter) == 1 and 'A' <= drive_letter <= 'Z'): return JSONResponse({"status": "error", "message": "无效的盘符。"}, status_code=400)
    scan_success = scan_wallpapers(drive_letter)
    if not scan_success: return JSONResponse({"status": "error", "message": "在所选盘符上未找到壁纸引擎目录。"}, status_code=404)
    config["selected_drive"] = drive_letter
    save_config()
    return {"status": "success", "message": f"盘符 {drive_letter} 已选择并扫描。"}

@app.post("/api/reset-config")
def reset_config():
    global config, wallpapers_cache, all_tags
    # 只重置选中的盘符，保留其他数据
    config["selected_drive"] = None
    save_config() # 保存更改到 config.json 文件
    
    # 清空内存中的壁纸缓存
    wallpapers_cache.clear()
    all_tags.clear()
    return {"status": "success"}

class HistoryUpdate(BaseModel): id: str; incrementPlayCount: Optional[bool] = None; progress: Optional[float] = None
@app.post("/api/update-history")
def update_history(update: HistoryUpdate):
    global config
    history = config.setdefault("history", {}); item_history = history.setdefault(update.id, {"playCount": 0, "progress": 0})
    if update.incrementPlayCount: item_history["playCount"] += 1
    if update.progress is not None:
        if update.progress > item_history.get("progress", 0): item_history["progress"] = update.progress
    save_config()
    return {"status": "success", "updated_history": item_history}

@app.get("/api/data")
def get_wallpaper_data():
    merged_data = []
    history = config.get("history", {})
    for wp in wallpapers_cache:
        wp_data = wp.copy(); item_history = history.get(wp["id"], {"playCount": 0, "progress": 0})
        wp_data["playCount"] = item_history.get("playCount", 0); wp_data["progress"] = item_history.get("progress", 0)
        merged_data.append(wp_data)
    return {"wallpapers": merged_data, "tags": sorted(list(all_tags))}

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
    except Exception: return "N/A"

def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} - 用于壁纸引擎视频的Web浏览器。")
    parser.add_argument('--host', type=str, default='127.0.0.1', help='服务器绑定的主机 (例如 0.0.0.0 用于外部访问)。')
    parser.add_argument('--port', type=int, default=9888, help='服务器运行的端口。')
    args = parser.parse_args()
    
    status_info["local_address"] = f"http://127.0.0.1:{args.port}"
    status_info["lan_address"] = f"http://{get_local_ip()}:{args.port}" if args.host == '0.0.0.0' else "已禁用"
    
    load_config()
    if config.get("selected_drive"):
        print(f"找到配置。正在扫描盘符 {config['selected_drive']}...")
        scan_wallpapers(config['selected_drive'])

    print(f"\n{APP_NAME} 服务已启动！")
    print(f"  - 本机访问: {status_info['local_address']}")
    if args.host == '0.0.0.0': print(f"  - 局域网访问: {status_info['lan_address']}")
    print("按 Ctrl+C 关闭服务器。")

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")

if __name__ == "__main__":
    main()