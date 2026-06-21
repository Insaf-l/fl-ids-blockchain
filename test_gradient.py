# test_gradient.py — teste submitGradient en isolation
import numpy as np
import json
from web3 import Web3

# Charger config
with open("blockchain_config.json") as f:
    addr = json.load(f)["contract_address"]

import sys
sys.path.insert(0, "fl")
from blockchain_logger import BlockchainLogger

bc = BlockchainLogger(account_index=0)

# Simuler les gradients du petit modele (41->32->16->1 = 1889 params)
flat = np.random.randn(1889).astype(np.float32)
print(f"Taille gradient : {flat.nbytes} bytes = {flat.nbytes/1024:.1f} KB")

try:
    tx = bc.submit_gradient(round_num=99, peer_id=0, flat_weights=flat)
    print(f"SUCCESS ! tx : {tx[:20]}...")
    
    recovered = bc.get_gradient(99, 0)
    print(f"Recupere : {len(recovered)} params, erreur max : {np.max(np.abs(flat - recovered)):.6f}")
except Exception as e:
    print(f"ECHEC : {e}")