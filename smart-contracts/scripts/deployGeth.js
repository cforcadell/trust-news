const { ethers } = require("hardhat");

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("👤 Cuenta deployer:", deployer.address);

  // Desplegar contrato
  const TrustNews = await ethers.getContractFactory("TrustNews");
  const trustNews = await TrustNews.deploy(); // dejar que Hardhat estime gas
  await trustNews.waitForDeployment();

  const address = await trustNews.getAddress();
  console.log("✅ Contrato desplegado en:", address);

  // --------------------------------------------------
  // Registrar categorías de noticias
  // --------------------------------------------------
  const categories = [
    { id: 1, name: "ECONOMÍA" },
    { id: 2, name: "DEPORTES" },
    { id: 3, name: "POLÍTICA" },
    { id: 4, name: "TECNOLOGÍA" },
    { id: 5, name: "SALUD" },
    { id: 6, name: "ENTRETENIMIENTO" },
    { id: 7, name: "CIENCIA" },
    { id: 8, name: "CULTURA" },
    { id: 9, name: "MEDIO AMBIENTE" },
    { id: 10, name: "SOCIAL" },
  ];

  console.log("\n⏳ Registrando categorías...");

  // Enviar todas las transacciones sin await
  const txs = categories.map(cat => trustNews.addCategory(cat.id, cat.name));

  // Esperar que todas las transacciones se minen
  await Promise.all(txs.map(tx => tx.wait()));

  console.log("✅ Todas las categorías registradas correctamente.");

  // Mostrar resumen
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
