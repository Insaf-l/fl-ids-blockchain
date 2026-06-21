# fl/model.py — Modele IDS reduit pour compatibilite blockchain
#
# Architecture : 41 -> 32 -> 16 -> 1
# Parametres   : 1 889  (contre 15 745 avant)
# Taille       : ~7.5 KB en float32  → ~2.5M gas → OK dans 16M gas cap Hardhat
#
# La reduction de taille est necessaire pour que submitGradient() et
# submitAggregation() passent dans la limite de gas du noeud Hardhat local
# (16 777 216 par defaut, non modifiable dans certaines versions).
# L'accuracy sur NSL-KDD reste bonne (dataset relativement simple).

import torch
import torch.nn as nn


class IDSModel(nn.Module):
    """
    Reseau fully-connected pour classification binaire sur NSL-KDD.
    Input(41) -> 32 -> 16 -> 1 (Sigmoid)
    """

    def __init__(self, input_dim: int = 41):
        super(IDSModel, self).__init__()
        self.network = nn.Sequential(
            nn.Linear(input_dim, 32),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.network(x)

    def get_flat_params(self) -> torch.Tensor:
        """Retourne tous les parametres concatenes en 1D (pour Krum)."""
        return torch.cat([p.data.view(-1) for p in self.parameters()])

    def set_flat_params(self, flat: torch.Tensor) -> None:
        """Charge des parametres 1D aplatis dans le modele."""
        offset = 0
        for p in self.parameters():
            numel = p.numel()
            p.data.copy_(flat[offset: offset + numel].view(p.shape))
            offset += numel

    def count_params(self) -> int:
        n = sum(p.numel() for p in self.parameters())
        print(f"[IDSModel] Parametres : {n} ({n*4/1024:.1f} KB float32)")
        return n