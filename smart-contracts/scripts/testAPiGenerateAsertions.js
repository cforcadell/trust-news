const { ethers } = require("hardhat");

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("Cuenta deployer:", deployer.address);

  let linkToken;
  let linkTokenAddress;

  // 🔹 Detectar red
  const network = await ethers.provider.getNetwork();
  console.log("Network ID:", network.chainId);

  if (network.chainId === 31337n) {
    // Local Hardhat → deploy LinkTokenMock
    console.log("Red local detectada: deployando LinkTokenMock...");

    const LinkTokenMock = await ethers.getContractFactory("LinkTokenMock");
    linkToken = await LinkTokenMock.deploy(ethers.parseUnits("1000", 18));
    await linkToken.waitForDeployment();
    linkTokenAddress = await linkToken.getAddress();
    console.log("LinkTokenMock desplegado en:", linkTokenAddress);
  } else {
    // Testnet/Mainnet → usar LINK real
    linkTokenAddress = "0x..."; // Dirección LINK real
    const LinkToken = await ethers.getContractFactory("LinkToken"); // opcional si quieres interactuar
    linkToken = await ethers.getContractAt("LinkToken", linkTokenAddress);
    console.log("Usando token LINK real en:", linkTokenAddress);
  }

  // 🔹 Oracle y JobId
  const oracleAddress = "0x8919aC75c29C538d21bB4D851670a163C6B4fCAA"; // Dirección del nodo Chainlink
  const uuid = "23035921-8e44-4cb2-8a10-0364b29bbf14";
  const jobId = "0x" + uuid.replace(/-/g, "").padEnd(64, "0"); // bytes32
  const fee = ethers.parseEther("0.1"); // 0.1 LINK

  // 🔹 Deploy del contrato consumidor
  const ApiExtraerConsumer = await ethers.getContractFactory("ApiExtraerConsumer");
  const consumer = await ApiExtraerConsumer.deploy(linkTokenAddress, oracleAddress, jobId, fee);
  await consumer.waitForDeployment();
  console.log("ApiExtraerConsumer desplegado en:", await consumer.getAddress());

  // 🔹 Fundear el contrato consumidor con LINK
  await linkToken.transfer(await consumer.getAddress(), ethers.parseEther("1"));
  console.log("Se transfirió 1 LINK al contrato consumidor");

  // 🔹 Enviar request al nodo Chainlink
  const tx = await consumer.requestExtraccion(
    "Catalunya tiene una población de 8 millones de habitantes y 2 millones de población extranjera"
  );
  await tx.wait();
  console.log("Request enviada al Chainlink Node. Esperando fulfillment...");

  // 🔹 Listener de evento ChainlinkFulfilled
  consumer.on("ChainlinkFulfilled", async (requestId) => {
    console.log(`Request ${requestId} cumplida por el Chainlink Node`);
    const result = await consumer.message();
    console.log("Resultado real de la API:", result);
    process.exit(0);
  });
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
