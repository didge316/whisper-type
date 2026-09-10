# Memory: qBittorrent for Downloads

When downloading files that are Cloudflare-protected or JS-driven (like MegaDB,
SteamRIP), the direct download often fails or is very slow. Use qBittorrent with a
torrent/magnet link instead.

## Setup

qBittorrent headless (`qbittorrent-nox`) runs without a display. It needs:

1. **`--webui-port` flag** — port 8080 is taken by the SearXNG docker container,
   so always use a different port:
   ```bash
   qbittorrent-nox --profile=/tmp/qbfresh --confirm-legal-notice --webui-port=8090
   ```
   (Create `/tmp/qbfresh/qBittorrent/config/qBittorrent.conf` first if needed,
   or just use a fresh profile dir.)

2. **Temporary password** — on first start, qBittorrent prints a temporary WebUI
   password to stdout:
   ```
   The WebUI administrator password was not set. A temporary password is provided
   for this session: G7dyENyMb
   ```
   Use `admin` / that password to log in via the API.

3. **Cookie auth** — log in once, save cookies, reuse them:
   ```bash
   curl -s --cookie-jar /tmp/qbc -c /tmp/qbc \
     "http://127.0.0.1:8090/api/v2/auth/login" \
     -d "username=admin&password=<TEMP_PASSWORD>"
   ```

## Common gotchas

- **`--webui-port` is the flag** — editing the config file's port does NOT work
  (qBittorrent ignores it and defaults to 8080). Always pass `--webui-port=NNNN`.
- **Port 8080 is used by SearXNG** — never use it. Use 8090 or another free port.
- **Session expires** — if API calls return "Bad Request", re-login (cookies in
  `/tmp/qbc`).
- **qBittorrent GUI needs a display** — use `qbittorrent-nox` (headless) or the
  GUI `qbittorrent` (needs X). For headless, `-nox` is the way.

## Adding a torrent

```bash
MAGNET='magnet:?xt=urn:btih:<HASH>&dn=<NAME>&tr=udp://tracker:1337/announce&...'
curl -s --cookie /tmp/qbc -b /tmp/qbc -c /tmp/qbc \
  "http://127.0.0.1:8090/api/v2/torrents/add" \
  --data-urlencode "urls=$MAGNET" \
  --data-urlencode "savePath=/path/to/download/dir"
```

## Checking status

```bash
curl -s --cookie /tmp/qbc -b /tmp/qbc -c /tmp/qbc \
  "http://127.0.0.1:8090/api/v2/torrents/info" 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
for t in d:
    print(f\"{t['name']}: {t['progress']*100:.1f}%  {t['dlspeed']/1e6:.1f} MB/s  seeds={t['num_seeds']}  {t['state']}\")"
```

## Live status in a Herdr pane

Run a loop in any pane (e.g. DotsMOCR pane `w1:p1D`):
```bash
herdr pane run w1:p1D "while true; do <status command above>; sleep 5; done"
```

## Real-world example: Prodeus

- Torrent: "Prodeus v1.0.2", info_hash `9E4929D3A188B5974D3B7E0BC65BFDD0BE640A54`
  (found via apibay.org API: `curl https://apibay.org/q.php?q=Prodeus`)
- Only 1-2 seeders — may stall with 0 seeders, then resume when a seeder returns.
- Add multiple trackers to help find peers:
  ```
  tr=udp://tracker.opentrackr.org:1337/announce
  tr=udp://open.tracker.cl:1337/announce
  tr=udp://tracker.openbittorrent.com:6969/announce
  tr=udp://exodus.desync.com:6969/announce
  tr=udp://tracker.torrent.eu.org:451/announce
  tr=udp://open.dittorrent.tracker:6969
  tr=udp://explodie.org:6969/announce
  ```

## Alternative: aria2c

aria2c handles magnets directly but this build doesn't support `--dl-limit` or
`--output` (use `-o` for output, `-s`/`--split` for connections). Torrents with
few seeders won't beat a good direct download. qBittorrent is more reliable for
these cases.
