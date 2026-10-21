# cocina (casa)

Recetario + despensa de la familia (tablet vía el hub `infra/home` y celulares).

## Servidor (`servidor.py`)

- `ThreadingHTTPServer` + `sqlite3`, solo biblioteca estándar, en `127.0.0.1:8772`. Variables `COCINA_BD` y `COCINA_PUERTO` para probar sin tocar los datos reales.
- BD `~/.local/share/casa/cocina.db` (WAL), tablas `recetas`, `despensa`, `codigos`, `meta` (`version`). Las fotos van como BLOB en `recetas.foto` (la página las reduce antes de subirlas, máx. 3 MB) para que el respaldo diario (`infra/respaldos`, copia `*.db`) las incluya sin hacer nada más.
- Ingredientes y pasos se guardan como listas de texto (JSON) tal como se escribieron; al leer una receta se devuelven analizados:
  - `analizar_ingrediente()`: "2 tazas de harina" → nombre "Harina", cantidad "2 tazas" (para mandarlo a la lista de compras). Entiende fracciones (½, 1/2, 1 1/2), números en palabra, unidades comunes y "al gusto"/"opcional".
  - `analizar_paso()`: busca un tiempo ("25 minutos", "1 hora y media", "media hora", "de 3 a 5 min" → el menor) para ofrecer un temporizador.
- Despensa: lugares fijos (`Alacena`, `Refri`, `Congelador`, `Otro`); `hay` marca si queda o se acabó. Agregar algo que ya existe (mismo nombre) lo vuelve a "hay".
- Códigos de barras: `GET /api/codigo/<código>` busca primero en la tabla `codigos` y luego en Open Food Facts (internet, 6 s de espera; 404 = no lo tienen). Lo que no se encuentra se guarda a mano con `POST` y queda para la próxima vez.
- La foto se sirve con caché larga: la página la pide con `?v=<actualizada>`.

## Dónde corre

- Página: https://192.168.1.4/cocina/ (archivos en `/var/www/cocina/`, copiados de `web/`).
- API: nginx publica `/cocina/api/` → `127.0.0.1:8772/api/` con `client_max_body_size` suficiente para las fotos (config en `infra/nginx`).
- Servicio systemd de usuario `cocina.service` (copia en `servicio/`).
