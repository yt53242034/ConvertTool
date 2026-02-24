import tkinter as tk
import os
from tkinter import filedialog, messagebox
import threading
import vtracer

def run_conversion(input_path, output_path, mode, btn_widget, lbl_widget):
    try:
        # 使用 vtracer 進行轉換
        vtracer.convert_image_to_svg_py(
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
        messagebox.showinfo("成功", f"轉換完成！已儲存至：\n{output_path}")
    except Exception as e:
        messagebox.showerror("錯誤", f"轉換過程中發生錯誤：\n{e}")
    finally:
        # 恢復按鈕狀態
        btn_widget.config(state=tk.NORMAL, text="選擇圖片並轉換")
        lbl_widget.config(text="點擊下方按鈕開始轉換")

def convert_jpg_to_svg():
    # 選擇輸入的 JPG 檔案
    input_path = filedialog.askopenfilename(
        title="選擇要轉換的 JPG 圖片",
        filetypes=[("JPEG files", "*.jpg;*.jpeg"), ("All files", "*.*")]
    )
    
    if not input_path:
        return

    # 設定並建立輸出資料夾
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "converted_files")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 自動產生輸出路徑 (使用原檔名，副檔名改為 .svg)
    base_name = os.path.basename(input_path)
    name_without_ext = os.path.splitext(base_name)[0]
    output_path = os.path.join(output_dir, name_without_ext + ".svg")

    try:
        # 使用 vtracer 進行轉換 (參數可根據工程圖紙需求調整)
        vtracer.convert_image_to_svg_py(
            input_path,
            output_path,
            colormode='color',      # 可選 'color' 或 'binary' (黑白，適合工程圖)
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
        messagebox.showinfo("成功", f"轉換完成！已儲存至：\n{output_path}")
    except Exception as e:
        messagebox.showerror("錯誤", f"轉換過程中發生錯誤：\n{e}")

# 建立簡單的圖形化介面 (GUI)
root = tk.Tk()
root.title("JPG 轉 SVG 工具")
root.geometry("300x150")

label = tk.Label(root, text="點擊下方按鈕開始轉換", pady=20)
label.pack()

btn = tk.Button(root, text="選擇圖片並轉換", command=convert_jpg_to_svg, width=20, height=2)
btn.pack()

root.mainloop()