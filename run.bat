@echo off
rem Use UTF-8 encoding for correct character display
chcp 65001 > nul
setlocal

:: ==================================================================
:: =                                                                =
:: =             WallpaperEngineLibrary Launcher v2.0             =
:: =                                                                =
:: ==================================================================

title WallpaperEngineLibrary Launcher

:: ------------------------------------------------------------------
:: Step 1: Set Port
:: ------------------------------------------------------------------
:menu_port
cls
echo.
echo  ===================== [ 步骤 1/2: 设置端口 ] =====================
echo.
echo   我们需要为这个程序设置一个“门牌号”, 也就是端口。
echo.
echo   默认是 [9888], 通常不需要修改。
echo.
set /p PORT="  -> 请输入端口号, 或直接按回车使用默认值 (9888): "
if not defined PORT set PORT=9888

echo.
echo   好的, 我们的“门牌号”已设置为: %PORT%
echo.
echo   按任意键继续...
pause > nul
goto menu_access

:: ------------------------------------------------------------------
:: Step 2: Set Access Scope
:: ------------------------------------------------------------------
:menu_access
cls
echo.
echo  ==================== [ 步骤 2/2: 设置访问范围 ] ====================
echo.
echo   请选择谁可以访问这个壁纸库:
echo.
echo    [1] 仅本机访问 (最安全, 只能在您当前使用的这台电脑上打开)
echo.
echo    [2] 局域网访问 (允许您用手机、平板等连接同一 WiFi 的设备访问)
echo.
choice /c 12 /n /m "  -> 请按键盘上的数字 1 或 2 进行选择: "
if errorlevel 2 (
    set HOST=0.0.0.0
    set ACCESS_MODE=局域网访问
    goto start_server
)
if errorlevel 1 (
    set HOST=127.0.0.1
    set ACCESS_MODE=仅本机访问
    goto start_server
)

:: ------------------------------------------------------------------
:: Start Server
:: ------------------------------------------------------------------
:start_server
cls
echo.
echo  ========================= [ 启动中... ] ==========================
echo.
echo   配置已完成, 正在为您启动壁纸库服务...
echo.
echo   您的配置:
echo     - 服务端口: [%PORT%]
echo     - 访问模式: [%ACCESS_MODE%]
echo.
echo   程序启动后, 请在浏览器中打开给出的地址。
echo   请不要关闭这个黑色的命令行窗口。
echo.
echo.

python we_server.py --host %HOST% --port %PORT%

echo.
echo.
echo ========================= [ 服务已停止 ] =========================
echo.
echo  按任意键退出此窗口...
pause
endlocal