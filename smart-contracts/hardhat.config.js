require("@nomicfoundation/hardhat-toolbox");
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
      accounts: [
        //"0x<CLAU_PRIVADA_DEL_COMPTE_QUE_HAS_DESBLOQUEJAT>"
        "0x1eac28e3c827c3ea589a86907de71e07590679fc07a4067db1c168858a38feeb"
      ],
      chainId: 1214
    }
  },
};
