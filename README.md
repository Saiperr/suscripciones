# Suscripciones

Gestor de suscripciones: qué pagas, cuándo se renueva y cuánto gastas al año. App web instalable (PWA), multiusuario, en español.

## Qué hace
- **Panel:** gasto anual y mensual, próximo cobro, gráfica de lo que pagarás los próximos 3, 6 o 12 meses, reparto por categorías y lo que más cuesta.
- **Varias monedas:** cada importe se guarda en su moneda original y se convierte al mostrar, con los tipos de cambio del BCE ([Frankfurter](https://frankfurter.dev)). Si la fuente falla, usa los últimos tipos guardados.
- **Renovaciones correctas:** periodicidad en días, semanas, meses o años, con el día de cobro anclado (un cobro el 31 cae el 28/29 en febrero y vuelve al 31 en marzo).
- **Avisos por email** antes de cada renovación y al acabar una prueba gratuita (sin duplicados).
- **Multiusuario** con registro por código de invitación y datos totalmente separados por usuario.
- Calendario ICS privado, exportación a CSV, historial de cambios de precio.

## Pila
Python 3.12 · FastAPI · Jinja2 · SQLite · Docker. Sin JavaScript de terceros ni fuentes externas.

## Puesta en marcha
```bash
cp .env.example .env        # y rellena SECRET_KEY e INVITE_CODE
docker compose up -d --build
```
La app queda en el puerto `8084`. Para uso real, ponla detrás de un proxy con HTTPS (con `COOKIE_SECURE=1`, el login solo funciona por HTTPS).

Los datos viven en `./data/app.db`. Haz copia de esa carpeta.

## Pruebas
```bash
pip install -r requirements.txt
python tests/test_dates.py && python tests/test_proj.py && python tests/test_app.py
```

## Seguridad
Contraseñas con Argon2, CSRF en todos los formularios, límite de intentos de login y registro, cabeceras CSP y cada consulta filtrada por usuario. Usa un solo proceso (`--workers 1`) porque el planificador de avisos corre dentro de la app.
