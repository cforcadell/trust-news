const { ethers } = require("ethers");
const fs = require("fs");

const provider = new ethers.JsonRpcProvider("http://localhost:8545");
const wallet = new ethers.Wallet(PRIVATE_KEY, provider);

async function deploy() {
  const abi = JSON.parse(fs.readFileSync("../contracts/TrustNews.abi"));
  const bytecode = fs.readFileSync("TrustNews.bin").toString();
  const factory = new ethers.ContractFactory(abi, bytecode, wallet);

  const contract = await factory.deploy();
  console.log("Contrato desplegado en:", contract.target);
}
deploy();