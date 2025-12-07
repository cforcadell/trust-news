const { ethers } = require("hardhat");

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("👤 Cuenta deployer:", deployer.address);

  const contractAddress = "0xcd01d6977F0d2B2aeF57F7c75924C9eC7eB60dFC";
  const TrustNews = await ethers.getContractFactory("TrustNews");
  const trustNews = await TrustNews.attach(contractAddress);

  // IDs de categorías que conocemos (debes definirlos tú)
  const categoryIds = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];

  for (const categoryId of categoryIds) {
    const validatorAddresses = await trustNews.getValidatorsByCategory(categoryId);
    console.log(`\n🗂 Categoría [${categoryId}]:`);
    if (validatorAddresses.length === 0) {
      console.log("   Ningún validador registrado.");
    } else {
      validatorAddresses.forEach((addr, index) => {
        console.log(`   ${index + 1}. Dirección: ${addr}`);
      });
    }
  }
}

main().catch((error) => {
  console.error("❌ Error al ejecutar script:", error);
  process.exitCode = 1;
});
