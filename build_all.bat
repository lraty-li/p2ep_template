@echo off
chcp 65001 >nul
echo ========================================
echo 开始构建流程
echo ========================================
echo.

echo [1/6] 更新 JSON...
python batch_update_json.py
if errorlevel 1 (
    echo 错误: 更新 JSON 失败
    
    exit /b 1
)
echo.

echo [2/6] 重建字体 JSON...
cd font
python rebuild_font_json.py
if errorlevel 1 (
    echo 错误: 重建字体 JSON 失败
    cd ..
    
    exit /b 1
)
cd ..
echo.

echo [3/6] 生成字体图片...
cd font
python generate_font_images.py
if errorlevel 1 (
    echo 错误: 生成字体图片失败
    cd ..
    
    exit /b 1
)
cd ..
echo.

echo [4/6] 同步事件 JSON...
cd font
python sync_event_json.py
if errorlevel 1 (
    echo 错误: 同步事件 JSON 失败
    cd ..
    
    exit /b 1
)
cd ..
echo.

echo [5/6] 重建 MSG 文件...
python batch_rebuild.py
if errorlevel 1 (
    echo 错误: 重建 MSG 文件失败
    
    exit /b 1
)
echo.

echo [6/6] 构建 ISO...
REM 尝试删除可能被锁定的 modded.iso 文件
if exist modded.iso (
    echo 正在尝试删除旧的 modded.iso 文件...
    del /f /q modded.iso 2>nul
    if exist modded.iso (
        echo 警告: 无法删除 modded.iso，文件可能被其他程序占用
        echo 请关闭可能使用该文件的程序（如虚拟光驱、文件管理器等）
        timeout /t 2 >nul
    )
)
call build.bat
if errorlevel 1 (
    echo 错误: 构建 ISO 失败
    exit /b 1
)
echo.

echo ========================================
echo 构建完成！
echo ========================================


