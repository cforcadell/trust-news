const { ethers } = require("hardhat");

async function main() {
  const [deployer, validator1, validator2] = await ethers.getSigners();

  console.log("👤 Cuenta deployer:", deployer.address);

  // Desplegar contrato
  const TrustNews = await ethers.getContractFactory("TrustNews");
  const trustNews = await TrustNews.deploy();
  await trustNews.waitForDeployment();
  console.log("✅ Contrato desplegado en:", await trustNews.getAddress());

  // Registrar categorías (owner)
  await (await trustNews.addCategory(1, "Noticias")).wait();
  await (await trustNews.addCategory(2, "Política")).wait();
  console.log("📚 Categorías añadidas correctamente.");

  // Registrar validadores indicando categorías
  await (await trustNews.connect(validator1).registerValidator("factcheck.org", [1])).wait();
  await (await trustNews.connect(validator2).registerValidator("truth.net", [2])).wait();
  console.log("🧾 Validadores registrados con sus categorías.");

  // Helper: construir Multihash compatible (bytes1, bytes1, bytes32)
  const mkMultihash = (text) => {
    return {
      hash_function: "0x12",
      hash_size: "0x20",
      digest: ethers.keccak256(ethers.toUtf8Bytes(text))
    };
  };

  // Preparar datos para registerNew
  const hash_new = mkMultihash("Noticia Principal");
  const hash_ipfs = mkMultihash("IPFS documento");

  const asertions = [
    { hash_asertion: mkMultihash("Asercion 1"), validations: [], categoryId: 1 },
    { hash_asertion: mkMultihash("Asercion 2"), validations: [], categoryId: 2 }
  ];
  const categoryIds = [1, 2];

  // Enviar la transacción real registerNew
  console.log("\n⏳ Enviando registerNew...");
  const tx = await trustNews.registerNew(hash_new, hash_ipfs, asertions, categoryIds);
  const receipt = await tx.wait();
  console.log("✅ Transacción minada. Bloque:", receipt.blockNumber);

  // Extraer el evento RegisterNewResult del recibo
  // El contrato debe emitir: event RegisterNewResult(uint256 postId, address[][] validatorAddressesByAsertion);
  const iface = trustNews.interface;
  const parsedEvent = receipt.logs
    .map((log) => {
      try { return iface.parseLog(log); } catch (err) { return null; }
    })
    .find((p) => p && p.name === "RegisterNewResult");

  if (!parsedEvent) {
    console.error("❌ No se encontró el evento RegisterNewResult en el recibo. Asegúrate de que el contrato emite ese evento.");
    return;
  }

  const postId = parsedEvent.args.postId;
  const validatorAddressesByAsertion = parsedEvent.args.validatorAddressesByAsertion;

  console.log("\n🔷 Resultado real de registerNew (desde evento):");
  console.log(" PostId:", postId.toString());

  for (let i = 0; i < validatorAddressesByAsertion.length; i++) {
    const arr = validatorAddressesByAsertion[i];
    const addresses = Array.isArray(arr) ? arr.map(a => a.toString()) : Object.values(arr).map(a => a.toString());
    console.log(`  Aserción #${i}: [${addresses.join(", ")}]`);
  }

  // Opcional: leer el postCounter y estado real en el contrato
  const postCounter = await trustNews.postCounter();
  console.log("\n📌 postCounter (desde contrato):", postCounter.toString());

  // Mostrar aserciones guardadas y su categoryId (lectura)
  const postIdNum = Number(postId.toString());
  console.log("📰 Post publicado con ID:", postId.toString());

  const asertionsWithValidationsBefore = await trustNews.getAsertionsWithValidations(postIdNum);
  console.log("\n📘 Aserciones guardadas (con validations):");
  for (let i = 0; i < asertionsWithValidationsBefore.length; i++) {
    const a = asertionsWithValidationsBefore[i];
    console.log(`\n Aserción #${i}`);
    console.log(`  Digest: ${a.hash_asertion.digest}`);
    console.log(`  CategoryId: ${a.categoryId.toString()}`);
    console.log(`  Validaciones: ${a.validations.length}`);
  }

  // 4️⃣a Consultar por hash_new
  const newByHash = await trustNews.getNewByHash(hash_new);
  const returnedHashCid = newByHash.hash_cid !== undefined ? newByHash.hash_cid : newByHash[0];
  const returnedPostIdFromHash = newByHash.PostId !== undefined ? newByHash.PostId : newByHash[1];
  console.log("\n🔹 getNewByHash:");
  console.log(" PostId:", returnedPostIdFromHash.toString());
  console.log(" hash_cid digest:", returnedHashCid.digest);

  // 4️⃣b Consultar por hash_ipfs
  const newByCid = await trustNews.getNewByCid(hash_ipfs);
  const returnedHashNew = newByCid.hash_new !== undefined ? newByCid.hash_new : newByCid[0];
  const returnedPostIdFromCid = newByCid.PostId !== undefined ? newByCid.PostId : newByCid[1];
  console.log("\n🔹 getNewByCid:");
  console.log(" PostId:", returnedPostIdFromCid.toString());
  console.log(" hash_new digest:", returnedHashNew.digest);

  // 5️⃣ Añadir validaciones posteriores
  const multihashVal1 = mkMultihash("Validación 1 de A1");
  const multihashVal2 = mkMultihash("Validación 2 de A2");

  // Añadir validaciones por los validadores registrados (índices de aserción 0 y 1)
  await (await trustNews.connect(validator1).addValidation(postIdNum, 0, 0, multihashVal1)).wait();
  await (await trustNews.connect(validator2).addValidation(postIdNum, 1, 1, multihashVal2)).wait();
  console.log("✅ Validaciones añadidas correctamente.");

  // 6️⃣ Consultar aserciones con sus validaciones y validadores
  const asertionsWithValidations = await trustNews.getAsertionsWithValidations(postIdNum);
  console.log("\n📘 Resultado de getAsertionsWithValidations:");
  for (let i = 0; i < asertionsWithValidations.length; i++) {
    const a = asertionsWithValidations[i];
    console.log(`\n🔹 Aserción #${i}`);
    console.log(` Digest: ${a.hash_asertion.digest}`);
    console.log(` CategoryId: ${a.categoryId.toString()}`);
    for (let j = 0; j < a.validations.length; j++) {
      const v = a.validations[j];
      console.log(` ➤ Validación #${j}`);
      console.log(`  Validator: ${v.validatorAddress}`);
      console.log(`  Domain: ${v.domain}`);
      console.log(`  Reputación: ${v.reputation.toString()}`);
      console.log(`  Veredicto: ${v.veredict}`);
      console.log(`  Hash descripción: ${v.hash_description.digest}`);
    }
  }

  console.log("\n✅ Test completado correctamente.");
}

main().catch((error) => {
  console.error("❌ Error en el test:", error);
  process.exitCode = 1;
});
