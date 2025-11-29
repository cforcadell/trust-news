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
      url: "http://localhost:8545", // el port HTTP del node N1
      accounts: [
        //"0x<CLAU_PRIVADA_DEL_COMPTE_QUE_HAS_DESBLOQUEJAT>"
        "d955e631028dcc4b1e3614217b7b719a6f7cd83f"
      ],
      chainId: 1214
    }
  },
};
