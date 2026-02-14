const { ethers } = require("hardhat");

async function main() {
  const CONTRACT_ADDRESS = process.env.CONTRACT_ADDRESS;
  const VALIDATOR_PRIVATE_KEY = process.env.VALIDATOR_PK;

  if (!CONTRACT_ADDRESS || !VALIDATOR_PRIVATE_KEY) {
    throw new Error("Faltan CONTRACT_ADDRESS o VALIDATOR_PK en variables de entorno");
  }

  // ===============================
  // CREATE WALLET FROM PRIVATE KEY
  // ===============================
  const validator = new ethers.Wallet(
    VALIDATOR_PRIVATE_KEY,
    ethers.provider
  );

  console.log("🔗 Contract:", CONTRACT_ADDRESS);
  console.log("👤 Validator:", validator.address);

  // ===============================
  // ATTACH CONTRACT
  // ===============================
  const TrustNews = await ethers.getContractFactory("TrustNews");
  const trustNews = await TrustNews.attach(CONTRACT_ADDRESS);

  // ===============================
  // UNREGISTER
  // ===============================
  console.log("⏳ Desregistrando validador...");

  const tx = await trustNews
    .connect(validator)
    .unregisterValidator();

  const receipt = await tx.wait();

  console.log("✅ Validador desregistrado correctamente");
  console.log("🧾 Tx Hash:", receipt.hash);
}

main().catch((error) => {
  console.error("❌ Error:", error);
  process.exitCode = 1;
});
