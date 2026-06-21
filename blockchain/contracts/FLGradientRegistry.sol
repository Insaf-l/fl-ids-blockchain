// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/**
 * FLGradientRegistry.sol
 *
 * Contrat unifié qui remplace COMPLÈTEMENT le dossier /shared.
 * Il joue le rôle de mémoire partagée décentralisée entre les peers FL.
 *
 * Ce qui était dans /shared         →  Ce qui est maintenant dans ce contrat
 * ─────────────────────────────────────────────────────────────────────────
 * weights_peer{id}_r{round}.npy    →  _gradients[round][peerId]  (bytes)
 * ready_peer{id}_r{round}.flag     →  _gradientReady[round][peerId] (bool)
 * vote_peer{id}_r{round}.json      →  _votes[round][peerId]  (bytes JSON)
 * aggregated_r{round}.npy          →  _aggregations[round]   (bytes)
 *
 * Les logs d'audit (logRound, blacklist) viennent de l'ancien FLRegistry.
 *
 * Déploiement : npx hardhat run scripts/deploy.js --network localhost
 */
contract FLGradientRegistry {

    // ─── Gradient storage ────────────────────────────────────────────────────
    // Gradients aplatis (float32 raw bytes) : round → peerId → bytes
    mapping(uint256 => mapping(uint256 => bytes)) private _gradients;
    mapping(uint256 => mapping(uint256 => bool))  private _gradientReady;

    // ─── Vote storage ─────────────────────────────────────────────────────────
    // Votes Krum sérialisés en JSON UTF-8 : round → peerId → bytes
    mapping(uint256 => mapping(uint256 => bytes)) private _votes;
    mapping(uint256 => mapping(uint256 => bool))  private _voteReady;

    // ─── Aggregation storage ──────────────────────────────────────────────────
    // Modèle agrégé (float32 raw bytes) : round → bytes
    mapping(uint256 => bytes) private _aggregations;
    mapping(uint256 => bool)  private _aggReady;

    // ─── Blacklist & rejections ───────────────────────────────────────────────
    mapping(uint256 => uint256) private _consecutiveRejections;
    mapping(uint256 => bool)    private _blacklisted;
    uint256 public constant BLACKLIST_THRESHOLD = 3;

    // ─── Round audit logs (compatibilité ancienne API) ────────────────────────
    struct RoundInfo {
        uint256 roundNum;
        uint256 leaderId;
        bool    consensus;
        uint256 accuracy;   // stocké * 1e6
        uint256 epsilon;    // stocké * 1e6
        uint256 timestamp;
    }
    RoundInfo[] public rounds;

    // ─── Events ───────────────────────────────────────────────────────────────
    event GradientSubmitted(uint256 indexed round, uint256 indexed peerId);
    event VoteSubmitted(uint256 indexed round, uint256 indexed peerId);
    event AggregationSubmitted(uint256 indexed round);
    event PeerBlacklisted(uint256 indexed peerId);
    event RoundLogged(uint256 indexed roundNum);

    // =========================================================================
    // GRADIENTS
    // =========================================================================

    /**
     * Publie les gradients d'un peer pour un round.
     * Remplace : np.save(weight_path(peer_id, round_num), flat)
     *          + open(flag_path(...), "w").close()
     */
    function submitGradient(
        uint256 round,
        uint256 peerId,
        bytes calldata data
    ) external {
        _gradients[round][peerId] = data;
        _gradientReady[round][peerId] = true;
        emit GradientSubmitted(round, peerId);
    }

    /**
     * Lit les gradients d'un peer.
     * Remplace : np.load(weight_path(peer_id, round_num))
     */
    function getGradient(uint256 round, uint256 peerId)
        external view returns (bytes memory)
    {
        require(_gradientReady[round][peerId], "Gradient pas encore publie");
        return _gradients[round][peerId];
    }

    /**
     * Vérifie si un peer a publié ses gradients (remplace le fichier .flag).
     * Remplace : os.path.exists(flag_path(peer_id, round_num))
     */
    function isGradientReady(uint256 round, uint256 peerId)
        external view returns (bool)
    {
        return _gradientReady[round][peerId];
    }

    // =========================================================================
    // VOTES KRUM
    // =========================================================================

    /**
     * Publie le vote Krum d'un peer (JSON encodé UTF-8).
     * Remplace : open(vote_path, "w"); json.dump(payload, f)
     */
    function submitVote(
        uint256 round,
        uint256 peerId,
        bytes calldata data
    ) external {
        _votes[round][peerId] = data;
        _voteReady[round][peerId] = true;
        emit VoteSubmitted(round, peerId);
    }

    /**
     * Lit le vote d'un peer.
     * Remplace : with open(vote_path) as f: json.load(f)
     */
    function getVote(uint256 round, uint256 peerId)
        external view returns (bytes memory)
    {
        return _votes[round][peerId];
    }

    /**
     * Vérifie si un peer a publié son vote.
     * Remplace : os.path.exists(vote_peer{id}_r{round}.json)
     */
    function isVoteReady(uint256 round, uint256 peerId)
        external view returns (bool)
    {
        return _voteReady[round][peerId];
    }

    // =========================================================================
    // MODÈLE AGRÉGÉ
    // =========================================================================

    /**
     * Le leader publie l'agrégat FedAvg.
     * Remplace : np.save(agg_path(round_num), aggregated)
     */
    function submitAggregation(
        uint256 round,
        bytes calldata data
    ) external {
        _aggregations[round] = data;
        _aggReady[round] = true;
        emit AggregationSubmitted(round);
    }

    /**
     * Lit l'agrégat du round.
     * Remplace : np.load(agg_path(round_num))
     */
    function getAggregation(uint256 round)
        external view returns (bytes memory)
    {
        require(_aggReady[round], "Agregation pas encore publiee");
        return _aggregations[round];
    }

    /**
     * Vérifie si l'agrégat est disponible.
     * Remplace : os.path.exists(agg_path(round_num))
     */
    function isAggregationReady(uint256 round)
        external view returns (bool)
    {
        return _aggReady[round];
    }

    // =========================================================================
    // BLACKLIST (repris de l'ancien FLRegistry)
    // =========================================================================

    function _updateBlacklist(uint256 peerId, bool accepted) internal {
        if (!accepted) {
            _consecutiveRejections[peerId] += 1;
            if (_consecutiveRejections[peerId] >= BLACKLIST_THRESHOLD) {
                _blacklisted[peerId] = true;
                emit PeerBlacklisted(peerId);
            }
        } else {
            _consecutiveRejections[peerId] = 0;
        }
    }

    function isBlacklisted(uint256 peerId) external view returns (bool) {
        return _blacklisted[peerId];
    }

    function getConsecutiveRejections(uint256 peerId) external view returns (uint256) {
        return _consecutiveRejections[peerId];
    }

    // Gardé pour compatibilité avec l'ancien code
    function getBlacklistCount() external pure returns (uint256) {
        return 0;
    }

    // =========================================================================
    // ROUND AUDIT LOG (repris de l'ancien FLRegistry)
    // =========================================================================

    /**
     * Enregistre un round complet sur la blockchain (appelé par le leader).
     * Met à jour la blacklist automatiquement selon les masques d'acceptation.
     */
    function logRound(
        uint256 roundNum,
        uint256 leaderId,
        bool[]     calldata acceptedMask,
        uint256[]  calldata /* krumScores — ignoré, trop volumineux pour Solidity */,
        bool    consensus,
        uint256 accuracy,   // * 1e6
        uint256 epsilon     // * 1e6
    ) external {
        for (uint256 i = 0; i < acceptedMask.length; i++) {
            _updateBlacklist(i, acceptedMask[i]);
        }

        rounds.push(RoundInfo({
            roundNum  : roundNum,
            leaderId  : leaderId,
            consensus : consensus,
            accuracy  : accuracy,
            epsilon   : epsilon,
            timestamp : block.timestamp
        }));

        emit RoundLogged(roundNum);
    }

    function getRound(uint256 idx) external view returns (
        uint256, uint256, bool, uint256, uint256, uint256
    ) {
        RoundInfo storage r = rounds[idx];
        return (r.roundNum, r.leaderId, r.consensus, r.accuracy, r.epsilon, r.timestamp);
    }

    function getRoundsCount() external view returns (uint256) {
        return rounds.length;
    }
}
