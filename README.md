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
...or 

## Use as a sytemd service

1. clone
```shell
git clone https://github.com/jonasbrauer/wol-redirect-proxy.git && cd wol-redirect-proxy
```

2. edit your configuration
```shell
cp example-config.yaml config.yaml
```

3. setup your virtualenv
```shell
python3.9 -m venv venv
./venv/bin/pip install -r requirements.txt
```

4. create & start the systemd service
```shell
sudo cp sample-systemd.unit /etc/systemd/system/wol-redirect-proxy.service  # ...and edit user/group
sudo systemctl daemon-reload
sudo systemctl enable --now wol-redirect-proxy.service
sudo systemctl status wol-redirect-proxy.service
```
