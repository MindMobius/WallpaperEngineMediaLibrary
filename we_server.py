import os
import json
import string
import mimetypes
import argparse # 新增：用于处理命令行参数
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse

# --- 1. 配置 ---
APP_NAME = "WallpaperEngineLibrary"
APP_VERSION = "3.0"
WE_WORKSHOP_ID = "431960"

# --- 2. FastAPI 应用实例 ---
app = FastAPI(title=APP_NAME)

# 全局变量
wallpapers_cache = []
workshop_base_path = ""
all_tags = set()

# --- 3. 核心业务逻辑 (更新以包含tags) ---

def scan_wallpapers(base_path: Path):
    """扫描目录，解析并缓存壁纸信息（包括tags）"""
    global wallpapers_cache, all_tags
    wallpapers_cache.clear()
    all_tags.clear()
    
    content_path = base_path / WE_WORKSHOP_ID
    if not content_path.is_dir():
        print(f"错误: 创意工坊目录不存在 -> {content_path}")
        return

    print(f"正在扫描: {content_path}")
    for item_dir in content_path.iterdir():
        if not item_dir.is_dir(): continue

        project_file = item_dir / "project.json"
        if project_file.exists():
            try:
                with open(project_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if data.get("type") == "video" and data.get("file"):
                    video_file_path = item_dir / data["file"]
                    if video_file_path.exists():
                        mtime_timestamp = video_file_path.stat().st_mtime
                        mtime_datetime = datetime.fromtimestamp(mtime_timestamp)
                        
                        # 获取tags，如果没有则为空列表
                        tags = data.get("tags", [])
                        all_tags.update(tags) # 更新全局tags集合

                        wallpapers_cache.append({
                            "id": item_dir.name,
                            "title": data.get("title", "无标题"),
                            "path": str(video_file_path.resolve()),
                            "mtime": mtime_timestamp,
                            "date": mtime_datetime.strftime("%Y-%m-%d"),
                            "tags": tags 
                        })
            except (json.JSONDecodeError, KeyError):
                continue
    
    print(f"扫描完成，找到 {len(wallpapers_cache)} 个视频壁纸。")
    print(f"共发现 {len(all_tags)} 个唯一标签。")

# --- 视频流逻辑 (无需修改) ---
def stream_video(video_path: str, request: Request):
    # ... (这部分代码和之前完全一样，为节省篇幅省略)
    file_size = os.path.getsize(video_path)
    range_header = request.headers.get("range")
    headers = {"Content-Type": mimetypes.guess_type(video_path)[0] or "video/mp4","Accept-Ranges": "bytes","Content-Length": str(file_size),"Connection": "keep-alive",}
    if range_header:
        start, end = range_header.replace("bytes=", "").split("-")
        start = int(start)
        end = int(end) if end else file_size - 1
        if start >= file_size or end >= file_size: raise HTTPException(status_code=416, detail="Requested range not satisfiable")
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
                    if not data: break
                    bytes_to_read -= len(data)
                    yield data
        return StreamingResponse(iterfile(), status_code=206, headers=headers)
    def iterfile_full():
        with open(video_path, "rb") as f: yield from f
    return StreamingResponse(iterfile_full(), headers=headers)

# --- 4. API 端点 (更新以支持tag过滤和提供tag列表) ---

@app.get("/api/data")
def get_initial_data():
    """一次性获取所有壁纸和所有tags"""
    sorted_wallpapers = sorted(wallpapers_cache, key=lambda x: x['mtime'], reverse=True)
    return {
        "wallpapers": sorted_wallpapers,
        "tags": sorted(list(all_tags))
    }

@app.get("/api/video/{wallpaper_id}")
def get_video_stream(wallpaper_id: str, request: Request):
    wallpaper = next((wp for wp in wallpapers_cache if wp["id"] == wallpaper_id), None)
    if not wallpaper: raise HTTPException(status_code=404, detail="Wallpaper not found")
    return stream_video(wallpaper["path"], request)

# --- 5. 前端界面 (HTML, CSS, JS) - 重大更新 ---
@app.get("/", response_class=HTMLResponse)
def get_main_page():
    return f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{APP_NAME}</title>
    <style>
        :root {{
            --bg-color: #141414; --card-bg: #1f1f1f; --text-color: #e5e5e5;
            --text-secondary-color: #8c8c8c; --hover-bg: #333; --accent-color: #e50914;
            --dialog-bg: rgba(0, 0, 0, 0.85); --tag-bg: #4d4d4d; --tag-active-bg: var(--accent-color);
        }}
        body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: var(--bg-color); color: var(--text-color); margin: 0; padding: 0; }}
        .container {{ max-width: 1800px; margin: 0 auto; padding: 20px; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 15px; }}
        .header h1 {{ font-size: 2em; margin: 0; color: var(--accent-color); }}
        .controls select, .controls input {{ background: var(--card-bg); color: var(--text-color); border: 1px solid var(--hover-bg); padding: 8px 12px; border-radius: 4px; font-size: 1em; margin-left: 10px; vertical-align: middle; }}
        .tags-filter {{ margin-bottom: 20px; display: flex; flex-wrap: wrap; gap: 8px; }}
        .tag {{ background-color: var(--tag-bg); padding: 5px 12px; border-radius: 15px; font-size: 0.9em; cursor: pointer; transition: background-color 0.2s; user-select: none; }}
        .tag.active {{ background-color: var(--tag-active-bg); font-weight: bold; }}
        .group-container h2 {{ font-size: 1.5em; border-bottom: 2px solid var(--hover-bg); padding-bottom: 10px; margin-top: 40px; margin-bottom: 20px; }}
        .wallpaper-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; }}
        .card {{ background-color: var(--card-bg); border-radius: 6px; overflow: hidden; cursor: pointer; transition: transform 0.2s ease, box-shadow 0.2s ease; display: flex; flex-direction: column; height: 160px; }}
        .card:hover {{ transform: scale(1.03); box-shadow: 0 10px 20px rgba(0,0,0,0.5); }}
        .card-content {{ padding: 15px; flex-grow: 1; display: flex; flex-direction: column; justify-content: center; align-items: center; }}
        .card-title {{ font-weight: bold; text-align: center; margin-bottom: 10px; font-size: 1.1em; }}
        .card-tags {{ display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; }}
        .card-tags .tag {{ font-size: 0.8em; padding: 3px 8px; cursor: default; }}
        .dialog-overlay {{ position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: var(--dialog-bg); display: flex; justify-content: center; align-items: center; z-index: 1000; opacity: 0; visibility: hidden; transition: opacity 0.3s ease; }}
        .dialog-overlay.visible {{ opacity: 1; visibility: visible; }}
        .dialog-content {{ position: relative; width: 80%; max-width: 1280px; max-height: 80%; }}
        #player {{ width: 100%; height: 100%; border-radius: 6px; }}
        .close-btn {{ position: absolute; top: -45px; right: -10px; font-size: 2.5em; color: #fff; cursor: pointer; line-height: 1; user-select: none; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{APP_NAME}</h1>
            <div class="controls">
                <label>排序:</label>
                <select id="sort-by"><option value="date">时间</option><option value="title">名称</option></select>
                <select id="sort-order"><option value="desc">倒序</option><option value="asc">正序</option></select>
                <label>分组:</label>
                <input type="checkbox" id="group-by-date" checked>
            </div>
        </div>
        <div class="tags-filter" id="tags-filter-container"></div>
        <div id="content-area"><div style="text-align:center;font-size:1.2em;">正在加载...</div></div>
    </div>

    <div class="dialog-overlay" id="player-dialog">
        <div class="dialog-content">
            <span class="close-btn" id="close-player-btn">×</span>
            <video id="player" controls autoplay loop playsinline></video>
        </div>
    </div>

    <script>
        const sortByEl = document.getElementById('sort-by');
        const sortOrderEl = document.getElementById('sort-order');
        const groupByDateEl = document.getElementById('group-by-date');
        const tagsFilterContainer = document.getElementById('tags-filter-container');
        const contentArea = document.getElementById('content-area');
        const playerDialog = document.getElementById('player-dialog');
        const videoElement = document.getElementById('player');
        
        let allWallpapers = [];
        let allTags = [];
        let activeTag = 'All';

        async function fetchInitialData() {{
            try {{
                const response = await fetch('/api/data');
                const data = await response.json();
                allWallpapers = data.wallpapers;
                allTags = data.tags;
                renderTagsFilter();
                applyFiltersAndRender();
            }} catch (error) {{
                contentArea.innerHTML = `<div style="color: red; text-align: center;">加载初始数据失败: ${{error.message}}</div>`;
            }}
        }}

        function renderTagsFilter() {{
            tagsFilterContainer.innerHTML = '';
            const allTagEl = createTagFilterPill('All');
            allTagEl.classList.add('active');
            tagsFilterContainer.appendChild(allTagEl);
            allTags.forEach(tag => tagsFilterContainer.appendChild(createTagFilterPill(tag)));
        }}
        
        function createTagFilterPill(tag) {{
            const tagEl = document.createElement('div');
            tagEl.className = 'tag';
            tagEl.textContent = tag;
            tagEl.dataset.tag = tag;
            tagEl.onclick = () => {{
                activeTag = tag;
                document.querySelectorAll('.tags-filter .tag').forEach(t => t.classList.remove('active'));
                tagEl.classList.add('active');
                applyFiltersAndRender();
            }};
            return tagEl;
        }}
        
        function applyFiltersAndRender() {{
            let filteredWallpapers = allWallpapers;
            
            // 1. Filter by tag
            if (activeTag !== 'All') {{
                filteredWallpapers = allWallpapers.filter(wp => wp.tags.includes(activeTag));
            }}
            
            // 2. Sort
            const sortBy = sortByEl.value;
            const isDesc = sortOrderEl.value === 'desc';
            filteredWallpapers.sort((a, b) => {{
                let valA, valB;
                if (sortBy === 'title') {{
                    valA = a.title.toLowerCase();
                    valB = b.title.toLowerCase();
                }} else {{ // date
                    valA = a.mtime;
                    valB = b.mtime;
                }}
                if (valA < valB) return isDesc ? 1 : -1;
                if (valA > valB) return isDesc ? -1 : 1;
                return 0;
            }});
            
            renderWallpapers(filteredWallpapers);
        }}

        function renderWallpapers(wallpapersToRender) {{
            contentArea.innerHTML = '';
            if(wallpapersToRender.length === 0){{
                contentArea.innerHTML = '<div style="text-align:center;font-size:1.2em;">没有匹配的壁纸。</div>';
                return;
            }}

            const groupByDate = groupByDateEl.checked && sortByEl.value === 'date';

            if (groupByDate) {{
                const groups = wallpapersToRender.reduce((acc, wp) => {{
                    (acc[wp.date] = acc[wp.date] || []).push(wp);
                    return acc;
                }}, {{}});

                for (const date in groups) {{
                    const groupContainer = document.createElement('div');
                    groupContainer.className = 'group-container';
                    groupContainer.innerHTML = `<h2>${{date}}</h2>`;
                    const grid = document.createElement('div');
                    grid.className = 'wallpaper-grid';
                    groups[date].forEach(wp => grid.appendChild(createCard(wp)));
                    groupContainer.appendChild(grid);
                    contentArea.appendChild(groupContainer);
                }}
            }} else {{
                const grid = document.createElement('div');
                grid.className = 'wallpaper-grid';
                wallpapersToRender.forEach(wp => grid.appendChild(createCard(wp)));
                contentArea.appendChild(grid);
            }}
        }}

        function createCard(wp) {{
            const card = document.createElement('div');
            card.className = 'card';
            card.dataset.id = wp.id;
            
            const cardContent = document.createElement('div');
            cardContent.className = 'card-content';
            
            const title = document.createElement('div');
            title.className = 'card-title';
            title.textContent = wp.title;
            
            const tagsContainer = document.createElement('div');
            tagsContainer.className = 'card-tags';
            wp.tags.slice(0, 3).forEach(tag => {{ // 只显示最多3个tag
                const tagEl = document.createElement('span');
                tagEl.className = 'tag';
                tagEl.textContent = tag;
                tagsContainer.appendChild(tagEl);
            }});
            
            cardContent.appendChild(title);
            cardContent.appendChild(tagsContainer);
            card.appendChild(cardContent);
            return card;
        }}

        function openPlayer(id) {{
            videoElement.src = `/api/video/${{id}}`;
            playerDialog.classList.add('visible');
            videoElement.play().catch(e => console.error("Playback failed:", e));
        }}

        function closePlayer() {{
            playerDialog.classList.remove('visible');
            videoElement.pause();
            videoElement.src = '';
        }}

        // --- Event Listeners ---
        contentArea.addEventListener('click', e => {{
            const card = e.target.closest('.card');
            if (card && card.dataset.id) openPlayer(card.dataset.id);
        }});
        sortByEl.addEventListener('change', applyFiltersAndRender);
        sortOrderEl.addEventListener('change', applyFiltersAndRender);
        groupByDateEl.addEventListener('change', applyFiltersAndRender);
        document.getElementById('close-player-btn').addEventListener('click', closePlayer);
        playerDialog.addEventListener('click', e => {{ if (e.target === playerDialog) closePlayer(); }});
        
        document.addEventListener('DOMContentLoaded', fetchInitialData);
    </script>
</body>
</html>
    """

# --- 6. 主程序入口 (更新以支持命令行参数和环境变量) ---
import socket # 新增：用于获取本机IP

def get_local_ip():
    """获取本机局域网IP地址"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 连接到一个公共DNS服务，这个连接实际上不会发送数据
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1" # 获取失败则返回本地环回地址

def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} - A web viewer for Wallpaper Engine videos.")
    parser.add_argument('--host', type=str, default='127.0.0.1', help='Host to bind the server to (e.g., 0.0.0.0 for external access).')
    parser.add_argument('--port', type=int, default=9888, help='Port to run the server on.')
    args = parser.parse_args()

    global workshop_base_path
    
    # 优先从环境变量读取盘符（由.bat脚本设置）
    drive_letter = os.environ.get('WE_VIEWER_DRIVE')
    
    if not drive_letter:
        # 如果环境变量不存在，则退回到手动输入模式
        while not drive_letter:
            raw_input = input("请输入 Steam 库所在的盘符 (例如: D): ").strip().upper()
            if len(raw_input) == 1 and 'A' <= raw_input <= 'Z':
                drive_letter = raw_input
            else:
                print("输入无效，请输入单个字母的盘符。")

    selected_drive = Path(f"{drive_letter}:\\")
    
    steamapps_path_patterns = ["SteamLibrary/steamapps", "Program Files (x86)/Steam/steamapps", "Steam/steamapps", "steamapps"]
    
    found_path = None
    for pattern in steamapps_path_patterns:
        path_to_check = selected_drive / pattern / "workshop" / "content"
        if (path_to_check / WE_WORKSHOP_ID).is_dir():
            found_path = path_to_check
            break
            
    if not found_path:
        print(f"\n错误: 在 {selected_drive} 下未找到 Wallpaper Engine 工坊目录。")
        input("按回车键退出...")
        return

    workshop_base_path = found_path
    scan_wallpapers(workshop_base_path)
    
    if not wallpapers_cache:
         print("\n警告: 在工坊目录中未找到任何有效的视频壁纸。")
         input("按回车键退出...")
         return

    print(f"\n{APP_NAME} 服务器已启动！")
    print(f"  - 本地访问: http://127.0.0.1:{args.port}")
    if args.host == '0.0.0.0':
        local_ip = get_local_ip()
        print(f"  - 局域网访问: http://{local_ip}:{args.port}")
    print("按 Ctrl+C 关闭服务器。")

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()