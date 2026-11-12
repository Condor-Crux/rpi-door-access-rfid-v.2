# Guía de despliegue en Raspberry Pi

Pasos para dejar una Raspberry Pi funcionando igual que la de producción,
partiendo de una tarjeta SD nueva. Esta guía reproduce la instalación actual
(relevada el 2026-11-12), no una instalación idealizada.

## Entorno de referencia

| | |
|---|---|
| Equipo | Raspberry Pi 3 Model B Rev 1.2 |
| Sistema | Raspberry Pi OS (Debian 13 "trixie"), 64 bits |
| Python | 3.13 del sistema (`/usr/bin/python3`), sin entorno virtual |
| Usuario | `kodex`, en los grupos `gpio` y `spi` |
| Carpeta del proyecto | `/home/kodex/rpi-door-access-rfid` |
| Servicio | `rpi-door-access.service`, puerto 8000 |
| Zona horaria | `America/Argentina/Buenos_Aires` |

Si el usuario o la carpeta cambian, hay que ajustar `User`, `Group` y
`WorkingDirectory` en [`rpi-door-access.service`](rpi-door-access.service).

## Qué no está en este repositorio

Estos elementos son necesarios y se guardan aparte, en el repositorio privado
de respaldos (`Condor-Crux/rpi-door-access-backups`):

- el archivo `.env` real (contraseña de administrador y clave de sesiones);
- la base de datos `rpi_door_access.db` (usuarios, tarjetas, créditos, historial);
- el token del túnel de Cloudflare.

## 1. Preparar el sistema

1. Grabar Raspberry Pi OS de 64 bits y crear el usuario `kodex`.
2. Habilitar SPI (lo usa el lector MFRC522):

   ```bash
   sudo raspi-config nonint do_spi 0
   ```

   Equivale a tener `dtparam=spi=on` en `/boot/firmware/config.txt`. Tras
   reiniciar deben existir `/dev/spidev0.0` y `/dev/spidev0.1`.
3. Fijar la zona horaria:

   ```bash
   sudo timedatectl set-timezone America/Argentina/Buenos_Aires
   ```

4. Instalar los paquetes del sistema:

   ```bash
   sudo apt update
   ```

   ```bash
   sudo apt install -y git python3-pip python3-lgpio sqlite3
   ```

   `python3-lgpio` es la librería que usa `gpiozero` para manejar los pines en
   este sistema. No está en `requirements.txt` porque se instala con `apt`.
5. Confirmar que el usuario está en los grupos correctos (`gpio` y `spi`):

   ```bash
   id -nG
   ```

## 2. Obtener el código

```bash
git clone https://github.com/Condor-Crux/rpi-door-access-rfid-v.2.git ~/rpi-door-access-rfid
```

```bash
cd ~/rpi-door-access-rfid
```

El CSS compilado (`app/static/dist/app.css`) está versionado, así que no hace
falta Node ni Tailwind para desplegar.

## 3. Instalar las dependencias de Python

En producción las dependencias están instaladas para el usuario, sobre el
Python del sistema:

```bash
python3 -m pip install --user --break-system-packages -r requirements.txt
```

`--break-system-packages` es necesario porque Debian 13 bloquea `pip` fuera de
un entorno virtual. El servicio llama a `/usr/bin/python3`, por eso no se usa
un `.venv`.

## 4. Configurar `.env`

Para restaurar producción, copiar el `.env` guardado en el repositorio privado
de respaldos a `~/rpi-door-access-rfid/.env`.

Para una instalación nueva:

```bash
cp .env.example .env
```

Después editar `.env` y cambiar `SUPER_PASSWORD` y `JWT_SECRET_KEY`. Una clave
de sesiones nueva se genera así:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

No dejar los valores de ejemplo: `.env.example` es público, y con esa clave
cualquiera puede fabricar una sesión de administrador válida.

## 5. Restaurar la base de datos

Sin base de datos la aplicación crea una vacía al arrancar. Para recuperar los
usuarios y tarjetas, copiar el respaldo más reciente del repositorio privado:

```bash
cp rpi_door_access_AAAA-MM-DD.db ~/rpi-door-access-rfid/rpi_door_access.db
```

Hacerlo con el servicio detenido, y borrar antes `rpi_door_access.db-wal` y
`rpi_door_access.db-shm` si existen.

## 6. Instalar el servicio

```bash
sudo cp deploy/rpi-door-access.service /etc/systemd/system/
```

```bash
sudo systemctl daemon-reload
```

```bash
sudo systemctl enable --now rpi-door-access
```

El servicio espera 5 segundos antes de arrancar, escucha en `0.0.0.0:8000` y
se reinicia solo si falla.

## 7. Verificar

```bash
systemctl status rpi-door-access
```

```bash
journalctl -u rpi-door-access -n 30 --no-pager
```

En el registro debe aparecer `hardware mode: GPIO`. Si dice `MOCK`, la
aplicación no reconoció el equipo como Raspberry Pi y no va a manejar el
lector ni el relé.

Después abrir `http://<IP_DE_LA_RPI>:8000`, iniciar sesión y pasar una tarjeta
por el lector: debe aparecer el evento en el Dashboard.

## 8. Acceso remoto (túnel de Cloudflare)

Producción publica el panel a través de un túnel de `cloudflared`, que corre
como servicio aparte. El servicio de la aplicación ya está preparado para eso
(`--proxy-headers --forwarded-allow-ips 127.0.0.1`).

1. Instalar `cloudflared` desde el repositorio `apt` de Cloudflare.
2. Registrar el servicio con el token del túnel (guardado en el repositorio
   privado):

   ```bash
   sudo cloudflared service install <TOKEN>
   ```

3. Comprobar:

   ```bash
   systemctl status cloudflared
   ```

Este paso es opcional: sin el túnel, el panel sigue disponible en la red local.

## Conexiones del hardware

Numeración BCM. Los valores son los de `app/core/config.py` y se pueden
cambiar desde `.env`. El diagrama está en [`docs/GPIO.jpeg`](../docs/GPIO.jpeg).

| Función | Pin (BCM) | Variable |
|---|---|---|
| Relé de la puerta | 17 | `RELAY_PIN` |
| LED verde | 27 | `LED_GREEN_PIN` |
| LED rojo | 18 | `LED_RED_PIN` |
| Buzzer | 22 | `BUZZER_PIN` |
| MFRC522 RST | 25 | `RFID_RST_PIN` |
| MFRC522 SDA, SCK, MOSI, MISO | bus SPI0 (CE0) | — |

## Actualizar una instalación existente

```bash
cd ~/rpi-door-access-rfid
```

```bash
git pull
```

```bash
sudo systemctl restart rpi-door-access
```

Si cambió `requirements.txt`, repetir antes el paso 3.

## Respaldar la base de datos

La copia se puede sacar con el servicio en marcha:

```bash
sqlite3 ~/rpi-door-access-rfid/rpi_door_access.db ".backup '/tmp/rpi_door_access_backup.db'"
```

No copiar el archivo `.db` directamente mientras la aplicación corre: los
cambios recientes están en el archivo `-wal` y la copia quedaría incompleta.
