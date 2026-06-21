const { ethers } = require("hardhat");
const fs   = require("fs");
const path = require("path");

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("Deployer :", deployer.address);

  const FL = await ethers.getContractFactory("FLGradientRegistry");
  const fl = await FL.deploy();
  await fl.waitForDeployment();                    // ← remplace fl.deployed()

  const address = await fl.getAddress();           // ← remplace fl.address
  console.log("FLGradientRegistry deployed at :", address);

  const configPath = path.join(__dirname, "..", "..", "blockchain_config.json");
  fs.writeFileSync(
    configPath,
    JSON.stringify({ contract_address: address }, null, 2)
  );
  console.log("blockchain_config.json mis a jour ->", configPath);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});