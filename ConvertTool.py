import tkinter as tk
import os
from tkinter import filedialog, messagebox, ttk
import threading
import sys
import subprocess

# 初始化主視窗 (移至最上方，統一管理)
root = tk.Tk()
root.title("圖片 轉 SVG 工具")
root.geometry("350x250")

# 自動檢查並安裝 vtracer
vtracer_module = None
try:
    import vtracer
    vtracer_module = vtracer
except ImportError:
    # 使用已建立的 root 顯示提示，避免重複建立視窗導致閃退
    root.withdraw() # 先隱藏主視窗
    if messagebox.askyesno("系統提示", "首次執行需安裝必要套件 (vtracer)，是否立即安裝？"):
        try:
            # 顯示簡單的載入狀態
            root.deiconify()
            root.title("正在安裝套件，請稍候...")
            root.update()
            
            subprocess.check_call([sys.executable, "-m", "pip", "install", "vtracer"])
            messagebox.showinfo("系統提示", "安裝完成！請重新啟動程式以開始使用。")
            sys.exit(0) # 安裝後退出，避免 DLL 載入錯誤
        except Exception as e:
            messagebox.showerror("錯誤", f"安裝失敗，請手動執行 'pip install vtracer'。\n錯誤: {e}")
            sys.exit(1)
    else:
        sys.exit(0)

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

def run_conversion(input_path, output_path, mode, btn_widget, lbl_widget, progress_bar):
    try:
        # 確保 vtracer 已載入
        if vtracer_module is None:
            raise ImportError("vtracer 模組未正確載入")
            
        # 使用 vtracer 進行轉換
        vtracer_module.convert_image_to_svg_py(
            input_path,
            output_path,
            colormode=mode,         # 使用使用者選擇的模式
            hierarchical='stacked', # 堆疊路徑，使圖形更緊湊
            mode='spline',          # 使用曲線擬合，讓線條更平滑
            filter_speckle=4,       # 過濾小雜點
            color_precision=6,      # 顏色精度
            layer_difference=16,    # 圖層差異
            corner_threshold=60,    # 轉角閾值
            length_threshold=4.0,   # 長度閾值
            max_iterations=10,      # 最大迭代次數
            splice_threshold=45,    # 拼接閾值
            path_precision=3        # 路徑精度
        )
        # 轉換完成，排程回到主執行緒更新介面
        btn_widget.after(0, on_conversion_success, output_path, btn_widget, lbl_widget, progress_bar)
    except Exception as e:
        # 發生錯誤，排程回到主執行緒顯示錯誤
        btn_widget.after(0, on_conversion_error, str(e), btn_widget, lbl_widget, progress_bar)

def convert_jpg_to_svg():
    # 選擇輸入的圖片檔案
    input_path = filedialog.askopenfilename(
        title="選擇要轉換的圖片",
        filetypes=[("Image files", "*.jpg;*.jpeg;*.png;*.bmp;*.webp"), ("All files", "*.*")]
    )
    
    if not input_path:
        return

    # 詢問輸出資料夾 (若取消則預設為專案下的 converted_files)
    output_dir = filedialog.askdirectory(title="選擇輸出資料夾 (取消則預設為專案目錄)")
    if not output_dir:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "converted_files")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

    # 自動產生輸出路徑 (使用原檔名，副檔名改為 .svg)
    base_name = os.path.basename(input_path)
    name_without_ext = os.path.splitext(base_name)[0]
    output_path = os.path.join(output_dir, name_without_ext + ".svg")

    # 更新介面狀態並啟動轉換執行緒
    btn.config(state=tk.DISABLED, text="轉換中...")
    label.config(text="正在轉換，請稍候...")
    
    # 重置進度條狀態
    progress['mode'] = 'indeterminate'
    progress['value'] = 0
    progress.start(10)  # 在主執行緒啟動動畫
    
    # 使用執行緒執行轉換，避免介面卡死
    threading.Thread(target=run_conversion, args=(input_path, output_path, 'color', btn, label, progress)).start()

label = tk.Label(root, text="點擊下方按鈕開始轉換", pady=20)
label.pack()

btn = tk.Button(root, text="選擇圖片並轉換", command=convert_jpg_to_svg, width=20, height=2)
btn.pack()

# 建立進度條
progress = ttk.Progressbar(root, orient="horizontal", length=250, mode="indeterminate")
progress.pack(pady=15)

# 確保視窗顯示
root.deiconify()
root.mainloop()