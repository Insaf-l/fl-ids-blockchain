# fl/malicious_peer.py — Peer FL interne qui devient adversarial après start_round
#
# REFACTORING COMPLET — SUPPRESSION DE /shared
# Même logique d'attaque qu'avant, mais tout le partage de gradients,
# votes et agrégations passe par la blockchain.
#
# Lancement :
#   python malicious_peer.py 3
#   python malicious_peer.py 3 --start-round 4 --strategy flip
#   python malicious_peer.py 3 --start-round 3 --strategy boost --boost-factor 8.0
 
import argparse
import json
import os
import sys
import time
import logging
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
 
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
 
# ─── Constantes d'attaque ──────────────────────────────────────────────────────
SCALE_FACTOR = -10.0
NOISE_SIGMA  = 50.0
 
 
# ─── Logging ───────────────────────────────────────────────────────────────────
 
def setup_logger(peer_id: int) -> logging.Logger:
    os.makedirs(LOGS_DIR, exist_ok=True)
    logger = logging.getLogger(f"MalPeer{peer_id}")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [MalPeer%(name)s] %(levelname)s --- %(message)s")
    ch  = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    fh = logging.FileHandler(os.path.join(LOGS_DIR, f"malicious_peer{peer_id}.log"))
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger
 
 
# ─── Utilitaires blockchain (identiques à peer.py) ─────────────────────────────
 
def wait_for_gradients_bc(round_num, expected_peers, bc, logger,
                           timeout=GRADIENT_WAIT_TIMEOUT):
    waited = 0
    interval = 2.0
    while waited < timeout:
        ready = [p for p in expected_peers if bc.is_gradient_ready(round_num, p)]
        if len(ready) == len(expected_peers):
            return True
        logger.info(f"  Attente gradients {len(ready)}/{len(expected_peers)} ({waited:.0f}s)")
        time.sleep(interval)
        waited += interval
    logger.warning("Timeout attente gradients !")
    return False
 
 
def load_peer_weights_bc(peer_ids, round_num, bc, logger):
    weights = {}
    for pid in peer_ids:
        try:
            if bc.is_gradient_ready(round_num, pid):
                weights[pid] = bc.get_gradient(round_num, pid)
        except Exception as e:
            logger.warning(f"  Impossible de charger gradients peer {pid}: {e}")
    return weights
 
 
def wait_for_aggregation_bc(round_num, bc, logger, timeout=90):
    waited = 0
    while waited < timeout:
        if bc.is_aggregation_ready(round_num):
            return True
        time.sleep(1.0)
        waited += 1.0
    logger.warning(f"  Timeout agrégation round {round_num} !")
    return False
 
 
# ─── Entraînement honnête ──────────────────────────────────────────────────────
 
def local_train(model, loader, epochs, logger):
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    criterion = nn.BCELoss()
    total_loss = 0.0
    for ep in range(epochs):
        if USE_PRIVACY:
            loss = dp_train_epoch(model, loader, optimizer, criterion,
                                  max_grad_norm=DP_MAX_GRAD_NORM)
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
 
 
def evaluate(model, loader):
    model.eval()
    correct = total = 0
    with torch.no_grad():
        for X_b, y_b in loader:
            preds    = (model(X_b) >= 0.5).float()
            correct += (preds == y_b).sum().item()
            total   += len(y_b)
    return correct / total if total > 0 else 0.0
 
 
# ─── Stratégies d'empoisonnement (inchangées) ──────────────────────────────────
 
def make_flipped_loader(honest_loader):
    all_X, all_y = [], []
    for X_b, y_b in honest_loader:
        all_X.append(X_b)
        all_y.append(1.0 - y_b)
    X_cat = torch.cat(all_X, dim=0)
    y_cat = torch.cat(all_y, dim=0)
    return DataLoader(TensorDataset(X_cat, y_cat), batch_size=BATCH_SIZE, shuffle=True)
 
 
def poison_scale(flat, scale=SCALE_FACTOR):
    return (flat * scale).astype(np.float32)
 
 
def poison_boost(flat_honest, prev_agg, boost_factor):
    delta = flat_honest - prev_agg
    return (prev_agg + boost_factor * delta).astype(np.float32)
 
 
def poison_noise(flat, sigma=NOISE_SIGMA):
    noise = np.random.normal(0.0, sigma, size=flat.shape).astype(np.float32)
    return flat + noise
 
 
# ─── Main ──────────────────────────────────────────────────────────────────────
 
def run_malicious_peer(peer_id: int, start_round: int, strategy: str,
                       boost_factor: float):
    logger = setup_logger(peer_id)
    logger.info("=" * 60)
    logger.info(f"PEER MALVEILLANT {peer_id} démarre")
    logger.info(f"  Phase honnete  : rounds 0 -> {start_round - 1}")
    logger.info(f"  Phase attaque  : rounds {start_round} -> {NUM_ROUNDS - 1}")
    logger.info(f"  Strategie      : {strategy}"
                + (f" (boost_factor={boost_factor})" if strategy == "boost" else ""))
    logger.info("=" * 60)
 
    local_blacklist = load_local_blacklist()
 
    honest_loader = load_and_partition(peer_id, batch_size=BATCH_SIZE)
    test_loader   = load_test_set(batch_size=256)
    dataset_size  = len(honest_loader.dataset)
 
    model = IDSModel(input_dim=41)
 
    # Connexion blockchain (OBLIGATOIRE)
    try:
        bc = BlockchainLogger(account_index=peer_id)
    except Exception as e:
        logger.error(f"Blockchain indisponible : {e}")
        sys.exit(1)
 
    results       = []
    total_steps   = 0
    prev_agg_flat = np.zeros_like(model.get_flat_params().numpy())
 
    for round_num in range(NUM_ROUNDS):
        logger.info(f"\n{'='*50}")
        is_malicious = (round_num >= start_round)
        phase_label  = "MALVEILLANT" if is_malicious else "honnête"
        logger.info(f"ROUND {round_num} — Peer {peer_id} [{phase_label}]")
 
        # ── 1. Blacklist ──────────────────────────────────────────────────────
        blacklisted = []
        try:
            blacklisted = bc.get_blacklist()
            if peer_id in blacklisted:
                logger.warning(f"Peer {peer_id} est BLACKLISTÉ. Skip round.")
                continue
        except Exception as e:
            logger.warning(f"Erreur blacklist : {e}")
 
        active_peers = [p for p in range(NUM_PEERS) if p not in blacklisted]
        leader_id    = round_num % NUM_PEERS
 
        # ── 2. Entraînement ───────────────────────────────────────────────────
        if is_malicious and strategy == "flip":
            flipped_loader = make_flipped_loader(honest_loader)
            loss = local_train(model, flipped_loader, EPOCHS_PER_ROUND, logger)
            logger.warning("  [ATTAQUE] Entraînement sur labels INVERSÉS")
        else:
            loss = local_train(model, honest_loader, EPOCHS_PER_ROUND, logger)
 
        total_steps += EPOCHS_PER_ROUND * len(honest_loader)
 
        # ── 3. Vecteur de gradients ───────────────────────────────────────────
        flat_honest = model.get_flat_params().numpy().copy()
        if USE_PRIVACY:
            flat_honest = add_gaussian_noise_to_weights(flat_honest)
 
        # ── 4. Empoisonnement (si phase malveillante) ─────────────────────────
        if is_malicious:
            if strategy == "scale":
                flat_published = poison_scale(flat_honest)
                logger.warning(
                    f"  [ATTAQUE scale] "
                    f"||avant||={np.linalg.norm(flat_honest):.2f} "
                    f"-> ||apres||={np.linalg.norm(flat_published):.2f}"
                )
            elif strategy == "flip":
                flat_published = flat_honest
                logger.warning(f"  [ATTAQUE flip] labels inverses, ||w||={np.linalg.norm(flat_published):.2f}")
            elif strategy == "boost":
                flat_published = poison_boost(flat_honest, prev_agg_flat, boost_factor)
                logger.warning(
                    f"  [ATTAQUE boost x{boost_factor}] "
                    f"||delta_amplified||={np.linalg.norm(flat_published - prev_agg_flat):.4f}"
                )
            elif strategy == "noise":
                flat_published = poison_noise(flat_honest)
                logger.warning(
                    f"  [ATTAQUE noise sigma={NOISE_SIGMA}] "
                    f"||après||={np.linalg.norm(flat_published):.2f}"
                )
            else:
                logger.error(f"Stratégie inconnue '{strategy}'. Publication honnête.")
                flat_published = flat_honest
        else:
            flat_published = flat_honest
 
        # ── 5. Publication des gradients sur la blockchain ────────────────────
        try:
            tx = bc.submit_gradient(round_num, peer_id, flat_published)
            logger.info(f"  Gradients publies blockchain - tx : {tx[:16]}...")
        except Exception as e:
            logger.error(f"  ERREUR publication gradients : {e}")
            continue
 
        # ── 6. Fenêtre de synchronisation ─────────────────────────────────────
        time.sleep(ATTACK_WINDOW)
 
        # ── 7. Attendre les gradients des autres peers ────────────────────────
        wait_for_gradients_bc(round_num, active_peers, bc, logger)
 
        # ── 8. Charger les gradients ──────────────────────────────────────────
        weight_vectors = load_peer_weights_bc(active_peers, round_num, bc, logger)
 
        # ── 9. Vote Krum + publication blockchain ─────────────────────────────
        krum_scores   = {}
        accepted_mask = {}
        if USE_DEFENSE and len(weight_vectors) > 1:
            accepted_mask = compute_local_vote_bc(
                weight_vectors, peer_id, round_num, bc, local_blacklist
            )
            _, krum_scores = multi_krum(weight_vectors)
            if is_malicious:
                my_score  = krum_scores.get(peer_id, 0)
                avg_score = np.mean(list(krum_scores.values()))
                logger.warning(
                    f"  [ATTAQUE] Mon score Krum : {my_score:.4f} "
                    f"(moyenne : {avg_score:.4f}) - "
                    f"{'DETECTE' if not accepted_mask.get(peer_id, True) else 'non detecte'}"
                )
        else:
            accepted_mask = {pid: True for pid in weight_vectors}
 
        # ── 10. Consensus BFT via blockchain ──────────────────────────────────
        final_mask        = accepted_mask
        consensus_reached = True
        if USE_DEFENSE:
            final_mask, consensus_reached = bft_consensus_bc(round_num, bc, timeout=90)
 
        local_blacklist = update_blacklist_state(final_mask, local_blacklist)
        accepted_ids    = [pid for pid, ok in final_mask.items() if ok]
        i_was_accepted  = final_mask.get(peer_id, True)
        if is_malicious:
            logger.warning(f"  [ATTAQUE] Inclus dans FedAvg : {i_was_accepted}")
 
        # ── 11. Agrégation (leader) ───────────────────────────────────────────
        if peer_id == leader_id:
            aggregated = fedavg(weight_vectors, accepted_ids)
            if aggregated is not None:
                try:
                    bc.submit_aggregation(round_num, aggregated)
                    logger.info("  Agrégat publié sur blockchain")
                except Exception as e:
                    logger.error(f"  ERREUR publication agrégat : {e}")
 
        # ── 12. Attendre l'agrégat ────────────────────────────────────────────
        if wait_for_aggregation_bc(round_num, bc, logger):
            try:
                agg_weights   = bc.get_aggregation(round_num)
                prev_agg_flat = agg_weights.copy()
                model.set_flat_params(torch.tensor(agg_weights))
            except Exception as e:
                logger.warning(f"  Impossible de charger l'agrégat : {e}")
 
        # ── 13. Évaluation ────────────────────────────────────────────────────
        train_acc = evaluate(model, honest_loader)
        test_acc  = evaluate(model, test_loader)
        logger.info(f"  Train acc: {train_acc:.4f} | Test acc: {test_acc:.4f}")
 
        # ── 14. DP Summary ────────────────────────────────────────────────────
        dp_info = {}
        if USE_PRIVACY:
            dp_info = dp_summary(total_steps, dataset_size, BATCH_SIZE)
 
        # ── 15. Blockchain log (leader) ───────────────────────────────────────
        if peer_id == leader_id:
            try:
                bc.log_round(
                    round_num, leader_id, final_mask, krum_scores,
                    consensus_reached, test_acc,
                    epsilon=dp_info.get("epsilon_estimate", 0.0),
                )
            except Exception as e:
                logger.warning(f"  Erreur log_round : {e}")
 
        # ── 16. Sauvegarde locale ─────────────────────────────────────────────
        results.append({
            "round"           : round_num,
            "peer_id"         : peer_id,
            "phase"           : "malicious" if is_malicious else "honest",
            "strategy"        : strategy if is_malicious else None,
            "accuracy"        : round(test_acc, 4),
            "train_accuracy"  : round(train_acc, 4),
            "loss"            : round(loss, 4),
            "accepted_peers"  : accepted_ids,
            "i_was_accepted"  : bool(i_was_accepted),
            "krum_score_self" : round(float(krum_scores.get(peer_id, 0)), 4),
            "consensus"       : consensus_reached,
            "blacklisted"     : blacklisted,
            "dp"              : dp_info,
        })
 
    # ── Sauvegarde finale ──────────────────────────────────────────────────────
    out_path = RESULTS_FILE.replace(".json", f"_peer{peer_id}_malicious.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    logger.info(f"\nResultats sauvegardes -> {out_path}")
 
    malicious_rounds = [r for r in results if r["phase"] == "malicious"]
    if malicious_rounds:
        detected = sum(1 for r in malicious_rounds if not r["i_was_accepted"])
        logger.info(
            f"\n[RESUME ATTAQUE] Detecte : "
            f"{detected}/{len(malicious_rounds)} rounds malveillants"
        )
 
 
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Peer FL malveillant (blockchain)")
    parser.add_argument("peer_id", type=int)
    parser.add_argument("--start-round",  type=int,   default=4)
    parser.add_argument("--strategy",     type=str,   default="flip",
                        choices=["scale", "flip", "boost", "noise"])
    parser.add_argument("--boost-factor", type=float, default=5.0)
    args = parser.parse_args()
    run_malicious_peer(args.peer_id, args.start_round, args.strategy, args.boost_factor)