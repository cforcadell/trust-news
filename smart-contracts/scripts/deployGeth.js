const { ethers } = require("hardhat");

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("👤 Cuenta deployer:", deployer.address);

  // -------------------------------
  // Preparar despliegue de contrato
  // -------------------------------
  const TrustNews = await ethers.getContractFactory("TrustNews");
  console.log("GetContractFactory listo.");

  // -------------------------------
  // Obtener límite de gas del bloque actual
  // -------------------------------
  const block = await ethers.provider.getBlock("latest");
  console.log("⛓️ Block Gas Limit actual:", block.gasLimit.toString());

  // -------------------------------
  // Crear transacción de deploy
  // -------------------------------
  const deployTx = TrustNews.getDeployTransaction({
    gasPrice: ethers.parseUnits("1", "gwei")
  });

  // -------------------------------
  // Estimar gas necesario para deploy
  // -------------------------------
  let gasEstimate = await ethers.provider.estimateGas(deployTx); // bigint
  console.log("⛽ Gas estimado para desplegar contrato:", gasEstimate.toString());

  // Añadir margen de seguridad (+20%)
  gasEstimate = BigInt(Math.floor(Number(gasEstimate) * 1.2));
  console.log("⚡ Gas con margen de seguridad (+20%):", gasEstimate.toString());

  if (gasEstimate > BigInt(block.gasLimit)) {
    console.error("❌ El contrato necesita más gas que el límite del bloque. Ajusta el contrato o la red.");
    process.exit(1);
  }

  // -------------------------------
  // Desplegar contrato
  // -------------------------------
  const trustNews = await TrustNews.deploy({
    gasLimit: 5_000_000,             // Holgado para redes privadas
    gasPrice: ethers.parseUnits("10", "gwei") // Suficiente para Geth
  });


  console.log("Deploy enviado, esperando confirmación...");
  await trustNews.waitForDeployment();
  console.log("✅ Contrato desplegado en:", await trustNews.getAddress());

  // -------------------------------
  // Registrar categorías
  // -------------------------------
  const categories = require("../config/categories.json");

  console.log("\n⏳ Registrando categorías...");
  for (const cat of categories) {
    const tx = await trustNews.addCategory(cat.id, cat.name, {
      gasLimit: 5_000_000,
      gasPrice: ethers.parseUnits("1", "gwei")
    });
    await tx.wait();
    console.log(`   ✅ Categoria [${cat.id}] ${cat.name} registrada`);
  }

  // -------------------------------
  // Mostrar resumen de categorías
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
  console.error("❌ Error en script:", error);
  process.exitCode = 1;
});
