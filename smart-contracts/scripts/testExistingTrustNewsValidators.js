const { ethers } = require("hardhat");

async function main() {
  const [deployer, validator2, validator3] = await ethers.getSigners();
  console.log("👤 Cuenta deployer:", deployer.address);

  // --------------------------------------------------
  // 1️⃣ Desplegar contrato
  // --------------------------------------------------
  const TrustNews = await ethers.getContractFactory("TrustNews");

  const contractAddress = "0x5FbDB2315678afecb367f032d93F642f64180aa3";
  const trustNews = await TrustNews.attach(contractAddress);
  console.log("✅ Contrato :", contractAddress);


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

  console.log("\n📌 Categorías registradas:");
  for (let i = 1; i <= 10; i++) {
    try {
      const name = await trustNews.categories(i);
      console.log(`   [${i}] ${name}`);
    } catch {
      console.log(`   [${i}] (no registrada)`);
    }
  }
  // --------------------------------------------------
  // 3️⃣ Registrar validadores de prueba
  // --------------------------------------------------
  // Validador 1: deployer en categorías 1-5
  await (await trustNews.registerValidator("Validador1", [1,2,3,4,5])).wait();
  console.log("✅ Validador1 registrado en categorías 1-5");

  // Validador 2: validator2 en categorías 6-10
  await (await trustNews.connect(validator2).registerValidator("Validador2", [6,7,8,9,10])).wait();
  console.log("✅ Validador2 registrado en categorías 6-10");

  // Validador 3: validator3 en todas las categorías
  await (await trustNews.connect(validator3).registerValidator("Validador3", [1,2,3,4,5,6,7,8,9,10])).wait();
  console.log("✅ Validador3 registrado en todas las categorías");

  // --------------------------------------------------
  // 4️⃣ Listar todos los validadores por categoría
  // --------------------------------------------------
  console.log("\n📌 Listado de validadores por categoría:");

for (const cat of categories) {
  let validatorAddresses = [];
  try {
    validatorAddresses = await trustNews.getValidatorsByCategory(cat.id);
  } catch (err) {
    console.error(`Error en categoría ${cat.id}:`, err.message || err);
  }

  console.log(`\n🗂 Categoría [${cat.id}] ${cat.name}:`);
  if (validatorAddresses.length === 0) {
    console.log("   Ningún validador registrado o error en la llamada.");
  } else {
    validatorAddresses.forEach((addr, index) => {
      console.log(`   ${index + 1}. Dirección: ${addr}`);
    });
  }
}
  console.log("\n✅ Listado completo finalizado.");
}

main().catch((error) => {
  console.error("❌ Error al ejecutar script:", error);
  process.exitCode = 1;
});
