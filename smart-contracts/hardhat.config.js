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
        "0xd65e41d84cf076f7624184243ef298b5de143a9495db66c6425724e35b441c68"
      ],
      gas: 25_000_000,
      chainId: 1214
    }
  },
};
