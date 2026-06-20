require("@nomicfoundation/hardhat-toolbox");

const configuredPrivateKey = (process.env.DEPLOYER_PRIVATE_KEY || "").trim();
const deployerAccounts = configuredPrivateKey
  ? [configuredPrivateKey.startsWith("0x") ? configuredPrivateKey : `0x${configuredPrivateKey}`]
  : [];

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: "0.8.28",
  networks: {
    hardhat: {
      chainId: 31337,
      mining: {
        auto: true
      }
    },
    privateGeth: {
      url: "http://localhost:8555", // el port HTTP del node N1
      accounts: deployerAccounts,
      gas: 25_000_000,
      chainId: 1214
    }
    ,
    cloudGeth: {
      url: "http://localhost:8565", // el port HTTP del node N1
      accounts: deployerAccounts,
      gas: 25_000_000,
      chainId: 1214
    }
  },
};
