const { ethers } = require("hardhat");
const categories = require("../config/categories.json");

async function main() {
  const contractAddress = process.env.CONTRACT_ADDRESS;
  if (!contractAddress || !ethers.isAddress(contractAddress)) {
    throw new Error("CONTRACT_ADDRESS must contain the deployed TrustNews address");
  }

  const [signer] = await ethers.getSigners();
  if (!signer) {
    throw new Error("DEPLOYER_PRIVATE_KEY is required for the selected network");
  }
  const trustNews = await ethers.getContractAt("TrustNews", contractAddress, signer);
  const owner = await trustNews.owner();
  if (owner.toLowerCase() !== signer.address.toLowerCase()) {
    throw new Error(`Signer ${signer.address} is not contract owner ${owner}`);
  }

  for (const category of categories) {
    const current = await trustNews.categories(category.id);
    if (!current) {
      const tx = await trustNews.addCategory(category.id, category.name);
      await tx.wait();
      console.log(`[categories] created id=${category.id} name=${category.name}`);
      continue;
    }
    if (current !== category.name) {
      throw new Error(`Category ${category.id} mismatch: chain=${current} config=${category.name}`);
    }
    console.log(`[categories] unchanged id=${category.id} name=${category.name}`);
  }

  console.log(`[categories] initialized=${categories.length} contract=${contractAddress}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
