# Firmware ESP32-CAM

Firmware propio: 320x240 en grises, JPEG calidad 50, tope de 10 FPS, servidor de un solo cliente.

## Preparación
1. `cp secrets.example.h secrets.h` y completar `WIFI_SSID` / `WIFI_PASS` (`secrets.h` está fuera de git).
2. Compilar y cargar el firmware desde el entorno de Arduino/PlatformIO (el código fuente se añadirá aquí).

## Endpoints
- `/stream`: `multipart/x-mixed-replace`, boundary `frame`. Cabeceras por parte: `X-Capture-Us`, `X-Jpeg-Us`, `X-Rssi-Dbm`.
- `/capture`: JPEG con `Connection: close`. Cabeceras: `X-Capture-Us`, `X-Jpeg-Us`, `X-Rssi-Dbm`, `X-Flush-Us`.
- `/status`: JSON con `fw` (versión de firmware) y RSSI. Consultar solo con el stream cerrado.

Semántica distinta por endpoint: ver `docs/DISENO.md`.
