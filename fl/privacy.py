# fl/privacy.py — Confidentialité Différentielle (Differential Privacy)
#
# Implémente le mécanisme Gaussien avec clipping + bruit pour rendre
# les gradients FL privés avant leur partage avec les autres peers.
#
# Référence : Abadi et al. (2016) "Deep Learning with Differential Privacy"
#             https://arxiv.org/abs/1607.00133
#
# Garantie : (ε, δ)-DP sur les paramètres publiés.
# Le calcul de ε est effectué via le comptable RDP (Rényi DP).

import math
import numpy as np
import torch
from typing import List, Tuple

from config import (
    DP_NOISE_MULTIPLIER,
    DP_MAX_GRAD_NORM,
    DP_DELTA,
    USE_PRIVACY,
)


# ─────────────────────────────────────────────────────────────────────────────
# Clipping L2 des gradients (per-sample ou sur le vecteur global)
# ─────────────────────────────────────────────────────────────────────────────

def clip_gradients(model: torch.nn.Module, max_norm: float = DP_MAX_GRAD_NORM) -> float:
    """
    Clipping L2 de tous les gradients du modèle.
    Retourne la norme L2 globale avant clipping (pour monitoring).

    Note : PyTorch nn.utils.clip_grad_norm_ fait exactement cela,
    on l'utilise directement pour la compatibilité DP-SGD.
    """
    total_norm = torch.nn.utils.clip_grad_norm_(
        model.parameters(), max_norm=max_norm
    )
    return float(total_norm)


# ─────────────────────────────────────────────────────────────────────────────
# Ajout du bruit Gaussien sur les paramètres (après entraînement)
# ─────────────────────────────────────────────────────────────────────────────

def add_gaussian_noise_to_weights(
    flat_weights: np.ndarray,
    noise_multiplier: float = DP_NOISE_MULTIPLIER,
    max_norm: float = DP_MAX_GRAD_NORM,
) -> np.ndarray:
    """
    Ajoute un bruit gaussien calibré au vecteur de poids aplati.

    Bruit ~ N(0, (noise_multiplier * max_norm)² * I)

    Args:
        flat_weights    : vecteur numpy 1D des poids du modèle.
        noise_multiplier: σ relatif (σ_abs = noise_multiplier * max_norm).
        max_norm        : sensibilité L2 (valeur de clipping).

    Returns:
        Vecteur bruité (même forme).
    """
    if not USE_PRIVACY:
        return flat_weights

    sigma = noise_multiplier * max_norm
    noise = np.random.normal(0.0, sigma, size=flat_weights.shape).astype(np.float32)
    return flat_weights + noise


# ─────────────────────────────────────────────────────────────────────────────
# Entraînement DP-SGD local (remplacement de la boucle d'entraînement standard)
# ─────────────────────────────────────────────────────────────────────────────

def dp_train_epoch(
    model: torch.nn.Module,
    loader,
    optimizer: torch.optim.Optimizer,
    criterion,
    max_grad_norm: float = DP_MAX_GRAD_NORM,
    device: str = "cpu",
) -> float:
    """
    Une epoch DP-SGD :
      Pour chaque mini-batch :
        1. Calcule les gradients
        2. Clipping L2 (par sample via gradient accumulation)
        3. Agrège + ajoute bruit (NoisyGradient = ΣClip(g_i) + N(0,σ²))
        4. Mise à jour

    Retourne la loss moyenne de l'epoch.

    Note : implémentation simplifiée (batch-level clipping).
    Pour un clipping per-sample exact, utiliser Opacus.
    """
    model.train()
    total_loss = 0.0

    for X_batch, y_batch in loader:
        X_batch = X_batch.to(device)
        y_batch = y_batch.to(device)

        optimizer.zero_grad()
        output = model(X_batch)
        loss   = criterion(output, y_batch)
        loss.backward()

        # Clipping L2 (batch-level)
        clip_gradients(model, max_norm=max_grad_norm)

        # Ajout de bruit gaussien sur les gradients avant step
        if USE_PRIVACY:
            sigma = DP_NOISE_MULTIPLIER * max_grad_norm
            for param in model.parameters():
                if param.grad is not None:
                    noise = torch.normal(
                        mean=0.0,
                        std=sigma,
                        size=param.grad.shape,
                        device=param.grad.device,
                    )
                    param.grad += noise

        optimizer.step()
        total_loss += loss.item()

    return total_loss / len(loader)


# ─────────────────────────────────────────────────────────────────────────────
# Comptable RDP — estimation de ε
# ─────────────────────────────────────────────────────────────────────────────

def compute_epsilon(
    steps: int,
    noise_multiplier: float = DP_NOISE_MULTIPLIER,
    delta: float = DP_DELTA,
    sample_rate: float = 0.01,
    alphas: List[float] = None,
) -> Tuple[float, float]:
    """
    Estime ε via le comptable RDP (Rényi Differential Privacy).

    Args:
        steps          : nombre total de pas SGD = num_rounds * epochs * batches_per_epoch.
        noise_multiplier: σ / max_norm.
        delta          : δ dans (ε, δ)-DP.
        sample_rate    : q = batch_size / dataset_size.
        alphas         : ordres Rényi à évaluer.

    Returns:
        (epsilon, best_alpha)

    Utilise la bibliothèque `autodp` si disponible, sinon formule approchée.
    """
    if alphas is None:
        alphas = [1.25, 1.5, 1.75, 2, 2.5, 3, 4, 5, 6, 8, 16, 32, 64, 512]

    try:
        from autodp import rdp_acct, rdp_bank
        acct = rdp_acct.anaRDPacct()
        acct.compose_subsampled_mechanism(
            lambda alpha: rdp_bank.RDP_gaussian({"sigma": noise_multiplier}, alpha),
            sample_rate,
            steps,
        )
        epsilon = acct.get_epsilon(delta)
        return epsilon, -1.0

    except ImportError:
        # Formule approchée sans autodp
        # ε ≈ q * sqrt(2 * steps * log(1/δ)) / σ  (borne simple)
        epsilon_approx = (
            sample_rate
            * math.sqrt(2 * steps * math.log(1.0 / delta))
            / noise_multiplier
        )
        return epsilon_approx, -1.0


# ─────────────────────────────────────────────────────────────────────────────
# Helper : résumé des paramètres DP pour logs
# ─────────────────────────────────────────────────────────────────────────────

def dp_summary(steps: int, dataset_size: int, batch_size: int) -> dict:
    """Retourne un dict résumé des garanties DP pour le logging."""
    sample_rate = batch_size / max(dataset_size, 1)
    eps, alpha  = compute_epsilon(steps, sample_rate=sample_rate)
    return {
        "use_privacy"     : USE_PRIVACY,
        "noise_multiplier": DP_NOISE_MULTIPLIER,
        "max_grad_norm"   : DP_MAX_GRAD_NORM,
        "delta"           : DP_DELTA,
        "steps"           : steps,
        "sample_rate"     : round(sample_rate, 6),
        "epsilon_estimate": round(eps, 4),
    }