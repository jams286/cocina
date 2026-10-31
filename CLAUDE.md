# cocina (casa)

Tracker: cocina

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

## Página (`web/`)

- Estática, sin frameworks. Navegación por hash (`#/`, `#/receta/<id>`, `#/nueva`, `#/editar/<id>`, `#/despensa`) para que el botón Atrás del celular funcione. `el()` arma el DOM (todo el texto va por `textContent`).
- Receta: casillas por ingrediente + "Agregar marcados a la lista de compras" → `POST ../lista-compras/api/items` con el nombre y la cantidad analizados (uno por uno; avisa si alguno falló). Los pasos con `minutos` traen un enlace a `../temporizadores/?nombre=…&min=…` en pestaña nueva.
- Foto: se reduce en el navegador (canvas, lado máx. 1280 px, JPEG 0.82) antes de `PUT`.
- Despensa: agrupada por lugar; se revisa cada 5 s mientras se ve. "Se acabó" marca `hay=false` y además agrega el producto a la lista de compras.
- Escáner: `BarcodeDetector` nativo si existe (Chrome Android); si no (iPhone/Safari, Firefox) carga `vendor/zxing.min.js` (@zxing/library 0.21.3, Apache 2.0, licencia en `vendor/`) y usa `BrowserMultiFormatReader.decodeFromConstraints`. Formatos EAN-13/8, UPC-A/E, Code 128. Cámara trasera (`facingMode: environment`); necesita HTTPS. Si el código no se conoce, pide el nombre y lo guarda con `POST /api/codigo/<código>`.
- El botón 🎤 de dictado (ingredientes y pasos) usa `../voz/voz.js`; los `<span class="dictar">` del formulario son donde se ponen.
- ✨ IA (servicio `casa/ia`, `../ia/api/`, modelo local, 15 s–1 min, con "Pensando… N s"):
  - "¿Qué cocino con lo que hay en la despensa?" (lista de recetas): manda los productos con `hay` a `sugerir-recetas`; cada sugerencia se puede guardar como receta (usa → ingredientes, idea → paso, nota "Sugerida por la IA…") o mandar sus faltantes a la lista de compras.
  - "Llenar desde un texto" (formulario): pega una receta de WhatsApp/internet → `importar-receta` llena título, porciones, tiempo, ingredientes y pasos (pide confirmar si ya había ingredientes o pasos). Al abrir el diálogo se llama `precalentar` para que el modelo vaya cargando.
