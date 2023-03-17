## Wake-on-LAN redirect proxy

Brutally simple, single file, Fast API based proxy service. Create a simple **path based**
redirects that send WoL packets if target URL is not reachable.

Great for a simple auto-suspend setup, e.g. your home jellyfin server.

That's it!

E.g.:
```yaml
targets:
- handler: "wol"
  target_url: "http://my-jellyfin-server.home:8096"
  options:
    mac: "75:55:39:a4:33:27"
    timeout_s: 2
  matches:
  - route: "/my-jellyfin/*"
  - route: "/another-alias/*"

  { ... }
```

```shell
$ ./app.py --host "0.0.0.0" --port 12345
```
...or use the attached systemd unit file