# fl/peer.py — Noeud FL décentralisé (1 processus = 1 peer)
#
# REFACTORING COMPLET — SUPPRESSION DE /shared
# ─────────────────────────────────────────────
# Toutes les opérations sur le dossier /shared ont été remplacées
# par des appels à la blockchain (Hardhat local via Web3).
#
# Ce qui a changé         Avant (/shared)          Après (blockchain)
# ──────────────────────  ───────────────────────  ──────────────────────────
# Publier gradients       np.save(weight_path)     bc.submit_gradient()
# Sentinelle              open(flag_path, "w")     [inclus dans submit_gradient]
# Attendre les peers      os.path.exists(flag)     bc.is_gradient_ready()
# Lire les gradients      np.load(weight_path)     bc.get_gradient()
# Publier vote Krum       json.dump(vote_path)     bc.submit_vote() [via defense]
# Lire votes BFT          json.load(vote_path)     bc.get_vote()   [via defense]
# Publier agrégat         np.save(agg_path)        bc.submit_aggregation()
# Lire agrégat            np.load(agg_path)        bc.get_aggregation()
#
# Lancement : python peer.py <peer_id>
 
import argparse
import json
import os
import sys
import time
import logging
import numpy as np
import torch
import torch.nn as nn
 
from config import (
    NUM_PEERS, NUM_ROUNDS, EPOCHS_PER_ROUND, BATCH_SIZE, LEARNING_RATE,
    USE_DEFENSE, USE_PRIVACY, DP_NOISE_MULTIPLIER, DP_MAX_GRAD_NORM,
    LOGS_DIR, RESULTS_FILE, ATTACK_WINDOW,
    GRADIENT_WAIT_TIMEOUT, BFT_QUORUM, BLACKLIST_THRESHOLD,
)
from model import IDSModel
from data_loader import load_and_partition, load_test_set
from defense import (
    compute_local_vote_bc, bft_consensus_bc, fedavg, multi_krum,
    load_local_blacklist, update_blacklist_state,
)
from privacy import dp_train_epoch, add_gaussian_noise_to_weights, dp_summary
from blockchain_logger import BlockchainLogger
 
 
# ─── Setup logging ─────────────────────────────────────────────────────────────
 
def setup_logger(peer_id: int) -> logging.Logger:
    os.makedirs(LOGS_DIR, exist_ok=True)
    logger = logging.getLogger(f"Peer{peer_id}")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [Peer%(name)s] %(levelname)s --- %(message)s")
    ch  = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    fh = logging.FileHandler(os.path.join(LOGS_DIR, f"peer{peer_id}.log"))
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger
 
 
# ─── Utilitaires blockchain (remplacent les utilitaires /shared) ───────────────
 
def wait_for_gradients_bc(
    round_num: int,
    expected_peers: list,
    bc: BlockchainLogger,
    logger,
    timeout: int = GRADIENT_WAIT_TIMEOUT,
) -> bool:
    """
    Attend que tous les peers attendus aient publié leurs gradients
    sur la blockchain.
 
    Remplace wait_for_flags() qui attendait les fichiers .flag dans /shared.
    """
    waited   = 0
    interval = 2.0   # 2s entre chaque interrogation RPC (limiter les appels)
    while waited < timeout:
        ready = [p for p in expected_peers if bc.is_gradient_ready(round_num, p)]
        if len(ready) == len(expected_peers):
            return True
        logger.info(
            f"  Attente gradients blockchain : "
            f"{len(ready)}/{len(expected_peers)} prets ({waited:.0f}s)"
        )
        time.sleep(interval)
        waited += interval
    logger.warning("Timeout attente gradients blockchain !")
    return False
 
 
def load_peer_weights_bc(
    peer_ids: list,
    round_num: int,
    bc: BlockchainLogger,
    logger,
) -> dict:
    """
    Charge les vecteurs de gradients de tous les peers depuis la blockchain.
 
    Remplace load_peer_weights() qui lisait les fichiers .npy dans /shared.
    """
    weights = {}
    for pid in peer_ids:
        try:
            if bc.is_gradient_ready(round_num, pid):
                weights[pid] = bc.get_gradient(round_num, pid)
                logger.debug(f"    Gradients peer {pid} charges depuis blockchain")
        except Exception as e:
            logger.warning(f"  Impossible de charger gradients peer {pid}: {e}")
    return weights
 
 
def wait_for_aggregation_bc(
    round_num: int,
    bc: BlockchainLogger,
    logger,
    timeout: int = 90,
) -> bool:
    """
    Attend que le leader publie l'agrégat sur la blockchain.
 
    Remplace la boucle while + os.path.exists(agg_path(round_num)).
    """
    waited   = 0
    interval = 1.0
    while waited < timeout:
        if bc.is_aggregation_ready(round_num):
            return True
        time.sleep(interval)
        waited += interval
    logger.warning(f"  Timeout attente agregation round {round_num} !")
    return False
 
 
# ─── Entraînement local ────────────────────────────────────────────────────────
 
def local_train(model, loader, epochs: int, logger, peer_id: int) -> float:
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    criterion = nn.BCELoss()
    total_loss = 0.0
    for ep in range(epochs):
        if USE_PRIVACY:
            loss = dp_train_epoch(
                model, loader, optimizer, criterion,
                max_grad_norm=DP_MAX_GRAD_NORM,
            )
            logger.info(f"  Epoch {ep+1}/{epochs} [DP-SGD] loss={loss:.4f}")
        else:
            model.train()
            ep_loss = 0.0
            for X_b, y_b in loader:
                optimizer.zero_grad()
                out    = model(X_b)
                loss_b = criterion(out, y_b)
                loss_b.backward()
                optimizer.step()
                ep_loss += loss_b.item()
            loss = ep_loss / len(loader)
            logger.info(f"  Epoch {ep+1}/{epochs} loss={loss:.4f}")
        total_loss = loss
    return total_loss
 
 
# ─── Évaluation ────────────────────────────────────────────────────────────────
 
def evaluate(model, loader) -> float:
    model.eval()
    correct = total = 0
    with torch.no_grad():
        for X_b, y_b in loader:
            preds    = (model(X_b) >= 0.5).float()
            correct += (preds == y_b).sum().item()
            total   += len(y_b)
    return correct / total if total > 0 else 0.0
 
 
# ─── Main Peer ─────────────────────────────────────────────────────────────────
 
def run_peer(peer_id: int):
    logger = setup_logger(peer_id)
    logger.info(
        f"=== Peer {peer_id} demarre - "
        f"USE_PRIVACY={USE_PRIVACY} USE_DEFENSE={USE_DEFENSE} ==="
    )
 
    # Initialisation de la blacklist locale persistante
    local_blacklist = load_local_blacklist()
    logger.info(f"Blacklist locale chargee : { {k:v for k,v in local_blacklist.items() if v>0} }")
 
    # Chargement données
    train_loader = load_and_partition(peer_id, batch_size=BATCH_SIZE)
    test_loader  = load_test_set(batch_size=256)
    dataset_size = len(train_loader.dataset)

    # Modèle
    model = IDSModel(input_dim=41)
 
    # Connexion à la blockchain (OBLIGATOIRE — remplace /shared)
    try:
        bc = BlockchainLogger(account_index=peer_id)
    except Exception as e:
        logger.error(f"Blockchain indisponible : {e}")
        logger.error("Arret - la blockchain est necessaire pour le partage de gradients.")
        sys.exit(1)
 
    results     = []
    total_steps = 0
 
    for round_num in range(NUM_ROUNDS):
        logger.info(f"\n{'='*50}")
        logger.info(f"ROUND {round_num} — Peer {peer_id}")
 
        # ── 1. Vérifier blacklist sur la blockchain ───────────────────────────
        blacklisted = []
        try:
            blacklisted = bc.get_blacklist()
            if peer_id in blacklisted:
                logger.warning(f"Peer {peer_id} est BLACKLISTÉ. Skip round.")
                continue
        except Exception as e:
            logger.warning(f"Erreur lecture blacklist : {e}")
 
        active_peers = [p for p in range(NUM_PEERS) if p not in blacklisted]
        leader_id    = round_num % NUM_PEERS
 
        # ── 2. Entraînement local ─────────────────────────────────────────────
        loss          = local_train(model, train_loader, EPOCHS_PER_ROUND, logger, peer_id)
        steps_round   = EPOCHS_PER_ROUND * len(train_loader)
        total_steps  += steps_round
 
        # ── 3. Préparation des gradients ──────────────────────────────────────
        flat = model.get_flat_params().numpy().copy()
        if USE_PRIVACY:
            flat = add_gaussian_noise_to_weights(flat)
            logger.info(
                f"  [DP] Bruit sigma={DP_NOISE_MULTIPLIER*DP_MAX_GRAD_NORM:.4f} "
                f"ajoute aux gradients publies"
            )
 
        # ── 4. Publication des gradients sur la blockchain ────────────────────
        #    Remplace :
        #      np.save(weight_path(peer_id, round_num), flat)
        #      open(flag_path(peer_id, round_num), "w").close()
        try:
            tx = bc.submit_gradient(round_num, peer_id, flat)
            logger.info(f"  Gradients publies sur blockchain - tx : {tx[:16]}...")
        except Exception as e:
            logger.error(f"  ERREUR publication gradients : {e}")
            continue
 
        # ── 5. Fenêtre d'attaque (inchangée) ─────────────────────────────────
        time.sleep(ATTACK_WINDOW)
 
        # ── 6. Attendre que tous les peers actifs publient leurs gradients ─────
        #    Remplace wait_for_flags() qui attendait les fichiers .flag
        wait_for_gradients_bc(round_num, active_peers, bc, logger)
 
        # ── 7. Charger les gradients de tous les peers depuis la blockchain ────
        #    Remplace load_peer_weights() qui lisait les fichiers .npy
        weight_vectors = load_peer_weights_bc(active_peers, round_num, bc, logger)
        logger.info(f"  {len(weight_vectors)}/{len(active_peers)} gradients chargés")
 
        # ── 8. Vote Krum local + publication sur blockchain ───────────────────
        #    Remplace compute_local_vote() qui écrivait vote_peer{id}_r{round}.json
        krum_scores  = {}
        accepted_mask = {}
        if USE_DEFENSE and len(weight_vectors) > 1:
            accepted_mask = compute_local_vote_bc(
                weight_vectors, peer_id, round_num, bc, local_blacklist
            )
            _, krum_scores = multi_krum(weight_vectors)
            logger.info(f"  Krum scores : {krum_scores}")
            logger.info(f"  Masque local publie sur blockchain : {accepted_mask}")
        else:
            accepted_mask = {pid: True for pid in weight_vectors}
 
        # ── 9. Consensus BFT via blockchain ───────────────────────────────────
        #    Remplace bft_consensus() qui lisait les vote_peer*.json depuis /shared
        final_mask        = accepted_mask
        consensus_reached = True
        if USE_DEFENSE:
            final_mask, consensus_reached = bft_consensus_bc(round_num, bc, timeout=90)
            logger.info(
                f"  BFT consensus : {consensus_reached} - masque final : {final_mask}"
            )
 
        # Mise à jour de la blacklist locale persistante
        local_blacklist = update_blacklist_state(final_mask, local_blacklist)
        logger.info(
            f"  Blacklist locale mise a jour : "
            f"{ {k:v for k,v in local_blacklist.items() if v>=BLACKLIST_THRESHOLD} }"
        )
 
        accepted_ids = [pid for pid, ok in final_mask.items() if ok]
 
        # ── 10. Agrégation (leader uniquement) ───────────────────────────────
        #    Remplace np.save(agg_path(round_num), aggregated)
        if peer_id == leader_id:
            aggregated = fedavg(weight_vectors, accepted_ids)
            if aggregated is None:
                logger.warning("  Agrégation impossible (aucun peer accepté).")
            else:
                try:
                    tx_agg = bc.submit_aggregation(round_num, aggregated)
                    logger.info(
                        f"  Agregat publie sur blockchain - tx : {tx_agg[:16]}..."
                    )
                except Exception as e:
                    logger.error(f"  ERREUR publication agregat : {e}")
 
        # ── 11. Attendre le modèle agrégé depuis la blockchain ────────────────
        #    Remplace la boucle while + os.path.exists(agg_path(round_num))
        if wait_for_aggregation_bc(round_num, bc, logger):
            try:
                agg_weights = bc.get_aggregation(round_num)
                model.set_flat_params(torch.tensor(agg_weights))
                logger.info(f"  Modele mis a jour depuis l'agregat blockchain")
            except Exception as e:
                logger.warning(f"  Impossible de charger l'agrégat : {e}")
 
        # ── 12. Évaluation ────────────────────────────────────────────────────
        train_acc = evaluate(model, train_loader)
        test_acc  = evaluate(model, test_loader)
        logger.info(f"  Train acc: {train_acc:.4f} | Test acc: {test_acc:.4f}")
 
        # ── 13. DP Summary ────────────────────────────────────────────────────
        dp_info = {}
        if USE_PRIVACY:
            dp_info = dp_summary(total_steps, dataset_size, BATCH_SIZE)
            logger.info(
                f"  [DP] epsilon estime = {dp_info['epsilon_estimate']:.4f} "
                f"(delta={dp_info['delta']})"
            )
 
        # ── 14. Enregistrement du round sur la blockchain (leader) ────────────
        if peer_id == leader_id:
            try:
                tx = bc.log_round(
                    round_num, leader_id, final_mask, krum_scores,
                    consensus_reached, test_acc,
                    epsilon=dp_info.get("epsilon_estimate", 0.0),
                )
                logger.info(f"  Round logge blockchain - tx : {tx[:16]}...")
            except Exception as e:
                logger.warning(f"  Erreur log_round blockchain : {e}")
 
        # ── 15. Sauvegarde locale ─────────────────────────────────────────────
        results.append({
            "round"          : round_num,
            "peer_id"        : peer_id,
            "accuracy"       : round(test_acc, 4),
            "train_accuracy" : round(train_acc, 4),
            "loss"           : round(loss, 4),
            "accepted_peers" : accepted_ids,
            "consensus"      : consensus_reached,
            "blacklisted"    : blacklisted,
            "dp"             : dp_info,
        })
 
    # ── Sauvegarde finale ──────────────────────────────────────────────────────
    out_path = RESULTS_FILE.replace(".json", f"_peer{peer_id}.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    logger.info(f"\nResultats sauvegardes -> {out_path}")
 
 
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Peer FL Décentralisé (blockchain)")
    parser.add_argument("peer_id", type=int, help="ID du peer (0 à NUM_PEERS-1)")
    args = parser.parse_args()
    run_peer(args.peer_id)