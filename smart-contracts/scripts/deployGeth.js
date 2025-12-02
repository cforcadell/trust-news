const { ethers } = require("hardhat");

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("👤 Cuenta deployer:", deployer.address);

  // -------------------------------
  // Desplegar contrato TrustNews
  // -------------------------------
  const TrustNews = await ethers.getContractFactory("TrustNews");
  console.log("GetContractFactory.");

  const trustNews = await TrustNews.deploy({
    gasLimit: 25_000_000,    // suficiente para redes privadas
    gasPrice: 1_000_000_000  // 1 Gwei
  });
  
  console.log("Deploy Sent:");
  await trustNews.waitForDeployment(); // esperar a que se mine
  console.log("✅ Deploy Mined");

  const address = await trustNews.getAddress();
  console.log("✅ Contrato desplegado en:", address);

  // -------------------------------
  // Registrar categorías
  // -------------------------------
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

  for (const cat of categories) {
    try {
      const tx = await trustNews.addCategory(cat.id, cat.name, {
        gasLimit: 5_000_000,
        gasPrice: 1_000_000_000
      });
      // Esperar a que se mine la transacción
      if (tx.wait) {
        await tx.wait();
      }
      console.log(`   ✅ Categoria [${cat.id}] ${cat.name} registrada`);
    } catch (error) {
      console.error(`   ❌ Error registrando categoría [${cat.id}] ${cat.name}:`, error.message);
    }
  }

  // -------------------------------
  // Mostrar resumen
  // -------------------------------
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
