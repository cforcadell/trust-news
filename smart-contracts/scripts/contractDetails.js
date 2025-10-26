const { ethers } = require("hardhat");

async function main() {
  // Dirección del contrato desplegado
  const contractAddress = "0x5FbDB2315678afecb367f032d93F642f64180aa3";

  // ABI: normalmente lo generas al compilar
  const TrustNews = await ethers.getContractFactory("TrustNews");
  const trustNews = await TrustNews.attach(contractAddress);

  // Comprobar dueño
  const owner = await trustNews.owner();
  console.log("Owner:", owner);

  // Comprobar contador de posts
  const postCounter = await trustNews.postCounter();
  console.log("Posts registrados:", postCounter);
}

main().catch((error) => {
  console.error("❌ Error:", error);
  process.exit(1);
});
