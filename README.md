# Despliegue en OCI

## 📘 Guía para despliegue en OCI - Capa Gratuita

Explicación paso a paso para desplegar la aplicación `DocuMind` hecha con python y streamlit, en una máquina virtual de Oracle Cloud Infrastructure (OCI).

---

### Paso 1: Configurar el Servidor en OCI (UFW & SWAP)

En la VM gratuita de OCI AMD (1GB de RAM), es indispensable habilitar memoria swap para evitar desbordes.

```bash
# 1. Crear un Swap File de 4 GB para prevenir colapso de RAM
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 2. Configurar el Firewall Local (UFW) para permitir HTTP y HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw reload
```

---

### Paso 2: Abrir los puertos en la Consola de OCI

Para que la aplicación sea visible desde la web:

1. Ir a la consola de OCI -> **Networking** -> **Virtual Cloud Networks**.
2. Hacer clic en la VCN y luego en **Security Lists**.
3. Añadir una **Ingress Rule** con:
   - **Source CIDR:** `0.0.0.0/0`
   - **IP Protocol:** `TCP`
   - **Destination Port Range:** `80, 443`

---

### Paso 3: Configurar Proxy Inverso Nginx & SSL Certbot

Streamlit corre por defecto en el puerto `8501`. Usamos `Nginx` para redirigir el tráfico del puerto `80` (HTTP) de manera transparente y encriptarlo con SSL Certbot para HTTPS gratis.

Instalamos Nginx y lo configuramos asi:

```bash
sudo apt update
sudo apt install nginx -y
```

Creamos la configuración para el sitio de Streamlit:
```bash
sudo nano /etc/nginx/sites-available/documind
```

Agrega este bloque de código (reemplaza `tu-dominio.com` por el tuyo):
```nginx
server {
    listen 80;
    server_name tu-dominio.com;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Habilita el sitio y reinicia Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/documind /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default
sudo systemctl restart nginx
```

Obtén tu certificado SSL gratuito con Certbot:
```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d tu-dominio.com
```

---

### Paso 4: Despliegue de la Aplicación en OCI

```bash
# 1. Clonar el repositorio en OCI
git clone <URL_DE_TU_REPOSITORIO_GITHUB>
cd <nombre_de_carpeta>

# 2. Crear un entorno virtual de Python e instalar dependencias
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. Crear el archivo .env con tus secretos
nano .env
```
Contenido de `.env`:
```env
GEMINI_API_KEY="tu_clave_api_aquí"
DB_HOST="localhost"
DB_PORT=5432
DB_NAME="ragdb"
DB_USER="postgres"
DB_PASSWORD="tu_password_seguro"
```

Inicia la aplicación en segundo plano con `nohup` o un servicio de `systemd`:

```bash
nohup streamlit run app.py --server.port 8501 --server.address 127.0.0.1 &
```

---



Hazlo ejecutable y córrelo:

```bash
chmod +x git_push.sh
./git_push.sh
```

Esto dejará tu repositorio en GitHub con un historial de commits sumamente profesional, modular y ordenado, demostrando excelencia en el desarrollo paso a paso del MVP.
