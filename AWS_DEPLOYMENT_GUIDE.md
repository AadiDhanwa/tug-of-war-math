# 🚀 AWS EC2 Deployment Guide — Tug of War Math Game

## 📁 Project Structure
```
tug_of_war_math/
├── app.py
├── requirements.txt
└── templates/
    └── index.html
```

---

## ✅ STEP 1: Launch EC2 Instance on AWS

1. Go to → https://console.aws.amazon.com/ec2
2. Click **"Launch Instance"**
3. Set these values:
   - **Name**: `TugOfWarMathGame`
   - **AMI**: Ubuntu Server 22.04 LTS (Free Tier eligible)
   - **Instance type**: `t2.micro` (free tier) or `t3.small`
   - **Key pair**: Create new → Name it `tug-key` → Download `.pem` file (SAVE THIS!)
4. Under **"Network settings"**, click **Edit**, then add these inbound rules:
   - SSH: Port 22 (My IP)
   - Custom TCP: Port 5000 (Anywhere 0.0.0.0/0)
   - HTTP: Port 80 (Anywhere 0.0.0.0/0)
5. Click **"Launch Instance"**

---

## ✅ STEP 2: Connect to Your EC2 Instance

On your local machine (Mac/Linux Terminal or Git Bash on Windows):

```bash
# Fix key permissions first
chmod 400 tug-key.pem

# Connect (replace with YOUR EC2 public IP)
ssh -i "tug-key.pem" ubuntu@YOUR_EC2_PUBLIC_IP
```

> 📌 Find your Public IP in EC2 Console → Instances → your instance → "Public IPv4 address"

---

## ✅ STEP 3: Install Python & Dependencies on EC2

Run these commands inside your EC2 terminal:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python and pip
sudo apt install python3 python3-pip python3-venv -y

# Verify installation
python3 --version
pip3 --version
```

---

## ✅ STEP 4: Upload Your Project Files to EC2

**Option A: Using SCP (from your local terminal)**

```bash
# Upload entire project folder
scp -i "tug-key.pem" -r ./tug_of_war_math ubuntu@YOUR_EC2_PUBLIC_IP:/home/ubuntu/
```

**Option B: Using Git (if project is on GitHub)**

```bash
# On EC2, clone your repo
sudo apt install git -y
git clone https://github.com/YOUR_USERNAME/tug-of-war-math.git
cd tug-of-war-math
```

**Option C: Create files directly on EC2**

```bash
mkdir -p /home/ubuntu/tug_of_war_math/templates
nano /home/ubuntu/tug_of_war_math/app.py
# (paste app.py content, Ctrl+X → Y → Enter to save)

nano /home/ubuntu/tug_of_war_math/requirements.txt
# (paste requirements, save)

nano /home/ubuntu/tug_of_war_math/templates/index.html
# (paste HTML, save)
```

---

## ✅ STEP 5: Create Virtual Environment & Install Dependencies

```bash
# Navigate to project
cd /home/ubuntu/tug_of_war_math

# Create virtual env
python3 -m venv venv

# Activate it
source venv/bin/activate

# Install requirements
pip install -r requirements.txt

# Verify
pip list
```

---

## ✅ STEP 6: Test Run the App

```bash
# Make sure you're in project folder with venv active
cd /home/ubuntu/tug_of_war_math
source venv/bin/activate

# Run the app
python app.py
```

Now visit in your browser:
```
http://YOUR_EC2_PUBLIC_IP:5000
```

You should see the game! ✅

Press `Ctrl+C` to stop it.

---

## ✅ STEP 7: Run App Permanently with systemd (Keeps running after you close SSH)

```bash
# Create a service file
sudo nano /etc/systemd/system/tugofwar.service
```

Paste this content:

```ini
[Unit]
Description=Tug of War Math Game
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/tug_of_war_math
Environment="PATH=/home/ubuntu/tug_of_war_math/venv/bin"
ExecStart=/home/ubuntu/tug_of_war_math/venv/bin/gunicorn \
    --worker-class eventlet \
    -w 1 \
    --bind 0.0.0.0:5000 \
    app:app

Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Save: `Ctrl+X` → `Y` → `Enter`

```bash
# Enable and start the service
sudo systemctl daemon-reload
sudo systemctl enable tugofwar
sudo systemctl start tugofwar

# Check status
sudo systemctl status tugofwar
```

✅ Your app is now running permanently!

---

## ✅ STEP 8: (Optional) Set Up on Port 80 with Nginx

So users can access `http://YOUR_IP` without `:5000`

```bash
# Install Nginx
sudo apt install nginx -y

# Configure Nginx
sudo nano /etc/nginx/sites-available/tugofwar
```

Paste:

```nginx
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
# Enable config
sudo ln -s /etc/nginx/sites-available/tugofwar /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default   # remove default
sudo nginx -t                              # test config
sudo systemctl restart nginx

# Open port 80 in security group (if not already done)
# Go to EC2 → Security Groups → Inbound → Add: HTTP port 80
```

Now visit: `http://YOUR_EC2_PUBLIC_IP` (no port needed!)

---

## ✅ STEP 9: (Optional) Add a Domain Name

1. Buy a domain on Route 53 or GoDaddy
2. Create an A record pointing to your EC2 Public IP
3. Install SSL with Let's Encrypt:

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d yourdomain.com
```

Now your game is at `https://yourdomain.com` 🎉

---

## 🔧 Useful Commands

```bash
# Restart app
sudo systemctl restart tugofwar

# View logs
sudo journalctl -u tugofwar -f

# Check Nginx logs
sudo tail -f /var/log/nginx/error.log

# Stop app
sudo systemctl stop tugofwar
```

---

## 💰 Cost Estimate

| Resource         | Cost                        |
|------------------|-----------------------------|
| t2.micro EC2     | Free (first 12 months)      |
| Elastic IP       | Free if attached to running instance |
| Data Transfer    | First 1GB/month free        |
| Domain (optional)| ~$12/year                   |

---

## 🎮 Game URL After Deployment

```
http://YOUR_EC2_PUBLIC_IP:5000     ← Direct
http://YOUR_EC2_PUBLIC_IP          ← With Nginx
https://yourdomain.com             ← With domain + SSL
```
