const { ethers } = require("hardhat");

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("Deploying with account:", deployer.address);

  // 1. Deploy LINK token (mock)
  const LinkToken = await ethers.getContractFactory("LinkToken");
  const linkToken = await LinkToken.deploy();
  await linkToken.deployed();
  console.log("LINK token deployed at:", linkToken.address);

  // 2. Deploy Operator (oracle)
  const Operator = await ethers.getContractFactory("Operator");
  const operator = await Operator.deploy(linkToken.address, deployer.address);
  await operator.deployed();
  console.log("Operator deployed at:", operator.address);

  // 3. Deploy ApiExtraerConsumer
  const ApiExtraerConsumer = await ethers.getContractFactory("ApiExtraerConsumer");

  // ❗ JobID: lo obtendrás del nodo Chainlink al crear el job TOML
  const jobId = "0xef5c4f61-aeca-4fc9-b666-d1806e0e1329"; 
  const fee = ethers.utils.parseEther("0.1"); // 0.1 LINK

  const consumer = await ApiExtraerConsumer.deploy(
    linkToken.address,
    operator.address,
    jobId,
    fee
  );

  await consumer.deployed();
  console.log("ApiConsumer deployed at:", consumer.address);

  // 4. Transfiere algunos LINK al contrato consumidor
  const tx = await linkToken.transfer(consumer.address, ethers.utils.parseEther("1"));
  await tx.wait();
  console.log("1 LINK transferred to ApiConsumer");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
