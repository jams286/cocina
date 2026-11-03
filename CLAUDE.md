# cocina (casa)

Tracker: cocina

Recetario + despensa de la familia (tablet vía el hub `infra/home` y celulares).

## Servidor (`servidor.py`)

- `ThreadingHTTPServer` + `sqlite3`, solo biblioteca estándar, en `127.0.0.1:8772`. Variables `COCINA_BD` y `COCINA_PUERTO` para probar sin tocar los datos reales.
- BD `~/.local/share/casa/cocina.db` (WAL), tablas `recetas`, `despensa`, `codigos`, `meta` (`version`). Las fotos van como BLOB en `recetas.foto` (la página las reduce antes de subirlas, máx. 3 MB) para que el respaldo diario (`infra/respaldos`, copia `*.db`) las incluya sin hacer nada más.
- Ingredientes y pasos se guardan como listas de texto (JSON) tal como se escribieron; al leer una receta se devuelven analizados:
  - `analizar_ingrediente()`: "2 tazas de harina" → nombre "Harina", cantidad "2 tazas" (para mandarlo a la lista de compras). Entiende fracciones (½, 1/2, 1 1/2), números en palabra, unidades comunes y "al gusto"/"opcional".
  - `GET /api/recetas/<id>?porciones=N` escala los ingredientes (v2): `numero_porciones()` toma el primer número de `porciones` ("8 hamburguesas" → 8) como base; `escalar()` reescribe el texto ("1 tomate" x2 → "2 tomates", 1000 g → 1 kg). Sin número en porciones no se escala. Devuelve `porciones_base` y `porciones_ver`.
  - Cada ingrediente trae `compra` = lo que se manda a la lista (`comprable()`): medidas de cocina (taza, cucharada, hoja, diente, pizca…) van sin cantidad (se compra el producto); g/kg/l/ml tal cual (≥1000 g → kg); piezas y latas/paquetes redondeadas hacia arriba (1/2 limón → 1).
  - `derivado` (`es_derivado()`): "… de la lata", "del frasco", "reservado", o "X del/de los Y" cuando Y está en otro ingrediente ("jugo de los pepinillos"). Sale desmarcado al mandar a la lista.
  - `enviada_en` / `enviada_porciones` (`POST /api/recetas/<id>/enviada`): cuándo se mandó por última vez a la lista, para avisar antes de mandarla otra vez. No cambia `actualizada` (es la clave de caché de la foto).
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
- Receta: ingredientes sin casillas; chip de porciones con − / + que vuelve a pedir la receta escalada (sin "Cargando…" para no saltar el scroll).
- "🛒 Mandar a la lista de compras…" (al final de los ingredientes) abre la hoja `#hoja-lista`: casillas con lo comprable, derivados desmarcados, aviso amarillo si ya se mandó ("hoy a las 14:30 (para 8)…") y "Agregar N". Manda `compra` a `POST ../lista-compras/api/items` uno por uno (la lista suma repetidos) y luego marca la receta como enviada. Así un toque por error no manda nada (idea #44 del tracker). Los pasos con `minutos` traen un enlace a `../temporizadores/?nombre=…&min=…` en pestaña nueva.
- Foto: se reduce en el navegador (canvas, lado máx. 1280 px, JPEG 0.82) antes de `PUT`.
- Despensa: agrupada por lugar; se revisa cada 5 s mientras se ve. "Se acabó" marca `hay=false` y además agrega el producto a la lista de compras.
- Escáner: `BarcodeDetector` nativo si existe (Chrome Android); si no (iPhone/Safari, Firefox) carga `vendor/zxing.min.js` (@zxing/library 0.21.3, Apache 2.0, licencia en `vendor/`) y usa `BrowserMultiFormatReader.decodeFromConstraints`. Formatos EAN-13/8, UPC-A/E, Code 128. Cámara trasera (`facingMode: environment`); necesita HTTPS. Si el código no se conoce, pide el nombre y lo guarda con `POST /api/codigo/<código>`.
- El botón 🎤 de dictado (ingredientes y pasos) usa `../voz/voz.js`; los `<span class="dictar">` del formulario son donde se ponen.
- ✨ IA (servicio `casa/ia`, `../ia/api/`, modelo local, 15 s–1 min, con "Pensando… N s"):
  - "¿Qué cocino con lo que hay en la despensa?" (lista de recetas): manda los productos con `hay` a `sugerir-recetas`; cada sugerencia se puede guardar como receta (usa → ingredientes, idea → paso, nota "Sugerida por la IA…") o mandar sus faltantes a la lista de compras.
  - "Llenar desde un texto" (formulario): pega una receta de WhatsApp/internet → `importar-receta` llena título, porciones, tiempo, ingredientes y pasos (pide confirmar si ya había ingredientes o pasos). Al abrir el diálogo se llama `precalentar` para que el modelo vaya cargando.

## Pruebas

- `python3 -m unittest -v` (`test_servidor.py`, BD temporal): comprable, escalar, derivados, porciones y enviada.
- UI: Playwright (venv de `personal/rm-ecommerce`) contra servidores de prueba con `COCINA_BD`/`COCINA_PUERTO` (copia de la BD con `sqlite3.backup`) y un proxy que imite a nginx con la lista de compras al lado.
