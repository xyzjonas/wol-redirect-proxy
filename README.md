## Wake-on-LAN redirect proxy

Brutally simple, single file, Fast API based proxy service. Create a simple `path` and/or  `hostname` based
redirects that send WoL packets if target URL is not reachable. Only works for `HTTP(S)` redirects.

Great complement for a simple [auto-suspend](https://autosuspend.readthedocs.io/) setup,
e.g. your home jellyfin server or any other `HTTP` service.

That's it!

### Install
```shell
# 1. install script - install wol-proxy into a new virtualenv inside your $HOME
curl https://raw.githubusercontent.com/xyzjonas/wol-redirect-proxy/main/install.sh | bash
```
```shell
# 2. from PyPi
pip install wol-redirect-proxy
```
```shell
# 3. from source using Poetry
poetry install
```
### ...and run
```shell
wol-proxy --host "0.0.0.0" --port 12345
```
```shell
wol-proxy --help
```

### Configuration
Specify a list of proxy mappings using a yaml config, e.g.:

```yaml
#  This will WoL redirect any HTTP request and carry over the path.
#  e.g.: POST: http://my-proxy.home/login -> POST "http://my-jellyfin.home:8096/login"

targets:
- handler: "wol"
  source_url: "http://my-proxy.home/*"
  target_url: "http://my-jellyfin.home:8096"
  methods: [GET, POST, DELETE, PATCH]
  options:
    mac: "75:55:39:a4:33:27"
    timeout_s: 2
```

```yaml
#  Multiple redirects to different services by hostname
#  (requires working DNS setup)

targets:
- handler: "plain"
  source_url: "http://jellyfin.home/*"
  target_url: "http://192.168.0.124:8096"
  methods: [GET, POST, DELETE, PATCH]
  
- handler: "plain"
  source_url: "http://nextcloud.home/*"
  target_url: "http://192.168.0.129:8080"
  methods: [GET, POST]
  
- handler: "plain"
  source_url: "http://torrent-box.home/*"
  target_url: "http://192.168.0.135:8080"
  methods: [GET, POST]
```

### Use as a systemd service

```shell
# use install script and follow instructions
curl https://raw.githubusercontent.com/xyzjonas/wol-redirect-proxy/main/install.sh | bash
```

```shell
# use the sample systemd unit file
git clone https://github.com/jonasbrauer/wol-redirect-proxy.git && cd wol-redirect-proxy 
sudo cp sample-systemd.unit /etc/systemd/system/wol-redirect-proxy.service  # ...and edit user/group
sudo systemctl daemon-reload
sudo systemctl enable --now wol-redirect-proxy.service
sudo systemctl status wol-redirect-proxy.service
```
