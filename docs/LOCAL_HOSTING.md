# Hosting on your own PC / local network

Run the whole system on one Windows PC in the plant or office. Everyone on the
same Wi-Fi or LAN — desktops, phones, scanners — uses it through that PC's IP address.

---

## 1. Start it

Double-click **`start-windows.bat`**.

The first run:

1. creates a Python environment and installs the components (a couple of minutes),
2. writes a `.env` configured for this network, with a fresh secret key and this PC's
   detected address,
3. creates the database and seeds the roles, units, categories, label template and logo,
4. **asks you to choose an administrator username and password** — the password does not
   appear as you type, which is normal,
5. starts the server.

Later runs skip straight to step 5. Nothing overwrites `.env` once it exists, so any
edit you make there survives.

Then it prints:

```
==============================================================
  SPARES INVENTORY - running on your local network
==============================================================
  On this PC        : http://127.0.0.1:8000
  On the network    : http://192.168.1.45:8000
  Label QR codes    : http://192.168.1.45:8000
==============================================================
```

Open the network address from any PC or phone on the same network and sign in with the
account you just created.

(Linux or Mac: run `./start-linux.sh` instead.)

To add more logins later, use **Users → New user** inside the application.

---

## 2. Windows firewall

The first time you start it, Windows asks whether to allow Python through the
firewall. **Tick "Private networks" and allow it.** If you clicked Cancel, other
devices will not connect. To fix it later, in an Administrator PowerShell:

```powershell
New-NetFirewallRule -DisplayName "Spares Inventory" -Direction Inbound `
  -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private
```

---

## 3. Give this PC a fixed IP — before printing labels

This is the one step that is expensive to undo.

Every QR code is printed with the **full URL** baked into it, for example
`http://192.168.1.45:8000/i/ngrFc5le8CAM.../`. If the PC's address later changes,
every sticker already on a shelf points nowhere and has to be reprinted.

Pick one of these before you print a batch:

**a) DHCP reservation (easiest).** In your router, bind this PC's MAC address to a
fixed IP. Nothing else to configure.

**b) Static IP on the PC.** Settings → Network → Change adapter options → IPv4 →
enter a fixed address outside the DHCP pool.

**c) A hostname (best).** If your network has DNS, use a name instead of a number, so
the address survives even if the IP moves. Set it in `.env`:

```
PUBLIC_BASE_URL=http://inventory.local:8000
```

Then restart. Print one label, scan it with a phone, confirm the page opens — *then*
print the rest.

The server re-checks this every time it starts. If `PUBLIC_BASE_URL` no longer matches
the address the PC actually has, it prints a warning — so a DHCP change gets caught on
the next restart, rather than at a rack with a scanner that will not beep.

---

## 4. What the QR code shows

The QR opens a **public product page**: item number, name, category, make, model,
material, weight, size, colour, specification, drawing/OEM numbers and the product
image.

It deliberately does **not** show stock quantity, warehouse/rack location, suppliers,
document numbers or the company logo, because the link is public — a customer, supplier
or visitor holding the part can open it. Your staff see stock and location on the
internal scanner and item pages after signing in.

If you are on a fully closed network and want those figures on the QR page anyway, turn
them on at **Settings → System Settings → Public QR page**.

To switch the public page off entirely, untick **Public QR page enabled**.

---

## 5. Keeping it running

`start-windows.bat` runs in a console window; closing the window stops the server.
For an always-on install, run it as a Windows service with
[NSSM](https://nssm.cc/) (free):

```bat
nssm install SparesInventory "C:\spares\.venv\Scripts\python.exe" "C:\spares\manage.py serve_lan --port 8000"
nssm set SparesInventory AppDirectory C:\spares
nssm start SparesInventory
```

It then starts automatically with Windows.

---

## 6. Backups

The database is a single file, `data/spares.sqlite3`, and uploads live in `media/`.
Use **Settings → Backup & Restore** to produce one zip containing both, and copy it to
a network drive or USB stick. To automate it, add a Windows Task Scheduler job:

```bat
C:\spares\.venv\Scripts\python.exe C:\spares\manage.py backup_now --scheduled --keep 30
```

A backup that lives only on the same PC is not a backup.

---

## 7. When to move off SQLite

The local setup uses SQLite, which is genuinely fine for a single-site store with a
handful of concurrent users. Move to PostgreSQL when you have more than roughly five
people posting transactions at the same time, or when you outgrow one PC — SQLite
serialises writes, so heavy concurrent posting will start to queue.

Switching is a settings change plus a data reload; see `INSTALLATION.md`.

---

## 8. Reaching it from outside the plant

Everything above is LAN-only: phones on mobile data cannot open the QR links. If you
need that — field staff, customers scanning at their own site — the system has to be on
a public address with HTTPS. Two options:

- **Move it to a cloud VPS** (see `INSTALLATION.md`) and set `PUBLIC_BASE_URL` to the
  public domain. This is the cleaner answer.
- **Publish the local PC** through your firewall with a domain name and a TLS
  certificate. Do not expose port 8000 directly; put nginx or Caddy in front.

Decide this **before** printing labels, because the URL is physically on the sticker.
