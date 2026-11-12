# RPi Door Access con RFID

Control de acceso por tarjetas RFID sobre Raspberry Pi, usado en las duchas del
Parador Km1151. La Raspberry Pi lee la tarjeta, decide si abre la puerta según
el estado, el vencimiento y los créditos de la tarjeta, y ofrece un panel web
para administrar usuarios, empresas y tarjetas.

Hecho con Python, FastAPI, SQLite, HTMX y Alpine.js.

## Qué hace

- Lee tarjetas con un lector MFRC522 y acciona relé, LEDs y buzzer.
- Descuenta un crédito por acceso y registra cada intento.
- Panel web con indicadores, historial en vivo y exportación a CSV.
- Alta y edición de usuarios, empresas y tarjetas (particulares, cuenta
  corriente y ticket de carga).
- Recuperación de tarjetas abandonadas para volver a asignarlas.

## Ramas

| Rama | Contenido |
|---|---|
| `main` | El código que corre en producción en la Raspberry Pi. |
| `desarrollo` | Cambios todavía no desplegados. |
| `produccion-rpi` | Copia histórica del estado de producción al 2026-11-11. |

## Ejecutar en una PC (sin hardware)

Fuera de una Raspberry Pi la aplicación arranca sola en modo simulado: no hay
lector ni relé, pero el panel funciona completo.

```bash
pip install -r requirements.txt
```

```bash
cp .env.example .env
```

```bash
python run.py
```

El panel queda en `http://127.0.0.1:8000`. La contraseña es el valor de
`SUPER_PASSWORD` en `.env`.

## Desplegar en la Raspberry Pi

La guía paso a paso, el archivo del servicio y las conexiones del hardware
están en [`deploy/`](deploy/README.md).

La base de datos, el `.env` real y el token del túnel de acceso remoto no están
en este repositorio; se guardan en un repositorio privado de respaldos.

## Tests

```bash
python -m pytest
```

## Documentación

- [`HELP.md`](HELP.md): manual del operador.
- [`deploy/README.md`](deploy/README.md): instalación y restauración.
- [`docs/PRD.md`](docs/PRD.md): requisitos del producto.
- [`docs/ADRs/`](docs/ADRs/): decisiones de arquitectura.
- [`docs/GPIO.jpeg`](docs/GPIO.jpeg): diagrama de conexiones.
