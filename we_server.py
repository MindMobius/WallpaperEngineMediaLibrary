import os
import sys
import json
import string
import mimetypes
import argparse
import socket
import psutil
import winreg
import vdf
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List

# --- PYINSTALLER HELPER ---
# This function helps find bundled assets (like index.html, public/)
# when running as a frozen .exe file.
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        # Not running in a bundle, so use the script's directory
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# --- CONFIGURATION ---
APP_NAME = "壁纸引擎媒体库"
APP_VERSION = "4.4"
WE_WORKSHOP_ID = "431960"
# NOTE: CONFIG_FILE is user data, so it should NOT use resource_path.
# It will be created next to the .exe file.
CONFIG_FILE = Path("config.json")
OVERSPEED_RATINGS = ["adult", "mild"]

# --- FastAPI APP ---
app = FastAPI(title=APP_NAME)
# vvv MODIFIED vvv Use resource_path for static assets
app.mount("/public", StaticFiles(directory=resource_path("public")), name="public")
# ^^^ MODIFIED ^^^

# --- GLOBAL STATE ---
# ... (rest of the global state is unchanged)
wallpapers_cache = []
all_tags = set()
config = {"selected_drive": None, "history": {}, "visitors": []}
status_info = {
    "scan_path": "N/A", "local_address": "N/A", "lan_address": "N/A",
    "item_count": 0, "last_refresh": "从未"
}


# --- HELPER FUNCTIONS (Unchanged) ---
def format_bytes(byte_count):
    if byte_count is None: return "0 B"
    power = 1024; n = 0; power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while byte_count >= power and n < len(power_labels):
        byte_count /= power; n += 1
    return f"{byte_count:.1f} {power_labels[n]}B"

def save_config():
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

# --- CORE SCANNING LOGIC (Unchanged) ---
# 添加新的辅助函数
def get_steam_install_path():
    """
    通过读取注册表获取 Steam 的安装路径
    """
    try:
        # 尝试 64 位注册表路径
        reg_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 
                                 r"SOFTWARE\WOW6432Node\Valve\Steam")
        install_path, _ = winreg.QueryValueEx(reg_key, "InstallPath")
        winreg.CloseKey(reg_key)
        return install_path
    except FileNotFoundError:
        try:
            # 尝试 32 位注册表路径
            reg_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 
                                     r"SOFTWARE\Valve\Steam")
            install_path, _ = winreg.QueryValueEx(reg_key, "InstallPath")
            winreg.CloseKey(reg_key)
            return install_path
        except Exception:
            return None
    except Exception:
        return None

def find_we_workshop_path():
    """
    查找 Wallpaper Engine 工坊目录路径
    """
    # 首先获取 Steam 安装路径
    steam_path = get_steam_install_path()
    if not steam_path:
        return None
    
    # 构造 libraryfolders.vdf 文件路径
    vdf_path = Path(steam_path) / "config" / "libraryfolders.vdf"
    if not vdf_path.exists():
        return None
    
    try:
        # 解析 libraryfolders.vdf 文件
        with open(vdf_path, 'r', encoding='utf-8') as f:
            library_data = vdf.load(f)
        
        # 遍历所有库路径，查找包含 Wallpaper Engine (431960) 的路径
        for key, library in library_data["libraryfolders"].items():
            if "apps" in library and WE_WORKSHOP_ID in library["apps"]:
                # 找到包含 Wallpaper Engine 的库
                library_path = Path(library["path"])
                workshop_path = library_path / "steamapps" / "workshop" / "content" / WE_WORKSHOP_ID
                if workshop_path.exists():
                    return workshop_path
        
        # 如果在已知库中没找到，则检查 Steam 安装目录本身
        local_workshop_path = Path(steam_path) / "steamapps" / "workshop" / "content" / WE_WORKSHOP_ID
        if local_workshop_path.exists():
            return local_workshop_path
            
    except Exception as e:
        print(f"解析 libraryfolders.vdf 出错: {e}")
        return None
    
    return None

def scan_wallpapers(drive_letter: str = None):
    """
    扫描壁纸文件，如果提供了 drive_letter 则使用原有逻辑，
    否则尝试自动查找 Wallpaper Engine 工坊目录
    """
    global wallpapers_cache, all_tags, status_info
    wallpapers_cache.clear()
    all_tags.clear()
    
    # 如果提供了 drive_letter，则使用原有逻辑
    if drive_letter:
        steamapps_patterns = ["SteamLibrary/steamapps", "Program Files (x86)/Steam/steamapps", "Steam/steamapps", "steamapps"]
        base_path = None
        for pattern in steamapps_patterns:
            path_to_check = Path(f"{drive_letter}:\\") / pattern / "workshop" / "content"
            if (path_to_check / WE_WORKSHOP_ID).is_dir():
                base_path = path_to_check
                break
        if not base_path:
            status_info["scan_path"] = f"在 {drive_letter}:\\ 盘未找到工坊目录"
            status_info["item_count"] = 0
            print(f"警告: 未在 {drive_letter} 盘找到壁纸引擎工坊目录。")
            return False
    else:
        # 尝试自动查找 Wallpaper Engine 工坊目录
        base_path = find_we_workshop_path()
        if not base_path:
            status_info["scan_path"] = "未找到工坊目录"
            status_info["item_count"] = 0
            print("警告: 未找到壁纸引擎工坊目录。")
            return False

    content_path = base_path / WE_WORKSHOP_ID if drive_letter else base_path
    status_info["scan_path"] = str(content_path)
    print(f"正在扫描: {content_path}")
    
    for item_dir in content_path.iterdir():
        if not item_dir.is_dir():
            continue
        project_file = item_dir / "project.json"
        if project_file.exists():
            try:
                data = json.load(open(project_file, 'r', encoding='utf-8'))
                if data.get("type") == "video" and data.get("file"):
                    video_path = item_dir / data["file"]
                    if video_path.exists():
                        tags = data.get("tags", [])
                        all_tags.update(tags)
                        raw_rating = data.get("ratingsex", "none")
                        rating_mode = "overspeed" if raw_rating in OVERSPEED_RATINGS else "normal"
                        wallpapers_cache.append({
                            "id": item_dir.name,
                            "title": data.get("title", "无标题"),
                            "path": str(video_path.resolve()),
                            "tags": tags,
                            "rating": rating_mode,
                            "mtime": video_path.stat().st_mtime,
                            "date": datetime.fromtimestamp(video_path.stat().st_mtime).strftime("%Y-%m-%d")
                        })
            except Exception:
                continue
    
    status_info["item_count"] = len(wallpapers_cache)
    status_info["last_refresh"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"扫描完成, 找到 {status_info['item_count']} 个壁纸。")
    return True

# --- VIDEO STREAMING (Unchanged) ---
def stream_video(video_path: str, request: Request):
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
    # vvv MODIFIED vvv Use resource_path for the main page
    return FileResponse(resource_path("index.html"))
    # ^^^ MODIFIED ^^^

# ... (All other API endpoints are unchanged)
@app.get("/api/status")
def get_status():
    status_info["visitors"] = config.get("visitors", [])
    return status_info

@app.post("/api/refresh")
def refresh_data(request: Request):
    record_visitor(request)
    if config.get("selected_drive"):
        print("客户端请求刷新...")
        # 根据配置的驱动器类型选择不同的扫描方式
        if config["selected_drive"] == "auto":
            # 使用自动检测模式
            scan_success = scan_wallpapers()  # 不传递参数，使用自动检测
        else:
            # 使用指定盘符模式
            scan_success = scan_wallpapers(config["selected_drive"])
        
        if scan_success: 
            return {"status": "success", "message": "媒体库已刷新。"}
        else: 
            return JSONResponse({"status": "error", "message": "刷新时未找到工坊目录。"}, status_code=404)
    return JSONResponse({"status": "error", "message": "没有配置需要刷新的盘符。"}, status_code=400)

@app.get("/api/config-status")
def get_config_status(): return {"configured": config.get("selected_drive") is not None}

# 修改 get_drives 函数
@app.get("/api/drives")
def get_drives():
    drives = []
    
    # 添加自动检测选项
    drives.append({
        "letter": "auto",
        "total": "自动检测",
        "used": "",
        "free": "",
        "percent": 0
    })
    
    for partition in psutil.disk_partitions(all=False):
        if 'cdrom' in partition.opts or partition.fstype == '':
            continue
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
            continue
    return drives

class DriveSelection(BaseModel): drive: str

# 修改 select_drive 函数
@app.post("/api/select-drive")
def select_drive(selection: DriveSelection, request: Request):
    record_visitor(request)
    global config
    
    # 处理自动检测模式
    if selection.drive.lower() == "auto":
        scan_success = scan_wallpapers()  # 不传递 drive_letter 参数
        if not scan_success:
            return JSONResponse({"status": "error", "message": "未找到壁纸引擎目录。"}, status_code=404)
        config["selected_drive"] = "auto"  # 标记为自动检测模式
        save_config()
        return {"status": "success", "message": "已自动检测并扫描壁纸引擎目录。"}
    else:
        # 原有逻辑处理指定盘符的情况
        drive_letter = selection.drive.upper()
        if not (len(drive_letter) == 1 and 'A' <= drive_letter <= 'Z'):
            return JSONResponse({"status": "error", "message": "无效的盘符。"}, status_code=400)
        scan_success = scan_wallpapers(drive_letter)
        if not scan_success:
            return JSONResponse({"status": "error", "message": "在所选盘符上未找到壁纸引擎目录。"}, status_code=404)
        config["selected_drive"] = drive_letter
        save_config()
        return {"status": "success", "message": f"盘符 {drive_letter} 已选择并扫描。"}

@app.post("/api/reset-config")
def reset_config():
    global config, wallpapers_cache, all_tags
    config["selected_drive"] = None
    save_config()
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
    parser.add_argument('--host', type=str, default='0.0.0.0', help='服务器绑定的主机 (例如 0.0.0.0 用于外部访问)。')
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
    print("如果是通过 EXE 运行，请直接关闭此命令行窗口来停止服务。") # Added for clarity

    import uvicorn
    # When running bundled, sys.argv might be different. We'll use our parsed args.
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")

if __name__ == "__main__":
    main()