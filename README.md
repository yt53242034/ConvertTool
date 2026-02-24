# JPG 轉 SVG 轉換工具 (JPG to SVG Converter)

這是一個簡單且實用的 Python 工具，提供圖形化介面 (GUI)，協助使用者將 JPG/JPEG 點陣圖片轉換為 SVG 向量圖檔。核心轉換引擎採用 `vtracer`，能產生高品質的向量圖形。

## 功能特色

- **圖形化介面 (GUI)**：使用 Tkinter 構建，操作簡單直觀，無需輸入複雜指令。
- **自動管理輸出**：轉換後的檔案會自動儲存於程式目錄下的 `converted_files` 資料夾中，並保留原始檔名。
- **高品質轉換參數**：預設配置了適合的轉換參數（如曲線擬合、堆疊路徑、雜點過濾），以獲得平滑且緊湊的 SVG 輸出。
- **狀態提示**：轉換成功或發生錯誤時，皆會彈出視窗提示。

## 安裝需求

在使用此工具之前，請確保您的電腦已安裝 Python 3.x。

### 安裝依賴套件

本專案主要依賴 `vtracer` 進行影像處理。請開啟終端機或命令提示字元，執行以下指令進行安裝：

```bash
pip install vtracer
```

*備註：`tkinter` 為 Python 標準庫的一部分，通常無需額外安裝。*

## 如何使用

1. 下載專案程式碼 `ConvertTool.py`。
2. 在終端機中切換到程式所在目錄。
3. 執行程式：

   ```bash
   python ConvertTool.py
   ```

4. 程式視窗開啟後，點擊 **「選擇圖片並轉換」** 按鈕。
5. 在檔案瀏覽器中選擇您想要轉換的 `.jpg` 或 `.jpeg` 檔案。
6. 等待轉換完成。成功後會彈出視窗提示，您可以在自動建立的 `converted_files` 資料夾中找到生成的 `.svg` 檔案。

## 進階設定

若您需要調整轉換效果（例如改為黑白模式或調整精細度），可以直接修改 `ConvertTool.py` 中的 `vtracer.convert_image_to_svg_py` 參數：

- `colormode`: 設定為 `'binary'` 可進行黑白轉換。
- `color_precision`: 調整顏色精度。
- `filter_speckle`: 調整雜點過濾程度。