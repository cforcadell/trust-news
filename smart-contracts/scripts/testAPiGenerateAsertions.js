const { ethers } = require("hardhat");

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("Cuenta deployer:", deployer.address);

  // 1. Deploy LinkTokenMock
  const LinkTokenMock = await ethers.getContractFactory("LinkTokenMock");
  const linkToken = await LinkTokenMock.deploy(ethers.utils.parseUnits("1000", 18));
  await linkToken.deployed();
  console.log("LinkTokenMock desplegado en:", linkToken.address);

  // 2. Deploy OperatorMock
  const OperatorMock = await ethers.getContractFactory("OperatorMock");
  const operator = await OperatorMock.deploy(linkToken.address);
  await operator.deployed();
  console.log("OperatorMock desplegado en:", operator.address);

  // 3. Deploy ApiExtraerConsumer
  // ⚠️ Sustituye jobId por el que te dé tu nodo Chainlink en hexadecimal (0x...)
  const jobId = "0xef5c4f61aeca4fc9b666d1806e0e1329"; // <- ejemplo en hex sin guiones
  const fee = ethers.utils.parseEther("0.1"); // 0.1 LINK

  const ApiExtraerConsumer = await ethers.getContractFactory("ApiExtraerConsumer");
  const consumer = await ApiExtraerConsumer.deploy(
    linkToken.address,
    operator.address,
    jobId,
    fee
  );
  await consumer.deployed();
  console.log("ApiExtraerConsumer desplegado en:", consumer.address);

  // 4. Mandar 1 LINK al consumidor
  const txFund = await linkToken.transfer(consumer.address, ethers.utils.parseEther("1"));
  await txFund.wait();
  console.log("1 LINK transferido al contrato consumidor");

  // 5. Hacer request a la API
  const tx = await consumer.requestPoblacion(
    "Catalunya tiene una población de 8 millones de habitantes y 2 millones de población extranjera"
  );
  await tx.wait();
  console.log("Request enviada, esperando fulfillment...");

  // 6. Simular fulfillment desde OperatorMock
  const requestId = await consumer.lastRequestId(); // suponiendo que ApiExtraerConsumer guarda el último requestId
  const result = 8000000; // ejemplo de valor que la API devolvería
  const txFulfill = await operator.fulfillRequest(requestId, result);
  await txFulfill.wait();
  console.log("Fulfillment simulado enviado al contrato consumidor");

  // 7. Leer el resultado
  const poblacion = await consumer.poblacion();
  console.log("Resultado almacenado en contrato:", poblacion.toString());
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
