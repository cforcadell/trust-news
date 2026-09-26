const { ethers } = require("hardhat");

async function main() {
  const [deployer, validator1, validator2] = await ethers.getSigners();

  console.log("👤 Deployer:", deployer.address);

  // ===============================
  // DEPLOY
  // ===============================
  const TrustNews = await ethers.getContractFactory("TrustNews");
  const trustNews = await TrustNews.deploy();
  await trustNews.waitForDeployment();

  const contractAddress = await trustNews.getAddress();
  console.log("✅ TrustNews desplegado en:", contractAddress);

  // ===============================
  // CATEGORIES
  // ===============================
  await (await trustNews.addCategory(1, "Noticias")).wait();
  await (await trustNews.addCategory(2, "Política")).wait();
  console.log("📚 Categorías creadas");

  // ===============================
  // MULTIHASH HELPER
  // ===============================
  const mkMultihash = (text) => ({
    hash_function: "0x12",
    hash_size: "0x20",
    digest: ethers.keccak256(ethers.toUtf8Bytes(text))
  });

  // ===============================
  // VALIDATOR CONFIG HELPER
  // ===============================
  const mkValidatorConfig = ({
    name,
    type,
    provider,
    model,
    active_date,
    updated_date,
    end_date = "",
    status
  }) => JSON.stringify({
    name,
    type,
    provider,
    model,
    active_date,
    updated_date,
    end_date,
    status
  });

  const mkConfigMultihash = (configJson) => ({
    hash_function: "0x12",
    hash_size: "0x20",
    digest: ethers.keccak256(ethers.toUtf8Bytes(configJson))
  });

  // ===============================
  // VALIDATORS
  // ===============================
  const now = new Date().toISOString();

  const validator1ConfigJson = mkValidatorConfig({
    name: "factcheck.org",
    type: 1, // General_AI
    provider: "mistral",
    model: "mistral-small-latest",
    active_date: now,
    updated_date: now,
    status: 1 // Registered
  });

  const validator2ConfigJson = mkValidatorConfig({
    name: "truth.net",
    type: 3, // Dedicated_Agent
    provider: "openrouter",
    model: "meta-llama/llama-3.1-8b-instruct",
    active_date: now,
    updated_date: now,
    status: 1 // Registered
  });

  const validator1IpfsConfig = mkConfigMultihash(validator1ConfigJson);
  const validator2IpfsConfig = mkConfigMultihash(validator2ConfigJson);

  const txReg1 = await trustNews.connect(validator1).registerValidator(
    "factcheck.org",
    [1],
    validator1IpfsConfig
  );
  const receiptReg1 = await txReg1.wait();

  const txReg2 = await trustNews.connect(validator2).registerValidator(
    "truth.net",
    [2],
    validator2IpfsConfig
  );
  const receiptReg2 = await txReg2.wait();

  console.log("🧾 Validadores registrados");

  // ===============================
  // READ NewValidatorConfig EVENTS
  // ===============================
  const readNewValidatorConfig = (receipt) =>
    receipt.logs
      .map(log => {
        try { return trustNews.interface.parseLog(log); }
        catch { return null; }
      })
      .filter(e => e?.name === "NewValidatorConfig");

  console.log("\n🧩 NewValidatorConfig events:");

  [...readNewValidatorConfig(receiptReg1),
   ...readNewValidatorConfig(receiptReg2)
  ].forEach(e => {
    console.log(
      ` ➤ Validator ${e.args.validator} | ` +
      `Digest ${e.args.ipfsConfig.digest}`
    );
  });

  // ===============================
  // UPDATE VALIDATOR CONFIG
  // ===============================
  const updatedAt = new Date().toISOString();

  const validator1UpdatedConfigJson = mkValidatorConfig({
    name: "factcheck.org",
    type: 1, // General_AI
    provider: "mistral",
    model: "mistral-large-latest",
    active_date: now,
    updated_date: updatedAt,
    status: 1 // Registered
  });

  const validator1UpdatedIpfsConfig = mkConfigMultihash(validator1UpdatedConfigJson);

  const txUpdateConfig = await trustNews.connect(validator1).updateValidatorConfig(
    validator1UpdatedIpfsConfig
  );
  const receiptUpdateConfig = await txUpdateConfig.wait();

  console.log("🔄 Configuración de validator1 actualizada");

  console.log("\n🧩 NewValidatorConfig update event:");

  readNewValidatorConfig(receiptUpdateConfig).forEach(e => {
    console.log(
      ` ➤ Validator ${e.args.validator} | ` +
      `Digest ${e.args.ipfsConfig.digest}`
    );
  });

  // ===============================
  // READ VALIDATORS WITH CONFIG
  // ===============================
  const [validatorAddresses, ipfsConfigs] = await trustNews.getValidatorsWithConfig();

  console.log("\n👥 Validadores con configuración IPFS:");

  for (let i = 0; i < validatorAddresses.length; i++) {
    const addr = validatorAddresses[i];
    const validator = await trustNews.validators(addr);

    console.log(`\n🔹 Validator #${i}`);
    console.log(" Address:", addr);
    console.log(" Domain:", validator.domain);
    console.log(" Reputation:", validator.reputation.toString());
    console.log(" Exists:", validator.exists);
    console.log(" Config digest:", ipfsConfigs[i].digest);
  }

  // ===============================
  // REGISTER NEW POST
  // ===============================
  const postDocument = mkMultihash("Documento IPFS principal");
  const categoryIds = [1, 2];

  console.log("\n⏳ registerNew...");
  const tx = await trustNews.registerNew(postDocument, categoryIds);
  const receipt = await tx.wait();

  // ===============================
  // READ ValidationRequested EVENTS
  // ===============================
  const validationRequestedEvents = receipt.logs
    .map(log => {
      try { return trustNews.interface.parseLog(log); }
      catch { return null; }
    })
    .filter(e => e?.name === "ValidationRequested");

  if (validationRequestedEvents.length === 0) {
    console.warn("⚠️ No se emitieron eventos ValidationRequested");
    return;
  }

  console.log("\n📣 ValidationRequested events:");
  validationRequestedEvents.forEach(e => {
    console.log(
      ` ➤ Post ${e.args.postId.toString()} | ` +
      `Aserción #${e.args.asertionIndex.toString()} | ` +
      `Validador ${e.args.validator}`
    );
  });

  const postId = validationRequestedEvents[0].args.postId;

  // ===============================
  // READ POST
  // ===============================
  const [doc, publisher] = await trustNews.getPostFlat(postId);

  console.log("\n📄 Post document digest:", doc.digest);
  console.log("✍️ Publisher:", publisher);

  // ===============================
  // ADD VALIDATIONS
  // ===============================
  const validation1 = mkMultihash("Validación de Aserción 0");
  const validation2 = mkMultihash("Validación de Aserción 1");

  const txVal1 = await trustNews.connect(validator1)
    .addValidation(postId, 0, 1, validation1); // True
  const receiptVal1 = await txVal1.wait();

  const txVal2 = await trustNews.connect(validator2)
    .addValidation(postId, 1, 2, validation2); // False
  const receiptVal2 = await txVal2.wait();

  console.log("✅ Validaciones añadidas");

  // ===============================
  // READ ValidationSubmitted EVENTS
  // ===============================
  const readValidationSubmitted = (receipt) =>
    receipt.logs
      .map(log => {
        try { return trustNews.interface.parseLog(log); }
        catch { return null; }
      })
      .filter(e => e?.name === "ValidationSubmitted");

  console.log("\n📬 ValidationSubmitted events:");

  [...readValidationSubmitted(receiptVal1),
   ...readValidationSubmitted(receiptVal2)
  ].forEach(e => {
    console.log(
      ` ➤ Post ${e.args.postId.toString()} | ` +
      `Aserción #${e.args.asertionIndex.toString()} | ` +
      `Validador ${e.args.validator} | ` +
      `Digest ${e.args.validationDocument.digest}`
    );
  });

  // ===============================
  // READ ASSERTIONS + VALIDATIONS
  // ===============================
  const asertions = await trustNews.getAsertionsWithValidations(postId);

  console.log("\n📘 Aserciones y validaciones:");

  for (let i = 0; i < asertions.length; i++) {
    const a = asertions[i];
    console.log(`\n🔹 Aserción #${i}`);
    console.log(" CategoryId:", a.categoryId.toString());

    for (let j = 0; j < a.validations.length; j++) {
      const v = a.validations[j];
      console.log(`  ➤ Validación #${j}`);
      console.log("   Validator:", v.validatorAddress);
      console.log("   Domain:", v.domain);
      console.log("   Reputation:", v.reputation.toString());
      console.log("   Veredict:", v.veredict);
      console.log("   Digest:", v.document.digest);

      if (v.validatorIpfsConfig) {
        console.log("   Validator config digest:", v.validatorIpfsConfig.digest);
      }
    }
  }

  // ===============================
  // UNREGISTER
  // ===============================
  const endDate = new Date().toISOString();

  const validator1UnregisteredConfigJson = mkValidatorConfig({
    name: "factcheck.org",
    type: 1,
    provider: "mistral",
    model: "mistral-large-latest",
    active_date: now,
    updated_date: endDate,
    end_date: endDate,
    status: 2 // Unregistered
  });

  const validator2UnregisteredConfigJson = mkValidatorConfig({
    name: "truth.net",
    type: 3,
    provider: "openrouter",
    model: "meta-llama/llama-3.1-8b-instruct",
    active_date: now,
    updated_date: endDate,
    end_date: endDate,
    status: 2 // Unregistered
  });

  await (await trustNews.connect(validator1).updateValidatorConfig(
    mkConfigMultihash(validator1UnregisteredConfigJson)
  )).wait();

  await (await trustNews.connect(validator2).updateValidatorConfig(
    mkConfigMultihash(validator2UnregisteredConfigJson)
  )).wait();

  await (await trustNews.connect(validator1).unregisterValidator()).wait();
  await (await trustNews.connect(validator2).unregisterValidator()).wait();

  console.log("\n✅ Test completado correctamente");
}

main().catch((error) => {
  console.error("❌ Error:", error);
  process.exitCode = 1;
});