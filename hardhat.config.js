require("@nomicfoundation/hardhat-toolbox");
/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: "0.8.28",
  networks: {
    privateGeth: {
      url: "http://192.168.56.108:8545", // el port HTTP del node N1
      accounts: [
        //"0x<CLAU_PRIVADA_DEL_COMPTE_QUE_HAS_DESBLOQUEJAT>"
        "45a407904ebd8d0f6e9690ee36d7654c50a20e43dc2fa863c1eea9633f567667"
      ],
      chainId: 12345
    }
  },
};
