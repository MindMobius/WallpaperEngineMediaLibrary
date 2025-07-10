@echo off
rem 使用UTF-8编码，确保中文字符正确显示
chcp 65001 > nul
setlocal

:: ==================================================================
:: =                                                                =
:: =             WallpaperEngineLibrary 一键启动器 v1.2             =
:: =                                                                =
:: ==================================================================

title WallpaperEngineLibrary Launcher

:: ------------------------------------------------------------------
:: 步骤 1: 选择 Steam 库所在的硬盘
:: ------------------------------------------------------------------
:menu_drive
cls
echo.
echo  ===================== [ 步骤 1/3: 选择硬盘 ] =====================
echo.
echo   为了找到您的壁纸文件, 我需要知道您的 Steam 安装在哪个硬盘上。
echo.
echo   通常是 C, D, E 或 F 盘。
echo.
set /p DRIVE="  -> 请输入 Steam 所在的盘符 (大小写均可, 例如: d): "

:: -- 最简化的输入验证 --
if not defined DRIVE (
    echo.
    echo    [!] 您没有输入任何内容, 请重新输入。
    echo.
    pause
    goto menu_drive
)

set WE_VIEWER_DRIVE=%DRIVE%
echo.
echo   好的, 我会去 [%DRIVE%:] 盘寻找您的壁纸。
echo.
echo   按任意键继续...
pause > nul
goto menu_port

:: ------------------------------------------------------------------
:: 步骤 2: 设置端口号
:: ------------------------------------------------------------------
:menu_port
cls
echo.
echo  ===================== [ 步骤 2/3: 设置端口 ] =====================
echo.
echo   接下来, 我们需要为这个程序设置一个“门牌号”, 也就是端口。
echo   这样您的浏览器才能通过它找到我们的程序。
echo.
echo   默认的门牌号是 [9888], 通常不需要修改。
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
:: 步骤 3: 设置访问范围
:: ------------------------------------------------------------------
:menu_access
cls
echo.
echo  ==================== [ 步骤 3/3: 设置访问范围 ] ====================
echo.
echo   最后, 请选择谁可以访问这个壁纸库:
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
:: 启动服务器
:: ------------------------------------------------------------------
:start_server
cls
echo.
echo  ========================= [ 启动中... ] ==========================
echo.
echo   配置已完成, 正在为您启动壁纸库服务...
echo.
echo   您的配置:
echo     - 目标硬盘: [%WE_VIEWER_DRIVE%:]
echo     - 服务端口: [%PORT%]
echo     - 访问模式: [%ACCESS_MODE%]
echo.
echo   程序启动后, 请不要关闭这个黑色的命令行窗口。
echo   关闭窗口意味着关闭服务。
echo.
echo.

:: 核心执行命令
python we_server.py --host %HOST% --port %PORT%

:: Python 脚本执行结束后 (例如用户按 Ctrl+C 关闭了服务), 代码会继续执行到这里
echo.
echo.
echo ========================= [ 服务已停止 ] =========================
echo.
echo  WallpaperEngineLibrary 服务已成功关闭。
echo.
echo  您可以随时重新双击 run.bat 来启动。
echo.
echo  按任意键退出此窗口...
pause

:: 结束
endlocal