import tkinter as tk
import os
from tkinter import filedialog, messagebox, ttk
import threading
import sys
import subprocess
import time
import shutil
import urllib.request
import zipfile
import io
import webbrowser
import tempfile

# 初始化主視窗 (移至最上方，統一管理)
root = tk.Tk()
root.title("圖片 轉 SVG 工具")
root.geometry("850x600")

# 檢查並安裝必要套件 (Pillow, scikit-image, numpy, rdp)
try:
    from PIL import Image, ImageTk, ImageEnhance, ImageFilter
    import numpy as np
    from skimage.morphology import skeletonize, remove_small_objects, binary_dilation, disk
    from rdp import rdp
except ImportError:
    root.withdraw()
    if messagebox.askyesno("缺少套件", "本程式需要 Pillow, scikit-image, numpy, rdp 套件來執行中心線運算。\n\n是否立即安裝？"):
        try:
            root.deiconify()
            root.title("正在安裝必要套件 (可能需要幾分鐘)...")
            root.update()
            # 安裝所有依賴
            subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow", "scikit-image", "numpy", "rdp"])
            
            from PIL import Image, ImageTk, ImageEnhance, ImageFilter
            import numpy as np
            from skimage.morphology import skeletonize, remove_small_objects, binary_dilation, disk
            from rdp import rdp
            
            messagebox.showinfo("成功", "套件安裝完成！")
        except Exception as e:
            messagebox.showerror("錯誤", f"安裝失敗：{e}")
            sys.exit(1)
    else:
        sys.exit(0)
    root.deiconify()
    root.title("圖片 轉 SVG 工具")

# 檢查 Potrace 是否存在
potrace_path = None

def check_potrace():
    # 1. 檢查系統 PATH
    path = shutil.which("potrace")
    if path:
        return path
    # 2. 檢查程式所在目錄
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "potrace", "potrace.exe")
    if os.path.exists(local_path):
        return local_path
    return None

def download_potrace():
    dl_win = tk.Toplevel(root)
    dl_win.title("下載元件")
    dl_win.geometry("300x150")
    
    lbl_status = tk.Label(dl_win, text="正在連接伺服器...", pady=10)
    lbl_status.pack()
    
    pb = ttk.Progressbar(dl_win, mode="determinate")
    pb.pack(fill=tk.X, padx=20, pady=5)
    
    # 強制更新視窗以顯示介面
    dl_win.update()
    
    try:
        # 嘗試下載 (若連結失效會被 except 捕捉)
        url = "https://downloads.sourceforge.net/project/potrace/1.16/potrace-1.16.win64.zip"
        # 加入 User-Agent 避免被阻擋
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        
        with urllib.request.urlopen(req) as response:
            total_length = response.getheader('content-length')
            data = b''
            
            if total_length:
                total_length = int(total_length)
                dl_bytes = 0
                chunk_size = 8192
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk: break
                    data += chunk
                    dl_bytes += len(chunk)
                    percent = (dl_bytes / total_length) * 100
                    
                    # 直接在主執行緒更新介面
                    pb.configure(value=percent)
                    lbl_status.configure(text=f"下載中: {int(percent)}%")
                    dl_win.update()
            else:
                pb.configure(mode='indeterminate')
                pb.start(20)
                lbl_status.configure(text="下載中...")
                dl_win.update()
                data = response.read()

            lbl_status.configure(text="正在解壓縮...")
            dl_win.update()
            
            target_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "potrace")
            if not os.path.exists(target_dir):
                os.makedirs(target_dir)
            
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for info in z.infolist():
                    if info.filename.endswith(".exe") or info.filename.endswith(".dll"):
                        # 修改檔名以去除資料夾路徑 (Flatten)
                        info.filename = os.path.basename(info.filename)
                        if info.filename:
                            z.extract(info, target_dir)
        
        dl_win.destroy()
        return True

    except Exception as e:
        dl_win.destroy()
        messagebox.showerror("下載失敗", f"無法自動下載 Potrace。\n\n錯誤訊息: {e}\n\n點擊確定將開啟下載頁面，請下載 'potrace-1.16.win64.zip' (請勿下載 .tar.gz)。")
        webbrowser.open("https://sourceforge.net/projects/potrace/files/1.16/")
        return False

potrace_path = check_potrace()
if not potrace_path:
    root.withdraw()
    if messagebox.askyesno("缺少元件", "找不到 potrace.exe。\n\n是否嘗試自動下載並安裝？"):
        if download_potrace():
            potrace_path = check_potrace()
            
    if not potrace_path:
        messagebox.showerror("缺少元件", "找不到 potrace.exe。\n\n請手動下載 Potrace 並將其放置於程式目錄下的 potrace 資料夾中。")
        sys.exit(1)

# --- Python 實作中心線演算法 (取代 Autotrace) ---

def preprocess_image(img):
    """圖片前處理：增強對比與銳化，提升線條識別率"""
    # 確保是 RGB 模式
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    # 0. 初步降噪 (平滑化)，避免後續銳化步驟放大原始噪點
    img = img.filter(ImageFilter.SMOOTH)
    
    # 1. 增強對比度 (1.5倍)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.5)
    
    # 2. 銳化濾鏡
    img = img.filter(ImageFilter.SHARPEN)
    return img

def process_centerline_svg(input_path, output_path, threshold, turdsize):
    # 1. 讀取圖片並二值化
    with Image.open(input_path) as img:
        # 前處理：清晰化圖片
        img = preprocess_image(img)
        gray = img.convert("L")
        # 轉為 0.0-1.0 浮點數，以便進行高斯模糊
        arr = np.array(gray) / 255.0
    
    # 閾值處理：直接使用清晰化後的影像進行二值化
    # 移除高斯模糊，以符合「先最清晰化後找到中心線」的邏輯，確保像素級精確度
    binary = arr < float(threshold)
    
    # 優化：微幅膨脹以連接斷裂的線條 (Gap Closing)
    # 這能確保「原本的連續線條無斷裂」，避免因閾值導致的 1 像素斷點
    binary = binary_dilation(binary, disk(1))
    
    # 自動去掉只有一格像素且周圍完全不相連的像素點
    # connectivity=2 (8-鄰域) 確保保留對角線連接的像素，但移除真正的孤立點
    binary = remove_small_objects(binary, min_size=2, connectivity=2)
    
    # 2. 移除雜點
    if turdsize > 0:
        binary = remove_small_objects(binary, min_size=int(turdsize), connectivity=2)
    
    # 3. 骨架化 (Skeletonization)
    skeleton = skeletonize(binary)
    
    # 3.1 骨架修剪 (Pruning): 基於節點分析，去除短於 turdsize 的毛邊與雜線
    # 這能強化對直線的判斷，只保留連接主要節點的「正確路線」
    prune_len = int(turdsize)
    if prune_len > 0:
        for _ in range(5): # 執行多次以處理巢狀分支
            ys, xs = np.where(skeleton)
            points = list(zip(ys, xs))
            if not points: break
            
            point_set = set(points)
            neighbors = {pt: [] for pt in points}
            for pt in points:
                y, x = pt
                for dy in [-1, 0, 1]:
                    for dx in [-1, 0, 1]:
                        if dy == 0 and dx == 0: continue
                        ny, nx = y + dy, x + dx
                        if (ny, nx) in point_set:
                            neighbors[pt].append((ny, nx))
            
            # 找出所有端點 (Degree = 1)
            endpoints = [pt for pt, ns in neighbors.items() if len(ns) == 1]
            if not endpoints: break
            
            to_remove = set()
            for ep in endpoints:
                path = [ep]
                curr = ep
                # 從端點往回追蹤
                while len(path) <= prune_len:
                    ns = neighbors[curr]
                    
                    # 遇到交叉點(度數>2)或另一個端點(度數=1且非起點)則停止
                    if len(ns) > 2: break
                    if len(ns) == 1 and curr != ep: break
                    
                    next_node = None
                    for n in ns:
                        if len(path) > 1 and n == path[-2]: continue
                        next_node = n
                        break
                    
                    if next_node:
                        path.append(next_node)
                        curr = next_node
                    else:
                        break
                
                # 判斷是否移除
                # 1. 連接到交叉點的短分支 (Spur) -> 視為雜線移除
                if len(neighbors[curr]) > 2 and len(path) <= prune_len:
                    to_remove.update(path[:-1]) # 保留交叉點本身
                # 2. 孤立的短線段 -> 視為躁點移除
                elif len(neighbors[curr]) == 1 and curr != ep and len(path) <= prune_len:
                    to_remove.update(path)
            
            if not to_remove: break
            for p in to_remove:
                skeleton[p] = False

    # 4. 向量化 (基於圖論的追蹤演算法 - 優化交叉點處理)
    ys, xs = np.where(skeleton)
    points = list(zip(ys, xs))
    
    if not points:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write('<svg></svg>')
        return

    # 建立鄰接表 (Adjacency List)
    point_set = set(points)
    neighbors = {pt: [] for pt in points}
    for pt in points:
        y, x = pt
        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                if dy == 0 and dx == 0: continue
                ny, nx = y + dy, x + dx
                if (ny, nx) in point_set:
                    neighbors[pt].append((ny, nx))

    # 找出所有的端點(度數=1)與交叉點(度數>2)作為路徑起點
    # 度數=2 的點是路徑中間點
    seeds = [pt for pt, ns in neighbors.items() if len(ns) != 2]
    
    # 處理完全封閉的圓環 (沒有端點與交叉點)
    if not seeds and points:
        seeds = [points[0]]

    paths = []
    visited_edges = set() # 記錄已走過的邊 (u, v) 避免重複

    for start_node in seeds:
        # 從起點向所有鄰居延伸
        for next_node in neighbors[start_node]:
            # 建立邊的唯一識別 (無向圖，排序確保一致性)
            edge = frozenset({start_node, next_node})
            if edge in visited_edges:
                continue
            
            visited_edges.add(edge)
            current_path = [start_node, next_node]
            
            # 開始追蹤這條路徑
            prev = start_node
            curr = next_node
            
            while True:
                ns = neighbors[curr]
                
                # 如果遇到另一個端點或交叉點，這條路徑結束
                if len(ns) != 2 or curr in seeds:
                    break
                
                # 尋找下一個未走訪的鄰居 (排除回頭路)
                next_step = None
                for n in ns:
                    if n != prev:
                        next_step = n
                        break
                
                if next_step:
                    # 記錄邊並前進
                    new_edge = frozenset({curr, next_step})
                    visited_edges.add(new_edge)
                    current_path.append(next_step)
                    prev = curr
                    curr = next_step
                else:
                    break
            
            paths.append(current_path)

    # 檢查是否有遺漏的獨立圓環 (Isolated Loops)
    # 上述邏輯可能漏掉不與任何交叉點相連的獨立圓環
    visited_nodes = set()
    for p in paths:
        visited_nodes.update(p)
    
    remaining_nodes = point_set - visited_nodes
    while remaining_nodes:
        start = remaining_nodes.pop()
        # 追蹤這個圓環
        loop_path = [start]
        curr = start
        
        # 隨便找一個鄰居開始
        ns = neighbors[curr]
        if not ns: break
        
        prev = curr
        curr = ns[0]
        
        while curr != start:
            loop_path.append(curr)
            if curr in remaining_nodes: remaining_nodes.remove(curr)
            
            ns = neighbors[curr]
            next_step = None
            for n in ns:
                if n != prev:
                    next_step = n
                    break
            if not next_step: break
            prev = curr
            curr = next_step
            
        loop_path.append(start) # 閉合
        paths.append(loop_path)

    # 5. 寫入 SVG
    h, w = skeleton.shape
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f'<svg width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg">\n')
        f.write(f'<g fill="none" stroke="black" stroke-width="1">\n')
        
        for path in paths:
            # 座標轉換 (y, x) -> (x, y)
            xy_path = [(p[1], p[0]) for p in path]
            
            # 使用 RDP 演算法簡化線條
            # 移除 smooth_polyline 以確保「夾角做到最銳利化」
            # epsilon 設為 1.0 像素，可根據需求調整
            simplified_path = rdp(xy_path, epsilon=1.0)
            
            points_str = " ".join([f"{p[0]},{p[1]}" for p in simplified_path])
            f.write(f'<polyline points="{points_str}" />\n')
            
        f.write('</g>\n</svg>')

# 轉換成功時的回呼函式 (在主執行緒執行)
def on_conversion_success(output_path, btn, label, progress):
    try:
        # 檢查元件是否還存在 (防止使用者途中關閉視窗導致報錯)
        if not btn.winfo_exists(): return
        
        progress.stop()
        progress['mode'] = 'determinate'
        progress['value'] = 100
        btn.config(state=tk.NORMAL, text="選擇圖片並轉換")
        label.config(text="點擊下方按鈕開始轉換")
        messagebox.showinfo("成功", f"轉換完成！已儲存至：\n{output_path}")
    except Exception:
        pass

# 轉換失敗時的回呼函式 (在主執行緒執行)
def on_conversion_error(error_msg, btn, label, progress):
    try:
        if not btn.winfo_exists(): return
        
        progress.stop()
        btn.config(state=tk.NORMAL, text="選擇圖片並轉換")
        label.config(text="點擊下方按鈕開始轉換")
        messagebox.showerror("錯誤", f"轉換過程中發生錯誤：\n{error_msg}")
    except Exception:
        pass

def run_conversion(input_path, output_path, threshold, turdsize, is_centerline, btn_widget, lbl_widget, progress_bar):
    try:
        # 稍作延遲，讓介面有時間完成更新，避免瞬間卡死
        time.sleep(0.1)
        
        # 1. 建立暫存 BMP 檔案 (避免路徑編碼問題與權限問題)
        fd, temp_bmp = tempfile.mkstemp(suffix=".ppm")
        os.close(fd) # 關閉檔案描述符，釋放佔用
        
        try:
            if is_centerline:
                # 中心線模式：使用 Python 內建演算法 (scikit-image + rdp)
                # 不再依賴 autotrace.exe
                process_centerline_svg(input_path, output_path, threshold, turdsize)
            else:
                # 一般模式 (Potrace)
                with Image.open(input_path) as img:
                    img = preprocess_image(img)
                    img.convert("L").save(temp_bmp)
                
                cmd = [
                    potrace_path, "-s", "-o", output_path,
                    "-t", str(turdsize), "-k", str(threshold), temp_bmp
                ]
                subprocess.check_call(cmd, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        finally:
            if os.path.exists(temp_bmp):
                try: os.remove(temp_bmp)
                except: pass

        # 轉換完成，排程回到主執行緒更新介面
        btn_widget.after(0, on_conversion_success, output_path, btn_widget, lbl_widget, progress_bar)
    except Exception as e:
        # 發生錯誤，排程回到主執行緒顯示錯誤
        btn_widget.after(0, on_conversion_error, str(e), btn_widget, lbl_widget, progress_bar)

# 數值輸入驗證函式
def validate_float(P):
    # 簡單驗證：允許空值，且只包含數字與一個小數點 (不允許負號，因為閾值為 0-1)
    if P == "": return True
    if all(c in "0123456789." for c in P) and P.count('.') <= 1:
        return True
    return False

def validate_int(P):
    if P == "":
        return True
    if P.isdigit():
        return True
    return False

current_input_path = None
current_image = None
current_processed_image = None
zoom_level = 1.0

def convert_jpg_to_svg():
    global current_input_path
    # 若尚未載入圖片，先執行載入
    if not current_input_path:
        load_image()
        
    if not current_input_path:
        return
        
    input_path = current_input_path

    # 詢問輸出資料夾
    output_dir = filedialog.askdirectory(title="選擇輸出資料夾")
    if not output_dir:
        return

    # 自動產生輸出路徑 (使用原檔名，副檔名改為 .svg)
    base_name = os.path.basename(input_path)
    name_without_ext = os.path.splitext(base_name)[0]
    output_path = os.path.join(output_dir, name_without_ext + ".svg")

    # 取得使用者輸入的參數
    thresh = 0.5
    # 提高預設雜點過濾值，以利骨架修剪演算法去除交叉點的三角形雜訊與毛邊
    t_size = 15
    is_centerline = centerline_var.get()

    # 更新介面狀態並啟動轉換執行緒
    btn.config(state=tk.DISABLED, text="轉換中...")
    label.config(text="正在轉換，請稍候...")
    
    # 重置進度條狀態
    progress['mode'] = 'indeterminate'
    progress['value'] = 0
    progress.start(30)  # 在主執行緒啟動動畫 (降低頻率避免卡頓)
    root.update()       # 強制立即更新介面
    
    # 使用執行緒執行轉換，避免介面卡死
    threading.Thread(target=run_conversion, args=(input_path, output_path, thresh, t_size, is_centerline, btn, label, progress)).start()

# --- 新增圖片載入與預覽功能 ---

def load_image():
    global current_input_path, zoom_level, current_image, current_processed_image
    path = filedialog.askopenfilename(
        title="選擇要轉換的圖片",
        filetypes=[("Image files", "*.jpg;*.jpeg;*.png;*.bmp;*.webp"), ("All files", "*.*")]
    )
    if path:
        current_input_path = path
        current_image = Image.open(path)
        # 預先處理圖片 (快取以加速預覽)
        current_processed_image = preprocess_image(current_image)
        zoom_level = 1.0
        lbl_file_info.config(text=f"目前檔案: {os.path.basename(path)}")
        update_preview()
        btn.config(text="開始轉換 SVG", state=tk.NORMAL)

def on_mouse_wheel(event):
    global zoom_level
    # Windows delta is usually 120. Linux uses buttons 4 and 5.
    if hasattr(event, 'delta') and event.delta != 0:
        if event.delta > 0:
            zoom_level *= 1.1
        else:
            zoom_level *= 0.9
    elif hasattr(event, 'num'):
        if event.num == 4:
            zoom_level *= 1.1
        elif event.num == 5:
            zoom_level *= 0.9
            
    # Limit zoom
    zoom_level = max(0.1, min(zoom_level, 10.0))
    update_preview()

def on_mouse_down(event):
    event.widget.scan_mark(event.x, event.y)

def on_mouse_drag(event):
    event.widget.scan_dragto(event.x, event.y, gain=1)

def update_preview(*args):
    if not current_input_path: return
    try:
        # 取得目前的閾值參數
        thresh = 0.5
            
        # 載入圖片並調整大小以適應預覽框
        img = current_image
        
        # 計算縮放後的大小
        base_size = 380
        w, h = img.size
        ratio = min(base_size/w, base_size/h)
        new_w = int(w * ratio * zoom_level)
        new_h = int(h * ratio * zoom_level)
        
        # 確保至少 1x1
        new_w = max(1, new_w)
        new_h = max(1, new_h)
        
        # 1. 顯示原始圖片 (左側)
        img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        global img_tk_original
        img_tk_original = ImageTk.PhotoImage(img_resized)
        canvas_original.delete("all")
        canvas_original.create_image(0, 0, image=img_tk_original, anchor=tk.NW)
        canvas_original.config(scrollregion=(0, 0, new_w, new_h))
        
        # 2. 顯示預覽圖片 (右側) - 模擬 Potrace 的閾值處理
        # Potrace 邏輯: 亮度 < 閾值 則為黑色(0)，否則為白色(255)
        # 修正：使用已前處理(清晰化)的圖片進行預覽
        gray = current_processed_image.convert("L")
        limit = thresh * 255
        bw = gray.point(lambda x: 0 if x < limit else 255, '1')
        
        # 縮放二值圖用於預覽 (轉回 L 模式以獲得較好的縮放視覺效果)
        bw_resized = bw.convert("L").resize((new_w, new_h), Image.Resampling.LANCZOS)
        
        global img_tk_preview
        img_tk_preview = ImageTk.PhotoImage(bw_resized)
        canvas_preview.delete("all")
        canvas_preview.create_image(0, 0, image=img_tk_preview, anchor=tk.NW)
        canvas_preview.config(scrollregion=(0, 0, new_w, new_h))
        
    except Exception as e:
        print(f"Preview error: {e}")

# --- GUI 介面佈局調整 ---

# 頂部控制區
top_frame = tk.Frame(root)
top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)

btn_open = tk.Button(top_frame, text="開啟圖片", command=load_image, width=15)
btn_open.pack(side=tk.LEFT, padx=5)

lbl_file_info = tk.Label(top_frame, text="尚未載入圖片", fg="gray")
lbl_file_info.pack(side=tk.LEFT, padx=10)

# 參數設定區塊
settings_frame = tk.Frame(top_frame)
settings_frame.pack(side=tk.RIGHT)

centerline_var = tk.BooleanVar()
chk_centerline = tk.Checkbutton(settings_frame, text="提取中心單線 (Python 內建)", variable=centerline_var)
chk_centerline.grid(row=0, column=0, columnspan=3, pady=5, sticky="w")

# 中間預覽區 (畫布)
preview_frame = tk.Frame(root)
preview_frame.pack(expand=True, fill=tk.BOTH, padx=10, pady=5)

# 左側：原圖
frame_left = tk.LabelFrame(preview_frame, text="原始圖片")
frame_left.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=5)

canvas_original = tk.Canvas(frame_left, bg='#e0e0e0')
scroll_x_orig = tk.Scrollbar(frame_left, orient="horizontal", command=canvas_original.xview)
scroll_y_orig = tk.Scrollbar(frame_left, orient="vertical", command=canvas_original.yview)
canvas_original.configure(xscrollcommand=scroll_x_orig.set, yscrollcommand=scroll_y_orig.set)

canvas_original.grid(row=0, column=0, sticky="nsew")
scroll_y_orig.grid(row=0, column=1, sticky="ns")
scroll_x_orig.grid(row=1, column=0, sticky="ew")
frame_left.grid_rowconfigure(0, weight=1)
frame_left.grid_columnconfigure(0, weight=1)

canvas_original.bind("<MouseWheel>", on_mouse_wheel)
canvas_original.bind("<Button-4>", on_mouse_wheel)
canvas_original.bind("<Button-5>", on_mouse_wheel)
canvas_original.bind("<ButtonPress-1>", on_mouse_down)
canvas_original.bind("<B1-Motion>", on_mouse_drag)

# 右側：預覽
frame_right = tk.LabelFrame(preview_frame, text="轉換預覽 (黑白閾值效果)")
frame_right.pack(side=tk.RIGHT, expand=True, fill=tk.BOTH, padx=5)

canvas_preview = tk.Canvas(frame_right, bg='#e0e0e0')
scroll_x_prev = tk.Scrollbar(frame_right, orient="horizontal", command=canvas_preview.xview)
scroll_y_prev = tk.Scrollbar(frame_right, orient="vertical", command=canvas_preview.yview)
canvas_preview.configure(xscrollcommand=scroll_x_prev.set, yscrollcommand=scroll_y_prev.set)

canvas_preview.grid(row=0, column=0, sticky="nsew")
scroll_y_prev.grid(row=0, column=1, sticky="ns")
scroll_x_prev.grid(row=1, column=0, sticky="ew")
frame_right.grid_rowconfigure(0, weight=1)
frame_right.grid_columnconfigure(0, weight=1)

canvas_preview.bind("<MouseWheel>", on_mouse_wheel)
canvas_preview.bind("<Button-4>", on_mouse_wheel)
canvas_preview.bind("<Button-5>", on_mouse_wheel)
canvas_preview.bind("<ButtonPress-1>", on_mouse_down)
canvas_preview.bind("<B1-Motion>", on_mouse_drag)

# 底部按鈕與狀態
bottom_frame = tk.Frame(root)
bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)

label = tk.Label(bottom_frame, text="調整參數後，按 Enter 可更新預覽 (可使用滑鼠滾輪縮放圖片)", fg="blue")
label.pack(pady=5)

btn = tk.Button(bottom_frame, text="請先開啟圖片", command=convert_jpg_to_svg, width=20, height=2, state=tk.DISABLED)
btn.pack()

# 建立進度條
progress = ttk.Progressbar(bottom_frame, orient="horizontal", length=400, mode="indeterminate")
progress.pack(pady=10)

# 確保視窗顯示
try:
    root.deiconify()
    root.mainloop()
except Exception as e:
    messagebox.showerror("嚴重錯誤", f"程式發生未預期的錯誤而終止：\n{e}")

# 防止命令提示字元視窗直接關閉
os.system("pause")