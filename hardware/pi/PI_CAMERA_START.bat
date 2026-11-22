@echo off
chcp 65001 >nul
set SCRIPT=%~dp0pi_camera_setup.sh
for %%H in (172.20.10.3 warirak.local raspberrypi.local) do (
  echo Trying warirak@%%H ...
  ssh -o ConnectTimeout=6 -o StrictHostKeyChecking=accept-new warirak@%%H "bash -s" < "%SCRIPT%" && goto done
)
echo.
echo Could not reach the Pi. Check that the Pi and this PC are on the same Wi-Fi.
:done
echo.
pause
