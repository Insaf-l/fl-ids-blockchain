# fl/defense.py — Krum (Multi-Krum) + Seuil adaptatif + Blacklist persistante
#
# MODIFICATIONS :
#   • compute_local_vote_bc()  : publie le vote sur la blockchain (plus de fichier .json)
#   • collect_votes_bc()       : lit les votes depuis la blockchain (plus de /shared)
#   • bft_consensus_bc()       : consensus via blockchain
#
# Les anciennes fonctions compute_local_vote / collect_votes / bft_consensus
# (basées sur le filesystem) sont conservées pour compatibilité mais ne
# doivent plus être appelées depuis peer.py.
 
import json
import os
import time
import numpy as np
from typing import Dict, List, Optional, Tuple
from config import (
    NUM_PEERS,
    NUM_BYZANTINE_ASSUMED,
    BFT_QUORUM,
    BLACKLIST_THRESHOLD,
    LOGS_DIR,
)
 
# ─── Fichier de persistance de la blacklist locale ────────────────────────────
BLACKLIST_FILE = os.path.join(LOGS_DIR, "blacklist_state.json")
 
# ─── Seuil Krum adaptatif ─────────────────────────────────────────────────────
KRUM_SIGMA_THRESHOLD = 2.5
 
 
# ─── Persistance de la blacklist locale ───────────────────────────────────────
 
def load_local_blacklist() -> Dict[int, int]:
    if os.path.exists(BLACKLIST_FILE):
        try:
            with open(BLACKLIST_FILE, "r") as f:
                return {int(k): v for k, v in json.load(f).items()}
        except Exception:
            pass
    return {}
 
 
def save_local_blacklist(blacklist: Dict[int, int]) -> None:
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(BLACKLIST_FILE, "w") as f:
        json.dump(blacklist, f, indent=2)
 
 
# ─── Multi-Krum adaptatif ─────────────────────────────────────────────────────
 
def multi_krum_adaptive(
    weight_vectors: Dict[int, np.ndarray],
    local_blacklist: Dict[int, int],
    f: int = NUM_BYZANTINE_ASSUMED,
) -> Tuple[List[int], Dict[int, float]]:
    ids = list(weight_vectors.keys())
    n   = len(ids)
 
    if n <= 2:
        return ids, {i: 0.0 for i in ids}
 
    k    = max(1, n - f - 2)
    vecs = np.array([weight_vectors[i] for i in ids])
 
    dist_matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i != j:
                dist_matrix[i, j] = np.sum((vecs[i] - vecs[j]) ** 2)
 
    scores = {}
    for idx, peer_id in enumerate(ids):
        row            = dist_matrix[idx].copy()
        row[idx]       = np.inf
        nearest_k      = np.sort(row)[:k]
        scores[peer_id] = float(np.sum(nearest_k))
 
    score_values  = list(scores.values())
    median_score  = np.median(score_values)
    q1            = np.percentile(score_values, 25)
    q3            = np.percentile(score_values, 75)
    iqr           = q3 - q1
    sigma_approx  = iqr / 1.349 if iqr > 0 else np.std(score_values)
    dyn_threshold = median_score + KRUM_SIGMA_THRESHOLD * sigma_approx
 
    accepted_ids = []
    for pid in ids:
        is_above     = scores[pid] > dyn_threshold and sigma_approx > 0
        is_bl_local  = local_blacklist.get(pid, 0) >= BLACKLIST_THRESHOLD
        if not is_above and not is_bl_local:
            accepted_ids.append(pid)
 
    min_accepted = max(1, n - f)
    if len(accepted_ids) < min_accepted:
        sorted_ids   = sorted(ids, key=lambda i: scores[i])
        accepted_ids = sorted_ids[:min_accepted]
 
    return accepted_ids, scores
 
 
# ─── Gestion de la blacklist locale ───────────────────────────────────────────
 
def update_blacklist_state(
    acceptance_mask: Dict[int, bool],
    local_blacklist: Dict[int, int],
) -> Dict[int, int]:
    for pid, accepted in acceptance_mask.items():
        if not accepted:
            local_blacklist[pid] = local_blacklist.get(pid, 0) + 1
        else:
            local_blacklist[pid] = 0
 
    active_ids = list(acceptance_mask.keys())
    for pid in list(local_blacklist.keys()):
        if pid not in active_ids:
            del local_blacklist[pid]
 
    save_local_blacklist(local_blacklist)
    return local_blacklist
 
 
# =============================================================================
# NOUVELLES FONCTIONS BLOCKCHAIN (remplacent les fonctions fichier)
# =============================================================================
 
def compute_local_vote_bc(
    weight_vectors: Dict[int, np.ndarray],
    peer_id: int,
    round_num: int,
    bc,                                      # BlockchainLogger
    local_blacklist: Optional[Dict[int, int]] = None,
) -> Dict[int, bool]:
    """
    Exécute Krum adaptatif localement et PUBLIE le vote sur la blockchain.
 
    Remplace compute_local_vote() qui écrivait dans :
        shared/vote_peer{peer_id}_r{round_num}.json
    Maintenant appelle :
        bc.submit_vote(round_num, peer_id, mask, scores, local_blacklist)
    """
    if local_blacklist is None:
        local_blacklist = load_local_blacklist()
 
    accepted_ids, scores = multi_krum_adaptive(weight_vectors, local_blacklist)
    mask = {pid: (pid in accepted_ids) for pid in weight_vectors}
 
    # Publication sur la blockchain (remplace l'écriture fichier)
    bc.submit_vote(round_num, peer_id, mask, scores, local_blacklist)
 
    return mask
 
 
def collect_votes_bc(
    round_num: int,
    bc,                   # BlockchainLogger
    timeout: int = 90,
) -> List[dict]:
    """
    Attend et lit tous les votes depuis la blockchain.
 
    Remplace collect_votes() qui lisait les fichiers vote_peer{id}_r{round}.json
    dans /shared. Maintenant appelle bc.is_vote_ready() + bc.get_vote().
    """
    votes   = []
    waited  = 0
    interval = 1.0
 
    while len(votes) < NUM_PEERS and waited < timeout:
        votes = []
        for pid in range(NUM_PEERS):
            if bc.is_vote_ready(round_num, pid):
                vote = bc.get_vote(round_num, pid)
                if vote is not None:
                    votes.append(vote)
        if len(votes) < NUM_PEERS:
            time.sleep(interval)
            waited += interval
 
    return votes
 
 
def bft_consensus_bc(
    round_num: int,
    bc,                   # BlockchainLogger
    timeout: int = 90,
) -> Tuple[Dict[int, bool], bool]:
    """
    Consensus BFT via blockchain.
 
    Remplace bft_consensus() qui lisait les fichiers depuis /shared.
    La logique de comptage/quorum est identique, seule la source des
    votes change (blockchain au lieu de fichiers).
    """
    votes = collect_votes_bc(round_num, bc, timeout)
    if not votes:
        return {pid: True for pid in range(NUM_PEERS)}, False
 
    acceptance_count: Dict[int, int] = {pid: 0 for pid in range(NUM_PEERS)}
    for vote in votes:
        for pid_str, accepted in vote["mask"].items():
            if accepted:
                acceptance_count[int(pid_str)] += 1
 
    final_mask = {
        pid: (count >= BFT_QUORUM)
        for pid, count in acceptance_count.items()
    }
 
    target = json.dumps(
        {str(k): v for k, v in final_mask.items()}, sort_keys=True
    )
    agreement_count = sum(
        1 for vote in votes
        if json.dumps(
            {str(k): v for k, v in {int(kk): vv
             for kk, vv in vote["mask"].items()}.items()},
            sort_keys=True,
        ) == target
    )
    consensus_reached = agreement_count >= BFT_QUORUM
 
    return final_mask, consensus_reached
 
 
# =============================================================================
# AGRÉGATION (inchangée)
# =============================================================================
 
def fedavg(
    weight_vectors: Dict[int, np.ndarray],
    accepted_ids: List[int],
) -> Optional[np.ndarray]:
    if not accepted_ids:
        return None
    selected = [weight_vectors[pid] for pid in accepted_ids if pid in weight_vectors]
    if not selected:
        return None
    return np.mean(selected, axis=0).astype(np.float32)
 
 
# =============================================================================
# FONCTIONS LEGACY (conservées pour compatibilité, ne plus appeler depuis peer.py)
# =============================================================================
 
def multi_krum(
    weight_vectors: Dict[int, np.ndarray],
    f: int = NUM_BYZANTINE_ASSUMED,
) -> Tuple[List[int], Dict[int, float]]:
    """Compatibilité — utilise la version adaptative avec blacklist vide."""
    return multi_krum_adaptive(weight_vectors, {})
 
 
def compute_local_vote(
    weight_vectors, peer_id, round_num, local_blacklist=None
):
    """LEGACY — nécessite /shared. Utiliser compute_local_vote_bc() à la place."""
    raise RuntimeError(
        "compute_local_vote() utilise /shared qui n'existe plus. "
        "Utiliser compute_local_vote_bc(weight_vectors, peer_id, round_num, bc)."
    )
 
 
def bft_consensus(round_num, timeout=60):
    """LEGACY — nécessite /shared. Utiliser bft_consensus_bc() à la place."""
    raise RuntimeError(
        "bft_consensus() utilise /shared qui n'existe plus. "
        "Utiliser bft_consensus_bc(round_num, bc)."
    )