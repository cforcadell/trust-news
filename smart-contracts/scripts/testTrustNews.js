const hre = require("hardhat");

async function main() {
  const [deployer, validator1, validator2] = await hre.ethers.getSigners();
  console.log("Cuenta deployer:", deployer.address);

  // ================================
  // DESPLEGAR CONTRATO
  // ================================
  const TrustManager = await hre.ethers.getContractFactory("TrustNews");
  const tm = await TrustManager.deploy();
  await tm.waitForDeployment();
  console.log("Contrato desplegado en:", await tm.getAddress());

  // ================================
  // AÑADIR CATEGORÍAS DE PRUEBA
  // ================================
  const categories = [
    { id: "0x4e", desc: "News" },   // 'N'
    { id: "0x54", desc: "Tech" },   // 'T'
    { id: "0x53", desc: "Sports" }, // 'S'
  ];

  for (const cat of categories) {
    const tx = await tm.addCategory(cat.id, cat.desc);
    await tx.wait();
    console.log(`Categoría añadida: ${cat.desc} (${cat.id})`);
  }

  // ================================
  // REGISTRAR VALIDADORES
  // ================================
  const tx1 = await tm.connect(validator1).registerValidator("ValidatorOne", ["News"]);
  await tx1.wait();
  console.log("Validador 1 registrado:", validator1.address);

  const tx2 = await tm.connect(validator2).registerValidator("ValidatorTwo", ["Tech"]);
  await tx2.wait();
  console.log("Validador 2 registrado:", validator2.address);

  // ================================
  // CREAR HASHES DE PRUEBA
  // ================================
  const hash_new = {
    hash_function: "0x12",
    hash_size: "0x20",
    digest: hre.ethers.toBeHex(hre.ethers.toUtf8Bytes("hash_new_test"), { size: 32 }),
  };

  const hash_ipfs = {
    hash_function: "0x12",
    hash_size: "0x20",
    digest: hre.ethers.toBeHex(hre.ethers.toUtf8Bytes("hash_ipfs_test"), { size: 32 }),
  };

  const hash_assertion = {
    hash_function: "0x12",
    hash_size: "0x20",
    digest: hre.ethers.toBeHex(hre.ethers.toUtf8Bytes("assertion_1"), { size: 32 }),
  };

  const hash_description = {
    hash_function: "0x12",
    hash_size: "0x20",
    digest: hre.ethers.toBeHex(hre.ethers.toUtf8Bytes("desc_validation_1"), { size: 32 }),
  };

  // ================================
  // CREAR VALIDACIONES Y ASERCIONES
  // ================================
  const validations = [
    {
      id: "0x01",
      validator: {
        validatorAddress: validator1.address,
        domain: "ValidatorOne",
        reputation: 10,
      },
      veredict: true,
      hash_description,
    },
  ];

  const asertions = [
    {
      hash_asertion: hash_assertion,
      validations,
    },
  ];

  // ================================
  // PUBLICAR UNA NOTICIA
  // ================================
  const txNew = await tm.publishNew(hash_new, hash_ipfs, asertions);
  const receipt = await txNew.wait();

  const result = await tm.getNewByHash(hash_new);
  const postId = result[1];

  console.log("\n=== Resultado de publicación ===");
  console.log("PostId:", postId);

  // Ver validaciones registradas
  const validationsStored = await tm.getValidationsByNew(postId);
  console.log("Validaciones guardadas:", validationsStored.length);
  console.log("Validator address:", validationsStored[0].validator.validatorAddress);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
