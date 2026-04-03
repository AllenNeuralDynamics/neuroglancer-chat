## VM Deployment Fix: Neuroglancer Viewer Iframe

### Root Cause
`panel-neuroglancer` spawns a local Tornado server serving the neuroglancer bundle. The iframe src is hardcoded to `http://127.0.0.1:<random-port>/v/...`. Remote browsers can't reach that.

---

### Step 1 — Pull latest code on VM
```bash
cd /opt/neuroglancer-chat
git pull
```

---

### Step 2 — Add env vars to systemd environment file
```bash
sudo nano /etc/neuroglancer-chat.env
```
Add these two lines (replace with your VM's actual public IP):
```
NEUROGLANCER_SERVER_HOST=<VM-PUBLIC-IP>
NEUROGLANCER_SERVER_PORT=37293
```

> **Why the public IP, not `0.0.0.0`?**  
> The neuroglancer library builds the iframe src directly from `bind_address`. With `0.0.0.0` it falls back to `socket.getfqdn()` which returns `ng-chat.novalocal` — not reachable from your browser. Using the public IP puts that IP directly in the iframe src.

---

### Step 3 — Open port 37293 in the firewall
```bash
# firewalld (Rocky Linux / RHEL)
sudo firewall-cmd --permanent --add-port=37293/tcp
sudo firewall-cmd --reload

# verify
sudo firewall-cmd --list-ports
```

---

### Step 4 — Restart the frontend service
```bash
sudo systemctl daemon-reload
sudo systemctl restart neuroglancer-chat-frontend
```

---

### Step 5 — Verify
```bash
# 1. Confirm bind log line exists
sudo journalctl -u neuroglancer-chat-frontend -n 30 | grep "neuroglancer server bind"
# Expected: neuroglancer server bind: <VM-PUBLIC-IP>:37293

# 2. Confirm server is reachable on that port from VM itself
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:37293/
# Expected: 200 or 404 (anything but refused = server is up)
```

Then in your browser **DevTools → Elements**, find the `<iframe>` and confirm its src starts with `http://<VM-PUBLIC-IP>:37293/v/...` instead of `127.0.0.1`.

---

### What this does NOT require
- No nginx config changes
- No changes to the backend service
- No changes to Panel's `--address` or `--allow-websocket-origin` flags
- Bidirectional state sync (`viewer.param.watch`) continues to work unchanged