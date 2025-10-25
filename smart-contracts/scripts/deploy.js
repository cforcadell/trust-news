const { ethers, hre } = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("👤 Cuenta deployer:", deployer.address);

  const TrustNews = await ethers.getContractFactory("TrustNews");
  const trustNews = await TrustNews.deploy();
  await trustNews.waitForDeployment();

  const address = await trustNews.getAddress();
  console.log("✅ Contrato desplegado en:", address);

  
}

main().catch((error) => {
  console.error("❌ Error al desplegar:", error);
  process.exitCode = 1;
});
