# fl/config.py — Configuration centrale du système FL
#
# MODIFICATION : SHARED_DIR supprimé.
# Le dossier /shared n'existe plus. Tous les échanges de gradients,
# votes et agrégations passent désormais par la blockchain (Hardhat local).

import os

# ─── Paramètres réseau FL ────────────────────────────────────────────────────
NUM_PEERS        = 7
NUM_ROUNDS       = 10
EPOCHS_PER_ROUND = 3
BATCH_SIZE       = 32
LEARNING_RATE    = 0.001

# ─── Défense ─────────────────────────────────────────────────────────────────
USE_DEFENSE            = True
NUM_BYZANTINE_ASSUMED  = 2
BLACKLIST_THRESHOLD    = 3
BFT_QUORUM             = NUM_PEERS // 2 + 1

# ─── Privacy Différentielle ───────────────────────────────────────────────────
USE_PRIVACY         = False
DP_NOISE_MULTIPLIER = 1.0
DP_MAX_GRAD_NORM    = 1.0
DP_DELTA            = 1e-5

# ─── Chemins (SHARED_DIR supprimé) ───────────────────────────────────────────
BASE_DIR        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# SHARED_DIR supprimé — les fichiers partagés passent par la blockchain
LOGS_DIR        = os.path.join(BASE_DIR, "logs")
DATA_PATH       = os.path.join(BASE_DIR, "data", "KDDTrain+.txt")
RESULTS_FILE    = os.path.join(BASE_DIR, "fl_results.json")
ATTACK_LOG_FILE = os.path.join(BASE_DIR, "attack_log.json")
BC_CONFIG_FILE  = os.path.join(BASE_DIR, "blockchain_config.json")

# ─── Blockchain ───────────────────────────────────────────────────────────────
HARDHAT_RPC_URL = "http://127.0.0.1:8545"
CHAIN_ID        = 31337

# ─── Timeouts ─────────────────────────────────────────────────────────────────
# Temps max pour attendre qu'un peer publie ses gradients sur la blockchain
GRADIENT_WAIT_TIMEOUT = 180   # secondes (plus long car tx blockchain ~1-2s)
ATTACK_WINDOW         = 0.5   # délai entre publication gradients et sentinelle