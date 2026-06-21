# fl/blockchain_logger.py — Bridge Web3 vers Hardhat local
#
# MODIFICATION PRINCIPALE :
# Ajout de méthodes pour soumettre/lire gradients, votes et agrégations
# via le contrat FLGradientRegistry, en remplacement du dossier /shared.
#
# Sérialisation :
#   Gradients  : numpy float32 → .tobytes() → bytes Solidity
#   Votes      : dict Python  → json.dumps().encode("utf-8") → bytes Solidity
#   Agrégation : numpy float32 → .tobytes() → bytes Solidity
 
import json
import os
import numpy as np
from typing import Dict, List, Optional
from web3 import Web3
from web3.exceptions import ContractLogicError
from config import HARDHAT_RPC_URL, BC_CONFIG_FILE, CHAIN_ID
 
 
def _load_abi() -> dict:
    """Charge l'ABI du contrat depuis l'artefact Hardhat."""
    artifact_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "blockchain", "artifacts", "contracts",
        "FLGradientRegistry.sol", "FLGradientRegistry.json",
    )
    with open(artifact_path) as f:
        return json.load(f)["abi"]
 
 
def _load_contract_address() -> str:
    with open(BC_CONFIG_FILE) as f:
        return json.load(f)["contract_address"]
 
 
class BlockchainLogger:
    """
    Interface avec le smart contract FLGradientRegistry sur Hardhat local.
 
    Ce logger remplace TOUT le dossier /shared :
      • submit_gradient / get_gradient / is_gradient_ready
          → remplacent weights_peer{id}_r{round}.npy + .flag
      • submit_vote / get_vote / is_vote_ready
          → remplacent vote_peer{id}_r{round}.json
      • submit_aggregation / get_aggregation / is_aggregation_ready
          → remplacent aggregated_r{round}.npy
 
    Les méthodes d'audit (log_round, get_blacklist, …) viennent de l'ancien
    FLRegistry et sont conservées à l'identique.
    """
 
    def __init__(self, account_index: int = 0):
        self.w3 = Web3(Web3.HTTPProvider(HARDHAT_RPC_URL))
        if not self.w3.is_connected():
            raise ConnectionError(f"Impossible de joindre Hardhat sur {HARDHAT_RPC_URL}")
 
        self.account  = self.w3.eth.accounts[account_index]
        self.abi      = _load_abi()
        self.address  = _load_contract_address()
        self.contract = self.w3.eth.contract(
            address=self.w3.to_checksum_address(self.address),
            abi=self.abi,
        )
        print(f"[Blockchain] Connecté — contrat {self.address} — compte {self.account}")
 
    # =========================================================================
    # GRADIENTS  (remplacent les fichiers .npy + .flag dans /shared)
    # =========================================================================
 
    def submit_gradient(self, round_num: int, peer_id: int,
                        flat_weights: np.ndarray) -> str:
        """
        Publie les gradients aplatis d'un peer sur la blockchain.
 
        Remplace :
            np.save(weight_path(peer_id, round_num), flat)
            open(flag_path(peer_id, round_num), "w").close()
        """
        # float32 — ~7.5KB avec le modele reduit → ~2.5M gas → OK
        data = flat_weights.astype(np.float32).tobytes()
        tx = self.contract.functions.submitGradient(
            round_num, peer_id, data
        ).transact({"from": self.account, "gas": 12_000_000})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx)
        return receipt["transactionHash"].hex()

    def get_gradient(self, round_num: int, peer_id: int) -> np.ndarray:
        """
        Lit les gradients d'un peer depuis la blockchain.
 
        Remplace : np.load(weight_path(peer_id, round_num))
        """
        raw = self.contract.functions.getGradient(round_num, peer_id).call()
        return np.frombuffer(raw, dtype=np.float32).copy()
 
    def is_gradient_ready(self, round_num: int, peer_id: int) -> bool:
        """
        Vérifie si un peer a publié ses gradients.
 
        Remplace : os.path.exists(flag_path(peer_id, round_num))
        """
        return self.contract.functions.isGradientReady(round_num, peer_id).call()
 
    # =========================================================================
    # VOTES KRUM  (remplacent les fichiers vote_peer{id}_r{round}.json)
    # =========================================================================
 
    def submit_vote(
        self,
        round_num: int,
        peer_id: int,
        mask: Dict[int, bool],
        scores: Dict[int, float],
        local_blacklist: Optional[Dict[int, int]] = None,
    ) -> str:
        """
        Publie le vote Krum d'un peer sur la blockchain.
 
        Remplace :
            vote_path = os.path.join(SHARED_DIR, f"vote_peer{peer_id}_r{round_num}.json")
            with open(vote_path, "w") as f: json.dump(payload, f)
 
        Le payload est identique à l'ancien format JSON pour que defense.py
        reste compatible sans modification de la logique BFT.
        """
        payload = {
            "voter": peer_id,
            "round": round_num,
            "mask": {str(k): v for k, v in mask.items()},
            "scores": {str(k): round(v, 6) for k, v in scores.items()},
            "blacklisted_locally": {
                str(k): v
                for k, v in (local_blacklist or {}).items()
                if v > 0
            },
        }
        data = json.dumps(payload).encode("utf-8")
        tx = self.contract.functions.submitVote(
            round_num, peer_id, data
        ).transact({"from": self.account, "gas": 500_000})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx)
        return receipt["transactionHash"].hex()
 
    def get_vote(self, round_num: int, peer_id: int) -> Optional[dict]:
        """
        Lit le vote d'un peer depuis la blockchain.
 
        Remplace :
            with open(vote_peer{id}_r{round}.json) as f: json.load(f)
        """
        try:
            raw = self.contract.functions.getVote(round_num, peer_id).call()
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None
 
    def is_vote_ready(self, round_num: int, peer_id: int) -> bool:
        """
        Vérifie si un peer a publié son vote.
 
        Remplace : os.path.exists(vote_peer{id}_r{round}.json)
        """
        return self.contract.functions.isVoteReady(round_num, peer_id).call()
 
    # =========================================================================
    # AGRÉGATION  (remplace aggregated_r{round}.npy dans /shared)
    # =========================================================================
 
    def submit_aggregation(self, round_num: int,
                           flat_weights: np.ndarray) -> str:
        """
        Le leader publie le modèle agrégé sur la blockchain.
 
        Remplace :
            np.save(agg_path(round_num), aggregated)
        """
        data = flat_weights.astype(np.float32).tobytes()
        tx = self.contract.functions.submitAggregation(
            round_num, data
        ).transact({"from": self.account, "gas": 12_000_000})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx)
        return receipt["transactionHash"].hex()

    def get_aggregation(self, round_num: int) -> np.ndarray:
        """
        Lit le modèle agrégé depuis la blockchain.
 
        Remplace : np.load(agg_path(round_num))
        """
        raw = self.contract.functions.getAggregation(round_num).call()
        return np.frombuffer(raw, dtype=np.float32).copy()
 
    def is_aggregation_ready(self, round_num: int) -> bool:
        """
        Vérifie si l'agrégat est disponible.
 
        Remplace : os.path.exists(agg_path(round_num))
        """
        return self.contract.functions.isAggregationReady(round_num).call()
 
    # =========================================================================
    # AUDIT LOG  (inchangé par rapport à l'ancien FLRegistry)
    # =========================================================================
 
    def log_round(
        self,
        round_num: int,
        leader_id: int,
        accepted_mask: Dict[int, bool],
        krum_scores: Dict[int, float],
        consensus_reached: bool,
        accuracy: float,
        epsilon: float = 0.0,
    ) -> str:
        """
        Enregistre un round complet sur la blockchain.
        Retourne le hash de la transaction.
        """
        scores_int = [int(krum_scores.get(i, 0) * 1e6) for i in range(len(accepted_mask))]
        mask_list  = [accepted_mask.get(i, False) for i in range(len(accepted_mask))]
        epsilon_int = int(epsilon * 1e6)
 
        tx = self.contract.functions.logRound(
            round_num,
            leader_id,
            mask_list,
            scores_int,
            consensus_reached,
            int(accuracy * 1e6),
            epsilon_int,
        ).transact({"from": self.account, "gas": 500_000})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx)
        return receipt["transactionHash"].hex()
 
    # =========================================================================
    # BLACKLIST (inchangé)
    # =========================================================================
 
    def get_blacklist(self) -> List[int]:
        blacklisted = []
        for peer_id in range(20):
            try:
                if self.contract.functions.isBlacklisted(peer_id).call():
                    blacklisted.append(peer_id)
            except Exception:
                break
        return blacklisted
 
    def is_blacklisted(self, peer_id: int) -> bool:
        try:
            return self.contract.functions.isBlacklisted(peer_id).call()
        except Exception:
            return False
 
    def get_consecutive_rejections(self, peer_id: int) -> int:
        try:
            return self.contract.functions.getConsecutiveRejections(peer_id).call()
        except Exception:
            return 0
 
    def get_rounds_count(self) -> int:
        try:
            return self.contract.functions.getRoundsCount().call()
        except Exception:
            return 0
 
    def get_all_rounds(self) -> List[dict]:
        n = self.get_rounds_count()
        rounds = []
        for i in range(n):
            try:
                r = self.contract.functions.getRound(i).call()
                rounds.append({
                    "round_num"  : r[0],
                    "leader_id"  : r[1],
                    "consensus"  : r[2],
                    "accuracy"   : r[3] / 1e6,
                    "epsilon"    : r[4] / 1e6,
                    "timestamp"  : r[5],
                })
            except Exception:
                pass
        return rounds