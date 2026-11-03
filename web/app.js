(() => {
  const API = "api/";                            // /cocina/api/ (nginx -> servicio en 8772)
  const LISTA_API = "../lista-compras/api/";     // otra tool, misma máquina
  const TEMPORIZADORES = "../temporizadores/";
  const CADA_CUANTO_MS = 5000;                   // revisión de la despensa mientras se ve
  const FOTO_LADO_MAX = 1280;

  const $ = (id) => document.getElementById(id);

  // ---------- Utilidades ----------

  async function pedir(url, opciones = {}) {
    const r = await fetch(url, { cache: "no-store", ...opciones });
    const datos = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(datos.error || `Error ${r.status}`);
    return datos;
  }

  const api = (ruta, opciones) => pedir(API + ruta, opciones);
  const json = (metodo, cuerpo) => ({
    method: metodo,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cuerpo),
  });

  let temporizadorAviso = null;
  function avisar(texto, error = false) {
    const caja = $("aviso");
    caja.textContent = texto;
    caja.classList.toggle("error", error);
    caja.hidden = false;
    clearTimeout(temporizadorAviso);
    temporizadorAviso = setTimeout(() => (caja.hidden = true), error ? 5000 : 3000);
  }

  // Para buscar sin importar tildes ni mayúsculas
  const normal = (t) => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

  function el(etiqueta, props = {}, ...hijos) {
    const e = document.createElement(etiqueta);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? "" : v);
    }
    e.append(...hijos.filter((h) => h !== null && h !== undefined && h !== false));
    return e;
  }

  const urlFoto = (r) => `${API}recetas/${r.id}/foto?v=${encodeURIComponent(r.actualizada)}`;

  // ---------- Navegación (#/, #/receta/3, #/nueva, #/editar/3, #/despensa) ----------

  const VISTAS = ["recetas", "receta", "editar", "despensa"];
  let sondeo = null;

  function mostrarVista(nombre) {
    VISTAS.forEach((v) => ($(`vista-${v}`).hidden = v !== nombre));
    const pestana = nombre === "despensa" ? "despensa" : "recetas";
    document.querySelectorAll(".pestanas a").forEach((a) => {
      if (a.dataset.vista === pestana) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    window.scrollTo(0, 0);
  }

  function enrutar() {
    clearInterval(sondeo);
    detenerEscaner();
    const [vista, id] = location.hash.replace(/^#\/?/, "").split("/");
    if (vista === "receta" && id) return verReceta(Number(id));
    if (vista === "editar" && id) return editarReceta(Number(id));
    if (vista === "nueva") return editarReceta(null);
    if (vista === "despensa") return verDespensa();
    return verRecetas();
  }
  window.addEventListener("hashchange", enrutar);

  // ---------- Lista de recetas ----------

  let recetas = [];

  async function verRecetas() {
    mostrarVista("recetas");
    document.title = "Cocina";
    try {
      recetas = (await api("recetas")).recetas;
    } catch (e) {
      avisar(`No se pudieron cargar las recetas: ${e.message}`, true);
    }
    dibujarRecetas();
  }

  function dibujarRecetas() {
    const filtro = normal($("buscar").value.trim());
    const visibles = recetas.filter((r) => !filtro || normal(r.titulo).includes(filtro));
    $("recetas").replaceChildren(
      ...visibles.map((r) =>
        el("li", {},
          el("a", { class: "receta-tarjeta", href: `#/receta/${r.id}` },
            el("span", { class: "receta-imagen" },
              r.foto ? el("img", { src: urlFoto(r), alt: "", loading: "lazy" }) : "🍲"),
            el("span", { class: "receta-texto" },
              el("span", { class: "receta-nombre", text: r.titulo }),
              el("span", { class: "receta-meta", text: [r.tiempo, r.porciones && `${r.porciones} porciones`].filter(Boolean).join(" · ") })
            )
          )
        )
      )
    );
    const vacio = $("recetas-vacio");
    vacio.hidden = visibles.length > 0;
    vacio.textContent = recetas.length ? "Ninguna receta con ese nombre." : "Todavía no hay recetas. Toca “+ Nueva” para guardar la primera.";
  }

  $("buscar").addEventListener("input", dibujarRecetas);

  // ---------- Una receta ----------

  // "8 hamburguesas" con 16 -> "16 hamburguesas"; "4" -> "4 porciones"
  function textoPorciones(r) {
    if (!r.porciones_base) return `${r.porciones} porciones`;
    const t = r.porciones.replace(/\d+/, r.porciones_ver);
    return /^\d+$/.test(r.porciones.trim()) ? `${t} porciones` : t;
  }

  // porciones: para cuántas se quiere cocinar (el servidor escala los ingredientes)
  async function verReceta(id, porciones) {
    mostrarVista("receta");
    const caja = $("receta");
    const mismaReceta = Number(caja.dataset.id) === id && porciones;
    if (!mismaReceta) caja.replaceChildren(el("p", { class: "vacio", text: "Cargando…" }));
    let r;
    try {
      r = await api(`recetas/${id}${porciones ? `?porciones=${porciones}` : ""}`);
    } catch (e) {
      caja.replaceChildren(el("p", { class: "vacio", text: e.message }));
      return;
    }
    caja.dataset.id = id;
    document.title = `${r.titulo} · Cocina`;

    const botonLista = el("button", {
      type: "button",
      class: "boton boton-ancho",
      text: "🛒 Mandar a la lista de compras…",
      onclick: () => abrirHojaLista(r),
    });

    const cambiarPorciones = (delta) => {
      const n = r.porciones_ver + delta;
      if (n >= 1 && n <= 100) verReceta(r.id, n);
    };
    const chipPorciones = !r.porciones
      ? null
      : r.porciones_base
        ? el("span", { class: "chip chip-porciones" },
            el("button", { type: "button", class: "paso-porcion", "aria-label": "Menos porciones", text: "−", onclick: () => cambiarPorciones(-1) }),
            el("span", { text: `🍽 ${textoPorciones(r)}` }),
            el("button", { type: "button", class: "paso-porcion", "aria-label": "Más porciones", text: "+", onclick: () => cambiarPorciones(1) })
          )
        : el("span", { class: "chip", text: `🍽 ${r.porciones} porciones` });

    // replaceChildren convierte un null en el texto "null": las partes que faltan se quitan antes
    caja.replaceChildren(...[
      r.foto ? el("img", { class: "receta-foto", src: urlFoto(r), alt: "" }) : null,
      el("div", {},
        el("h2", { text: r.titulo }),
        el("div", { class: "chips" },
          r.tiempo ? el("span", { class: "chip", text: `⏱ ${r.tiempo}` }) : null,
          chipPorciones
        ),
        r.porciones_ver !== r.porciones_base
          ? el("p", { class: "nota-porciones" },
              `Cantidades para ${r.porciones_ver} (la receta es para ${r.porciones_base}). `,
              el("button", { type: "button", class: "enlace", text: "Volver a la original", onclick: () => verReceta(r.id, r.porciones_base) }))
          : null
      ),
      r.ingredientes.length
        ? el("section", { class: "bloque" },
            el("h3", { text: "Ingredientes" }),
            el("ul", { class: "ingredientes" },
              ...r.ingredientes.map((ing) => el("li", {},
                el("span", { text: ing.texto }),
                ing.derivado ? el("span", { class: "derivado", text: "sale de otro ingrediente" }) : null))
            ),
            botonLista
          )
        : null,
      r.pasos.length
        ? el("section", { class: "bloque" },
            el("h3", { text: "Pasos" }),
            el("ol", { class: "pasos" },
              ...r.pasos.map((p, i) =>
                el("li", {},
                  el("div", { text: p.texto }),
                  p.minutos
                    ? el("a", {
                        class: "boton paso-tiempo",
                        href: `${TEMPORIZADORES}?nombre=${encodeURIComponent(`${r.titulo} (paso ${i + 1})`.slice(0, 30))}&min=${p.minutos}`,
                        target: "_blank",
                        rel: "noopener",
                        text: `⏱ Temporizador de ${p.minutos >= 60 && p.minutos % 60 === 0 ? `${p.minutos / 60} h` : `${p.minutos} min`}`,
                      })
                    : null
                )
              )
            )
          )
        : null,
      r.notas ? el("section", { class: "bloque" }, el("h3", { text: "Notas" }), el("p", { class: "notas", text: r.notas })) : null,
      el("div", { class: "acciones-receta" },
        el("a", { class: "boton", href: `#/editar/${r.id}`, text: "✎ Editar" }),
        el("button", {
          type: "button",
          class: "enlace peligro",
          text: "Borrar receta",
          onclick: async () => {
            if (!confirm(`¿Borrar la receta "${r.titulo}"?`)) return;
            try {
              await api(`recetas/${r.id}`, { method: "DELETE" });
              avisar("Receta borrada");
              location.hash = "#/";
            } catch (e) {
              avisar(e.message, true);
            }
          },
        })
      )
    ].filter(Boolean));
  }

  // "hoy a las 14:30", "ayer a las 9:05", "el 3 nov a las 18:00"
  function cuando(iso) {
    const f = new Date(iso);
    const hora = f.toLocaleTimeString("es", { hour: "numeric", minute: "2-digit" });
    const dia = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    const dias = Math.round((dia(new Date()) - dia(f)) / 86400000);
    if (dias === 0) return `hoy a las ${hora}`;
    if (dias === 1) return `ayer a las ${hora}`;
    return `el ${f.toLocaleDateString("es", { day: "numeric", month: "short" })} a las ${hora}`;
  }

  // 🛒 Hoja para elegir qué ingredientes mandar: así un toque por error no manda nada
  const hojaLista = $("hoja-lista");
  $("hoja-lista-cancelar").addEventListener("click", () => hojaLista.close());
  hojaLista.addEventListener("click", (e) => {
    if (e.target === hojaLista) hojaLista.close();
  });

  function abrirHojaLista(r) {
    const casillas = r.ingredientes.map((ing) => el("input", { type: "checkbox", checked: !ing.derivado }));
    const confirmar = $("hoja-lista-agregar");
    const contar = () => {
      const n = casillas.filter((c) => c.checked).length;
      confirmar.textContent = n ? `Agregar ${n}` : "Agregar";
      confirmar.disabled = !n;
    };
    casillas.forEach((c) => c.addEventListener("change", contar));
    contar();

    $("hoja-lista-subtitulo").textContent = r.porciones_base ? `${r.titulo} · para ${r.porciones_ver}` : r.titulo;
    const aviso = $("hoja-lista-aviso");
    aviso.hidden = !r.enviada_en;
    if (r.enviada_en) {
      aviso.textContent = `⚠ Esta receta ya se mandó ${cuando(r.enviada_en)}${r.enviada_porciones ? ` (para ${r.enviada_porciones})` : ""}. Si la mandas otra vez, las cantidades se suman.`;
    }
    $("hoja-lista-items").replaceChildren(
      ...r.ingredientes.map((ing, i) =>
        el("li", {},
          el("label", {},
            casillas[i],
            el("span", { class: "hoja-item-nombre" },
              ing.compra.nombre,
              ing.derivado ? el("small", { text: "sale de otro ingrediente" }) : null),
            ing.compra.cantidad ? el("span", { class: "chip", text: ing.compra.cantidad }) : null
          )
        )
      )
    );
    confirmar.onclick = () => mandarALista(r, casillas, confirmar);
    hojaLista.showModal();
  }

  async function mandarALista(receta, casillas, boton) {
    const elegidos = receta.ingredientes.filter((_, i) => casillas[i].checked);
    if (!elegidos.length) return;
    boton.disabled = true;
    let ok = 0;
    for (const ing of elegidos) {
      try {
        await pedir(LISTA_API + "items", json("POST", ing.compra));
        ok++;
      } catch {
        /* se informa abajo */
      }
    }
    boton.disabled = false;
    if (ok) {
      try {
        await api(`recetas/${receta.id}/enviada`, json("POST", { porciones: receta.porciones_ver }));
      } catch {
        /* solo es el aviso de "ya se mandó" */
      }
    }
    hojaLista.close();
    if (ok === elegidos.length) avisar(`${ok} ${ok === 1 ? "ingrediente agregado" : "ingredientes agregados"} a la lista de compras`);
    else avisar(`Se agregaron ${ok} de ${elegidos.length}. Revisa la conexión.`, true);
    verReceta(receta.id, receta.porciones_ver);
  }

  // ---------- Nueva / editar ----------

  let editando = null;      // id o null
  let fotoNueva = null;     // Blob ya reducido
  let quitarFoto = false;

  async function editarReceta(id) {
    mostrarVista("editar");
    editando = id;
    fotoNueva = null;
    quitarFoto = false;
    $("form-receta").reset();
    $("editar-titulo").textContent = id ? "Editar receta" : "Nueva receta";
    $("editar-volver").href = id ? `#/receta/${id}` : "#/";
    mostrarFoto(null);

    if (id) {
      try {
        const r = await api(`recetas/${id}`);
        $("r-titulo").value = r.titulo;
        $("r-porciones").value = r.porciones;
        $("r-tiempo").value = r.tiempo;
        $("r-ingredientes").value = r.ingredientes.map((i) => i.texto).join("\n");
        $("r-pasos").value = r.pasos.map((p) => p.texto).join("\n");
        $("r-notas").value = r.notas;
        if (r.foto) mostrarFoto(urlFoto(r));
      } catch (e) {
        avisar(e.message, true);
      }
    } else {
      $("r-titulo").focus();
    }
  }

  function mostrarFoto(src) {
    const vista = $("r-foto-vista");
    vista.hidden = !src;
    if (src) vista.src = src;
    else vista.removeAttribute("src");
    $("r-foto-texto").textContent = src ? "Cambiar foto" : "Elegir foto";
    $("r-foto-quitar").hidden = !src;
  }

  function cargarImagen(src) {
    return new Promise((resolver, rechazar) => {
      const img = new Image();
      img.onload = () => resolver(img);
      img.onerror = () => rechazar(new Error("No se pudo leer la foto"));
      img.src = src;
    });
  }

  // La foto se reduce en el celular: sube rápido y no llena el servidor
  async function reducirFoto(archivo) {
    const url = URL.createObjectURL(archivo);
    try {
      const img = await cargarImagen(url);
      const escala = Math.min(1, FOTO_LADO_MAX / Math.max(img.naturalWidth, img.naturalHeight));
      const lienzo = document.createElement("canvas");
      lienzo.width = Math.round(img.naturalWidth * escala);
      lienzo.height = Math.round(img.naturalHeight * escala);
      lienzo.getContext("2d").drawImage(img, 0, 0, lienzo.width, lienzo.height);
      return await new Promise((resolver) => lienzo.toBlob(resolver, "image/jpeg", 0.82));
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  $("r-foto").addEventListener("change", async (e) => {
    const archivo = e.target.files[0];
    if (!archivo) return;
    try {
      fotoNueva = await reducirFoto(archivo);
      quitarFoto = false;
      mostrarFoto(URL.createObjectURL(fotoNueva));
    } catch (err) {
      avisar(err.message, true);
    }
  });

  $("r-foto-quitar").addEventListener("click", () => {
    fotoNueva = null;
    quitarFoto = true;
    $("r-foto").value = "";
    mostrarFoto(null);
  });

  const lineas = (texto) => texto.split("\n").map((l) => l.trim()).filter(Boolean);

  $("form-receta").addEventListener("submit", async (e) => {
    e.preventDefault();
    const boton = $("r-guardar");
    const datos = {
      titulo: $("r-titulo").value.trim(),
      porciones: $("r-porciones").value.trim(),
      tiempo: $("r-tiempo").value.trim(),
      ingredientes: lineas($("r-ingredientes").value),
      pasos: lineas($("r-pasos").value),
      notas: $("r-notas").value.trim(),
    };
    if (!datos.titulo) {
      $("r-titulo").focus();
      return;
    }
    boton.disabled = true;
    boton.textContent = "Guardando…";
    try {
      let receta = editando
        ? await api(`recetas/${editando}`, json("PATCH", datos))
        : await api("recetas", json("POST", datos));
      if (fotoNueva) {
        receta = await api(`recetas/${receta.id}/foto`, {
          method: "PUT",
          headers: { "Content-Type": "image/jpeg" },
          body: fotoNueva,
        });
      } else if (quitarFoto && receta.foto) {
        receta = await api(`recetas/${receta.id}/foto`, { method: "DELETE" });
      }
      avisar("Receta guardada");
      location.hash = `#/receta/${receta.id}`;
    } catch (err) {
      avisar(`No se pudo guardar: ${err.message}`, true);
    } finally {
      boton.disabled = false;
      boton.textContent = "Guardar";
    }
  });

  // 🎤 dictar ingredientes ("dos tazas de harina, tres huevos y sal") y pasos (cada oración, un paso)
  function agregarLineas(id, nuevas) {
    const caja = $(id);
    const actual = caja.value.replace(/\s+$/, "");
    caja.value = [actual, ...nuevas].filter(Boolean).join("\n");
    caja.scrollTop = caja.scrollHeight;
  }

  if (window.Voz) {
    document.querySelector('[data-dictar="r-ingredientes"]').append(
      Voz.boton({
        modo: "lista",
        etiqueta: "Dictar ingredientes",
        alTerminar: ({ items = [] }) =>
          agregarLineas("r-ingredientes", items.map(({ nombre, cantidad }) =>
            cantidad ? `${cantidad} ${nombre[0].toLowerCase()}${nombre.slice(1)}` : nombre)),
        alError: (m) => avisar(m, true),
      })
    );
    document.querySelector('[data-dictar="r-pasos"]').append(
      Voz.boton({
        modo: "texto",
        etiqueta: "Dictar pasos",
        alTerminar: ({ texto }) =>
          agregarLineas("r-pasos", texto.split(/(?<=[.!?])\s+/).map((p) => p.trim()).filter(Boolean)),
        alError: (m) => avisar(m, true),
      })
    );
  }

  // ---------- IA (servicio casa/ia, modelo local) ----------
  // Tarda entre 15 s y 1 min: se muestra un "pensando…" con los segundos que van.

  const IA = "../ia/api/";
  const dialogoIA = $("dialogo-ia");

  function abrirIA(titulo, ...contenido) {
    $("ia-titulo").textContent = titulo;
    $("ia-cuerpo").replaceChildren(...contenido);
    if (!dialogoIA.open) dialogoIA.showModal();
  }

  // Carga el modelo en memoria mientras la persona escribe o pega el texto
  const precalentarIA = () => fetch(IA + "precalentar", { method: "POST" }).catch(() => {});

  async function pedirIA(ruta, cuerpo) {
    const segundos = el("span", { text: "0" });
    $("ia-cuerpo").replaceChildren(
      el("div", { class: "ia-espera" },
        el("div", { class: "girando" }),
        el("strong", { text: "Pensando…" }),
        el("span", {}, "Puede tardar hasta un minuto · ", segundos, " s")
      )
    );
    const inicio = Date.now();
    const reloj = setInterval(() => (segundos.textContent = Math.round((Date.now() - inicio) / 1000)), 1000);
    try {
      return await pedir(IA + ruta, json("POST", cuerpo));
    } finally {
      clearInterval(reloj);
    }
  }

  function errorIA(e, reintentar) {
    $("ia-cuerpo").replaceChildren(
      el("p", { text: `⚠ ${e.message === "Failed to fetch" ? "No hay conexión con el servidor." : e.message}` }),
      el("div", { class: "ia-botones" }, el("button", { type: "button", class: "boton-principal", text: "Intentar otra vez", onclick: reintentar }))
    );
  }

  $("ia-cerrar").addEventListener("click", () => dialogoIA.close());

  // ✨ ¿Qué cocino con lo que hay?
  async function queCocino() {
    abrirIA("✨ ¿Qué cocino con lo que hay?");
    let productos;
    try {
      productos = (await api("despensa")).items.filter((i) => i.hay).map((i) => i.nombre);
    } catch (e) {
      return errorIA(e, queCocino);
    }
    if (!productos.length) {
      $("ia-cuerpo").replaceChildren(el("p", { text: "La despensa está vacía. Agrega primero lo que hay en casa (pestaña Despensa)." }));
      return;
    }
    try {
      const { recetas: ideas } = await pedirIA("sugerir-recetas", { despensa: productos });
      $("ia-cuerpo").replaceChildren(
        el("div", { class: "sugerencias" }, ...ideas.map(tarjetaSugerencia)),
        el("p", { class: "ia-nota", text: `Con ${productos.length} productos de la despensa. Sugerencias de una IA local: revísalas antes de cocinar 🙂` }),
        el("div", { class: "ia-botones" }, el("button", { type: "button", class: "boton", text: "Otras ideas", onclick: queCocino }))
      );
    } catch (e) {
      errorIA(e, queCocino);
    }
  }

  function tarjetaSugerencia(s) {
    const acciones = [
      el("button", {
        type: "button",
        class: "boton",
        text: "Guardar como receta",
        onclick: async (ev) => {
          ev.target.disabled = true;
          try {
            const r = await api("recetas", json("POST", {
              titulo: s.titulo,
              ingredientes: s.usa,
              pasos: [s.idea],
              notas: "Sugerida por la IA con lo que había en la despensa.",
            }));
            dialogoIA.close();
            location.hash = `#/receta/${r.id}`;
          } catch (e) {
            ev.target.disabled = false;
            avisar(e.message, true);
          }
        },
      }),
    ];
    if (s.falta.length) {
      acciones.push(el("button", {
        type: "button",
        class: "boton",
        text: "Faltantes a la lista",
        onclick: async (ev) => {
          ev.target.disabled = true;
          let ok = 0;
          for (const nombre of s.falta) {
            try {
              await pedir(LISTA_API + "items", json("POST", { nombre, cantidad: "" }));
              ok++;
            } catch {
              /* se informa abajo */
            }
          }
          avisar(ok === s.falta.length ? `${ok} ${ok === 1 ? "faltante agregado" : "faltantes agregados"} a la lista` : "No se pudo agregar todo a la lista", ok !== s.falta.length);
        },
      }));
    }
    return el("article", { class: "sugerencia" },
      el("h3", { text: s.titulo }),
      el("p", { text: s.idea }),
      el("p", { class: "detalle", text: `Usa: ${s.usa.join(", ")}` }),
      s.falta.length ? el("p", { class: "detalle", text: `Falta: ${s.falta.join(", ")}` }) : null,
      el("div", { class: "acciones" }, ...acciones)
    );
  }

  $("que-cocino").addEventListener("click", queCocino);

  // ✨ Llenar el formulario desde un texto pegado (WhatsApp, internet…)
  function importarTexto() {
    const caja = el("textarea", { rows: "9", placeholder: "Pega aquí la receta tal como te la mandaron…", "aria-label": "Texto de la receta" });
    abrirIA("✨ Llenar desde un texto",
      el("p", { class: "ia-nota", text: "La IA separa título, ingredientes y pasos. Después puedes revisar y corregir antes de guardar." }),
      caja,
      el("div", { class: "ia-botones" },
        el("button", {
          type: "button",
          class: "boton-principal",
          text: "Ordenar receta",
          onclick: async () => {
            const texto = caja.value.trim();
            if (!texto) return caja.focus();
            const intentar = async () => {
              try {
                const r = await pedirIA("importar-receta", { texto });
                const lleno = ["r-ingredientes", "r-pasos"].some((id) => $(id).value.trim());
                if (lleno && !confirm("El formulario ya tiene ingredientes o pasos. ¿Reemplazarlos con lo de la IA?")) {
                  dialogoIA.close();
                  return;
                }
                if (r.titulo) $("r-titulo").value = r.titulo;
                if (r.porciones) $("r-porciones").value = r.porciones;
                if (r.tiempo) $("r-tiempo").value = r.tiempo;
                $("r-ingredientes").value = r.ingredientes.join("\n");
                $("r-pasos").value = r.pasos.join("\n");
                dialogoIA.close();
                avisar("Listo: revisa la receta y toca Guardar");
              } catch (e) {
                errorIA(e, intentar);
              }
            };
            intentar();
          },
        })
      )
    );
    caja.focus();
    precalentarIA();
  }

  $("importar-texto").addEventListener("click", importarTexto);

  // ---------- Despensa ----------

  let despensa = { version: -1, items: [], lugares: [] };
  let codigoActual = null;  // código escaneado que va con el próximo producto

  async function verDespensa() {
    mostrarVista("despensa");
    document.title = "Despensa · Cocina";
    await cargarDespensa(true);
    sondeo = setInterval(() => !document.hidden && cargarDespensa(), CADA_CUANTO_MS);
  }

  async function cargarDespensa(forzar = false) {
    try {
      const datos = await api("despensa");
      if (forzar || datos.version !== despensa.version) {
        despensa = datos;
        dibujarDespensa();
      }
    } catch (e) {
      if (forzar) avisar(`No se pudo cargar la despensa: ${e.message}`, true);
    }
  }

  function dibujarLugares() {
    const selector = $("d-lugar");
    if (selector.options.length) return;
    despensa.lugares.forEach((l) => selector.append(new Option(l, l)));
  }

  function filaProducto(item) {
    const acciones = item.hay
      ? [el("button", { type: "button", class: "boton", text: "Se acabó", onclick: () => seAcabo(item) })]
      : [
          el("button", { type: "button", class: "boton", text: "Ya hay", onclick: () => cambiar(item, { hay: true }) }),
          el("button", {
            type: "button",
            class: "quitar",
            "aria-label": `Quitar ${item.nombre} de la despensa`,
            text: "✕",
            onclick: () => confirm(`¿Quitar "${item.nombre}" de la despensa?`) && borrar(item),
          }),
        ];
    return el("li", { class: "producto" },
      el("span", { class: "producto-nombre", text: item.nombre }),
      el("span", { class: "producto-cantidad", text: item.cantidad }),
      ...acciones
    );
  }

  function dibujarDespensa() {
    dibujarLugares();
    const hay = despensa.items.filter((i) => i.hay);
    const acabados = despensa.items.filter((i) => !i.hay);
    const secciones = despensa.lugares
      .map((lugar) => [lugar, hay.filter((i) => i.lugar === lugar)])
      .filter(([, items]) => items.length)
      .map(([lugar, items]) =>
        el("section", { class: "lugar" }, el("h3", { text: lugar }), el("ul", { class: "productos" }, ...items.map(filaProducto)))
      );
    if (acabados.length) {
      secciones.push(
        el("section", { class: "lugar acabados" },
          el("h3", { text: `Se acabó (${acabados.length})` }),
          el("ul", { class: "productos" }, ...acabados.map(filaProducto))
        )
      );
    }
    $("despensa").replaceChildren(
      ...(secciones.length ? secciones : [el("p", { class: "vacio", text: "La despensa está vacía. Agrega lo que hay en casa o escanea los códigos de barras." })])
    );
  }

  async function cambiar(item, cambios) {
    try {
      despensa = await api(`despensa/${item.id}`, json("PATCH", cambios));
      dibujarDespensa();
    } catch (e) {
      avisar(e.message, true);
    }
  }

  async function borrar(item) {
    try {
      despensa = await api(`despensa/${item.id}`, { method: "DELETE" });
      dibujarDespensa();
    } catch (e) {
      avisar(e.message, true);
    }
  }

  // Lo que se acaba pasa solo a la lista de compras
  async function seAcabo(item) {
    await cambiar(item, { hay: false });
    try {
      await pedir(LISTA_API + "items", json("POST", { nombre: item.nombre, cantidad: "" }));
      avisar(`${item.nombre} pasó a la lista de compras`);
    } catch {
      avisar(`${item.nombre} se marcó, pero no se pudo agregar a la lista de compras`, true);
    }
  }

  $("form-despensa").addEventListener("submit", async (e) => {
    e.preventDefault();
    const nombre = $("d-nombre").value.trim();
    if (!nombre) {
      $("d-nombre").focus();
      return;
    }
    try {
      despensa = await api("despensa", json("POST", {
        nombre,
        cantidad: $("d-cantidad").value.trim(),
        lugar: $("d-lugar").value,
        codigo: codigoActual,
      }));
      dibujarDespensa();
      $("d-nombre").value = "";
      $("d-cantidad").value = "";
      ponerCodigo(null);
      avisar(`${nombre} agregado a la despensa`);
    } catch (err) {
      avisar(err.message, true);
    }
  });

  function ponerCodigo(codigo) {
    codigoActual = codigo;
    $("d-codigo").hidden = !codigo;
    $("d-codigo").textContent = codigo ? `Código ${codigo}` : "";
  }

  // Si se escribe a mano después de escanear, el código ya no corresponde
  $("d-nombre").addEventListener("input", () => codigoActual && ponerCodigo(null));

  // ---------- Escáner de códigos de barras ----------
  // Android (Chrome) trae BarcodeDetector; en iPhone se usa ZXing (vendor/zxing.min.js).

  const dialogo = $("escaner");
  const video = $("escaner-video");
  const estadoEscaner = $("escaner-estado");
  let flujo = null;
  let lector = null;      // ZXing
  let buscando = false;   // bucle de BarcodeDetector
  let codigoEscaneado = null;

  function cargarScript(src) {
    return new Promise((resolver, rechazar) => {
      if (document.querySelector(`script[src="${src}"]`)) return resolver();
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolver;
      s.onerror = () => rechazar(new Error("No se pudo cargar el lector de códigos"));
      document.head.append(s);
    });
  }

  async function detectorNativo() {
    if (!("BarcodeDetector" in window)) return null;
    try {
      const formatos = await BarcodeDetector.getSupportedFormats();
      const queremos = ["ean_13", "ean_8", "upc_a", "upc_e", "code_128"].filter((f) => formatos.includes(f));
      return queremos.length ? new BarcodeDetector({ formats: queremos }) : null;
    } catch {
      return null;
    }
  }

  async function abrirEscaner() {
    if (!navigator.mediaDevices || !window.isSecureContext) {
      avisar("La cámara necesita abrir la app por https", true);
      return;
    }
    $("escaner-nombre").hidden = true;
    video.hidden = false;
    estadoEscaner.textContent = "Abriendo la cámara…";
    dialogo.showModal();

    const camara = { video: { facingMode: { ideal: "environment" } }, audio: false };
    const nativo = await detectorNativo();
    try {
      if (nativo) {
        flujo = await navigator.mediaDevices.getUserMedia(camara);
        video.srcObject = flujo;
        await video.play();
        estadoEscaner.textContent = "Apunta al código de barras";
        buscando = true;
        const ciclo = async () => {
          if (!buscando) return;
          try {
            const codigos = await nativo.detect(video);
            if (codigos.length) return encontrado(codigos[0].rawValue);
          } catch {
            /* cuadro sin imagen todavía */
          }
          setTimeout(ciclo, 150);
        };
        ciclo();
      } else {
        await cargarScript("vendor/zxing.min.js");
        const pistas = new Map();
        pistas.set(ZXing.DecodeHintType.POSSIBLE_FORMATS, [
          ZXing.BarcodeFormat.EAN_13, ZXing.BarcodeFormat.EAN_8,
          ZXing.BarcodeFormat.UPC_A, ZXing.BarcodeFormat.UPC_E, ZXing.BarcodeFormat.CODE_128,
        ]);
        lector = new ZXing.BrowserMultiFormatReader(pistas, 200);
        estadoEscaner.textContent = "Apunta al código de barras";
        await lector.decodeFromConstraints(camara, video, (resultado) => {
          if (resultado && lector) encontrado(resultado.getText());
        });
      }
    } catch (e) {
      detenerEscaner();
      estadoEscaner.textContent =
        e.name === "NotAllowedError" ? "No hay permiso para usar la cámara." : `No se pudo abrir la cámara: ${e.message}`;
    }
  }

  function detenerEscaner() {
    buscando = false;
    if (lector) {
      lector.reset();
      lector = null;
    }
    if (flujo) {
      flujo.getTracks().forEach((t) => t.stop());
      flujo = null;
    }
    video.srcObject = null;
  }

  async function encontrado(codigo) {
    detenerEscaner();
    codigoEscaneado = codigo;
    if (navigator.vibrate) navigator.vibrate(60);
    estadoEscaner.textContent = `Código ${codigo}: buscando…`;
    try {
      const r = await api(`codigo/${encodeURIComponent(codigo)}`);
      if (r.encontrado) {
        usarProducto(r.nombre, codigo);
      } else {
        video.hidden = true;
        estadoEscaner.textContent = `Código ${codigo}`;
        $("escaner-nombre").hidden = false;
        $("escaner-nombre-texto").value = "";
        $("escaner-nombre-texto").focus();
      }
    } catch (e) {
      estadoEscaner.textContent = e.message;
    }
  }

  function usarProducto(nombre, codigo) {
    dialogo.close();
    $("d-nombre").value = nombre;
    ponerCodigo(codigo);
    $("d-cantidad").focus();
    avisar(`Encontrado: ${nombre}`);
  }

  $("escaner-nombre").addEventListener("submit", async (e) => {
    e.preventDefault();
    const nombre = $("escaner-nombre-texto").value.trim();
    if (!nombre) return;
    try {
      // Se recuerda para la próxima vez que se escanee
      await api(`codigo/${encodeURIComponent(codigoEscaneado)}`, json("POST", { nombre }));
      usarProducto(nombre, codigoEscaneado);
    } catch (err) {
      avisar(err.message, true);
    }
  });

  $("d-escanear").addEventListener("click", abrirEscaner);
  $("escaner-cerrar").addEventListener("click", () => dialogo.close());
  dialogo.addEventListener("close", detenerEscaner);

  // ---------- Inicio ----------

  enrutar();
})();
