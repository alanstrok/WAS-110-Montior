# Déploiement sur Unraid

## Méthode 1 : Docker Compose (Recommandé)

### Prérequis
Installer le plugin **Docker Compose Manager** depuis Community Applications.

### Installation

1. Créer le dossier de configuration :
```bash
mkdir -p /mnt/user/appdata/was-110-monitor
```

2. Créer le fichier `docker-compose.yml` dans `/mnt/user/appdata/was-110-monitor/` :

```yaml
version: '3.8'

services:
  was110-monitor:
    build: https://github.com/alanstrok/WAS-110-Monitor.git
    container_name: was110-monitor
    restart: unless-stopped
    ports:
      - "5050:5050"
    volumes:
      - /mnt/user/appdata/was-110-monitor/data:/data
    environment:
      # Connexion WAS-110 (OBLIGATOIRE)
      - SFP_HOST=192.168.11.1
      - SFP_USER=root
      - SFP_ROOT_PASSWORD=VOTRE_MOT_DE_PASSE

      # Collecte de données
      - FETCH_INTERVAL_SECONDS=60
      - HISTORY_HOURS=72

      # Seuils d'alerte
      - TEMP_WARNING=65
      - TEMP_CRITICAL=75
      - OPTICAL_TEMP_WARNING=55
      - OPTICAL_TEMP_CRITICAL=65

      # Notifications (optionnel)
      - NOTIFICATIONS_ENABLED=false
      # Discord
      - DISCORD_WEBHOOK_URL=
      # Ntfy
      - NTFY_URL=https://ntfy.sh
      - NTFY_TOPIC=was110-alerts
```

3. Lancer via Docker Compose Manager ou en ligne de commande :
```bash
cd /mnt/user/appdata/was-110-monitor
docker-compose up -d
```

---

## Méthode 2 : Template Docker Unraid

### Installation manuelle du template

1. Télécharger le template XML :
```bash
mkdir -p /boot/config/plugins/dockerMan/templates-user
wget -O /boot/config/plugins/dockerMan/templates-user/was-110-monitor.xml \
  https://raw.githubusercontent.com/alanstrok/WAS-110-Monitor/main/unraid/was-110-monitor.xml
```

2. Dans l'interface Unraid :
   - Aller dans **Docker** → **Add Container**
   - Sélectionner le template **WAS-110-Monitor**
   - Configurer les paramètres

### Configuration requise

| Paramètre | Description |
|-----------|-------------|
| **SFP Host** | Adresse IP du WAS-110 (défaut: `192.168.11.1`) |
| **SFP Password** | Mot de passe SSH root du WAS-110 |
| **WebUI Port** | Port d'accès au dashboard (défaut: `5050`) |

---

## Méthode 3 : Ligne de commande Docker

```bash
# Créer le dossier de données
mkdir -p /mnt/user/appdata/was-110-monitor/data

# Construire l'image depuis GitHub
docker build -t was-110-monitor https://github.com/alanstrok/WAS-110-Monitor.git

# Lancer le conteneur
docker run -d \
  --name was-110-monitor \
  --restart unless-stopped \
  -p 5050:5050 \
  -v /mnt/user/appdata/was-110-monitor/data:/data \
  -e SFP_HOST=192.168.11.1 \
  -e SFP_USER=root \
  -e SFP_ROOT_PASSWORD="VOTRE_MOT_DE_PASSE" \
  -e FETCH_INTERVAL_SECONDS=60 \
  -e NOTIFICATIONS_ENABLED=false \
  was-110-monitor
```

---

## Accès au Dashboard

Une fois lancé, accéder à : **http://[IP_UNRAID]:5050**

---

## Configuration des Notifications

### Discord

1. Créer un webhook dans ton serveur Discord :
   - Paramètres du serveur → Intégrations → Webhooks → Nouveau webhook
2. Copier l'URL du webhook
3. Ajouter dans la configuration :
```yaml
- NOTIFICATIONS_ENABLED=true
- DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxx/yyy
```

### Ntfy (Notifications push mobile)

1. Installer l'app Ntfy sur ton téléphone
2. S'abonner à un topic (ex: `was110-alerts`)
3. Ajouter dans la configuration :
```yaml
- NOTIFICATIONS_ENABLED=true
- NTFY_URL=https://ntfy.sh
- NTFY_TOPIC=was110-alerts
```

### Email

```yaml
- NOTIFICATIONS_ENABLED=true
- SMTP_HOST=smtp.gmail.com
- SMTP_PORT=587
- SMTP_USER=ton_email@gmail.com
- SMTP_PASSWORD=mot_de_passe_application
- SMTP_FROM=ton_email@gmail.com
- SMTP_TO=alertes@exemple.com
```

---

## Réseau

Assure-toi que le serveur Unraid peut atteindre le WAS-110 :

```bash
# Test de connectivité
ping 192.168.11.1

# Test SSH
ssh root@192.168.11.1
```

Si ton WAS-110 est sur un VLAN différent, configure le routage approprié ou utilise le mode réseau `host` :

```yaml
network_mode: host
```

---

## Dépannage

### Le conteneur ne démarre pas
```bash
docker logs was-110-monitor
```

### Impossible de se connecter au WAS-110
- Vérifier l'adresse IP
- Vérifier le mot de passe SSH
- Vérifier que le port 22 est accessible

### Données non persistantes
Vérifier que le volume est correctement monté :
```bash
ls -la /mnt/user/appdata/was-110-monitor/data/
```
