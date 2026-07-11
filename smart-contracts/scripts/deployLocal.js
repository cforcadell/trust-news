const { ethers } = require("hardhat");

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("👤 Cuenta deployer:", deployer.address);

  // Desplegar contrato
  const TrustNews = await ethers.getContractFactory("TrustNews");

  const trustNews = await TrustNews.deploy();
  await trustNews.waitForDeployment();

  const address = await trustNews.getAddress();
  console.log("✅ Contrato desplegado en:", address);

  // --------------------------------------------------
  // Registrar categorías de noticias
  // --------------------------------------------------
  const categories = require("../config/categories.json");

  for (const cat of categories) {
    await (await trustNews.addCategory(cat.id, cat.name)).wait();
    console.log(`📚 Categoría añadida: [${cat.id}] ${cat.name}`);
  }

  console.log("✅ Todas las categorías registradas correctamente.");
  
  console.log("\n📌 Categorías registradas:");
  for (let i = 1; i <= 10; i++) {
    try {
      const name = await trustNews.categories(i);
      console.log(`   [${i}] ${name}`);
    } catch {
      console.log(`   [${i}] (no registrada)`);
    }
  }



}

main().catch((error) => {
  console.error("❌ Error al desplegar:", error);
  process.exitCode = 1;
});
