# 🖥️ Client Login Guide — Simple Steps

## Problem
Server par Chrome window nahi dikhti (no display). Isliye **local laptop par login karo**, session **automatically server par upload** ho jaayega.

---

## Steps for Client (Super Simple)

### Step 1: Download Files
Client ko yeh 2 files download karni hain:
- `login_local_and_upload.py`
- `login_and_upload.bat`

### Step 2: Edit 1 Line
`login_and_upload.bat` mein **Sirf 1 line change** karo:
```batch
set SERVER_IP=68.178.160.47   <-- Apna server IP daalo
set SSH_USER=autoclicker        <-- Apna SSH username
set PROFILE_NAME=indiamart      <-- Jo bhi naam chaho
```

### Step 3: Double Click
`login_and_upload.bat` par **double-click** karo:
1. Chrome window **apne laptop par** open hoga
2. IndiaMART mein **login karo**
3. Batch file window mein **ENTER dabaao**
4. Session **automatically server par upload** ho jaayega

---

## Alternative: Command Line

Agar batch file nahi chal rahi:
```bash
# Pehle dependencies install karo
pip install playwright paramiko
python -m playwright install chromium

# Phir script chalao
python login_local_and_upload.py \
  --server 68.178.160.47 \
  --user autoclicker \
  --profile indiamart
```

---

## Kya Hoga

| Step | Kya Dikhega |
|------|-------------|
| 1 | Chrome window open hoga **tere laptop par** |
| 2 | IndiaMART login page dikhega |
| 3 | Tu login karega (normal jaise karta hai) |
| 4 | Command window mein ENTER dabaane bola jayega |
| 5 | File upload hoga, "SUCCESS!" message aayega |

---

## After Upload

Server par session save ho gayi. Ab Velora dashboard mein:
- **Browser Profile Name** = `indiamart` (jo tune set kiya)

Job start karo — automation **logged in** hoke chalegi! 🎉

---

## Troubleshooting

### "Python not found"
→ Python install karo: https://python.org (3.10+ recommended)

### "SSH connection failed"
→ Server IP check karo, SSH password confirm karo

### "Upload failed"
→ Manually zip file bhej do:
   - Local folder: `%USERPROFILE%\.velora_profiles\indiamart`
   - Server par (Docker): `/data/browser_profiles/indiamart/`
