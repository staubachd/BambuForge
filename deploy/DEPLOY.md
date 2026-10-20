# Deploying to a Synology NAS

The install guide lives in the README, so there is only ever one copy of it to
keep correct:

### → [Installing on a Synology NAS](../README.md#installing-on-a-synology-nas)

This folder holds the pieces that guide refers to:

| File | What it is |
|---|---|
| [`schema_and_user.sql`](schema_and_user.sql) | Creates the `bambu_monitor` database and a least-privilege `bambu` user. Run once, as the server's root user. The app creates its own tables. |
| [`start.sh`](start.sh) | The launcher. Idempotent — starts the app only if it is not already running, so it doubles as the watchdog. `start.sh restart` kills the running instance and **waits for it to exit** before starting the new one. |
| [`sqlite_to_mariadb.py`](sqlite_to_mariadb.py) | Moves an existing SQLite database onto MariaDB or MySQL. |
| [`recalc_print_energy.py`](recalc_print_energy.py) | Recomputes stored per-print energy from the telemetry table. |

---

## Notes that only apply to a NAS

- **`APP_DIR` in `start.sh`** is an absolute path, `/volume1/apps/bambuforge`.
  Edit it if you install elsewhere; nothing else hardcodes a location.
- **Use the Python 3 package's interpreter**, not `/bin/python3` — Synology ships
  an older one there. The venv in the install guide takes care of this.
- **MariaDB needs "Enable TCP/IP connection"** ticked in its package settings. The
  app connects over TCP; without it the login fails with *Access denied* no matter
  what the password is.
- **The Flask server is fine** for single-user home use on a LAN. If you ever want
  something hardened, `pip install waitress` and swap the last line of `app.py`.
- **Backups:** the database holds the settings as well as the history, so your
  normal MariaDB backup already covers the configuration. The only thing outside
  it is `instance/db.json`, which is a handful of values you could retype in a
  minute. For a copy that does not depend on the database being readable, see
  [Backup and restore](../README.md#backup-and-restore).

## Moving an existing SQLite database to MariaDB

Stop the app, then:

```sh
cd /volume1/apps/bambuforge
./venv/bin/python3 deploy/sqlite_to_mariadb.py
```

It brings the destination schema up to date **first** (otherwise columns that do
not exist there yet are silently dropped), then copies telemetry, prints, filament
identities, acknowledgements and settings. Switch the connection over in
`instance/db.json` — or re-run the wizard with `app.py --setup` — and restart.

## Moving from the old folder `bambu-monitor`

Once, if the app still lives under `/volume1/apps/bambu-monitor` from before it
was renamed to BambuForge:

```sh
sudo -i
kill $(cat /volume1/apps/bambu-monitor/app.pid)
mv /volume1/apps/bambu-monitor /volume1/apps/bambuforge
```

Then copy the new files over (`deploy/start.sh` included - its `APP_DIR` is the
new path), run `sh /volume1/apps/bambuforge/deploy/start.sh`, and point **both**
Task Scheduler tasks (boot-up and the 5-minute watchdog) - and a scheduled
backup, if you have one - at the new path.

What stays as it is: the database (`bambu_monitor`), its user (`bambu`) and
`instance/db.json`. The venv moves with the folder and keeps working, because the
app is started through `venv/bin/python3`; only the helper scripts such as
`venv/bin/pip` still name the old path, so use `./venv/bin/python3 -m pip` as the
install guide does. Backups written before the rename (`bambu-monitor-*.json`)
can still be restored, and `tools/backup.py export --keep` prunes them along with
the new `bambuforge-*.json` files.
