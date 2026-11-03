"""Servicio de la cocina: recetas (con foto) y despensa, API JSON sobre SQLite.

Escucha solo en 127.0.0.1; nginx publica /cocina/api/ -> /api/.
Sin dependencias externas (solo la biblioteca estándar).

    python3 servidor.py

La página se conecta con otras tools desde el navegador (misma máquina):
la lista de compras (/lista-compras/api/) y los temporizadores (/temporizadores/?...).

Rutas:
    GET    /api/recetas                     resumen de todas (sin fotos)
    POST   /api/recetas                     {"titulo", "porciones", "tiempo", "ingredientes": [..], "pasos": [..], "notas"}
    GET    /api/recetas/<id>[?porciones=N]  completa; ingredientes (escalados a N porciones) y pasos ya analizados
    POST   /api/recetas/<id>/enviada        {"porciones"?}  anota que se mandó a la lista de compras
    PATCH  /api/recetas/<id>                mismos campos que POST
    DELETE /api/recetas/<id>
    PUT    /api/recetas/<id>/foto           cuerpo = imagen JPEG/PNG/WebP (la página la reduce antes)
    DELETE /api/recetas/<id>/foto
    GET    /api/recetas/<id>/foto           la imagen
    GET    /api/despensa                    {"version", "items"}
    POST   /api/despensa                    {"nombre", "cantidad"?, "lugar"?, "codigo"?}  (si ya existe, vuelve a "hay")
    PATCH  /api/despensa/<id>               {"hay"?, "nombre"?, "cantidad"?, "lugar"?}
    DELETE /api/despensa/<id>
    GET    /api/codigo/<codigo>             nombre del producto: primero lo guardado, luego Open Food Facts
    POST   /api/codigo/<codigo>             {"nombre"}  guarda el nombre de un código que no se encontró
"""

import json
import os
import re
import sqlite3
import threading
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime
from fractions import Fraction
from math import ceil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

HOST = '127.0.0.1'
# Se pueden cambiar para pruebas sin tocar los datos reales
PUERTO = int(os.environ.get('COCINA_PUERTO', 8772))
BD = Path(os.environ.get('COCINA_BD', Path.home() / '.local/share/casa/cocina.db'))
MAX_JSON = 64 * 1024
MAX_FOTO = 3 * 1024 * 1024
LUGARES = ('Alacena', 'Refri', 'Congelador', 'Otro')
OFF_URL = 'https://world.openfoodfacts.org/api/v2/product/{}.json?fields=product_name,product_name_es,brands,quantity'
OFF_AGENTE = 'CasaJams/1.0 (herramienta familiar local)'

candado = threading.Lock()


# ---------- Base de datos ----------

def conectar():
    con = sqlite3.connect(BD, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def preparar_bd():
    BD.parent.mkdir(parents=True, exist_ok=True)
    with conectar() as con:
        con.executescript('''
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS recetas (
                id           INTEGER PRIMARY KEY,
                titulo       TEXT NOT NULL,
                porciones    TEXT NOT NULL DEFAULT '',
                tiempo       TEXT NOT NULL DEFAULT '',
                ingredientes TEXT NOT NULL DEFAULT '[]',   -- JSON: lista de textos
                pasos        TEXT NOT NULL DEFAULT '[]',   -- JSON: lista de textos
                notas        TEXT NOT NULL DEFAULT '',
                foto         BLOB,
                foto_tipo    TEXT,
                creada       TEXT NOT NULL,
                actualizada  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS despensa (
                id          INTEGER PRIMARY KEY,
                nombre      TEXT NOT NULL,
                cantidad    TEXT NOT NULL DEFAULT '',
                lugar       TEXT NOT NULL DEFAULT 'Alacena',
                codigo      TEXT,
                hay         INTEGER NOT NULL DEFAULT 1,
                actualizado TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS codigos (
                codigo      TEXT PRIMARY KEY,
                nombre      TEXT NOT NULL,
                origen      TEXT NOT NULL,      -- 'openfoodfacts' | 'manual'
                actualizado TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor INTEGER NOT NULL);
            INSERT OR IGNORE INTO meta (clave, valor) VALUES ('version', 0);
        ''')
        columnas = {f[1] for f in con.execute('PRAGMA table_info(recetas)')}
        if 'enviada_en' not in columnas:
            # Cuándo y para cuántas porciones se mandó por última vez a la lista de compras
            con.execute('ALTER TABLE recetas ADD COLUMN enviada_en TEXT')
            con.execute('ALTER TABLE recetas ADD COLUMN enviada_porciones INTEGER')


def ahora():
    return datetime.now().isoformat(timespec='seconds')


def subir_version(con):
    con.execute("UPDATE meta SET valor = valor + 1 WHERE clave = 'version'")


def version(con):
    return con.execute("SELECT valor FROM meta WHERE clave = 'version'").fetchone()[0]


def limpiar(valor, maximo):
    if not isinstance(valor, str):
        return ''
    return re.sub(r'\s+', ' ', valor).strip()[:maximo]


def limpiar_lista(valor, maximo_items, maximo_texto):
    if not isinstance(valor, list):
        raise ValueError('Se esperaba una lista')
    return [t for t in (limpiar(v, maximo_texto) for v in valor[:maximo_items]) if t]


# ---------- Ingredientes y pasos ----------

FRACCIONES = {'½': '1/2', '⅓': '1/3', '⅔': '2/3', '¼': '1/4', '¾': '3/4', '⅛': '1/8'}
PALABRAS_NUM = {'un': '1', 'una': '1', 'uno': '1', 'dos': '2', 'tres': '3', 'cuatro': '4', 'cinco': '5',
                'seis': '6', 'siete': '7', 'ocho': '8', 'nueve': '9', 'diez': '10', 'media': '1/2', 'medio': '1/2'}
UNIDADES = (r'tazas?|cucharadas?|cucharaditas?|cdas?\.?|cdtas?\.?|gramos?|gr?\.?|kilos?|kg\.?|libras?|lbs?\.?|'
            r'onzas?|oz\.?|ml\.?|mililitros?|litros?|l\.?|latas?|paquetes?|bolsas?|sobres?|dientes?|pizcas?|'
            r'manojos?|ramitas?|rodajas?|rebanadas?|unidades?|botellas?|vasos?|chorritos?|puñados?|hojas?')
NUMERO = r'(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?)'


def analizar_ingrediente(texto):
    """'2 tazas de harina' -> {'texto', 'nombre': 'Harina', 'cantidad': '2 tazas'} (para la lista de compras)."""
    t = texto
    for simbolo, fraccion in FRACCIONES.items():
        t = t.replace(simbolo, f' {fraccion}')
    t = re.sub(r'\s+', ' ', t).strip()
    # "Sal al gusto", "Aceite (opcional)"
    t = re.sub(r'\s*(,\s*)?\(?(al gusto|opcional|c/n|cantidad necesaria)\)?\s*$', '', t, flags=re.IGNORECASE)

    cantidad = unidad = ''
    m = re.match(rf'^(?P<num>{NUMERO}|{"|".join(PALABRAS_NUM)})\s+(?P<resto>.+)$', t, flags=re.IGNORECASE)
    if m:
        num = PALABRAS_NUM.get(m['num'].lower(), m['num'])
        resto = m['resto']
        u = re.match(rf'^(?P<unidad>{UNIDADES})(?:\s+de)?\s+(?P<nombre>.+)$', resto, flags=re.IGNORECASE)
        if u:
            unidad, nombre = u['unidad'], u['nombre']
            cantidad = f"{num} {unidad}"
        else:
            cantidad, nombre = num, re.sub(r'^de\s+', '', resto, flags=re.IGNORECASE)
        nombre = re.sub(r'^del\s+', '', nombre, flags=re.IGNORECASE)    # "1 cucharada del adobo"
    else:
        nombre = t
    nombre = nombre.strip(' ,.;:') or texto
    return {'texto': texto, 'nombre': nombre[0].upper() + nombre[1:], 'cantidad': cantidad,
            'num': leer_numero(num) if m else None, 'unidad': unidad}


def leer_numero(texto):
    """'1 1/2' -> Fraction(3, 2); '0,5' -> Fraction(1, 2)."""
    partes = texto.replace(',', '.').split()
    try:
        return sum((Fraction(p) for p in partes), Fraction(0))
    except (ValueError, ZeroDivisionError):
        return None


def escribir_numero(n):
    if n.denominator == 1:
        return str(n.numerator)
    if n.denominator in (2, 3, 4):
        entero, resto = divmod(n.numerator, n.denominator)
        return f'{entero} {resto}/{n.denominator}' if entero else f'{resto}/{n.denominator}'
    return f'{float(n):.2f}'.rstrip('0').rstrip('.')


def _sin_tildes(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')


def plural(palabra):
    """Plural sencillo: taza -> tazas, limón -> limones, nuez -> nueces. Las abreviaturas (g, kg, ml) no cambian."""
    if len(palabra) <= 2 or palabra.endswith('.') or palabra[-1] in 'sS':
        return palabra
    if palabra.endswith('z'):
        return palabra[:-1] + 'ces'
    if palabra[-1] in 'aeiouáéíóú':
        return palabra + 's'
    base = palabra[:-2] + _sin_tildes(palabra[-2:]) if palabra[-2] in 'áéíóú' else palabra   # limón -> limon
    return base + 'es'


def singular(palabra):
    """latas -> lata, unidades -> unidad (para unidades escritas en plural con cantidad 1)."""
    if len(palabra) <= 3 or not palabra.endswith('s'):
        return palabra
    return palabra[:-2] if palabra.endswith('des') else palabra[:-1]


def _clave_unidad(unidad):
    return singular(_sin_tildes(unidad.lower()).rstrip('.'))


# Medidas de cocina: no se compran así, se compra el producto ("1/2 taza de mayonesa" -> "Mayonesa")
MEDIDAS_COCINA = {'taza', 'cucharada', 'cucharadita', 'cda', 'cdas', 'cdta', 'cdtas', 'pizca', 'hoja', 'ramita',
                  'rodaja', 'rebanada', 'vaso', 'chorrito', 'puñado', 'diente'}
PESOS = {'g', 'gr', 'gramo', 'kg', 'kilo', 'libra', 'lb', 'lbs', 'onza', 'oz', 'ml', 'mililitro', 'litro', 'l'}


def comprable(ing, factor=Fraction(1)):
    """Lo que se manda a la lista: medidas de cocina sin cantidad, pesos tal cual, piezas redondeadas hacia arriba."""
    nombre, num, unidad = ing['nombre'], ing['num'], ing['unidad']
    if num is None:
        return {'nombre': nombre, 'cantidad': ''}
    n = num * factor
    u = _clave_unidad(unidad) if unidad else ''
    if u in MEDIDAS_COCINA:
        return {'nombre': nombre, 'cantidad': ''}
    if u in PESOS:
        if u in ('g', 'gr', 'gramo', 'ml', 'mililitro'):
            n = Fraction(ceil(n))
            if n >= 1000:   # 1000 g -> 1 kg, 1500 ml -> 1 1/2 l
                n, unidad = n / 1000, 'kg' if u != 'ml' and u != 'mililitro' else 'l'
        return {'nombre': nombre, 'cantidad': f'{escribir_numero(n)} {singular(unidad) if n <= 1 else plural(unidad)}'}
    piezas = max(1, ceil(n))
    return {'nombre': nombre, 'cantidad': f'{piezas} {singular(unidad) if piezas == 1 else plural(unidad)}'.strip()}


def escalar(ing, factor):
    """El texto del ingrediente con la cantidad multiplicada: '1/2 taza de mayonesa' x2 -> '1 taza de mayonesa'."""
    if factor == 1 or ing['num'] is None:
        return ing['texto'], ing['cantidad']
    n = ing['num'] * factor
    numero = escribir_numero(n)
    if ing['unidad']:
        u = _clave_unidad(ing['unidad'])
        if u in ('g', 'gr', 'gramo', 'ml', 'mililitro') and n >= 1000:   # 1000 g -> 1 kg
            n, ing = n / 1000, {**ing, 'unidad': 'l' if u in ('ml', 'mililitro') else 'kg'}
            numero = escribir_numero(n)
        unidad = singular(ing['unidad']) if n <= 1 else plural(ing['unidad'])
        cantidad = f'{numero} {unidad}'
        resto = ing['nombre'][0].lower() + ing['nombre'][1:]
        return f'{cantidad} de {resto}', cantidad
    # Sin unidad, la primera palabra es la cosa: "1 tomate" x2 -> "2 tomates"
    palabras = (ing['nombre'][0].lower() + ing['nombre'][1:]).split(' ', 1)
    if n > 1:
        palabras[0] = plural(palabras[0])
    return f"{numero} {' '.join(palabras)}", numero


def _raices(texto):
    t = _sin_tildes(texto.lower())
    return {re.sub(r'(es|s)$', '', w) for w in re.findall(r'[a-zñ]{4,}', t)}


RE_DERIVADO = re.compile(r'\b(?:de la lata|del frasco|de la cocci[oó]n|reservad[oa]s?)\b', re.IGNORECASE)
RE_DE_OTRO = re.compile(r'\b(?:del|de la|de las|de los)\s+(.+)$', re.IGNORECASE)


def es_derivado(ing, otros):
    """'Jugo de los pepinillos', 'adobo de la lata': sale de otro ingrediente, no se compra aparte."""
    if RE_DERIVADO.search(ing['texto']):
        return True
    m = RE_DE_OTRO.search(ing['nombre'])
    if not m:
        return False
    cola = _raices(m[1])
    return any(cola & _raices(o['nombre']) for o in otros if o is not ing)


def numero_porciones(texto):
    """'8 hamburguesas' -> 8; 'para 4' -> 4; sin número -> None."""
    m = re.search(r'\d+', texto or '')
    return int(m[0]) if m and int(m[0]) > 0 else None


def analizar_paso(texto):
    """Busca un tiempo en el paso ('hornear 25 minutos', '1 hora y media') para ofrecer un temporizador."""
    minutos = None
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:a\s*\d+\s*)?(h|hrs?|horas?)\b(\s+y\s+media)?', texto, flags=re.IGNORECASE)
    if m:
        minutos = float(m.group(1).replace(',', '.')) * 60 + (30 if m.group(3) else 0)
    m2 = re.search(r'(\d+)\s*(?:a\s*(\d+)\s*)?(min|mins|minutos?)\b', texto, flags=re.IGNORECASE)
    if m2:
        # "20 a 25 minutos": se usa el menor, para revisar a tiempo (siempre se puede sumar 1 min)
        minutos = (minutos or 0) + int(m2.group(1))
    if minutos is None and re.search(r'\bmedia hora\b', texto, flags=re.IGNORECASE):
        minutos = 30
    return {'texto': texto, 'minutos': round(minutos) if minutos else None}


# ---------- Recetas ----------

def fila_resumen(f):
    return {'id': f['id'], 'titulo': f['titulo'], 'porciones': f['porciones'], 'tiempo': f['tiempo'],
            'foto': bool(f['tiene_foto']), 'actualizada': f['actualizada']}


def listar_recetas():
    with conectar() as con:
        filas = con.execute('''
            SELECT id, titulo, porciones, tiempo, foto IS NOT NULL AS tiene_foto, actualizada
            FROM recetas ORDER BY titulo COLLATE NOCASE
        ''').fetchall()
        return {'version': version(con), 'recetas': [fila_resumen(f) for f in filas]}


def leer_receta(con, receta_id, porciones=None):
    f = con.execute('''
        SELECT id, titulo, porciones, tiempo, ingredientes, pasos, notas,
               foto IS NOT NULL AS tiene_foto, actualizada, enviada_en, enviada_porciones
        FROM recetas WHERE id = ?
    ''', (receta_id,)).fetchone()
    if not f:
        raise LookupError('Esa receta ya no existe')
    receta = fila_resumen(f)
    receta['notas'] = f['notas']
    receta['enviada_en'] = f['enviada_en']
    receta['enviada_porciones'] = f['enviada_porciones']
    # Porciones: las de la receta (base) y para cuántas se quiere cocinar (escala los ingredientes)
    base = numero_porciones(f['porciones'])
    ver = porciones if base and porciones and 1 <= porciones <= 100 else base
    factor = Fraction(ver, base) if base else Fraction(1)
    receta['porciones_base'], receta['porciones_ver'] = base, ver
    ingredientes = [analizar_ingrediente(t) for t in json.loads(f['ingredientes'])]
    for ing in ingredientes:
        ing['derivado'] = es_derivado(ing, ingredientes)
    for ing in ingredientes:
        ing['texto'], ing['cantidad'] = escalar(ing, factor)
        ing['compra'] = comprable(ing, factor)
        del ing['num'], ing['unidad']
    receta['ingredientes'] = ingredientes
    receta['pasos'] = [analizar_paso(t) for t in json.loads(f['pasos'])]
    return receta


def datos_receta(datos, parcial):
    campos = {}
    if not parcial or 'titulo' in datos:
        titulo = limpiar(datos.get('titulo'), 100)
        if not titulo:
            raise ValueError('Falta el nombre de la receta')
        campos['titulo'] = titulo
    for campo, maximo in (('porciones', 30), ('tiempo', 30)):
        if not parcial or campo in datos:
            campos[campo] = limpiar(datos.get(campo), maximo)
    if not parcial or 'notas' in datos:
        notas = datos.get('notas') if isinstance(datos.get('notas'), str) else ''
        campos['notas'] = notas.strip()[:2000]
    if not parcial or 'ingredientes' in datos:
        campos['ingredientes'] = json.dumps(limpiar_lista(datos.get('ingredientes', []), 80, 120), ensure_ascii=False)
    if not parcial or 'pasos' in datos:
        campos['pasos'] = json.dumps(limpiar_lista(datos.get('pasos', []), 60, 600), ensure_ascii=False)
    return campos


def crear_receta(datos):
    campos = datos_receta(datos, parcial=False)
    with candado, conectar() as con:
        cur = con.execute(f'''
            INSERT INTO recetas ({", ".join(campos)}, creada, actualizada)
            VALUES ({", ".join("?" * len(campos))}, ?, ?)
        ''', (*campos.values(), ahora(), ahora()))
        subir_version(con)
        return leer_receta(con, cur.lastrowid)


def cambiar_receta(receta_id, datos):
    campos = datos_receta(datos, parcial=True)
    if not campos:
        raise ValueError('Nada que cambiar')
    with candado, conectar() as con:
        asignar = ', '.join(f'{c} = ?' for c in campos)
        cur = con.execute(f'UPDATE recetas SET {asignar}, actualizada = ? WHERE id = ?',
                          (*campos.values(), ahora(), receta_id))
        if not cur.rowcount:
            raise LookupError('Esa receta ya no existe')
        subir_version(con)
        return leer_receta(con, receta_id)


def marcar_enviada(receta_id, datos):
    porciones = datos.get('porciones')
    porciones = porciones if isinstance(porciones, int) and 1 <= porciones <= 100 else None
    with candado, conectar() as con:
        cur = con.execute('UPDATE recetas SET enviada_en = ?, enviada_porciones = ? WHERE id = ?',
                          (ahora(), porciones, receta_id))
        if not cur.rowcount:
            raise LookupError('Esa receta ya no existe')
        return leer_receta(con, receta_id, porciones)


def porciones_pedidas(handler):
    valor = parse_qs(urlsplit(handler.path).query).get('porciones', [''])[0]
    return int(valor) if valor.isdigit() else None


def borrar_receta(receta_id):
    with candado, conectar() as con:
        if con.execute('DELETE FROM recetas WHERE id = ?', (receta_id,)).rowcount:
            subir_version(con)
    return listar_recetas()


def tipo_imagen(datos):
    if datos[:3] == b'\xff\xd8\xff':
        return 'image/jpeg'
    if datos[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    if datos[:4] == b'RIFF' and datos[8:12] == b'WEBP':
        return 'image/webp'
    return None


def guardar_foto(receta_id, imagen):
    tipo = tipo_imagen(imagen)
    if not tipo:
        raise ValueError('La foto debe ser JPEG, PNG o WebP')
    with candado, conectar() as con:
        cur = con.execute('UPDATE recetas SET foto = ?, foto_tipo = ?, actualizada = ? WHERE id = ?',
                          (imagen, tipo, ahora(), receta_id))
        if not cur.rowcount:
            raise LookupError('Esa receta ya no existe')
        subir_version(con)
        return leer_receta(con, receta_id)


def quitar_foto(receta_id):
    with candado, conectar() as con:
        cur = con.execute('UPDATE recetas SET foto = NULL, foto_tipo = NULL, actualizada = ? WHERE id = ?',
                          (ahora(), receta_id))
        if not cur.rowcount:
            raise LookupError('Esa receta ya no existe')
        subir_version(con)
        return leer_receta(con, receta_id)


def leer_foto(receta_id):
    with conectar() as con:
        f = con.execute('SELECT foto, foto_tipo FROM recetas WHERE id = ?', (receta_id,)).fetchone()
    if not f or f['foto'] is None:
        raise LookupError('Sin foto')
    return f['foto'], f['foto_tipo']


# ---------- Despensa ----------

def leer_despensa(con):
    filas = con.execute('''
        SELECT id, nombre, cantidad, lugar, codigo, hay, actualizado FROM despensa
        ORDER BY hay DESC, lugar, nombre COLLATE NOCASE
    ''').fetchall()
    return {'version': version(con), 'lugares': LUGARES,
            'items': [dict(f, hay=bool(f['hay'])) for f in filas]}


def validar_lugar(lugar):
    if lugar not in LUGARES:
        raise ValueError('Lugar inválido')
    return lugar


def agregar_despensa(datos):
    nombre = limpiar(datos.get('nombre'), 60)
    if not nombre:
        raise ValueError('Falta el nombre')
    cantidad = limpiar(datos.get('cantidad'), 20)
    lugar = validar_lugar(datos.get('lugar') or 'Alacena')
    codigo = limpiar(datos.get('codigo'), 32) or None
    with candado, conectar() as con:
        existente = con.execute('SELECT id FROM despensa WHERE lower(nombre) = lower(?)', (nombre,)).fetchone()
        if existente:
            con.execute('''UPDATE despensa SET hay = 1, cantidad = coalesce(nullif(?, ''), cantidad),
                           codigo = coalesce(?, codigo), actualizado = ? WHERE id = ?''',
                        (cantidad, codigo, ahora(), existente['id']))
        else:
            con.execute('''INSERT INTO despensa (nombre, cantidad, lugar, codigo, actualizado)
                           VALUES (?, ?, ?, ?, ?)''', (nombre, cantidad, lugar, codigo, ahora()))
        subir_version(con)
        return leer_despensa(con)


def cambiar_despensa(item_id, datos):
    cambios, valores = [], []
    if 'hay' in datos:
        cambios.append('hay = ?')
        valores.append(int(bool(datos['hay'])))
    if 'nombre' in datos:
        nombre = limpiar(datos['nombre'], 60)
        if not nombre:
            raise ValueError('El nombre no puede quedar vacío')
        cambios.append('nombre = ?')
        valores.append(nombre)
    if 'cantidad' in datos:
        cambios.append('cantidad = ?')
        valores.append(limpiar(datos['cantidad'], 20))
    if 'lugar' in datos:
        cambios.append('lugar = ?')
        valores.append(validar_lugar(datos['lugar']))
    if not cambios:
        raise ValueError('Nada que cambiar')
    with candado, conectar() as con:
        cur = con.execute(f'UPDATE despensa SET {", ".join(cambios)}, actualizado = ? WHERE id = ?',
                          (*valores, ahora(), item_id))
        if cur.rowcount:
            subir_version(con)
        return leer_despensa(con)


def borrar_despensa(item_id):
    with candado, conectar() as con:
        if con.execute('DELETE FROM despensa WHERE id = ?', (item_id,)).rowcount:
            subir_version(con)
        return leer_despensa(con)


# ---------- Códigos de barras ----------

def validar_codigo(codigo):
    if not re.fullmatch(r'\d{6,14}', codigo):
        raise ValueError('Código de barras inválido')
    return codigo


def buscar_open_food_facts(codigo):
    pedido = urllib.request.Request(OFF_URL.format(quote(codigo)), headers={'User-Agent': OFF_AGENTE})
    try:
        with urllib.request.urlopen(pedido, timeout=6) as r:
            datos = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code != 404:  # 404 = el producto no está en su base: normal, no es un error
            print('Open Food Facts respondió', e.code, flush=True)
        return None
    except Exception as e:  # noqa: BLE001 - sin internet o servicio caído: se escribe a mano
        print('Open Food Facts no respondió:', repr(e), flush=True)
        return None
    producto = datos.get('product') or {}
    nombre = limpiar(producto.get('product_name_es') or producto.get('product_name'), 50)
    if not nombre:
        return None
    marca = limpiar((producto.get('brands') or '').split(',')[0], 25)
    if marca and marca.lower() not in nombre.lower():
        nombre = f'{nombre} {marca}'
    return nombre[:60]


def buscar_codigo(codigo):
    codigo = validar_codigo(codigo)
    with conectar() as con:
        f = con.execute('SELECT nombre, origen FROM codigos WHERE codigo = ?', (codigo,)).fetchone()
    if f:
        return {'codigo': codigo, 'encontrado': True, 'nombre': f['nombre'], 'origen': f['origen']}
    nombre = buscar_open_food_facts(codigo)
    if not nombre:
        return {'codigo': codigo, 'encontrado': False}
    with candado, conectar() as con:
        con.execute('INSERT OR REPLACE INTO codigos VALUES (?, ?, ?, ?)', (codigo, nombre, 'openfoodfacts', ahora()))
    return {'codigo': codigo, 'encontrado': True, 'nombre': nombre, 'origen': 'openfoodfacts'}


def guardar_codigo(codigo, datos):
    codigo = validar_codigo(codigo)
    nombre = limpiar(datos.get('nombre'), 60)
    if not nombre:
        raise ValueError('Falta el nombre')
    with candado, conectar() as con:
        con.execute('INSERT OR REPLACE INTO codigos VALUES (?, ?, ?, ?)', (codigo, nombre, 'manual', ahora()))
    return {'codigo': codigo, 'encontrado': True, 'nombre': nombre, 'origen': 'manual'}


# ---------- HTTP ----------

RUTAS = [
    ('GET',    r'/api/recetas',               lambda m, h: listar_recetas()),
    ('POST',   r'/api/recetas',               lambda m, h: crear_receta(h.leer_json())),
    ('GET',    r'/api/recetas/(\d+)',         lambda m, h: leer_receta(conectar(), int(m[1]), porciones_pedidas(h))),
    ('POST',   r'/api/recetas/(\d+)/enviada', lambda m, h: marcar_enviada(int(m[1]), h.leer_json())),
    ('PATCH',  r'/api/recetas/(\d+)',         lambda m, h: cambiar_receta(int(m[1]), h.leer_json())),
    ('DELETE', r'/api/recetas/(\d+)',         lambda m, h: borrar_receta(int(m[1]))),
    ('PUT',    r'/api/recetas/(\d+)/foto',    lambda m, h: guardar_foto(int(m[1]), h.leer_cuerpo(MAX_FOTO))),
    ('DELETE', r'/api/recetas/(\d+)/foto',    lambda m, h: quitar_foto(int(m[1]))),
    ('GET',    r'/api/despensa',              lambda m, h: leer_despensa(conectar())),
    ('POST',   r'/api/despensa',              lambda m, h: agregar_despensa(h.leer_json())),
    ('PATCH',  r'/api/despensa/(\d+)',        lambda m, h: cambiar_despensa(int(m[1]), h.leer_json())),
    ('DELETE', r'/api/despensa/(\d+)',        lambda m, h: borrar_despensa(int(m[1]))),
    ('GET',    r'/api/codigo/([^/]+)',        lambda m, h: buscar_codigo(m[1])),
    ('POST',   r'/api/codigo/([^/]+)',        lambda m, h: guardar_codigo(m[1], h.leer_json())),
]


class Manejador(BaseHTTPRequestHandler):
    server_version = 'Cocina'

    def log_message(self, formato, *args):
        pass

    def responder(self, codigo, datos):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode('utf-8')
        self.send_response(codigo)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def leer_cuerpo(self, maximo):
        largo = int(self.headers.get('Content-Length') or 0)
        if largo > maximo:
            raise ValueError('Demasiado grande')
        return self.rfile.read(largo) if largo else b''

    def leer_json(self):
        crudo = self.leer_cuerpo(MAX_JSON)
        if not crudo:
            return {}
        try:
            datos = json.loads(crudo)
        except json.JSONDecodeError:
            raise ValueError('JSON inválido') from None
        if not isinstance(datos, dict):
            raise ValueError('Se esperaba un objeto JSON')
        return datos

    def atender(self):
        ruta = self.path.split('?')[0]
        # La foto se sirve como imagen, no como JSON
        m = re.fullmatch(r'/api/recetas/(\d+)/foto', ruta)
        if self.command == 'GET' and m:
            try:
                imagen, tipo = leer_foto(int(m[1]))
            except LookupError:
                self.responder(404, {'error': 'Sin foto'})
                return
            self.send_response(200)
            self.send_header('Content-Type', tipo)
            # La página pide la foto con ?v=<actualizada>, así que puede quedar en caché
            self.send_header('Cache-Control', 'public, max-age=31536000, immutable')
            self.send_header('Content-Length', str(len(imagen)))
            self.end_headers()
            self.wfile.write(imagen)
            return

        for metodo, patron, accion in RUTAS:
            m = re.fullmatch(patron, ruta)
            if metodo == self.command and m:
                break
        else:
            self.responder(404, {'error': 'No existe'})
            return
        try:
            self.responder(200, accion(m, self))
        except LookupError as e:
            self.responder(404, {'error': str(e)})
        except ValueError as e:
            self.responder(400, {'error': str(e)})
        except Exception as e:  # noqa: BLE001 - que el servicio no se caiga por un pedido
            print('Error:', repr(e), flush=True)
            self.responder(500, {'error': 'Error interno'})

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = atender


def main():
    preparar_bd()
    servidor = ThreadingHTTPServer((HOST, PUERTO), Manejador)
    print(f'Cocina en http://{HOST}:{PUERTO} (BD: {BD})', flush=True)
    servidor.serve_forever()


if __name__ == '__main__':
    main()
