# cocina

Recetario y despensa de la casa. Las recetas mandan sus ingredientes a la lista de compras y abren temporizadores desde los pasos; la despensa se llena escaneando códigos de barras y lo que se acaba pasa a la lista de compras.

- Página: https://192.168.1.4/cocina/
- Datos: `~/.local/share/casa/cocina.db` (SQLite, fotos incluidas; entra en el respaldo diario de `infra/respaldos`)

## Partes

- `web/`: página estática que se publica en `/var/www/cocina/`.
- `servidor.py`: API JSON (solo Python estándar + SQLite) en `127.0.0.1:8772`. nginx publica `/cocina/api/` → `/api/`.
- `servicio/cocina.service`: servicio systemd de usuario.

## Comandos

Publicar la página:

```
rsync -a --delete ~/proyectos/casa/cocina/web/ /var/www/cocina/
```

Servicio:

```
cp ~/proyectos/casa/cocina/servicio/cocina.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now cocina.service
systemctl --user restart cocina.service   # después de cambiar servidor.py
journalctl --user -u cocina -f
```
