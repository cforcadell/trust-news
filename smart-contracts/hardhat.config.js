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
        //"0x9787ee136da3ee6ca61199d2462c8b11a6d93887090802bb9d85790c88cba36d",
        "0x1d3b44a2590c12a313948684a93fcdbfdf9cdd8a9ed2e636468663ae469462e6"
      ],
      chainId: 1214
    }
  },
};
