require("@nomicfoundation/hardhat-toolbox");

// Avec le modele reduit (41->32->16->1 = 1889 params = ~7.5KB),
// chaque submitGradient() utilise ~2.5M gas.
// Le blockGasLimit par defaut de Hardhat (16.7M) est donc suffisant.
// On laisse tout en automatique — pas besoin de forcer les valeurs.

module.exports = {
  solidity: "0.8.20",
  networks: {
    localhost: {
      url:     "http://127.0.0.1:8545",
      chainId: 31337,
    },
  },
};