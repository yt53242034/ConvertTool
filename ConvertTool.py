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
root.geometry("1000x700") # 加大視窗以容納新控制項

# 檢查並安裝必要套件 (Pillow, scikit-image, numpy, rdp)
try:
    from PIL import Image, ImageTk, ImageEnhance, ImageFilter
    import numpy as np
    from skimage.morphology import skeletonize, remove_small_objects, binary_dilation, disk, remove_small_holes
    from rdp import rdp
    import ezdxf
except ImportError:
    root.withdraw()
    if messagebox.askyesno("缺少套件", "本程式需要 Pillow, scikit-image, numpy, rdp, ezdxf 套件來執行運算。\n\n是否立即安裝？"):
        try:
            root.deiconify()
            root.title("正在安裝必要套件 (可能需要幾分鐘)...")
            root.update()
            # 安裝所有依賴
            subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow", "scikit-image", "numpy", "rdp", "ezdxf"])
            
            from PIL import Image, ImageTk, ImageEnhance, ImageFilter
            import numpy as np
            from skimage.morphology import skeletonize, remove_small_objects, binary_dilation, disk, remove_small_holes
            from rdp import rdp
            import ezdxf
            
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

# --- 核心影像處理邏輯 (新增局部閾值支援) ---

def generate_binary_mask(img_pil, global_thresh, region_list):
    """
    產生二值化遮罩，支援全域閾值與局部區域閾值混合
    img_pil: PIL Image (RGB or L)
    global_thresh: float (0.0 - 1.0)
    region_list: list of dict {'coords': (x1, y1, x2, y2), 'threshold': float}
    """
    # 轉為灰階並正規化為 0.0-1.0
    arr = np.array(img_pil.convert("L")) / 255.0
    
    # 1. 全域二值化
    binary = arr < global_thresh
    
    # 2. 覆蓋局部區域
    for r in region_list:
        x1, y1, x2, y2 = r['coords']
        t = r['threshold']
        # 邊界檢查與裁切
        x1, x2 = max(0, int(x1)), min(arr.shape[1], int(x2))
        y1, y2 = max(0, int(y1)), min(arr.shape[0], int(y2))
        
        if x1 < x2 and y1 < y2:
            # 局部二值化覆蓋
            binary[y1:y2, x1:x2] = arr[y1:y2, x1:x2] < t
            
    return binary

# --- Python 實作中心線演算法 (取代 Autotrace) ---

def preprocess_image(img):
    """圖片前處理：增強對比與銳化，提升線條識別率"""
    # 確保是 RGB 模式
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    # 0. 初步降噪 (平滑化)，避免後續銳化步驟放大原始噪點
    # img = img.filter(ImageFilter.SMOOTH) # 移除平滑化以保留更多細節
    
    # 1. 增強對比度 (1.5倍)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.0)
    
    # 2. 銳化濾鏡
    # img = img.filter(ImageFilter.SHARPEN)
    return img

def get_centerline_paths(input_path, threshold, turdsize, region_list):
    # 1. 讀取圖片並二值化
    with Image.open(input_path) as img:
        # 前處理：清晰化圖片
        img = preprocess_image(img)
        # 使用混合二值化邏輯
        binary = generate_binary_mask(img, float(threshold), region_list)
    
    # 優化：微幅膨脹以連接斷裂的線條 (Gap Closing) - 暫時關閉
    # 這能確保「原本的連續線條無斷裂」，避免因閾值導致的 1 像素斷點
    # binary = binary_dilation(binary, disk(1))
    
    # 填補微小孔洞，避免骨架化時產生封閉迴圈 (三角形/圓形雜訊)
    # binary = remove_small_holes(binary, area_threshold=5)

    # 自動去掉只有一格像素且周圍完全不相連的像素點
    # connectivity=2 (8-鄰域) 確保保留對角線連接的像素，但移除真正的孤立點
    binary = remove_small_objects(binary, min_size=1, connectivity=2)
    
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
        return [], skeleton.shape[1], skeleton.shape[0]

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

    # 回傳路徑列表與圖片尺寸 (寬, 高)
    h, w = skeleton.shape
    return paths, w, h

def save_as_dxf(paths, width, height, output_path):
    """將路徑儲存為 DXF 檔案 (AutoCAD R2010 格式)"""
    try:
        doc = ezdxf.new('R2010')
        # 設定單位為毫米 (Millimeters)
        doc.header['$INSUNITS'] = 4 
        
        # 建立 CENTER 圖層，設定顏色為紅色 (AutoCAD Color Index 1)
        doc.layers.new(name='CENTER', dxfattribs={'color': 1})
        
        msp = doc.modelspace()
        
        for path in paths:
            # 座標轉換：
            # 1. (y, x) -> (x, y)
            # 2. 翻轉 Y 軸：CAD 原點在左下，圖片在左上。為了讓圖形正立，需用 height - y
            dxf_points = [(p[1], height - p[0]) for p in path]
            
            # 使用 RDP 簡化
            simplified_path = rdp(dxf_points, epsilon=0.1)
            
            # 加入輕量聚合線 (LWPolyline) 到 CENTER 圖層
            msp.add_lwpolyline(simplified_path, dxfattribs={'layer': 'CENTER'})
            
        doc.saveas(output_path)
    except Exception as e:
        raise RuntimeError(f"DXF 儲存失敗: {e}")

def save_as_svg(paths, width, height, output_path):
    """將路徑儲存為 SVG 檔案"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">\n')
        f.write(f'<g fill="none" stroke="black" stroke-width="0.5">\n')
        
        for path in paths:
            # 座標轉換 (y, x) -> (x, y)
            xy_path = [(p[1], p[0]) for p in path]
            
            # 使用 RDP 演算法簡化線條
            # 移除 smooth_polyline 以確保「夾角做到最銳利化」
            # epsilon 設為 1.0 像素，可根據需求調整
            simplified_path = rdp(xy_path, epsilon=0.1)
            
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

def run_conversion(input_path, output_path, threshold, turdsize, is_centerline, region_list, btn_widget, lbl_widget, progress_bar):
    try:
        # 稍作延遲，讓介面有時間完成更新，避免瞬間卡死
        time.sleep(0.1)
        
        # 1. 建立暫存 BMP 檔案 (避免路徑編碼問題與權限問題)
        fd, temp_bmp = tempfile.mkstemp(suffix=".ppm")
        os.close(fd) # 關閉檔案描述符，釋放佔用
        
        try:
            if is_centerline:
                # 中心線模式：計算路徑
                paths, w, h = get_centerline_paths(input_path, threshold, turdsize, region_list)
                
                # 依據副檔名決定存檔格式
                if output_path.lower().endswith(".dxf"):
                    save_as_dxf(paths, w, h, output_path)
                else:
                    save_as_svg(paths, w, h, output_path)
            else:
                # 一般模式 (Potrace)
                with Image.open(input_path) as img:
                    img = preprocess_image(img)
                    # 產生混合後的二值圖
                    binary = generate_binary_mask(img, threshold, region_list)
                    # 轉回 uint8 圖片 (0=Black, 255=White) 供 Potrace 使用
                    # Potrace: 黑色是前景。我們的 binary True(1) 是線條(黑)。
                    # Image.fromarray: True->1, False->0. 
                    # 我們需要: 線條(True) -> 黑色(0)? 不，Potrace 讀取 BMP 時，通常深色是前景。
                    # 讓我們先轉成標準灰階： True(線條) -> 0(黑), False(背景) -> 255(白)
                    # binary 是 boolean，True 代表"是線條"。
                    # np.where(binary, 0, 255)
                    img_out = Image.fromarray(np.where(binary, 0, 255).astype(np.uint8))
                    img_out.save(temp_bmp)
                
                # 判斷輸出格式
                backend = "svg"
                if output_path.lower().endswith(".dxf"):
                    backend = "dxf"
                
                cmd = [
                    potrace_path, "-b", backend, "-o", output_path,
                    "-t", str(turdsize), "-k", "0.5", temp_bmp # 這裡 -k 設為 0.5，因為我們已經手動二值化了
                ]
                # Potrace 的 SVG 模式需要 -s 參數，DXF 不需要
                if backend == "svg":
                    cmd.insert(1, "-s")
                    
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

    # 自動產生輸出路徑 (使用原檔名，副檔名改為 .svg)
    base_name = os.path.basename(input_path)
    name_without_ext = os.path.splitext(base_name)[0]
    
    # 詢問存檔位置與格式 (支援 SVG 與 DXF)
    output_path = filedialog.asksaveasfilename(
        title="儲存檔案",
        initialfile=name_without_ext,
        defaultextension=".dxf",
        filetypes=[("DXF 工程圖", "*.dxf"), ("SVG 向量圖", "*.svg")]
    )
    
    if not output_path:
        return

    # 取得使用者輸入的參數
    thresh = scale_global_thresh.get()
    # 提高預設雜點過濾值，以利骨架修剪演算法去除交叉點的三角形雜訊與毛邊
    t_size = int(entry_turd.get()) if entry_turd.get() else 0
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
    # 傳入 regions 副本以防轉換過程中被修改
    regions_copy = list(regions)
    threading.Thread(target=run_conversion, args=(input_path, output_path, thresh, t_size, is_centerline, regions_copy, btn, label, progress)).start()

# --- 新增圖片載入與預覽功能 ---

def load_image():
    global current_input_path, zoom_level, current_image, current_processed_image, regions, selected_region_index
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
        regions = [] # 清空舊的區域
        selected_region_index = None
        update_region_list_ui()
        update_delete_button_state()
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

# --- 互動式區域選擇邏輯 ---

regions = [] # 格式: {'coords': (x1, y1, x2, y2), 'threshold': 0.65, 'rect_id': canvas_id}
selected_region_index = None # 目前選取的區域索引
is_selection_mode = False
drag_start = None
temp_rect_id = None
current_ratio = 1.0 # 縮放比例，用於座標換算

def toggle_selection_mode():
    global is_selection_mode
    is_selection_mode = not is_selection_mode
    if is_selection_mode:
        btn_select_mode.config(text="結束框選模式", bg="#ffcccc", relief=tk.SUNKEN)
        canvas_original.config(cursor="crosshair")
        label.config(text="【框選模式】請在左側原圖上拖曳滑鼠框選區域", fg="red")
    else:
        btn_select_mode.config(text="新增局部調整區域", bg="SystemButtonFace", relief=tk.RAISED)
        canvas_original.config(cursor="")
        label.config(text="調整參數後，按 Enter 可更新預覽", fg="blue")

def clear_regions():
    global regions, selected_region_index
    for r in regions:
        canvas_original.delete(r['rect_id'])
    regions = []
    selected_region_index = None
    update_region_list_ui()
    update_preview()
    update_delete_button_state()

def undo_last_region():
    global selected_region_index
    if regions:
        r = regions.pop()
        canvas_original.delete(r['rect_id'])
        selected_region_index = None # 清除選取狀態避免索引錯誤
        update_region_list_ui()
        update_preview()
        update_delete_button_state()

def delete_selected_region():
    global regions, selected_region_index
    if selected_region_index is not None and 0 <= selected_region_index < len(regions):
        canvas_original.delete(regions[selected_region_index]['rect_id'])
        regions.pop(selected_region_index)
        selected_region_index = None
        update_region_list_ui()
        update_preview()
        update_delete_button_state()

def update_delete_button_state():
    if selected_region_index is not None:
        btn_delete_selected.config(state=tk.NORMAL, text="刪除選取區域")
    else:
        btn_delete_selected.config(state=tk.DISABLED, text="刪除選取區域")

def update_region_list_ui():
    lbl_region_count.config(text=f"已設定 {len(regions)} 個局部區域")

# 新增：更新局部閾值的回呼函式
def update_local_thresh(val):
    global selected_region_index
    # 如果有選取區域，更新最後一個區域的閾值並刷新預覽
    if selected_region_index is not None and selected_region_index < len(regions):
        regions[selected_region_index]['threshold'] = float(val)
        update_preview()
    elif regions and selected_region_index is None:
        # 若無選取，預設不動作，或可選擇更新最後一個 (視需求而定，這裡保持不動作以免誤觸)
        pass

def on_mouse_down(event):
    global drag_start, temp_rect_id, selected_region_index
    
    # 取得 Canvas 座標
    cx = event.widget.canvasx(event.x)
    cy = event.widget.canvasy(event.y)

    if is_selection_mode and current_input_path:
        drag_start = (cx, cy)
        # 建立暫時矩形
        temp_rect_id = event.widget.create_rectangle(cx, cy, cx, cy, outline="red", width=2, dash=(4, 4))
    else:
        # 檢查是否點擊到現有區域 (反向遍歷，優先選取最上層)
        clicked_region = None
        if regions:
            for i in range(len(regions) - 1, -1, -1):
                r = regions[i]
                # 將圖片座標轉換為目前的 Canvas 座標
                rx1, ry1, rx2, ry2 = r['coords']
                x1 = rx1 * current_ratio
                y1 = ry1 * current_ratio
                x2 = rx2 * current_ratio
                y2 = ry2 * current_ratio
                
                # 簡單的碰撞偵測
                if x1 <= cx <= x2 and y1 <= cy <= y2:
                    clicked_region = i
                    break
        
        if clicked_region is not None:
            selected_region_index = clicked_region
            # 更新滑桿數值以顯示該區域設定 (這會觸發 update_local_thresh，但數值一致所以無害)
            scale_local_thresh.set(regions[selected_region_index]['threshold'])
            update_preview()
            update_delete_button_state()
        else:
            # 點擊空白處，取消選取
            if selected_region_index is not None:
                selected_region_index = None
                update_preview()
                update_delete_button_state()
            
            # 原有的平移功能
            event.widget.scan_mark(event.x, event.y)

def on_mouse_drag(event):
    if is_selection_mode and drag_start:
        cx = event.widget.canvasx(event.x)
        cy = event.widget.canvasy(event.y)
        event.widget.coords(temp_rect_id, drag_start[0], drag_start[1], cx, cy)
    else:
        event.widget.scan_dragto(event.x, event.y, gain=1)

def on_mouse_up(event):
    global drag_start, temp_rect_id, regions, selected_region_index
    if is_selection_mode and drag_start:
        cx = event.widget.canvasx(event.x)
        cy = event.widget.canvasy(event.y)
        
        # 計算實際圖片座標
        # Canvas 座標 = 圖片座標 * zoom_level * ratio
        # 所以 圖片座標 = Canvas 座標 / (zoom_level * ratio)
        # 但注意 update_preview 中計算的 ratio 是基於 base_size 的
        scale = current_ratio # 這是 (new_w / w)
        
        x1, y1 = drag_start
        x2, y2 = cx, cy
        
        # 轉換回原始圖片像素座標
        ix1, iy1 = x1 / scale, y1 / scale
        ix2, iy2 = x2 / scale, y2 / scale
        
        # 確保座標正確 (左上到右下)
        rx1, rx2 = min(ix1, ix2), max(ix1, ix2)
        ry1, ry2 = min(iy1, iy2), max(iy1, iy2)
        
        # 只有當區域夠大時才新增
        if (rx2 - rx1) > 5 and (ry2 - ry1) > 5:
            # 使用目前的「局部閾值」滑桿數值
            thresh = scale_local_thresh.get()
            regions.append({'coords': (rx1, ry1, rx2, ry2), 'threshold': thresh, 'rect_id': temp_rect_id})
            selected_region_index = len(regions) - 1 # 自動選取剛建立的區域
            # 將虛線改為實線表示已確認
            event.widget.itemconfig(temp_rect_id, dash=(), outline="#ff0000", width=2)
            update_region_list_ui()
            update_preview()
            update_delete_button_state()
        else:
            event.widget.delete(temp_rect_id)
        
        drag_start = None
        temp_rect_id = None

def update_preview(*args):
    global current_ratio
    if not current_input_path: return
    try:
        # 取得目前的閾值參數
        global_thresh = scale_global_thresh.get()
            
        # 載入圖片並調整大小以適應預覽框
        img = current_image
        
        # 計算縮放後的大小
        base_size = 380
        w, h = img.size
        ratio = min(base_size/w, base_size/h)
        new_w = int(w * ratio * zoom_level)
        new_h = int(h * ratio * zoom_level)
        current_ratio = new_w / w # 更新全域比例供座標換算使用
        
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
        
        # 重繪所有區域框 (因為縮放可能改變了)
        for i, r in enumerate(regions):
            # 刪除舊框 (如果存在) - 其實 Canvas 清除 all 時已經刪了
            # 這裡我們不依賴舊 ID，而是重畫。但為了效能，我們應該只在 zoom 改變時重畫。
            # 簡單起見：每次 update_preview 都重畫框框
            rx1, ry1, rx2, ry2 = r['coords']
            cx1, cy1 = rx1 * current_ratio, ry1 * current_ratio
            cx2, cy2 = rx2 * current_ratio, ry2 * current_ratio
            
            # 根據選取狀態決定顏色與粗細
            color = "blue" if i == selected_region_index else "red"
            width = 3 if i == selected_region_index else 2
            
            # 畫在左側原圖上
            r['rect_id'] = canvas_original.create_rectangle(cx1, cy1, cx2, cy2, outline=color, width=width)

        # 2. 顯示預覽圖片 (右側) - 使用混合二值化邏輯
        binary_mask = generate_binary_mask(current_processed_image, global_thresh, regions)
        # 將 True/False 轉為 0/255 (True是線條=黑=0)
        bw = Image.fromarray(np.where(binary_mask, 0, 255).astype(np.uint8))
        
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
settings_frame = tk.LabelFrame(top_frame, text="參數設定")
settings_frame.pack(side=tk.RIGHT, padx=5)

# 全域閾值
tk.Label(settings_frame, text="全域閾值:").grid(row=0, column=0, padx=5, sticky="e")
scale_global_thresh = tk.Scale(settings_frame, from_=0.0, to=1.0, resolution=0.01, orient=tk.HORIZONTAL, length=150, command=update_preview)
scale_global_thresh.set(0.65)
scale_global_thresh.grid(row=0, column=1, padx=5)

# 雜點過濾
tk.Label(settings_frame, text="雜點過濾(px):").grid(row=1, column=0, padx=5, sticky="e")
entry_turd = tk.Entry(settings_frame, width=5)
entry_turd.insert(0, "2")
entry_turd.grid(row=1, column=1, sticky="w", padx=5)
entry_turd.bind('<Return>', update_preview)

centerline_var = tk.BooleanVar()
chk_centerline = tk.Checkbutton(settings_frame, text="提取中心單線 (Python 內建)", variable=centerline_var)
chk_centerline.grid(row=2, column=0, columnspan=2, pady=2, sticky="w")

# --- 新增：局部調整控制區 ---
roi_frame = tk.LabelFrame(root, text="局部區域調整 (ROI)", fg="blue")
roi_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

btn_select_mode = tk.Button(roi_frame, text="新增局部調整區域", command=toggle_selection_mode)
btn_select_mode.pack(side=tk.LEFT, padx=10, pady=5)

tk.Label(roi_frame, text="局部閾值:").pack(side=tk.LEFT, padx=5)
scale_local_thresh = tk.Scale(roi_frame, from_=0.0, to=1.0, resolution=0.01, orient=tk.HORIZONTAL, length=150, command=update_local_thresh)
scale_local_thresh.set(0.45) # 預設比全域低一點，適合去除雜點
scale_local_thresh.pack(side=tk.LEFT, padx=5)
tk.Label(roi_frame, text="(框選時套用此值)").pack(side=tk.LEFT)

btn_undo = tk.Button(roi_frame, text="復原上一個", command=undo_last_region)
btn_undo.pack(side=tk.LEFT, padx=10)

btn_delete_selected = tk.Button(roi_frame, text="刪除選取區域", command=delete_selected_region, state=tk.DISABLED)
btn_delete_selected.pack(side=tk.LEFT, padx=5)

btn_clear = tk.Button(roi_frame, text="清除所有區域", command=clear_regions)
btn_clear.pack(side=tk.LEFT, padx=5)

lbl_region_count = tk.Label(roi_frame, text="已設定 0 個局部區域", fg="gray")
lbl_region_count.pack(side=tk.RIGHT, padx=10)

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
canvas_original.bind("<ButtonRelease-1>", on_mouse_up) # 新增放開事件

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