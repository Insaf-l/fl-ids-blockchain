# FL-IDS — Federated Learning Intrusion Detection System via Blockchain

## Description

Ce projet implémente un système de **détection d'intrusions réseau** basé sur l'**apprentissage fédéré décentralisé**. Les peers entraînent localement un modèle de Deep Learning sur le dataset **NSL-KDD**, puis échangent leurs gradients via une **blockchain Ethereum locale** lancée avec Hardhat.

Le système intègre aussi une défense contre les comportements byzantins/adversariaux :

- **Blockchain Ethereum locale** avec Hardhat pour tracer les gradients, votes et agrégations.
- **Multi-Krum adaptatif + IQR** pour filtrer les gradients suspects.
- **Consensus BFT on-chain** et blacklist persistante des peers malveillants.
- **DP-SGD** optionnel pour la confidentialité différentielle.
- Dataset **NSL-KDD** pour la détection d'intrusions réseau.
- Simulation de peers honnêtes et de peers malveillants : `scale`, `flip`, `boost`, `noise`.

---

## Structure du projet

```text
fl-ids-blockchain/
│
├── fl/                          # Cœur du système Federated Learning
│   ├── peer.py                  # Peer honnête : entraînement local + rounds FL
│   ├── malicious_peer.py        # Peer malveillant : attaques scale/flip/boost/noise
│   ├── defense.py               # Défense Multi-Krum, IQR, BFT, blacklist
│   ├── model.py                 # Modèle MLP PyTorch
│   ├── data_loader.py           # Chargement et préparation NSL-KDD
│   ├── privacy.py               # DP-SGD, bruit gaussien, clipping
│   ├── blockchain_logger.py     # Interface Python ↔ Ethereum avec Web3.py
│   └── config.py                # Hyperparamètres et chemins du projet
│
├── blockchain/                  # Partie blockchain / smart contract
│   ├── contracts/
│   │   └── FLGradientRegistry.sol
│   ├── scripts/
│   │   └── deploy.js
│   ├── hardhat.config.js
│   ├── package.json
│   └── package-lock.json
│
├── data/                        # Dataset NSL-KDD
│   ├── KDDTrain+.txt
│   └── KDDTest+.txt
│
├── dashboard_server.py          # Serveur Flask pour visualisation des résultats
├── generate_dashboard.py        # Génération du dashboard HTML statique
├── start_fl.py                  # Lanceur automatique Windows / Linux / WSL
├── requirements.txt             # Dépendances Python
├── .gitignore                   # Fichiers générés ignorés par Git
└── README.md
```

> Les dossiers comme `logs/`, `blockchain/artifacts/`, `blockchain/cache/`, `blockchain/node_modules/` et les fichiers `fl_results_peer*.json` ne sont pas dans Git. Ils sont générés pendant l'installation ou l'exécution.

---

## Prérequis

| Outil | Version recommandée | Rôle |
|------|---------------------|------|
| Python | ≥ 3.10 | Entraînement FL et scripts Python |
| Node.js | ≥ 18, recommandé 20 LTS | Hardhat et blockchain locale |
| npm | ≥ 9 | Installation des dépendances Node |
| Git | ≥ 2.40 | Gestion du repo |
| lsof | Linux/WSL | Libération automatique du port 8545 |

---

## Installation — Linux / WSL Ubuntu

### 1. Cloner le projet

```bash
git clone <URL_DU_REPO>
cd fl-ids-blockchain
```

### 2. Installer les outils système

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv lsof curl git -y
python3 --version
```

### 3. Créer et activer un environnement virtuel

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

Pour désactiver l'environnement :

```bash
deactivate
```

### 4. Installer les dépendances Python

Installation normale :

```bash
python -m pip install -r requirements.txt
```

Si l'installation de `torch` installe beaucoup de paquets `nvidia-*` ou reste bloquée, installe d'abord la version CPU de PyTorch :

```bash
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
```

Vérification :

```bash
python -c "import torch, numpy, pandas, sklearn, web3, flask; print('OK Python dependencies')"
```

### 5. Installer Node.js avec nvm

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.bashrc
nvm install 20
nvm use 20
node --version
npm --version
```

### 6. Installer les dépendances blockchain

```bash
cd blockchain
npm install
cd ..
```

Vérification :

```bash
cd blockchain
npx hardhat --version
cd ..
```

### 7. Vérifier les données

```bash
ls data/
```

Le dossier doit contenir :

```text
KDDTrain+.txt
KDDTest+.txt
```

---

## Installation — Windows PowerShell

### 1. Cloner le projet

```powershell
git clone <URL_DU_REPO>
cd fl_project
```

### 2. Vérifier Python

```powershell
python --version
```

Si Python n'est pas installé :

```powershell
winget install Python.Python.3.12
```

### 3. Créer et activer un environnement virtuel

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
```

Si PowerShell bloque l'activation du venv :

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\.venv\Scripts\Activate.ps1
```

### 4. Installer les dépendances Python

```powershell
python -m pip install -r requirements.txt
```

Vérification :

```powershell
python -c "import torch, numpy, pandas, sklearn, web3, flask; print('OK Python dependencies')"
```

### 5. Installer Node.js

Avec winget :

```powershell
winget install OpenJS.NodeJS.LTS
```

Puis vérifier :

```powershell
node --version
npm --version
```

### 6. Installer les dépendances blockchain

```powershell
cd blockchain
npm install
cd ..
```

---

## 🚀 Lancement du projet

Le projet se lance avec un seul script :

```bash
python start_fl.py
```

Sous Linux/WSL, tu peux aussi utiliser :

```bash
python3 start_fl.py
```

Le script détecte automatiquement l'environnement :

- Windows → mode `windows`
- Linux → mode `linux`
- WSL → mode `linux`

Tu peux aussi forcer la plateforme :

```bash
python start_fl.py --platform windows
python start_fl.py --platform linux
```

---

## Mode normal — tous les peers honnêtes

Linux / WSL :

```bash
python3 start_fl.py --platform linux
```

Windows :

```powershell
python start_fl.py --platform windows
```

---

## Mode attaque — un seul peer malveillant

Exemple : peer 5 malveillant, attaque `flip`, à partir du round 4.

Linux / WSL :

```bash
python3 start_fl.py --malicious 5 --strategy flip --start-round 4 --platform linux
```

Windows :

```powershell
python start_fl.py --malicious 5 --strategy flip --start-round 4 --platform windows
```

Autres exemples :

```bash
python3 start_fl.py --malicious 3 --strategy scale --start-round 2 --platform linux
python3 start_fl.py --malicious 6 --strategy boost --start-round 4 --platform linux
python3 start_fl.py --malicious 4 --strategy noise --start-round 4 --platform linux
```

---

## Mode attaque — plusieurs peers malveillants

Format :

```bash
--attackers ID:STRATEGY:ROUND ID:STRATEGY:ROUND
```

Exemple :

```bash
python3 start_fl.py --platform linux --attackers 3:flip:3 5:scale:4
```

Cela signifie :

- peer 3 utilise l'attaque `flip` à partir du round 3 ;
- peer 5 utilise l'attaque `scale` à partir du round 4.

---

## Options de `start_fl.py`

| Option | Description | Exemple |
|--------|-------------|---------|
| `--platform` | Force la plateforme : `auto`, `windows`, `linux` | `--platform linux` |
| `--malicious` | Définit un seul peer malveillant | `--malicious 5` |
| `--strategy` | Stratégie d'attaque | `--strategy flip` |
| `--start-round` | Round de début d'attaque | `--start-round 4` |
| `--attackers` | Définit plusieurs attaquants | `--attackers 3:flip:3 5:scale:4` |

Stratégies disponibles :

| Stratégie | Description | Impact attendu |
|----------|-------------|----------------|
| `scale` | Multiplie les gradients | Déviation du modèle global |
| `flip` | Inverse les labels | Confusion normal/attaque |
| `boost` | Amplifie fortement les gradients | Tentative d'écrasement des autres gradients |
| `noise` | Injecte du bruit gaussien | Dégradation progressive |

---

## Ce que fait `start_fl.py`

```text
[1/3] Démarre le nœud Hardhat local sur le port 8545
[2/3] Déploie le smart contract FLGradientRegistry.sol
[2b]  Nettoie les anciens résultats d'exécution
[3/3] Lance les 7 peers FL en parallèle
```

Le script crée automatiquement le dossier `logs/` si nécessaire.

---

## Résultats générés

Après une exécution, le projet peut générer :

```text
logs/
├── hardhat_node.log
├── deploy.log
├── peer0_run.log
├── peer1_run.log
├── ...
└── blacklist_state.json

fl_results_peer0.json
fl_results_peer1.json
...
fl_results_peer5_malicious.json
blockchain_config.json
dashboard.html
```

Ces fichiers ne doivent pas être commités dans Git, car ils dépendent de l'exécution locale.

---

## Dashboard

### Dashboard HTML statique

Après un run :

```bash
python generate_dashboard.py
```

Sous WSL, pour ouvrir le dashboard dans Windows :

```bash
explorer.exe dashboard.html
```

Sous Windows PowerShell :

```powershell
Start-Process dashboard.html
```

### Dashboard serveur Flask

```bash
python dashboard_server.py
```

Puis ouvrir dans le navigateur :

```text
http://localhost:5000
```

---

## Configuration principale

Les paramètres principaux sont dans :

```text
fl/config.py
```

Exemples de paramètres :

```python
NUM_PEERS        = 7
NUM_ROUNDS       = 10
EPOCHS_PER_ROUND = 3
BATCH_SIZE       = 32
LEARNING_RATE    = 0.001

USE_DEFENSE           = True
NUM_BYZANTINE_ASSUMED = 2
BLACKLIST_THRESHOLD   = 3

USE_PRIVACY         = False
DP_NOISE_MULTIPLIER = 1.0
DP_MAX_GRAD_NORM    = 1.0
```

---

## Fichiers ignorés par Git

Le `.gitignore` exclut notamment :

```text
.venv/
__pycache__/
*.pyc
logs/
fl_results_peer*.json
blockchain_config.json
dashboard.html
blockchain/node_modules/
blockchain/artifacts/
blockchain/cache/
```

Ces fichiers/dossiers sont recréés automatiquement par Python, Hardhat, npm ou les scripts du projet.

---

## Erreurs courantes

### `Need to install the following packages: hardhat@...`

Cela signifie que les dépendances Node ne sont pas installées dans `blockchain/node_modules/`.

Solution :

```bash
cd blockchain
npm install
cd ..
```

Puis relancer :

```bash
python3 start_fl.py --platform linux
```

### `ERREUR : noeud Hardhat non disponible`

Causes possibles :

- Hardhat n'est pas installé.
- `npm install` n'a pas été exécuté.
- Le port 8545 est déjà occupé.
- `npx hardhat node` attend une confirmation interactive.

Solutions :

```bash
cd blockchain
npm install
cd ..
python3 start_fl.py --platform linux
```

### `Error: listen EADDRINUSE 0.0.0.0:8545`

Le port Hardhat est déjà utilisé.

Linux / WSL :

```bash
fuser -k 8545/tcp
```

Ou :

```bash
lsof -ti tcp:8545
kill -9 <PID>
```

Windows PowerShell :

```powershell
netstat -ano | findstr :8545
taskkill /F /PID <PID>
```

### `ModuleNotFoundError: No module named 'web3'`

Active d'abord ton environnement virtuel, puis installe les dépendances :

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Sous Windows :

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### Installation bloquée sur des paquets `nvidia-*`

Cela vient souvent de PyTorch qui installe une version CUDA lourde.

Solution CPU-only :

```bash
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
```

### `blockchain_config.json not found`

Le smart contract n'a pas été déployé correctement.

Vérifie Hardhat :

```bash
cd blockchain
npx hardhat node
```

Dans un autre terminal :

```bash
cd blockchain
npx hardhat run scripts/deploy.js --network localhost
```

### `FileNotFoundError: data/KDDTrain+.txt`

Vérifie que les fichiers suivants existent :

```text
data/KDDTrain+.txt
data/KDDTest+.txt
```

### PowerShell bloque l'environnement virtuel

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## Commandes utiles de test

Tester les dépendances Python :

```bash
python -c "import torch, flask, web3; print('OK')"
```

Tester Hardhat :

```bash
cd blockchain
npx hardhat --version
cd ..
```

Tester le port 8545 :

```bash
lsof -i :8545
```

---

## Technologies utilisées

| Couche | Technologie |
|-------|-------------|
| Deep Learning | PyTorch |
| Dataset | NSL-KDD |
| Federated Learning | Peers Python décentralisés |
| Défense | Multi-Krum, IQR, BFT, blacklist |
| Blockchain | Ethereum local, Solidity, Hardhat |
| Interface blockchain | Web3.py |
| Dashboard | HTML statique, Flask |

---

## Auteurs

| Nom | GitHub |
|-----|--------|
| Khadija Izarzar | `@khadija-izarzar` |
| Insaf Lachgar | `@insaf-l` |
| Soumya Ihmouten | `@soumya06ih` |

---

## Licence

Ce projet est réalisé dans le cadre académique de l'ENSA Oujda — Université Mohammed Premier.
