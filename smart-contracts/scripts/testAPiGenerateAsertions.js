const { ethers } = require("hardhat");

async function main() {
  const [deployer, val1, val2, val3] = await ethers.getSigners();
  console.log("Cuenta deployer:", deployer.address);

  // 🔹 Desplegar TrustNews
  const TrustNews = await ethers.getContractFactory("TrustNews");
  const trustNews = await TrustNews.deploy();
  await trustNews.waitForDeployment();
  const trustNewsAddress = await trustNews.getAddress();
  console.log("✅ TrustNews desplegado en:", trustNewsAddress);

  // ======================================================
  // 🔹 Configurar categorías y validadores
  // ======================================================

  const tx1 = await trustNews.connect(deployer).categories(1);
  if (!tx1) {
    // asignamos descripción solo si no existía
    await (await trustNews.connect(deployer)).categories(1);
  }

  console.log("🔧 Creando validadores y categorías...");

  // Creamos manualmente tres validadores
  await (await trustNews.connect(deployer).validators(val1.address, {
    validatorAddress: val1.address,
    domain: "politica.cat",
    reputation: 90
  })).wait;

  await (await trustNews.connect(deployer).validators(val2.address, {
    validatorAddress: val2.address,
    domain: "economia.cat",
    reputation: 80
  })).wait;

  await (await trustNews.connect(deployer).validators(val3.address, {
    validatorAddress: val3.address,
    domain: "sociedad.cat",
    reputation: 70
  })).wait;

  // Añadir validadores a dos categorías (por ejemplo)
  await (await trustNews.connect(deployer).validatorsByCategory(1)).push({
    validatorAddress: val1.address,
    domain: "politica.cat",
    reputation: 90
  });

  await (await trustNews.connect(deployer).validatorsByCategory(2)).push({
    validatorAddress: val2.address,
    domain: "economia.cat",
    reputation: 80
  });

  // ======================================================
  // 🔹 Crear multihash y aserciones de prueba
  // ======================================================
  const emptyHash = {
    hash_function: "0x12",
    hash_size: "0x20",
    digest: ethers.zeroPadBytes("0x1111", 32),
  };

  const asertions = [
    { hash_asertion: emptyHash, validations: [] },
    { hash_asertion: emptyHash, validations: [] },
  ];

  const categoryIds = [1, 2];

  // ======================================================
  // 🔹 Publicar una noticia
  // ======================================================
  console.log("📰 Publicando noticia...");
  const tx = await trustNews.registerNew(
    emptyHash,      // hash_new
    emptyHash,      // hash_ipfs
    asertions,      // aserciones
    categoryIds     // categorías
  );

  const receipt = await tx.wait();
  const event = receipt.logs.find(log => log.fragment?.name === "PostCreated");
  const postId = event ? event.args[0] : null;

  const [id, validatorAddressesByAsertion] = await trustNews.publishNew.staticCall(
    emptyHash, emptyHash, asertions, categoryIds
  );

  console.log("🆔 ID de publicación:", id.toString());
  console.log("📜 Direcciones devueltas por publishNew():");
  console.log(validatorAddressesByAsertion);

  console.log("🎉 Test de TrustNews completado correctamente");
}

main().catch((error) => {
  console.error("❌ Error:", error);
  process.exitCode = 1;
});
