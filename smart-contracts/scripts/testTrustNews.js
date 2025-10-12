const { ethers } = require("hardhat");

async function main() {
    const [deployer, validator1, validator2] = await ethers.getSigners();

    console.log("👤 Cuenta deployer:", deployer.address);

    // 1️⃣ Desplegar contrato
    const TrustNews = await ethers.getContractFactory("TrustNews");
    const trustNews = await TrustNews.deploy();
    await trustNews.waitForDeployment();
    console.log("✅ Contrato desplegado en:", await trustNews.getAddress());

    // 2️⃣ Registrar categorías
    await (await trustNews.addCategory(1, "Noticias")).wait();
    await (await trustNews.addCategory(2, "Política")).wait();
    console.log("📚 Categorías añadidas correctamente.");

    // 3️⃣ Registrar validadores indicando categorías
    await (await trustNews.connect(validator1).registerValidator("factcheck.org", [1])).wait(); // Noticias
    await (await trustNews.connect(validator2).registerValidator("truth.net", [2])).wait(); // Política
    console.log("🧾 Validadores registrados con sus categorías.");

    // 4️⃣ Publicar post con aserciones (sin validaciones)
    const hash_new = {
        hash_function: Uint8Array.from([0x12]),
        hash_size: Uint8Array.from([0x20]),
        digest: ethers.keccak256(ethers.toUtf8Bytes("Noticia Principal"))
    };

    const hash_ipfs = {
        hash_function: Uint8Array.from([0x12]),
        hash_size: Uint8Array.from([0x20]),
        digest: ethers.keccak256(ethers.toUtf8Bytes("IPFS documento"))
    };

    const asertions = [
        {
            hash_asertion: {
                hash_function: Uint8Array.from([0x12]),
                hash_size: Uint8Array.from([0x20]),
                digest: ethers.keccak256(ethers.toUtf8Bytes("Asercion 1"))
            },
            validations: []
        },
        {
            hash_asertion: {
                hash_function: Uint8Array.from([0x12]),
                hash_size: Uint8Array.from([0x20]),
                digest: ethers.keccak256(ethers.toUtf8Bytes("Asercion 2"))
            },
            validations: []
        }
    ];

    const txPublish = await trustNews.publishNew(hash_new, hash_ipfs, asertions, 1);
    await txPublish.wait();
    const postId = await trustNews.postCounter();
    console.log("📰 Post publicado con ID:", postId.toString());

    // 4️⃣a Consultar por hash_new
    const newByHash = await trustNews.getNewByHash(hash_new);
    console.log("\n🔹 getNewByHash:");
    console.log("   PostId:", newByHash.PostId.toString());
    console.log("   hash_cid digest:", newByHash.hash_cid.digest);

    // 4️⃣b Consultar por hash_ipfs
    const newByCid = await trustNews.getNewByCid(hash_ipfs);
    console.log("\n🔹 getNewByCid:");
    console.log("   PostId:", newByCid.PostId.toString());
    console.log("   hash_new digest:", newByCid.hash_new.digest);

    // 5️⃣ Añadir validaciones posteriores
    const multihashVal1 = {
        hash_function: Uint8Array.from([0x12]),
        hash_size: Uint8Array.from([0x20]),
        digest: ethers.keccak256(ethers.toUtf8Bytes("Validación 1 de A1"))
    };

    const multihashVal2 = {
        hash_function: Uint8Array.from([0x12]),
        hash_size: Uint8Array.from([0x20]),
        digest: ethers.keccak256(ethers.toUtf8Bytes("Validación 2 de A2"))
    };

    await (await trustNews.connect(validator1).addValidation(postId, 0, true, multihashVal1)).wait();
    await (await trustNews.connect(validator2).addValidation(postId, 1, false, multihashVal2)).wait();
    console.log("✅ Validaciones añadidas correctamente.");

    // 6️⃣ Consultar aserciones con sus validaciones y validadores
    const asertionsWithValidations = await trustNews.getAsertionsWithValidations(postId);

    console.log("\n📘 Resultado de getAsertionsWithValidations:");
    for (let i = 0; i < asertionsWithValidations.length; i++) {
        const a = asertionsWithValidations[i];
        console.log(`\n🔹 Aserción #${i}`);
        console.log(`   Digest: ${a.hash_asertion.digest}`);

        for (let j = 0; j < a.validations.length; j++) {
            const v = a.validations[j];
            console.log(`   ➤ Validación #${j}`);
            console.log(`      Validator: ${v.validatorAddress}`);
            console.log(`      Domain: ${v.domain}`);
            console.log(`      Reputación: ${v.reputation}`);
            console.log(`      Veredicto: ${v.veredict}`);
            console.log(`      Hash descripción: ${v.hash_description.digest}`);
        }
    }

    console.log("\n✅ Test completado correctamente.");
}

main().catch((error) => {
    console.error("❌ Error en el test:", error);
    process.exitCode = 1;
});
